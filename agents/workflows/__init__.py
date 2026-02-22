"""
AgentEHR Workflows Module

Pre-built clinical workflows that orchestrate multiple tool calls
for common clinical use cases.

Available Workflows:
- PostEncounterWorkflow: Process encounter notes and generate action items
- MedicationOrderWorkflow: Guided medication ordering with safety checks
"""

from .post_encounter import (
    PostEncounterWorkflow,
    PostEncounterResult,
    EncounterAnalysis,
    ProposedAction,
    ActionCategory,
    ActionPriority,
    create_post_encounter_workflow,
)
from .medication_order import (
    MedicationOrderWorkflow,
    MedicationOrderRequest,
    MedicationOrderResult,
    create_medication_order_workflow,
)

__all__ = [
    # Post-encounter workflow
    "PostEncounterWorkflow",
    "PostEncounterResult",
    "EncounterAnalysis",
    "ProposedAction",
    "ActionCategory",
    "ActionPriority",
    "create_post_encounter_workflow",
    # Medication order workflow
    "MedicationOrderWorkflow",
    "MedicationOrderRequest",
    "MedicationOrderResult",
    "create_medication_order_workflow",
]
