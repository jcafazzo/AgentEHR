"""
Approval Queue for Clinical Actions

Manages pending clinical actions that require clinician approval before execution.
All create operations (medications, orders, etc.) are queued as drafts and require
explicit approval to become active.

Safety principle: No clinical action executes without clinician approval.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("fhir-mcp-server.approval")


class ActionStatus(str, Enum):
    """Status of a queued action."""
    PENDING = "pending"       # Awaiting approval
    APPROVED = "approved"     # Approved, ready to execute
    REJECTED = "rejected"     # Rejected by clinician
    EXECUTED = "executed"     # Successfully executed in FHIR
    FAILED = "failed"         # Execution failed


class ActionType(str, Enum):
    """Types of clinical actions that can be queued."""
    MEDICATION_REQUEST = "MedicationRequest"
    CARE_PLAN = "CarePlan"
    APPOINTMENT = "Appointment"
    SERVICE_REQUEST = "ServiceRequest"
    DOCUMENT_REFERENCE = "DocumentReference"
    COMMUNICATION = "Communication"
    # Phase 8 additions
    ALLERGY_INTOLERANCE = "AllergyIntolerance"
    CONDITION = "Condition"
    PROCEDURE = "Procedure"
    # Phase 1 inpatient additions
    ENCOUNTER = "Encounter"
    FLAG = "Flag"
    CLINICAL_IMPRESSION = "ClinicalImpression"
    RISK_ASSESSMENT = "RiskAssessment"
    TASK = "Task"
    CARE_TEAM = "CareTeam"
    GOAL = "Goal"
    DEVICE_METRIC = "DeviceMetric"
    ADVERSE_EVENT = "AdverseEvent"


@dataclass
class ValidationWarning:
    """A warning from clinical validation."""
    severity: str  # "info", "warning", "error"
    code: str      # e.g., "drug-interaction", "dosage-high"
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class PendingAction:
    """A clinical action awaiting approval."""
    action_id: str
    action_type: ActionType
    patient_id: str
    resource: dict  # The FHIR resource (draft)
    fhir_id: str | None  # ID assigned by FHIR server
    status: ActionStatus
    created_at: float
    updated_at: float
    summary: str  # Human-readable summary
    warnings: list[ValidationWarning] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "patient_id": self.patient_id,
            "fhir_id": self.fhir_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "warnings": [
                {
                    "severity": w.severity,
                    "code": w.code,
                    "message": w.message,
                    "details": w.details,
                }
                for w in self.warnings
            ],
            "resource": self.resource,
            "metadata": self.metadata,
        }


class ApprovalQueue:
    """
    In-memory approval queue for clinical actions.

    Thread-safe for single-process usage. For production, consider
    using Redis or a database for persistence and multi-process support.
    """

    def __init__(self):
        self._actions: dict[str, PendingAction] = {}
        self._patient_actions: dict[str, list[str]] = {}  # patient_id -> [action_ids]

    def queue_action(
        self,
        action_type: ActionType,
        patient_id: str,
        resource: dict,
        fhir_id: str | None,
        summary: str,
        warnings: list[ValidationWarning] | None = None,
        metadata: dict | None = None,
    ) -> PendingAction:
        """
        Queue a new clinical action for approval.

        Args:
            action_type: Type of FHIR resource
            patient_id: FHIR Patient ID
            resource: The FHIR resource (should have status=draft)
            fhir_id: ID assigned by FHIR server (if already created)
            summary: Human-readable description of the action
            warnings: Any validation warnings
            metadata: Additional context (e.g., requester info)

        Returns:
            The created PendingAction
        """
        action_id = str(uuid.uuid4())
        now = time.time()

        action = PendingAction(
            action_id=action_id,
            action_type=action_type,
            patient_id=patient_id,
            resource=resource,
            fhir_id=fhir_id,
            status=ActionStatus.PENDING,
            created_at=now,
            updated_at=now,
            summary=summary,
            warnings=warnings or [],
            metadata=metadata or {},
        )

        self._actions[action_id] = action

        if patient_id not in self._patient_actions:
            self._patient_actions[patient_id] = []
        self._patient_actions[patient_id].append(action_id)

        logger.info(f"Queued action {action_id}: {summary}")
        return action

    def get_action(self, action_id: str) -> PendingAction | None:
        """Get a specific action by ID."""
        return self._actions.get(action_id)

    def list_pending(self, patient_id: str | None = None) -> list[PendingAction]:
        """
        List all pending actions, optionally filtered by patient.

        Args:
            patient_id: Filter to specific patient (optional)

        Returns:
            List of pending actions
        """
        if patient_id:
            action_ids = self._patient_actions.get(patient_id, [])
            actions = [self._actions[aid] for aid in action_ids if aid in self._actions]
        else:
            actions = list(self._actions.values())

        # Filter to pending only
        pending = [a for a in actions if a.status == ActionStatus.PENDING]

        # Sort by created_at (oldest first)
        pending.sort(key=lambda a: a.created_at)

        return pending

    def approve(self, action_id: str) -> PendingAction | None:
        """
        Mark an action as approved.

        The caller is responsible for executing the FHIR update
        (changing status from draft to active).

        Args:
            action_id: The action to approve

        Returns:
            The updated action, or None if not found
        """
        action = self._actions.get(action_id)
        if not action:
            return None

        if action.status != ActionStatus.PENDING:
            logger.warning(f"Cannot approve action {action_id}: status is {action.status}")
            return action

        action.status = ActionStatus.APPROVED
        action.updated_at = time.time()

        logger.info(f"Approved action {action_id}: {action.summary}")
        return action

    def reject(self, action_id: str, reason: str | None = None) -> PendingAction | None:
        """
        Reject an action.

        The caller is responsible for deleting the draft FHIR resource.

        Args:
            action_id: The action to reject
            reason: Optional reason for rejection

        Returns:
            The updated action, or None if not found
        """
        action = self._actions.get(action_id)
        if not action:
            return None

        if action.status != ActionStatus.PENDING:
            logger.warning(f"Cannot reject action {action_id}: status is {action.status}")
            return action

        action.status = ActionStatus.REJECTED
        action.updated_at = time.time()
        if reason:
            action.metadata["rejection_reason"] = reason

        logger.info(f"Rejected action {action_id}: {action.summary} (reason: {reason})")
        return action

    def mark_executed(self, action_id: str) -> PendingAction | None:
        """Mark an approved action as executed."""
        action = self._actions.get(action_id)
        if not action:
            return None

        action.status = ActionStatus.EXECUTED
        action.updated_at = time.time()

        logger.info(f"Executed action {action_id}: {action.summary}")
        return action

    def mark_failed(self, action_id: str, error: str) -> PendingAction | None:
        """Mark an action as failed."""
        action = self._actions.get(action_id)
        if not action:
            return None

        action.status = ActionStatus.FAILED
        action.updated_at = time.time()
        action.metadata["error"] = error

        logger.error(f"Failed action {action_id}: {error}")
        return action

    def remove(self, action_id: str) -> bool:
        """
        Remove an action from the queue.

        Only removes from queue - does not affect FHIR resources.
        """
        action = self._actions.pop(action_id, None)
        if not action:
            return False

        # Remove from patient index
        if action.patient_id in self._patient_actions:
            try:
                self._patient_actions[action.patient_id].remove(action_id)
            except ValueError:
                pass

        return True

    def clear_patient(self, patient_id: str) -> int:
        """
        Clear all actions for a patient.

        Returns the number of actions removed.
        """
        action_ids = self._patient_actions.pop(patient_id, [])
        for action_id in action_ids:
            self._actions.pop(action_id, None)
        return len(action_ids)

    def stats(self) -> dict:
        """Get queue statistics."""
        status_counts = {}
        for action in self._actions.values():
            status = action.status.value
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "total_actions": len(self._actions),
            "total_patients": len(self._patient_actions),
            "by_status": status_counts,
        }


# Global singleton instance
_approval_queue: ApprovalQueue | None = None


def get_approval_queue() -> ApprovalQueue:
    """Get the global approval queue instance."""
    global _approval_queue
    if _approval_queue is None:
        _approval_queue = ApprovalQueue()
    return _approval_queue
