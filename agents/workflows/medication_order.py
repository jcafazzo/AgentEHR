"""
Medication Ordering Workflow

Orchestrates the end-to-end medication ordering process:
1. Patient identification
2. Clinical context gathering
3. Drug interaction checking
4. Order creation with safety warnings
5. Approval queue management

This workflow is designed to be used with Claude or other LLM agents
via the MCP server tools.
"""

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class MedicationOrderRequest:
    """Request to order a medication."""
    patient_query: str  # Name, MRN, or other identifier
    medication_name: str
    dosage: str
    frequency: str
    route: str | None = None
    instructions: str | None = None
    reason: str | None = None


@dataclass
class MedicationOrderResult:
    """Result of a medication order attempt."""
    success: bool
    action_id: str | None
    fhir_id: str | None
    patient_id: str | None
    patient_name: str | None
    medication: str
    warnings: list[dict]
    requires_attention: bool
    message: str


class MedicationOrderWorkflow:
    """
    Workflow for ordering medications with safety checks.

    This class provides the orchestration logic for the medication
    ordering use case. It coordinates multiple MCP tool calls to:

    1. Identify the correct patient
    2. Retrieve relevant clinical context
    3. Check for drug interactions and allergies
    4. Create the medication order as a draft
    5. Queue for clinician approval

    Usage with Claude/MCP:

    The agent should follow this workflow when ordering medications:

    1. Use search_patient to find the patient
    2. Use get_patient_summary to understand context
    3. Use create_medication_request to create the draft order
    4. Present the result (including any warnings) to the clinician
    5. Use approve_action or reject_action based on clinician decision
    """

    # Workflow state machine
    STATES = [
        "initial",
        "patient_identified",
        "context_gathered",
        "order_created",
        "approval_pending",
        "approved",
        "rejected",
        "failed",
    ]

    def __init__(self):
        self.state = "initial"
        self.patient_id = None
        self.patient_name = None
        self.patient_context = None
        self.order_request = None
        self.order_result = None

    def get_workflow_prompt(self) -> str:
        """
        Get the system prompt for guiding the agent through this workflow.

        This prompt should be included when the agent is handling
        medication ordering tasks.
        """
        return """
## Medication Ordering Workflow

When ordering medications, follow these steps:

### Step 1: Identify Patient
Use the `search_patient` tool to find the patient by name or identifier.
- If multiple matches, ask for clarification
- If no match, report the issue

### Step 2: Gather Clinical Context
Use the `get_patient_summary` tool to retrieve:
- Current medications (for interaction checking)
- Known allergies
- Active conditions
- Recent encounters

### Step 3: Create Medication Order
Use the `create_medication_request` tool with:
- patient_id: The FHIR patient ID
- medication_name: Name of the medication
- dosage: Dose amount (e.g., "500mg")
- frequency: Dosing frequency (e.g., "twice daily")
- route: (optional) Route of administration
- instructions: (optional) Special instructions

The system will automatically:
- Check for drug-drug interactions
- Check for drug-allergy interactions
- Create the order as a DRAFT
- Queue for approval

### Step 4: Present for Approval
Present the order details to the clinician, including:
- Patient name and context
- Medication details
- ANY warnings (drug interactions, allergies)
- The action_id for approval

### Step 5: Handle Approval Decision
Based on clinician decision:
- Use `approve_action` to activate the order
- Use `reject_action` to cancel and delete the draft

### Safety Principles
1. NEVER skip interaction checking
2. ALWAYS present warnings prominently
3. Orders require explicit clinician approval
4. Document the reason for any override of warnings
"""

    def format_order_summary(
        self,
        patient_name: str,
        medication: str,
        dosage: str,
        frequency: str,
        warnings: list[dict],
        action_id: str,
    ) -> str:
        """
        Format a human-readable summary of the medication order
        for clinician review.
        """
        summary = f"""
## Medication Order for {patient_name}

**Medication:** {medication}
**Dosage:** {dosage}
**Frequency:** {frequency}
**Action ID:** {action_id}
"""

        if warnings:
            summary += "\n### ⚠️ Safety Warnings\n"
            for w in warnings:
                severity_emoji = {
                    "contraindicated": "🚫",
                    "severe": "🔴",
                    "moderate": "🟡",
                    "minor": "🟢",
                    "info": "ℹ️",
                }.get(w.get("severity", "info"), "⚠️")

                summary += f"\n{severity_emoji} **{w.get('severity', 'warning').upper()}**: {w.get('message', 'Unknown warning')}\n"
                if recommendation := w.get("details", {}).get("recommendation"):
                    summary += f"   _Recommendation: {recommendation}_\n"
        else:
            summary += "\n✅ No drug interactions or allergy concerns detected.\n"

        summary += """
---
**Actions:**
- To approve: Use `approve_action` with action_id
- To reject: Use `reject_action` with action_id and reason
"""
        return summary


# Workflow prompt for the clinical reasoning system
MEDICATION_ORDER_SYSTEM_PROMPT = """
You are a clinical decision support agent helping clinicians order medications safely.

Your responsibilities:
1. Accurately identify patients
2. Gather relevant clinical context
3. Check for drug interactions and allergies
4. Create medication orders as drafts
5. Present safety warnings clearly
6. Wait for explicit clinician approval

CRITICAL SAFETY RULES:
- All medication orders are created as DRAFTS requiring approval
- NEVER auto-approve orders - always wait for clinician decision
- ALWAYS prominently display any drug interaction or allergy warnings
- If a contraindication is detected, recommend against the order
- Document the clinical reasoning and any warning overrides

When presenting orders for approval, use this format:

---
## 📋 Medication Order Ready for Review

**Patient:** [Name] (ID: [patient_id])
**Medication:** [drug name]
**Dosage:** [dose] [frequency]
**Route:** [route]

### Clinical Context
- Current Meds: [list relevant]
- Allergies: [list relevant]
- Conditions: [list relevant]

### Safety Check
[✅ No concerns / ⚠️ Warnings listed]

### Actions
- **Approve:** `approve_action` (action_id: [id])
- **Reject:** `reject_action` (action_id: [id], reason: "[reason]")
---
"""


def create_medication_order_workflow() -> MedicationOrderWorkflow:
    """Factory function to create a new medication order workflow."""
    return MedicationOrderWorkflow()
