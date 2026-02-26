"""
Patient State Data Models for Inpatient Care Oversight

Provides typed data containers for tracking a patient's clinical state
with per-category freshness timestamps (NFR-05), FHIR resource provenance
tracking (NFR-04), and helper methods for converting state into formats
expected by the clinical scoring system and LLM supervisor prompt.

Usage:
    from agents.patient_state import PatientState, VitalSigns, LabResult

    state = PatientState(patient_id="patient-123", encounter_id="enc-456")
    state.vitals_history.append(VitalSigns(
        timestamp=datetime.now(timezone.utc),
        heart_rate=88.0,
        systolic_bp=120.0,
    ))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("agentehr.patient_state")


# =============================================================================
# VitalSigns
# =============================================================================


@dataclass
class VitalSigns:
    """A single vitals measurement set, typically parsed from FHIR Observations.

    Attributes:
        timestamp: When the measurement was taken.
        heart_rate: Heart rate in beats per minute.
        systolic_bp: Systolic blood pressure in mmHg.
        diastolic_bp: Diastolic blood pressure in mmHg.
        respiratory_rate: Breaths per minute.
        spo2: Oxygen saturation percentage (0-100).
        temperature_c: Body temperature in Celsius.
        consciousness: AVPU scale value -- A (alert), C (confusion),
            V (voice), P (pain), U (unresponsive).
        gcs: Glasgow Coma Scale score (3-15).
        supplemental_o2: Whether patient is on supplemental oxygen.
        fhir_observation_ids: FHIR Observation resource IDs for provenance
            tracking (NFR-04).
    """

    timestamp: datetime
    heart_rate: float | None = None
    systolic_bp: float | None = None
    diastolic_bp: float | None = None
    respiratory_rate: float | None = None
    spo2: float | None = None
    temperature_c: float | None = None
    consciousness: str = "A"
    gcs: int | None = None
    supplemental_o2: bool = False
    fhir_observation_ids: list[str] = field(default_factory=list)


# =============================================================================
# LabResult
# =============================================================================


@dataclass
class LabResult:
    """A single laboratory result, parsed from a FHIR Observation.

    Attributes:
        name: Standardized lab name (e.g. "creatinine", "platelets").
        value: Numeric result value.
        unit: Unit of measurement (e.g. "mg/dL", "x10^3/uL").
        timestamp: When the specimen was collected or result reported.
        loinc_code: LOINC code for the lab test.
        reference_low: Lower bound of the reference range.
        reference_high: Upper bound of the reference range.
        is_abnormal: Whether the value is outside the reference range.
        fhir_observation_id: FHIR Observation resource ID for provenance
            tracking (NFR-04).
    """

    name: str
    value: float
    unit: str
    timestamp: datetime
    loinc_code: str = ""
    reference_low: float | None = None
    reference_high: float | None = None
    is_abnormal: bool = False
    fhir_observation_id: str = ""


# =============================================================================
# Finding
# =============================================================================


@dataclass
class Finding:
    """A clinical finding produced by LLM evaluation or deterministic analysis.

    Attributes:
        category: Clinical domain (e.g. "sepsis", "cardiac", "renal",
            "pulmonary", "medication", "general").
        severity: Maps to AlertSeverity values -- "critical", "urgent",
            "routine", "informational".
        title: Brief human-readable finding title.
        description: Detailed clinical reasoning with data citations.
        evidence: List of evidence citations for provenance (NFR-04).
            Each dict has keys like type, name, value, timestamp.
        recommended_actions: Suggested clinician actions for approval queue.
        spawn_trigger: Specialist agent hint for Phase 6 (e.g.
            "infectious_disease", "cardiology", "renal"). None if no
            specialist needed.
    """

    category: str
    severity: str
    title: str
    description: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    spawn_trigger: str | None = None


# =============================================================================
# EvaluationResult
# =============================================================================


@dataclass
class EvaluationResult:
    """Result of a single supervisor evaluation cycle.

    Captures timing, scores, alerts, findings, and data gaps from one
    complete cycle of the supervisor's evaluate() method.

    Attributes:
        cycle_id: Unique identifier for this evaluation cycle.
        timestamp: When the cycle started.
        cycle_duration_seconds: Wall-clock time for the full cycle.
        scores: Output of calculate_all_available_scores(), keyed by
            score name (e.g. "NEWS2", "qSOFA").
        alerts_generated: Alert IDs created during this cycle.
        findings: Clinical findings from LLM and/or deterministic analysis.
        spawn_triggers: Specialist agent triggers identified (Phase 6 hooks).
        data_gaps: Missing parameters that could affect clinical decisions
            (e.g. "GCS not available for qSOFA calculation").
    """

    cycle_id: str
    timestamp: datetime
    cycle_duration_seconds: float
    scores: dict[str, dict] = field(default_factory=dict)
    alerts_generated: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    spawn_triggers: list[str] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)


# =============================================================================
# PatientState
# =============================================================================


@dataclass
class PatientState:
    """Complete clinical state for a monitored inpatient.

    Holds all clinical data categories with per-category freshness
    timestamps (NFR-05), provenance via FHIR resource IDs (NFR-04),
    and helper methods for scoring system integration and LLM context
    generation.

    Attributes:
        patient_id: FHIR Patient resource ID.
        encounter_id: FHIR Encounter resource ID for the current admission.
        patient_name: Human-readable patient name.
        last_updated: Timestamp of the most recent state mutation.
        vitals_history: Ordered list of vitals measurements (most recent last).
        vitals_fetched_at: When vitals were last fetched from FHIR.
        lab_results: List of lab results.
        labs_fetched_at: When labs were last fetched from FHIR.
        active_conditions: Simplified FHIR Condition resources.
        conditions_fetched_at: When conditions were last fetched from FHIR.
        active_medications: Simplified FHIR MedicationRequest resources.
        medications_fetched_at: When medications were last fetched from FHIR.
        care_team: List of care team members [{name, role}].
        scores: Output of calculate_all_available_scores(), keyed by name.
        active_alert_ids: IDs of active alerts from AlertManager.
        spawn_triggers: Specialist agent triggers (Phase 6 hooks).
        evaluation_history: Recent EvaluationResult records.
    """

    patient_id: str
    encounter_id: str
    patient_name: str = ""
    last_updated: datetime | None = None

    # Vitals with freshness tracking
    vitals_history: list[VitalSigns] = field(default_factory=list)
    vitals_fetched_at: datetime | None = None

    # Labs with freshness tracking
    lab_results: list[LabResult] = field(default_factory=list)
    labs_fetched_at: datetime | None = None

    # Conditions with freshness tracking
    active_conditions: list[dict[str, Any]] = field(default_factory=list)
    conditions_fetched_at: datetime | None = None

    # Medications with freshness tracking
    active_medications: list[dict[str, Any]] = field(default_factory=list)
    medications_fetched_at: datetime | None = None

    # Care team
    care_team: list[dict[str, str]] = field(default_factory=list)

    # Computed clinical scores
    scores: dict[str, dict] = field(default_factory=dict)

    # Alert tracking
    active_alert_ids: list[str] = field(default_factory=list)

    # Phase 6 hooks
    spawn_triggers: list[str] = field(default_factory=list)

    # Evaluation history
    evaluation_history: list[EvaluationResult] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Freshness checks (NFR-05)
    # ------------------------------------------------------------------ #

    def is_vitals_fresh(self, max_age_seconds: int = 60) -> bool:
        """Check if vitals data is within the freshness window.

        Args:
            max_age_seconds: Maximum acceptable age in seconds (default 60s
                per NFR-05).

        Returns:
            True if vitals were fetched within *max_age_seconds* of now.
        """
        if self.vitals_fetched_at is None:
            return False
        age = (datetime.now(timezone.utc) - self.vitals_fetched_at).total_seconds()
        return age < max_age_seconds

    def is_meds_fresh(self, max_age_seconds: int = 300) -> bool:
        """Check if medication data is within the freshness window.

        Args:
            max_age_seconds: Maximum acceptable age in seconds (default 300s
                per NFR-05).

        Returns:
            True if medications were fetched within *max_age_seconds* of now.
        """
        if self.medications_fetched_at is None:
            return False
        age = (datetime.now(timezone.utc) - self.medications_fetched_at).total_seconds()
        return age < max_age_seconds

    def is_conditions_fresh(self, max_age_seconds: int = 300) -> bool:
        """Check if conditions data is within the freshness window.

        Args:
            max_age_seconds: Maximum acceptable age in seconds (default 300s
                per NFR-05).

        Returns:
            True if conditions were fetched within *max_age_seconds* of now.
        """
        if self.conditions_fetched_at is None:
            return False
        age = (datetime.now(timezone.utc) - self.conditions_fetched_at).total_seconds()
        return age < max_age_seconds

    def is_labs_fresh(self, max_age_seconds: int = 300) -> bool:
        """Check if lab data is within the freshness window.

        Args:
            max_age_seconds: Maximum acceptable age in seconds (default 300s
                per NFR-05).

        Returns:
            True if labs were fetched within *max_age_seconds* of now.
        """
        if self.labs_fetched_at is None:
            return False
        age = (datetime.now(timezone.utc) - self.labs_fetched_at).total_seconds()
        return age < max_age_seconds

    # ------------------------------------------------------------------ #
    # Data access helpers
    # ------------------------------------------------------------------ #

    def latest_vitals(self) -> VitalSigns | None:
        """Return the most recent vitals measurement, or None if empty."""
        if not self.vitals_history:
            return None
        return self.vitals_history[-1]

    def get_vitals_dict(self) -> dict[str, Any]:
        """Convert latest vitals to the dict format expected by
        ``calculate_all_available_scores()``.

        Maps VitalSigns fields to the keys documented in the scoring
        interface: heart_rate, systolic_bp, diastolic_bp, respiratory_rate,
        spo2, temperature_c, consciousness, gcs, supplemental_o2.

        Only includes non-None values (except supplemental_o2 which always
        has a boolean value).

        Returns:
            Dict suitable for passing as the ``vitals`` argument to
            ``calculate_all_available_scores()``. Empty dict if no vitals.
        """
        latest = self.latest_vitals()
        if latest is None:
            return {}

        vitals: dict[str, Any] = {}

        if latest.heart_rate is not None:
            vitals["heart_rate"] = latest.heart_rate
        if latest.systolic_bp is not None:
            vitals["systolic_bp"] = latest.systolic_bp
        if latest.diastolic_bp is not None:
            vitals["diastolic_bp"] = latest.diastolic_bp
        if latest.respiratory_rate is not None:
            vitals["respiratory_rate"] = latest.respiratory_rate
        if latest.spo2 is not None:
            vitals["spo2"] = latest.spo2
        if latest.temperature_c is not None:
            vitals["temperature_c"] = latest.temperature_c
        if latest.consciousness:
            vitals["consciousness"] = latest.consciousness
        if latest.gcs is not None:
            vitals["gcs"] = latest.gcs
        vitals["supplemental_o2"] = latest.supplemental_o2

        return vitals

    def get_labs_dict(self) -> dict[str, Any]:
        """Convert lab results to the dict format expected by
        ``calculate_all_available_scores()``.

        Groups lab results by standardized name and uses the most recent
        value for each. Maps to the keys expected by the scoring interface:
        creatinine, baseline_creatinine, platelets, bilirubin, lactate,
        pao2_fio2_ratio, wbc, etc.

        Returns:
            Dict suitable for passing as the ``labs`` argument to
            ``calculate_all_available_scores()``. Empty dict if no labs.
        """
        if not self.lab_results:
            return {}

        # Group by name, keeping most recent per name
        latest_by_name: dict[str, LabResult] = {}
        for lab in self.lab_results:
            key = lab.name.lower().replace(" ", "_")
            existing = latest_by_name.get(key)
            if existing is None or lab.timestamp > existing.timestamp:
                latest_by_name[key] = lab

        return {name: lab.value for name, lab in latest_by_name.items()}

    # ------------------------------------------------------------------ #
    # LLM context generation
    # ------------------------------------------------------------------ #

    def to_clinical_summary(self) -> str:
        """Generate a concise text summary for LLM context injection.

        Produces a structured, human-readable clinical summary that avoids
        context window overflow (Pitfall 1 from research). Uses latest
        vitals only (not full history). Groups labs by name showing most
        recent value.

        Returns:
            Multi-line string suitable for injection into the supervisor
            system prompt's ``{patient_clinical_summary}`` placeholder.
        """
        lines: list[str] = []

        # Header
        lines.append(f"Patient: {self.patient_name} (ID: {self.patient_id})")
        lines.append(f"Encounter: {self.encounter_id}")
        lines.append("")

        # Vital signs
        latest = self.latest_vitals()
        if latest is not None:
            ts = self.vitals_fetched_at or latest.timestamp
            lines.append(f"VITAL SIGNS (as of {ts.isoformat()}):")
            parts: list[str] = []
            if latest.heart_rate is not None:
                parts.append(f"HR: {latest.heart_rate}")
            if latest.systolic_bp is not None and latest.diastolic_bp is not None:
                parts.append(f"BP: {latest.systolic_bp}/{latest.diastolic_bp}")
            elif latest.systolic_bp is not None:
                parts.append(f"SBP: {latest.systolic_bp}")
            if latest.respiratory_rate is not None:
                parts.append(f"RR: {latest.respiratory_rate}")
            if latest.spo2 is not None:
                parts.append(f"SpO2: {latest.spo2}%")
            if latest.temperature_c is not None:
                parts.append(f"Temp: {latest.temperature_c}C")
            parts.append(f"Consciousness: {latest.consciousness}")
            if latest.gcs is not None:
                parts.append(f"GCS: {latest.gcs}")
            if latest.supplemental_o2:
                parts.append("On supplemental O2")
            lines.append(" | ".join(parts))
        else:
            lines.append("VITAL SIGNS: No data available")
        lines.append("")

        # Active conditions
        lines.append("ACTIVE CONDITIONS:")
        if self.active_conditions:
            for cond in self.active_conditions:
                display = cond.get("display", cond.get("code", "Unknown"))
                code = cond.get("snomed_code", cond.get("code", ""))
                if code and code != display:
                    lines.append(f"- {display} (SNOMED: {code})")
                else:
                    lines.append(f"- {display}")
        else:
            lines.append("- None documented")
        lines.append("")

        # Active medications
        lines.append("ACTIVE MEDICATIONS:")
        if self.active_medications:
            for med in self.active_medications:
                display = med.get("display", med.get("medication", "Unknown"))
                dosage = med.get("dosage", "")
                if dosage:
                    lines.append(f"- {display} -- {dosage}")
                else:
                    lines.append(f"- {display}")
        else:
            lines.append("- None documented")
        lines.append("")

        # Recent labs
        lines.append("RECENT LABS:")
        if self.lab_results:
            # Group by name, show most recent
            latest_by_name: dict[str, LabResult] = {}
            for lab in self.lab_results:
                key = lab.name
                existing = latest_by_name.get(key)
                if existing is None or lab.timestamp > existing.timestamp:
                    latest_by_name[key] = lab

            for name, lab in sorted(latest_by_name.items()):
                abnormal_flag = " [ABNORMAL]" if lab.is_abnormal else ""
                loinc = f" (LOINC: {lab.loinc_code})" if lab.loinc_code else ""
                lines.append(
                    f"- {name}: {lab.value} {lab.unit}{abnormal_flag}{loinc}"
                )
        else:
            lines.append("- No results available")
        lines.append("")

        # Clinical scores
        lines.append("CLINICAL SCORES:")
        if self.scores:
            for score_name, score_data in sorted(self.scores.items()):
                if score_name == "NEWS2":
                    total = score_data.get("total_score", "?")
                    risk = score_data.get("risk_level", "?")
                    lines.append(f"- NEWS2: {total} ({risk})")
                elif score_name == "qSOFA":
                    score_val = score_data.get("score", "?")
                    sepsis = "sepsis risk" if score_data.get("sepsis_risk") else "low risk"
                    lines.append(f"- qSOFA: {score_val} ({sepsis})")
                elif score_name == "SOFA":
                    total = score_data.get("total_score", "?")
                    mortality = score_data.get("mortality_estimate", "?")
                    lines.append(f"- SOFA: {total} (mortality {mortality})")
                elif score_name == "KDIGO":
                    stage = score_data.get("stage", "?")
                    lines.append(f"- KDIGO: Stage {stage}")
                else:
                    lines.append(f"- {score_name}: {score_data}")
        else:
            lines.append("- No scores calculated")
        lines.append("")

        # Active alerts
        alert_count = len(self.active_alert_ids)
        lines.append(f"ACTIVE ALERTS: {alert_count}")

        return "\n".join(lines)
