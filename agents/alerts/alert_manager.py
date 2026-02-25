"""
Clinical Alert Classification and Management System

Implements a 4-tier clinical escalation framework designed to balance
patient safety with alarm fatigue mitigation. Alerts are classified by
severity (CRITICAL, URGENT, ROUTINE, INFORMATIONAL) and managed through
their full lifecycle: creation, deduplication, acknowledgement, escalation,
and resolution.

Clinical scoring classifiers (NEWS2, qSOFA) and vital-sign / lab-result
thresholds are drawn from widely-adopted early-warning guidelines.

Usage:
    from agents.alerts import get_alert_manager, AlertClassifier, AlertSeverity

    mgr = get_alert_manager()
    alert = mgr.create_alert(
        patient_id="patient-123",
        severity=AlertSeverity.URGENT,
        category="cardiac",
        title="Sustained tachycardia",
        description="HR 135 bpm sustained over 10 minutes.",
        source_agent="cardiac_monitor",
        evidence=[{"type": "vital_sign", "name": "HR", "value": 135}],
        recommended_actions=["Review rhythm strip", "Consider beta-blocker"],
    )
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger("agentehr.alerts")

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AlertSeverity(Enum):
    """Four-tier clinical alert severity aligned with escalation protocols.

    Each tier defines an expected response time and delivery mechanism:

    * CRITICAL  -- <5 min, bedside + phone + page
    * URGENT    -- 15-30 min, phone notification
    * ROUTINE   -- 1-2 hours, dashboard
    * INFORMATIONAL -- 4+ hours, passive display
    """

    CRITICAL = "critical"
    URGENT = "urgent"
    ROUTINE = "routine"
    INFORMATIONAL = "informational"

    # Convenience ordering: lower number == higher severity.
    def _severity_rank(self) -> int:
        _ranks = {
            AlertSeverity.CRITICAL: 0,
            AlertSeverity.URGENT: 1,
            AlertSeverity.ROUTINE: 2,
            AlertSeverity.INFORMATIONAL: 3,
        }
        return _ranks[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, AlertSeverity):
            return NotImplemented
        return self._severity_rank() < other._severity_rank()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, AlertSeverity):
            return NotImplemented
        return self._severity_rank() <= other._severity_rank()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, AlertSeverity):
            return NotImplemented
        return self._severity_rank() > other._severity_rank()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, AlertSeverity):
            return NotImplemented
        return self._severity_rank() >= other._severity_rank()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Alert:
    """A single clinical alert with full lifecycle tracking.

    Attributes:
        id: Unique identifier (UUID4).
        patient_id: FHIR patient resource ID.
        severity: Tier of the alert.
        category: Clinical domain, e.g. ``"sepsis"``, ``"cardiac"``,
            ``"renal"``, ``"medication"``, ``"care_gap"``.
        title: Short human-readable summary.
        description: Detailed description including supporting evidence.
        source_agent: Name of the agent that generated this alert,
            e.g. ``"infectious_disease"``, ``"supervisor"``.
        evidence: List of supporting data points, each a dict such as
            ``{"type": "vital_sign", "name": "HR", "value": 105}``.
        recommended_actions: Ordered list of suggested clinician actions.
        created_at: UTC timestamp when the alert was created.
        acknowledged_at: UTC timestamp when a clinician acknowledged.
        acknowledged_by: Identifier of the clinician who acknowledged.
        resolved_at: UTC timestamp when the alert was resolved.
        resolved_by: Identifier of the clinician who resolved.
        status: Lifecycle status -- ``"active"``, ``"acknowledged"``,
            ``"resolved"``, or ``"suppressed"``.
        escalation_count: Number of times this alert has been re-escalated
            due to lack of acknowledgement within the response window.
        related_alert_ids: IDs of related alerts (for deduplication tracking).
        metadata: Arbitrary additional data for downstream consumers.
    """

    id: str
    patient_id: str
    severity: AlertSeverity
    category: str
    title: str
    description: str
    source_agent: str
    evidence: list[dict[str, Any]]
    recommended_actions: list[str]
    created_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    status: str = "active"
    escalation_count: int = 0
    related_alert_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SuppressionRule:
    """Patient-specific rule that suppresses or adjusts alert thresholds.

    Useful for avoiding alarm fatigue on known chronic baselines (e.g. a
    patient with chronic tachycardia whose resting HR is 105).

    Attributes:
        category: Alert category this rule applies to (e.g. ``"cardiac"``).
        condition: Short descriptor of the clinical condition being
            accounted for, e.g. ``"hr_baseline_elevated"``.
        threshold_adjustment: Dict mapping threshold names to adjusted
            values, e.g. ``{"hr_upper": 120}``.
        reason: Human-readable justification for the suppression.
        expires_at: Optional expiration; ``None`` means indefinite.
    """

    category: str
    condition: str
    threshold_adjustment: dict[str, Any]
    reason: str
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# AlertManager
# ---------------------------------------------------------------------------


class AlertManager:
    """Manages clinical alerts with alarm-fatigue mitigation.

    Features:
    * **Deduplication** -- Prevents duplicate alerts for the same patient,
      category, and severity within a configurable time window.
    * **Suppression rules** -- Patient-specific threshold adjustments for
      known chronic conditions.
    * **Lifecycle management** -- Tracks alerts through active, acknowledged,
      resolved, and suppressed states.
    * **Escalation checks** -- Time-based re-escalation when alerts go
      unacknowledged past their expected response window.
    * **Thread safety** -- All mutations are guarded by a reentrant lock.
    """

    def __init__(self) -> None:
        # In-memory store keyed by patient_id -> list of alerts.
        self._alerts: dict[str, list[Alert]] = {}

        # Deduplication window in minutes per severity tier.
        self._dedup_window_minutes: dict[AlertSeverity, int] = {
            AlertSeverity.CRITICAL: 5,
            AlertSeverity.URGENT: 30,
            AlertSeverity.ROUTINE: 120,
            AlertSeverity.INFORMATIONAL: 480,
        }

        # Expected response time in minutes per severity (used for escalation).
        self._response_window_minutes: dict[AlertSeverity, int] = {
            AlertSeverity.CRITICAL: 5,
            AlertSeverity.URGENT: 30,
            AlertSeverity.ROUTINE: 120,
            AlertSeverity.INFORMATIONAL: 240,
        }

        # Suppression rules keyed by patient_id.
        self._suppressions: dict[str, list[SuppressionRule]] = {}

        # Lock for thread-safe mutations.
        self._lock: threading.RLock = threading.RLock()

        # Flat index for O(1) lookup by alert ID.
        self._alert_index: dict[str, Alert] = {}

    # ------------------------------------------------------------------
    # Alert creation
    # ------------------------------------------------------------------

    def create_alert(
        self,
        patient_id: str,
        severity: AlertSeverity,
        category: str,
        title: str,
        description: str,
        source_agent: str,
        evidence: list[dict[str, Any]],
        recommended_actions: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> Alert | None:
        """Create a clinical alert with deduplication and suppression checks.

        Returns the newly created ``Alert`` if it passes all filters, or
        ``None`` if the alert was suppressed or deduplicated.

        Args:
            patient_id: FHIR patient resource ID.
            severity: Alert severity tier.
            category: Clinical domain (e.g. ``"sepsis"``).
            title: Short summary of the alert.
            description: Detailed description with supporting evidence.
            source_agent: Originating agent name.
            evidence: List of evidence dicts.
            recommended_actions: Suggested clinician actions.
            metadata: Optional additional data.

        Returns:
            The created ``Alert``, or ``None`` if suppressed/deduplicated.
        """
        now = datetime.now(timezone.utc)

        with self._lock:
            # --- Suppression check ---
            if self._is_suppressed(patient_id, category, now):
                logger.info(
                    "Alert suppressed for patient %s, category %s",
                    patient_id,
                    category,
                )
                return None

            # --- Deduplication check ---
            if self._is_duplicate(patient_id, severity, category, now):
                logger.info(
                    "Duplicate alert filtered for patient %s, category %s, severity %s",
                    patient_id,
                    category,
                    severity.value,
                )
                return None

            alert = Alert(
                id=str(uuid.uuid4()),
                patient_id=patient_id,
                severity=severity,
                category=category,
                title=title,
                description=description,
                source_agent=source_agent,
                evidence=evidence,
                recommended_actions=list(recommended_actions),
                created_at=now,
                metadata=metadata if metadata is not None else {},
            )

            self._alerts.setdefault(patient_id, []).append(alert)
            self._alert_index[alert.id] = alert

            logger.info(
                "Alert created: id=%s severity=%s category=%s patient=%s title=%r",
                alert.id,
                alert.severity.value,
                alert.category,
                alert.patient_id,
                alert.title,
            )

            return alert

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> Alert:
        """Mark an alert as acknowledged by a clinician.

        Args:
            alert_id: UUID of the alert.
            acknowledged_by: Identifier of the acknowledging clinician.

        Returns:
            The updated ``Alert``.

        Raises:
            KeyError: If the alert ID is not found.
            ValueError: If the alert is not in an acknowledgeable state.
        """
        with self._lock:
            alert = self._get_alert_or_raise(alert_id)

            if alert.status not in ("active",):
                raise ValueError(
                    f"Cannot acknowledge alert in status '{alert.status}'. "
                    f"Only 'active' alerts can be acknowledged."
                )

            alert.acknowledged_at = datetime.now(timezone.utc)
            alert.acknowledged_by = acknowledged_by
            alert.status = "acknowledged"

            logger.info(
                "Alert acknowledged: id=%s by=%s",
                alert_id,
                acknowledged_by,
            )

            return alert

    def resolve_alert(self, alert_id: str, resolved_by: str) -> Alert:
        """Mark an alert as resolved.

        Args:
            alert_id: UUID of the alert.
            resolved_by: Identifier of the resolving clinician.

        Returns:
            The updated ``Alert``.

        Raises:
            KeyError: If the alert ID is not found.
            ValueError: If the alert is already resolved.
        """
        with self._lock:
            alert = self._get_alert_or_raise(alert_id)

            if alert.status == "resolved":
                raise ValueError(
                    f"Alert '{alert_id}' is already resolved."
                )

            alert.resolved_at = datetime.now(timezone.utc)
            alert.resolved_by = resolved_by
            alert.status = "resolved"

            logger.info(
                "Alert resolved: id=%s by=%s",
                alert_id,
                resolved_by,
            )

            return alert

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_active_alerts(
        self,
        patient_id: str | None = None,
        severity: AlertSeverity | None = None,
    ) -> list[Alert]:
        """Return active (unresolved) alerts, optionally filtered.

        Args:
            patient_id: If provided, restrict to this patient.
            severity: If provided, restrict to this severity tier.

        Returns:
            List of matching ``Alert`` objects sorted by severity (highest
            first), then by creation time (newest first).
        """
        with self._lock:
            if patient_id is not None:
                candidates = list(self._alerts.get(patient_id, []))
            else:
                candidates = [
                    alert
                    for alerts in self._alerts.values()
                    for alert in alerts
                ]

            results = [
                a
                for a in candidates
                if a.status in ("active", "acknowledged")
                and (severity is None or a.severity == severity)
            ]

            results.sort(key=lambda a: (a.severity._severity_rank(), -a.created_at.timestamp()))
            return results

    def get_alert_feed(
        self,
        severity_filter: list[AlertSeverity] | None = None,
        limit: int = 50,
    ) -> list[Alert]:
        """Get a cross-patient alert feed for the escalation dashboard.

        Returns alerts sorted by severity (highest first), then by creation
        time (newest first). Includes all statuses except ``"suppressed"``.

        Args:
            severity_filter: If provided, only include these severities.
            limit: Maximum number of alerts to return.

        Returns:
            Sorted list of ``Alert`` objects, capped at *limit*.
        """
        with self._lock:
            all_alerts = [
                alert
                for alerts in self._alerts.values()
                for alert in alerts
                if alert.status != "suppressed"
            ]

            if severity_filter is not None:
                severity_set = set(severity_filter)
                all_alerts = [a for a in all_alerts if a.severity in severity_set]

            all_alerts.sort(
                key=lambda a: (a.severity._severity_rank(), -a.created_at.timestamp())
            )
            return all_alerts[:limit]

    # ------------------------------------------------------------------
    # Suppression management
    # ------------------------------------------------------------------

    def add_suppression_rule(self, patient_id: str, rule: SuppressionRule) -> None:
        """Add a patient-specific suppression rule.

        Suppression rules allow the system to account for known chronic
        baselines (e.g. chronic tachycardia) so that expected deviations
        do not generate repetitive alerts.

        Args:
            patient_id: FHIR patient resource ID.
            rule: The suppression rule to add.
        """
        with self._lock:
            self._suppressions.setdefault(patient_id, []).append(rule)
            logger.info(
                "Suppression rule added for patient %s: category=%s condition=%s reason=%r",
                patient_id,
                rule.category,
                rule.condition,
                rule.reason,
            )

    def remove_suppression_rules(self, patient_id: str, category: str | None = None) -> int:
        """Remove suppression rules for a patient.

        Args:
            patient_id: FHIR patient resource ID.
            category: If provided, only remove rules matching this category.
                If ``None``, remove all rules for the patient.

        Returns:
            Number of rules removed.
        """
        with self._lock:
            rules = self._suppressions.get(patient_id, [])
            if not rules:
                return 0

            if category is None:
                count = len(rules)
                del self._suppressions[patient_id]
                return count

            original_len = len(rules)
            self._suppressions[patient_id] = [
                r for r in rules if r.category != category
            ]
            return original_len - len(self._suppressions[patient_id])

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------

    def check_escalation_needed(self, alert: Alert) -> bool:
        """Determine if an unacknowledged alert requires re-escalation.

        An alert needs escalation when it has been active (not acknowledged)
        for longer than the response window defined for its severity tier.

        If escalation is needed, the alert's ``escalation_count`` is
        incremented and a log entry is emitted.

        Args:
            alert: The alert to evaluate.

        Returns:
            ``True`` if the alert was re-escalated, ``False`` otherwise.
        """
        if alert.status != "active":
            return False

        now = datetime.now(timezone.utc)
        elapsed_minutes = (now - alert.created_at).total_seconds() / 60.0
        window = self._response_window_minutes.get(alert.severity, 30)

        # Account for previous escalations: each escalation resets the window
        effective_elapsed = elapsed_minutes - (alert.escalation_count * window)

        if effective_elapsed >= window:
            with self._lock:
                alert.escalation_count += 1
            logger.warning(
                "Alert escalation triggered: id=%s severity=%s escalation_count=%d "
                "elapsed_minutes=%.1f window=%d",
                alert.id,
                alert.severity.value,
                alert.escalation_count,
                elapsed_minutes,
                window,
            )
            return True

        return False

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    def get_patient_alert_summary(self, patient_id: str) -> dict[str, Any]:
        """Get a summary of alert counts by severity and status for a patient.

        Args:
            patient_id: FHIR patient resource ID.

        Returns:
            Dictionary with keys:
            * ``"patient_id"`` -- the patient ID.
            * ``"total"`` -- total number of alerts.
            * ``"by_severity"`` -- dict mapping severity values to counts.
            * ``"by_status"`` -- dict mapping statuses to counts.
            * ``"active_critical"`` -- count of active CRITICAL alerts.
            * ``"active_urgent"`` -- count of active URGENT alerts.
            * ``"needs_escalation"`` -- count of alerts needing re-escalation.
        """
        with self._lock:
            alerts = self._alerts.get(patient_id, [])

            by_severity: dict[str, int] = {}
            by_status: dict[str, int] = {}
            active_critical = 0
            active_urgent = 0
            needs_escalation = 0

            for alert in alerts:
                sev_key = alert.severity.value
                by_severity[sev_key] = by_severity.get(sev_key, 0) + 1
                by_status[alert.status] = by_status.get(alert.status, 0) + 1

                if alert.status == "active":
                    if alert.severity == AlertSeverity.CRITICAL:
                        active_critical += 1
                    elif alert.severity == AlertSeverity.URGENT:
                        active_urgent += 1

                    if self.check_escalation_needed(alert):
                        needs_escalation += 1

            return {
                "patient_id": patient_id,
                "total": len(alerts),
                "by_severity": by_severity,
                "by_status": by_status,
                "active_critical": active_critical,
                "active_urgent": active_urgent,
                "needs_escalation": needs_escalation,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_alert_or_raise(self, alert_id: str) -> Alert:
        """Look up an alert by ID or raise ``KeyError``."""
        alert = self._alert_index.get(alert_id)
        if alert is None:
            raise KeyError(f"Alert with id '{alert_id}' not found.")
        return alert

    def _is_duplicate(
        self,
        patient_id: str,
        severity: AlertSeverity,
        category: str,
        now: datetime,
    ) -> bool:
        """Return ``True`` if a matching active alert exists within the dedup window."""
        window_minutes = self._dedup_window_minutes.get(severity, 30)
        for alert in self._alerts.get(patient_id, []):
            if (
                alert.category == category
                and alert.severity == severity
                and alert.status in ("active", "acknowledged")
            ):
                elapsed = (now - alert.created_at).total_seconds() / 60.0
                if elapsed < window_minutes:
                    return True
        return False

    def _is_suppressed(
        self,
        patient_id: str,
        category: str,
        now: datetime,
    ) -> bool:
        """Return ``True`` if any active suppression rule matches."""
        rules = self._suppressions.get(patient_id, [])
        for rule in rules:
            if rule.category != category:
                continue
            # Check expiration.
            if rule.expires_at is not None and now >= rule.expires_at:
                continue
            return True
        return False

    def get_suppression_rules(self, patient_id: str) -> list[SuppressionRule]:
        """Return the current suppression rules for a patient.

        Args:
            patient_id: FHIR patient resource ID.

        Returns:
            List of active ``SuppressionRule`` objects.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            return [
                r
                for r in self._suppressions.get(patient_id, [])
                if r.expires_at is None or now < r.expires_at
            ]

    def clear(self) -> None:
        """Remove all alerts and suppression rules. Intended for testing."""
        with self._lock:
            self._alerts.clear()
            self._alert_index.clear()
            self._suppressions.clear()


# ---------------------------------------------------------------------------
# AlertClassifier
# ---------------------------------------------------------------------------


class AlertClassifier:
    """Determines alert severity from clinical scoring systems and raw values.

    All methods are static and stateless. The thresholds are based on
    widely-adopted clinical early-warning score guidelines:

    * **NEWS2** -- National Early Warning Score 2 (Royal College of Physicians)
    * **qSOFA** -- Quick Sequential Organ Failure Assessment
    * **Vital-sign thresholds** -- Derived from common critical-care ranges
    * **Lab thresholds** -- Derived from standard critical/panic lab values
    """

    # ------------------------------------------------------------------
    # Scoring-system classifiers
    # ------------------------------------------------------------------

    @staticmethod
    def classify_from_news2(
        news2_score: int,
        any_param_score_3: bool = False,
    ) -> AlertSeverity:
        """Classify alert severity based on a NEWS2 aggregate score.

        The NEWS2 score is an aggregate of six physiological parameters.
        The mapping follows Royal College of Physicians guidance:

        * **>=7** -> CRITICAL (immediate clinical review)
        * **5-6** -> URGENT (urgent clinical review)
        * **1-4 with any single parameter scoring 3** -> URGENT
        * **1-4 without a single 3** -> ROUTINE
        * **0** -> INFORMATIONAL

        Args:
            news2_score: The calculated NEWS2 aggregate score (0-20).
            any_param_score_3: ``True`` if any individual parameter scored 3.

        Returns:
            The corresponding ``AlertSeverity``.
        """
        if news2_score >= 7:
            return AlertSeverity.CRITICAL
        if news2_score >= 5:
            return AlertSeverity.URGENT
        if 1 <= news2_score <= 4:
            if any_param_score_3:
                return AlertSeverity.URGENT
            return AlertSeverity.ROUTINE
        return AlertSeverity.INFORMATIONAL

    @staticmethod
    def classify_from_qsofa(qsofa_score: int) -> AlertSeverity:
        """Classify alert severity based on a qSOFA score.

        The qSOFA score (0-3) assigns one point each for:
        * Altered mentation (GCS < 15)
        * Respiratory rate >= 22
        * Systolic blood pressure <= 100

        Mapping:
        * **3** -> CRITICAL
        * **2** -> URGENT
        * **1** -> ROUTINE
        * **0** -> INFORMATIONAL

        Args:
            qsofa_score: The calculated qSOFA score (0-3).

        Returns:
            The corresponding ``AlertSeverity``.
        """
        if qsofa_score >= 3:
            return AlertSeverity.CRITICAL
        if qsofa_score >= 2:
            return AlertSeverity.URGENT
        if qsofa_score == 1:
            return AlertSeverity.ROUTINE
        return AlertSeverity.INFORMATIONAL

    # ------------------------------------------------------------------
    # Vital-sign classifier
    # ------------------------------------------------------------------

    # Thresholds are structured as ordered lists of (lower, upper, severity)
    # tuples. The first matching range wins.
    _VITAL_THRESHOLDS: dict[str, list[tuple[float | None, float | None, AlertSeverity]]] = {
        # SpO2 (%) -- lower is worse
        "spo2": [
            (None, 80.0, AlertSeverity.CRITICAL),
            (None, 88.0, AlertSeverity.URGENT),
            (None, 92.0, AlertSeverity.ROUTINE),
        ],
        # Heart rate (bpm)
        "hr": [
            (150.0, None, AlertSeverity.CRITICAL),
            (None, 30.0, AlertSeverity.CRITICAL),
            (130.0, None, AlertSeverity.URGENT),
            (None, 40.0, AlertSeverity.URGENT),
        ],
        # Systolic blood pressure (mmHg)
        "sbp": [
            (None, 80.0, AlertSeverity.CRITICAL),
            (None, 90.0, AlertSeverity.URGENT),
        ],
        # Temperature (Fahrenheit)
        "temp_f": [
            (104.0, None, AlertSeverity.URGENT),
        ],
        # Temperature (Celsius)
        "temp_c": [
            (40.0, None, AlertSeverity.URGENT),
        ],
        # Respiratory rate (breaths/min)
        "rr": [
            (35.0, None, AlertSeverity.CRITICAL),
            (None, 6.0, AlertSeverity.CRITICAL),
            (30.0, None, AlertSeverity.URGENT),
            (None, 8.0, AlertSeverity.URGENT),
        ],
    }

    # Canonical name mapping so callers can use common variations.
    _VITAL_NAME_MAP: dict[str, str] = {
        "spo2": "spo2",
        "oxygen_saturation": "spo2",
        "o2sat": "spo2",
        "hr": "hr",
        "heart_rate": "hr",
        "pulse": "hr",
        "sbp": "sbp",
        "systolic_bp": "sbp",
        "systolic_blood_pressure": "sbp",
        "temp_f": "temp_f",
        "temperature_f": "temp_f",
        "temp_c": "temp_c",
        "temperature_c": "temp_c",
        "temperature": "temp_c",  # Default to Celsius
        "rr": "rr",
        "respiratory_rate": "rr",
        "resp_rate": "rr",
    }

    @staticmethod
    def classify_vital_sign(vital_name: str, value: float) -> AlertSeverity | None:
        """Classify an individual vital-sign reading against critical thresholds.

        The method normalizes the vital name to a canonical key and evaluates
        the value against ordered threshold ranges. Returns ``None`` when the
        value falls within normal limits (no alert warranted).

        Supported vitals (with aliases):
        * ``spo2`` / ``oxygen_saturation`` / ``o2sat``
        * ``hr`` / ``heart_rate`` / ``pulse``
        * ``sbp`` / ``systolic_bp`` / ``systolic_blood_pressure``
        * ``temp_f`` / ``temperature_f``
        * ``temp_c`` / ``temperature_c`` / ``temperature``
        * ``rr`` / ``respiratory_rate`` / ``resp_rate``

        Args:
            vital_name: Name of the vital sign (case-insensitive).
            value: Numeric value of the reading.

        Returns:
            ``AlertSeverity`` if the value is abnormal, or ``None`` if normal.
        """
        canonical = AlertClassifier._VITAL_NAME_MAP.get(vital_name.lower())
        if canonical is None:
            logger.debug("Unknown vital sign name: %s", vital_name)
            return None

        thresholds = AlertClassifier._VITAL_THRESHOLDS.get(canonical, [])
        for lower_bound, upper_bound, severity in thresholds:
            if lower_bound is not None and upper_bound is None:
                # Value must exceed lower_bound (high-side critical).
                if value > lower_bound:
                    return severity
            elif upper_bound is not None and lower_bound is None:
                # Value must be below upper_bound (low-side critical).
                if value < upper_bound:
                    return severity
            elif lower_bound is not None and upper_bound is not None:
                # Value must be within the range (inclusive).
                if lower_bound <= value <= upper_bound:
                    return severity

        return None

    # ------------------------------------------------------------------
    # Lab-result classifier
    # ------------------------------------------------------------------

    _LAB_THRESHOLDS: dict[str, list[tuple[float | None, float | None, AlertSeverity]]] = {
        # Potassium (mEq/L)
        "potassium": [
            (6.5, None, AlertSeverity.CRITICAL),
            (None, 2.5, AlertSeverity.CRITICAL),
            (6.0, None, AlertSeverity.URGENT),
            (None, 3.0, AlertSeverity.URGENT),
        ],
        # Sodium (mEq/L)
        "sodium": [
            (160.0, None, AlertSeverity.CRITICAL),
            (None, 120.0, AlertSeverity.CRITICAL),
            (155.0, None, AlertSeverity.URGENT),
            (None, 125.0, AlertSeverity.URGENT),
        ],
        # Glucose (mg/dL)
        "glucose": [
            (500.0, None, AlertSeverity.CRITICAL),
            (None, 40.0, AlertSeverity.CRITICAL),
            (400.0, None, AlertSeverity.URGENT),
            (None, 60.0, AlertSeverity.URGENT),
        ],
        # Lactate (mmol/L)
        "lactate": [
            (4.0, None, AlertSeverity.URGENT),
            (2.0, None, AlertSeverity.ROUTINE),
        ],
        # Troponin (ng/mL) -- any elevation is concerning
        "troponin": [
            (0.04, None, AlertSeverity.URGENT),
        ],
        # Creatinine (mg/dL)
        "creatinine": [
            (4.0, None, AlertSeverity.URGENT),
        ],
    }

    _LAB_NAME_MAP: dict[str, str] = {
        "potassium": "potassium",
        "k": "potassium",
        "k+": "potassium",
        "sodium": "sodium",
        "na": "sodium",
        "na+": "sodium",
        "glucose": "glucose",
        "blood_glucose": "glucose",
        "bg": "glucose",
        "lactate": "lactate",
        "lactic_acid": "lactate",
        "troponin": "troponin",
        "troponin_i": "troponin",
        "troponin_t": "troponin",
        "tnni": "troponin",
        "tnnt": "troponin",
        "creatinine": "creatinine",
        "cr": "creatinine",
        "scr": "creatinine",
    }

    @staticmethod
    def classify_lab_result(lab_name: str, value: float) -> AlertSeverity | None:
        """Classify a laboratory result against critical/panic thresholds.

        Supported labs (with aliases):
        * ``potassium`` / ``k`` / ``k+``
        * ``sodium`` / ``na`` / ``na+``
        * ``glucose`` / ``blood_glucose`` / ``bg``
        * ``lactate`` / ``lactic_acid``
        * ``troponin`` / ``troponin_i`` / ``troponin_t`` / ``tnni`` / ``tnnt``
        * ``creatinine`` / ``cr`` / ``scr``

        Args:
            lab_name: Name of the lab test (case-insensitive).
            value: Numeric lab result value.

        Returns:
            ``AlertSeverity`` if the value is abnormal, or ``None`` if normal.
        """
        canonical = AlertClassifier._LAB_NAME_MAP.get(lab_name.lower())
        if canonical is None:
            logger.debug("Unknown lab name: %s", lab_name)
            return None

        thresholds = AlertClassifier._LAB_THRESHOLDS.get(canonical, [])
        for lower_bound, upper_bound, severity in thresholds:
            if lower_bound is not None and upper_bound is None:
                if value > lower_bound:
                    return severity
            elif upper_bound is not None and lower_bound is None:
                if value < upper_bound:
                    return severity
            elif lower_bound is not None and upper_bound is not None:
                if lower_bound <= value <= upper_bound:
                    return severity

        return None


# ---------------------------------------------------------------------------
# Singleton access
# ---------------------------------------------------------------------------

_alert_manager_instance: AlertManager | None = None
_singleton_lock = threading.Lock()


def get_alert_manager() -> AlertManager:
    """Return the global ``AlertManager`` singleton.

    Thread-safe. The instance is created on first access and reused for
    all subsequent calls.

    Returns:
        The singleton ``AlertManager`` instance.
    """
    global _alert_manager_instance
    if _alert_manager_instance is None:
        with _singleton_lock:
            # Double-checked locking.
            if _alert_manager_instance is None:
                _alert_manager_instance = AlertManager()
    return _alert_manager_instance


def reset_alert_manager() -> None:
    """Reset the global singleton. Intended for testing only."""
    global _alert_manager_instance
    with _singleton_lock:
        _alert_manager_instance = None
