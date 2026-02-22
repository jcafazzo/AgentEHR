#!/usr/bin/env python3
"""
Post-Encounter Workflow

Processes encounter notes/transcripts to generate clinical action items:
- Medication orders (new prescriptions, refills, adjustments)
- Lab orders (routine monitoring, diagnostic workup)
- Imaging orders
- Follow-up appointments
- Referrals
- Patient communications/letters
- Care plan updates

The workflow analyzes clinical documentation and generates a batch of
draft actions for clinician review and approval.

Usage:
    workflow = PostEncounterWorkflow(orchestrator)
    result = await workflow.process_encounter(
        patient_id="patient-123",
        encounter_notes="Patient presents with...",
        encounter_type="follow_up"
    )
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import anthropic

logger = logging.getLogger("agentehr.workflows.post_encounter")


class ActionCategory(str, Enum):
    """Categories of post-encounter actions."""
    MEDICATION = "medication"
    LAB_ORDER = "lab_order"
    IMAGING_ORDER = "imaging_order"
    APPOINTMENT = "appointment"
    REFERRAL = "referral"
    COMMUNICATION = "communication"
    CARE_PLAN = "care_plan"
    DOCUMENTATION = "documentation"


class ActionPriority(str, Enum):
    """Priority levels for actions."""
    STAT = "stat"
    URGENT = "urgent"
    ROUTINE = "routine"
    LOW = "low"


@dataclass
class ProposedAction:
    """A proposed clinical action generated from the encounter."""
    category: ActionCategory
    priority: ActionPriority
    summary: str
    rationale: str
    tool_name: str
    tool_arguments: dict
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_review: bool = True


@dataclass
class EncounterAnalysis:
    """Analysis results from processing an encounter."""
    patient_id: str
    encounter_id: str | None
    encounter_type: str
    chief_complaint: str | None
    diagnoses: list[str]
    clinical_findings: list[str]
    assessment: str | None
    plan_items: list[str]
    proposed_actions: list[ProposedAction]
    metadata: dict = field(default_factory=dict)


@dataclass
class PostEncounterResult:
    """Result of post-encounter processing."""
    success: bool
    analysis: EncounterAnalysis | None
    executed_actions: list[dict]
    pending_action_ids: list[str]
    errors: list[str]
    summary: str


# System prompt for encounter analysis
ENCOUNTER_ANALYSIS_PROMPT = """You are a clinical AI assistant analyzing an encounter note to generate appropriate follow-up actions.

Your task is to:
1. Extract key clinical information from the encounter
2. Identify necessary follow-up actions based on clinical best practices
3. Generate specific, actionable items with proper clinical reasoning

## Clinical Categories to Consider

### Medications
- New prescriptions mentioned in the plan
- Medication adjustments (dose changes, discontinuations)
- Refill requests
- PRN medications for symptom management

### Laboratory Orders
- Routine monitoring for chronic conditions (e.g., A1c for diabetes, lipid panel for hyperlipidemia)
- Diagnostic workup for new symptoms
- Pre-procedure labs
- Drug level monitoring

### Imaging Orders
- Diagnostic imaging mentioned in plan
- Follow-up imaging for known findings
- Screening studies due

### Follow-up Appointments
- Specified follow-up intervals
- Condition-specific monitoring visits
- Urgent follow-up for concerning findings

### Referrals
- Specialist consultations mentioned
- Therapy referrals (PT, OT, etc.)
- Mental health referrals

### Communications
- Letters to referring physicians
- Patient education materials
- Insurance pre-authorizations

## Output Format

Analyze the encounter and output a JSON object with the following structure:

```json
{
    "chief_complaint": "Brief description",
    "diagnoses": ["Diagnosis 1", "Diagnosis 2"],
    "clinical_findings": ["Finding 1", "Finding 2"],
    "assessment": "Clinical assessment summary",
    "plan_items": ["Plan item 1", "Plan item 2"],
    "proposed_actions": [
        {
            "category": "medication|lab_order|imaging_order|appointment|referral|communication|care_plan",
            "priority": "stat|urgent|routine|low",
            "summary": "Brief action description",
            "rationale": "Clinical reasoning for this action",
            "tool_name": "create_medication_request|create_diagnostic_order|create_appointment|create_communication|create_care_plan",
            "tool_arguments": {
                // Tool-specific arguments
            },
            "evidence": ["Quote from encounter supporting this action"],
            "warnings": ["Any concerns or contraindications"]
        }
    ]
}
```

## Important Guidelines

1. Only propose actions that are clearly indicated by the encounter documentation
2. Include clinical rationale for each action
3. Flag any potential concerns or contraindications
4. Prioritize actions appropriately (stat/urgent for time-sensitive items)
5. Reference specific evidence from the encounter notes
6. Do not hallucinate or invent information not present in the notes

## Tool Arguments Reference

### create_medication_request
- patient_id, medication_name, dosage, frequency, route, duration, instructions

### create_diagnostic_order
- patient_id, order_type (lab/imaging), test_name, reason, priority, notes

### create_appointment
- patient_id, reason, appointment_type, preferred_date, duration_minutes

### create_communication
- patient_id, recipient_type, recipient_name, subject, content, category

### create_care_plan
- patient_id, title, description, goals, activities
"""


class PostEncounterWorkflow:
    """
    Workflow for processing encounter documentation and generating action items.

    Takes encounter notes or transcripts and uses Claude to analyze the clinical
    content and generate appropriate follow-up actions as draft items for
    clinician approval.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        tool_executor=None,
    ):
        """
        Initialize the post-encounter workflow.

        Args:
            api_key: Anthropic API key (or from ANTHROPIC_API_KEY env var)
            model: Claude model to use for analysis
            tool_executor: ToolExecutor instance for creating actions
        """
        import os
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY required")

        self.model = model
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.tool_executor = tool_executor

    async def process_encounter(
        self,
        patient_id: str,
        encounter_notes: str,
        encounter_type: str = "follow_up",
        encounter_id: str | None = None,
        patient_context: dict | None = None,
        auto_create_actions: bool = True,
    ) -> PostEncounterResult:
        """
        Process an encounter and generate action items.

        Args:
            patient_id: FHIR Patient ID
            encounter_notes: The encounter documentation (notes, transcript, etc.)
            encounter_type: Type of encounter (e.g., "follow_up", "new_patient", "urgent")
            encounter_id: Optional FHIR Encounter ID
            patient_context: Optional patient summary for additional context
            auto_create_actions: Whether to automatically create draft actions

        Returns:
            PostEncounterResult with analysis and created actions
        """
        errors = []
        executed_actions = []
        pending_action_ids = []

        try:
            # Step 1: Analyze the encounter
            analysis = await self._analyze_encounter(
                patient_id=patient_id,
                encounter_notes=encounter_notes,
                encounter_type=encounter_type,
                encounter_id=encounter_id,
                patient_context=patient_context,
            )

            if not analysis:
                return PostEncounterResult(
                    success=False,
                    analysis=None,
                    executed_actions=[],
                    pending_action_ids=[],
                    errors=["Failed to analyze encounter"],
                    summary="Encounter analysis failed",
                )

            # Step 2: Create draft actions if requested
            if auto_create_actions and self.tool_executor:
                for action in analysis.proposed_actions:
                    try:
                        result = await self._create_action(patient_id, action)
                        if result.get("success"):
                            executed_actions.append(result)
                            if result.get("action_id"):
                                pending_action_ids.append(result["action_id"])
                        else:
                            errors.append(f"Failed to create {action.category.value}: {result.get('error')}")
                    except Exception as e:
                        logger.exception(f"Error creating action: {action.summary}")
                        errors.append(f"Error creating {action.category.value}: {str(e)}")

            # Generate summary
            summary = self._generate_summary(analysis, executed_actions, errors)

            return PostEncounterResult(
                success=len(errors) == 0,
                analysis=analysis,
                executed_actions=executed_actions,
                pending_action_ids=pending_action_ids,
                errors=errors,
                summary=summary,
            )

        except Exception as e:
            logger.exception("Error processing encounter")
            return PostEncounterResult(
                success=False,
                analysis=None,
                executed_actions=[],
                pending_action_ids=[],
                errors=[str(e)],
                summary=f"Encounter processing failed: {str(e)}",
            )

    async def _analyze_encounter(
        self,
        patient_id: str,
        encounter_notes: str,
        encounter_type: str,
        encounter_id: str | None,
        patient_context: dict | None,
    ) -> EncounterAnalysis | None:
        """Analyze encounter notes using Claude."""
        # Build context message
        context_parts = [f"Encounter Type: {encounter_type}"]

        if patient_context:
            context_parts.append(f"Patient Context:\n{json.dumps(patient_context, indent=2)}")

        context_message = "\n\n".join(context_parts)

        # Call Claude for analysis
        user_message = f"""Please analyze the following encounter and generate appropriate follow-up actions.

{context_message}

## Encounter Notes

{encounter_notes}

---

Analyze this encounter and output a JSON object with the clinical analysis and proposed actions.
Remember to include patient_id="{patient_id}" in all tool_arguments.
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=ENCOUNTER_ANALYSIS_PROMPT,
                messages=[
                    {"role": "user", "content": user_message}
                ],
            )

            # Extract JSON from response
            response_text = response.content[0].text

            # Try to extract JSON from the response
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    logger.error(f"No JSON found in response: {response_text[:500]}")
                    return None

            analysis_data = json.loads(json_str)

            # Parse proposed actions
            proposed_actions = []
            for action_data in analysis_data.get("proposed_actions", []):
                try:
                    proposed_actions.append(ProposedAction(
                        category=ActionCategory(action_data.get("category", "documentation")),
                        priority=ActionPriority(action_data.get("priority", "routine")),
                        summary=action_data.get("summary", ""),
                        rationale=action_data.get("rationale", ""),
                        tool_name=action_data.get("tool_name", ""),
                        tool_arguments=action_data.get("tool_arguments", {}),
                        evidence=action_data.get("evidence", []),
                        warnings=action_data.get("warnings", []),
                        requires_review=action_data.get("requires_review", True),
                    ))
                except Exception as e:
                    logger.warning(f"Error parsing action: {e}")
                    continue

            return EncounterAnalysis(
                patient_id=patient_id,
                encounter_id=encounter_id,
                encounter_type=encounter_type,
                chief_complaint=analysis_data.get("chief_complaint"),
                diagnoses=analysis_data.get("diagnoses", []),
                clinical_findings=analysis_data.get("clinical_findings", []),
                assessment=analysis_data.get("assessment"),
                plan_items=analysis_data.get("plan_items", []),
                proposed_actions=proposed_actions,
                metadata={
                    "model": self.model,
                    "analyzed_at": datetime.now().isoformat(),
                },
            )

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return None
        except Exception as e:
            logger.exception("Error analyzing encounter")
            return None

    async def _create_action(self, patient_id: str, action: ProposedAction) -> dict:
        """Create a draft action using the tool executor."""
        if not self.tool_executor:
            return {
                "success": False,
                "error": "No tool executor configured",
                "action": action.summary,
            }

        # Ensure patient_id is in arguments
        arguments = action.tool_arguments.copy()
        arguments["patient_id"] = patient_id

        try:
            # Initialize if needed
            await self.tool_executor.initialize()

            # Execute the tool
            result = await self.tool_executor.execute(
                tool_name=action.tool_name,
                tool_use_id=f"post-encounter-{datetime.now().timestamp()}",
                arguments=arguments,
            )

            if result.success:
                return {
                    "success": True,
                    "action_id": result.result.get("action_id"),
                    "fhir_id": result.result.get("fhir_id") or _extract_fhir_id(result.result),
                    "category": action.category.value,
                    "summary": action.summary,
                    "rationale": action.rationale,
                    "result": result.result,
                }
            else:
                return {
                    "success": False,
                    "error": result.error,
                    "category": action.category.value,
                    "summary": action.summary,
                }

        except Exception as e:
            logger.exception(f"Error executing action: {action.summary}")
            return {
                "success": False,
                "error": str(e),
                "category": action.category.value,
                "summary": action.summary,
            }

    def _generate_summary(
        self,
        analysis: EncounterAnalysis,
        executed_actions: list[dict],
        errors: list[str],
    ) -> str:
        """Generate a human-readable summary of the processing results."""
        lines = []
        lines.append(f"## Post-Encounter Summary for Patient {analysis.patient_id}")
        lines.append(f"\nEncounter Type: {analysis.encounter_type}")

        if analysis.chief_complaint:
            lines.append(f"Chief Complaint: {analysis.chief_complaint}")

        if analysis.diagnoses:
            lines.append("\n### Diagnoses")
            for dx in analysis.diagnoses:
                lines.append(f"- {dx}")

        if analysis.assessment:
            lines.append(f"\n### Assessment\n{analysis.assessment}")

        lines.append(f"\n### Proposed Actions ({len(analysis.proposed_actions)} total)")

        # Group by category
        by_category = {}
        for action in analysis.proposed_actions:
            cat = action.category.value
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(action)

        for category, actions in by_category.items():
            lines.append(f"\n#### {category.replace('_', ' ').title()}")
            for action in actions:
                priority_icon = {
                    "stat": "[STAT]",
                    "urgent": "[URGENT]",
                    "routine": "",
                    "low": "[LOW]",
                }.get(action.priority.value, "")
                lines.append(f"- {priority_icon} {action.summary}")
                lines.append(f"  _Rationale: {action.rationale}_")
                if action.warnings:
                    for warning in action.warnings:
                        lines.append(f"  - Warning: {warning}")

        # Action creation results
        if executed_actions:
            lines.append(f"\n### Created Actions ({len(executed_actions)} drafts)")
            for result in executed_actions:
                status = "Created" if result.get("success") else "Failed"
                lines.append(f"- [{status}] {result.get('summary', 'Unknown')}")
                if result.get("action_id"):
                    lines.append(f"  Action ID: {result['action_id'][:8]}...")

        if errors:
            lines.append(f"\n### Errors ({len(errors)})")
            for error in errors:
                lines.append(f"- {error}")

        lines.append("\n---")
        lines.append("All actions require clinician review and approval.")

        return "\n".join(lines)

    def format_for_approval(self, result: PostEncounterResult) -> str:
        """
        Format the result for clinician approval workflow.

        Returns a formatted string suitable for display in a UI or CLI.
        """
        if not result.success or not result.analysis:
            return f"Error processing encounter:\n" + "\n".join(result.errors)

        lines = []
        lines.append("=" * 60)
        lines.append("POST-ENCOUNTER ACTION ITEMS FOR APPROVAL")
        lines.append("=" * 60)

        analysis = result.analysis

        lines.append(f"\nPatient ID: {analysis.patient_id}")
        lines.append(f"Encounter: {analysis.encounter_type}")
        if analysis.chief_complaint:
            lines.append(f"Chief Complaint: {analysis.chief_complaint}")

        lines.append(f"\nDiagnoses: {', '.join(analysis.diagnoses) if analysis.diagnoses else 'None documented'}")

        lines.append("\n" + "-" * 60)
        lines.append("PENDING ACTIONS")
        lines.append("-" * 60)

        for i, action_result in enumerate(result.executed_actions, 1):
            if action_result.get("success"):
                lines.append(f"\n[{i}] {action_result.get('category', 'Action').upper()}")
                lines.append(f"    Summary: {action_result.get('summary')}")
                lines.append(f"    Rationale: {action_result.get('rationale')}")
                lines.append(f"    Action ID: {action_result.get('action_id')}")
                lines.append(f"    Status: PENDING APPROVAL")

        if result.pending_action_ids:
            lines.append("\n" + "-" * 60)
            lines.append("APPROVAL COMMANDS")
            lines.append("-" * 60)
            lines.append("\nTo approve all actions:")
            for action_id in result.pending_action_ids:
                lines.append(f"  approve_action(action_id='{action_id}')")
            lines.append("\nTo reject an action:")
            lines.append("  reject_action(action_id='<id>', reason='<reason>')")

        lines.append("\n" + "=" * 60)

        return "\n".join(lines)


def _extract_fhir_id(result: dict) -> str | None:
    """Extract FHIR ID from various result formats."""
    if "medicationRequest" in result:
        return result["medicationRequest"].get("id")
    if "diagnosticOrder" in result:
        return result["diagnosticOrder"].get("id")
    if "appointment" in result:
        return result["appointment"].get("id")
    if "communication" in result:
        return result["communication"].get("id")
    if "carePlan" in result:
        return result["carePlan"].get("id")
    if "encounterNote" in result:
        return result["encounterNote"].get("id")
    return result.get("id")


# Factory function
def create_post_encounter_workflow(
    api_key: str | None = None,
    tool_executor=None,
) -> PostEncounterWorkflow:
    """
    Create a post-encounter workflow instance.

    Args:
        api_key: Anthropic API key
        tool_executor: Optional ToolExecutor for creating actions

    Returns:
        Configured PostEncounterWorkflow
    """
    return PostEncounterWorkflow(
        api_key=api_key,
        tool_executor=tool_executor,
    )


# Example usage and testing
async def _test():
    """Test the post-encounter workflow."""
    # Sample encounter note
    sample_encounter = """
PATIENT ENCOUNTER NOTE

Chief Complaint: Follow-up for diabetes management

History of Present Illness:
62-year-old female with type 2 diabetes mellitus presents for routine follow-up.
Reports good compliance with metformin 1000mg twice daily. Home glucose readings
averaging 140-160 mg/dL fasting. No hypoglycemic episodes. Occasional numbness
in feet, worse at night.

Current Medications:
- Metformin 1000mg BID
- Lisinopril 10mg daily
- Atorvastatin 20mg daily

Physical Exam:
BP: 138/84, Pulse: 72, Weight: 185 lbs (stable)
Feet: Diminished sensation to monofilament bilaterally, no ulcers
Cardiovascular: Regular rhythm, no murmurs

Assessment and Plan:
1. Type 2 Diabetes - Suboptimal control
   - Continue metformin
   - Start Jardiance 10mg daily for additional glycemic control and cardiovascular benefit
   - Order HbA1c, comprehensive metabolic panel
   - Diabetic foot exam shows early neuropathy - refer to podiatry

2. Hypertension - Borderline control
   - Increase lisinopril to 20mg daily
   - Recheck BP in 4 weeks

3. Hyperlipidemia - Continue atorvastatin
   - Order lipid panel

4. Health Maintenance
   - Due for annual eye exam - refer to ophthalmology for diabetic eye screening

Follow-up: Return in 3 months or sooner if needed. Call if any concerns.

Letter to be sent to referring physician Dr. Williams regarding patient's diabetes management.
"""

    # Create workflow without tool executor (analysis only)
    workflow = PostEncounterWorkflow()

    result = await workflow.process_encounter(
        patient_id="test-patient-123",
        encounter_notes=sample_encounter,
        encounter_type="follow_up",
        auto_create_actions=False,  # Don't actually create actions for test
    )

    print(result.summary)

    if result.analysis:
        print("\n\nRaw Analysis:")
        print(f"Diagnoses: {result.analysis.diagnoses}")
        print(f"Actions: {len(result.analysis.proposed_actions)}")
        for action in result.analysis.proposed_actions:
            print(f"  - [{action.category.value}] {action.summary}")


if __name__ == "__main__":
    asyncio.run(_test())
