#!/usr/bin/env python3
"""
OpenRouter Orchestrator for AgentEHR

Uses OpenRouter API to connect various LLMs (GLM-5, Claude, GPT-4, etc.)
to the FHIR MCP server tools.
"""

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "fhir-mcp-server" / "src"))

from openrouter_client import OpenRouterClient, ToolCall

logger = logging.getLogger("agentehr.openrouter_orchestrator")

# Load prompts
PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_clinical_reasoning_prompt() -> str:
    """Load the clinical reasoning system prompt."""
    prompt_path = PROMPTS_DIR / "clinical_reasoning.md"
    if prompt_path.exists():
        return prompt_path.read_text()
    return ""


# Tool definitions (same as main orchestrator)
FHIR_TOOLS = [
    {
        "name": "search_patient",
        "description": "Search for patients by name, identifier, or other criteria.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (name, MRN, etc.)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_patient",
        "description": "Get detailed patient demographics by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "get_patient_summary",
        "description": "Get a comprehensive patient summary including conditions, medications, allergies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "search_medications",
        "description": "Search for a patient's medications.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "status": {"type": "string", "enum": ["active", "completed", "stopped"]},
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "create_medication_request",
        "description": "Create a medication order (as draft, requires approval).",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "medication_name": {"type": "string", "description": "Name of medication"},
                "dosage": {"type": "string", "description": "Dosage (e.g., '500 mg')"},
                "frequency": {"type": "string", "description": "Frequency (e.g., 'twice daily')"},
                "route": {"type": "string", "enum": ["oral", "intravenous", "subcutaneous"]},
                "instructions": {"type": "string", "description": "Additional instructions"},
            },
            "required": ["patient_id", "medication_name", "dosage", "frequency"],
        },
    },
    {
        "name": "list_pending_actions",
        "description": "List all pending clinical actions awaiting approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "Filter by patient ID (optional)"},
            },
        },
    },
    {
        "name": "approve_action",
        "description": "Approve a pending clinical action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "Action ID to approve"},
            },
            "required": ["action_id"],
        },
    },
    {
        "name": "reject_action",
        "description": "Reject a pending clinical action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "Action ID to reject"},
                "reason": {"type": "string", "description": "Reason for rejection"},
            },
            "required": ["action_id"],
        },
    },
    {
        "name": "update_medication_status",
        "description": "Update the status of an existing medication. Use this to discontinue, stop, cancel, or reactivate medications.",
        "input_schema": {
            "type": "object",
            "properties": {
                "medication_id": {"type": "string", "description": "FHIR MedicationRequest ID to update"},
                "new_status": {
                    "type": "string",
                    "enum": ["active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft"],
                    "description": "New status. Use 'stopped' to discontinue, 'cancelled' to cancel, 'entered-in-error' for duplicates",
                },
                "reason": {"type": "string", "description": "Reason for the status change (required for audit)"},
            },
            "required": ["medication_id", "new_status", "reason"],
        },
    },
    {
        "name": "delete_medication_request",
        "description": "Delete a medication request record. Use this to remove duplicate entries or erroneous records. Only draft or entered-in-error records can be deleted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "medication_id": {"type": "string", "description": "FHIR MedicationRequest ID to delete"},
                "reason": {"type": "string", "description": "Reason for deletion (e.g., 'duplicate entry')"},
            },
            "required": ["medication_id", "reason"],
        },
    },
    {
        "name": "reconcile_medications",
        "description": "Reconcile a patient's medication list by keeping specified medications active and discontinuing or removing others. Use for medication reconciliation workflows.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "keep_medication_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of MedicationRequest IDs to keep active",
                },
                "discontinue_medication_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of MedicationRequest IDs to discontinue (mark as stopped)",
                },
                "delete_medication_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of MedicationRequest IDs to delete (duplicates or errors)",
                },
                "reason": {"type": "string", "description": "Clinical reason for reconciliation"},
            },
            "required": ["patient_id", "reason"],
        },
    },

    # =============================================================================
    # Phase 8: Comprehensive Clinical Tools
    # =============================================================================

    # Allergy Management
    {
        "name": "create_allergy_intolerance",
        "description": "Document a patient allergy or intolerance. Critical for medication safety.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "substance": {"type": "string", "description": "Allergen (drug, food, environmental)"},
                "reaction": {"type": "string", "description": "Reaction type (rash, anaphylaxis, etc.)"},
                "severity": {"type": "string", "enum": ["mild", "moderate", "severe"]},
                "criticality": {"type": "string", "enum": ["low", "high", "unable-to-assess"]},
                "category": {"type": "string", "enum": ["food", "medication", "environment", "biologic"]},
            },
            "required": ["patient_id", "substance", "category"],
        },
    },
    {
        "name": "update_allergy_intolerance",
        "description": "Update an existing allergy record (status, severity, add reactions).",
        "input_schema": {
            "type": "object",
            "properties": {
                "allergy_id": {"type": "string", "description": "FHIR AllergyIntolerance ID"},
                "clinical_status": {"type": "string", "enum": ["active", "inactive", "resolved"]},
                "verification_status": {"type": "string", "enum": ["confirmed", "refuted", "unconfirmed"]},
                "new_reaction": {"type": "string", "description": "Additional reaction to document"},
            },
            "required": ["allergy_id"],
        },
    },

    # Problem List Management
    {
        "name": "add_condition",
        "description": "Add a diagnosis or problem to the patient's problem list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "condition_name": {"type": "string", "description": "Condition/diagnosis name"},
                "icd10_code": {"type": "string", "description": "ICD-10 code (e.g., 'E11.9')"},
                "clinical_status": {"type": "string", "enum": ["active", "recurrence", "relapse", "inactive", "remission", "resolved"]},
                "onset_date": {"type": "string", "description": "Date condition started (YYYY-MM-DD)"},
                "notes": {"type": "string", "description": "Clinical notes"},
            },
            "required": ["patient_id", "condition_name"],
        },
    },
    {
        "name": "update_condition_status",
        "description": "Update the status of an existing condition (resolve, inactivate, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "condition_id": {"type": "string", "description": "FHIR Condition ID"},
                "clinical_status": {"type": "string", "enum": ["active", "inactive", "resolved"]},
                "abatement_date": {"type": "string", "description": "Date condition resolved (YYYY-MM-DD)"},
                "reason": {"type": "string", "description": "Reason for status change"},
            },
            "required": ["condition_id", "clinical_status"],
        },
    },

    # Procedure Documentation
    {
        "name": "create_procedure",
        "description": "Document a procedure performed on the patient.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "procedure_name": {"type": "string", "description": "Name of procedure"},
                "cpt_code": {"type": "string", "description": "CPT code (optional)"},
                "performed_date": {"type": "string", "description": "Date performed (YYYY-MM-DD)"},
                "notes": {"type": "string", "description": "Procedure notes"},
                "outcome": {"type": "string", "description": "Outcome/findings"},
            },
            "required": ["patient_id", "procedure_name"],
        },
    },
    {
        "name": "search_procedures",
        "description": "Search for procedures performed on a patient.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
            },
            "required": ["patient_id"],
        },
    },

    # Lab Results with Decision Support
    {
        "name": "get_lab_results_with_trends",
        "description": "Get lab results with trend analysis (improving, stable, worsening).",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "lab_type": {"type": "string", "description": "Lab type (e.g., 'A1C', 'creatinine')"},
                "months_back": {"type": "integer", "description": "How many months of history (default: 12)"},
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "check_renal_function",
        "description": "Get renal function (eGFR, creatinine) for medication dosing decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
            },
            "required": ["patient_id"],
        },
    },

    # Quick Documentation
    {
        "name": "document_counseling",
        "description": "Quick documentation of counseling provided (smoking, diet, exercise, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "counseling_type": {"type": "string", "enum": ["smoking_cessation", "diet_nutrition", "exercise", "medication_adherence", "disease_education", "other"]},
                "duration_minutes": {"type": "integer", "description": "Time spent counseling"},
                "notes": {"type": "string", "description": "Counseling details"},
            },
            "required": ["patient_id", "counseling_type"],
        },
    },
    {
        "name": "create_work_note",
        "description": "Generate a work/school excuse note for the patient.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "excuse_from_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "excuse_to_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                "reason": {"type": "string", "description": "General reason (no PHI)"},
                "restrictions": {"type": "string", "description": "Work restrictions if any"},
            },
            "required": ["patient_id", "excuse_from_date", "excuse_to_date"],
        },
    },
    {
        "name": "create_phone_encounter",
        "description": "Document a phone call with patient (refill request, test result, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "call_type": {"type": "string", "enum": ["refill_request", "test_results", "symptom_followup", "general_question", "referral_coordination"]},
                "duration_minutes": {"type": "integer", "description": "Call duration"},
                "summary": {"type": "string", "description": "Call summary"},
                "action_taken": {"type": "string", "description": "What was done"},
            },
            "required": ["patient_id", "call_type", "summary"],
        },
    },

    # Referral Management
    {
        "name": "create_referral",
        "description": "Create a referral to a specialist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "specialty": {"type": "string", "description": "Specialty (cardiology, dermatology, etc.)"},
                "reason": {"type": "string", "description": "Reason for referral"},
                "urgency": {"type": "string", "enum": ["routine", "urgent", "emergent"]},
                "clinical_summary": {"type": "string", "description": "Brief clinical summary for specialist"},
            },
            "required": ["patient_id", "specialty", "reason"],
        },
    },
    {
        "name": "search_referrals",
        "description": "Search for referrals for a patient.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
                "status": {"type": "string", "enum": ["draft", "active", "completed", "cancelled"]},
            },
            "required": ["patient_id"],
        },
    },

    # Immunization Status
    {
        "name": "get_immunization_status",
        "description": "Get patient's vaccination history and identify due/overdue immunizations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "FHIR Patient ID"},
            },
            "required": ["patient_id"],
        },
    },
]


@dataclass
class ToolResult:
    """Result of a tool execution."""
    tool_use_id: str
    success: bool
    result: Any
    error: str | None = None


@dataclass
class OrchestratorResponse:
    """Response from the orchestrator."""
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    pending_actions: list[dict] = field(default_factory=list)


class OpenRouterOrchestrator:
    """
    Orchestrator using OpenRouter for LLM access.

    Supports multiple models including GLM-5, Claude, GPT-4.
    """

    def __init__(
        self,
        model: str = "glm-5",
        api_key: str | None = None,
        max_turns: int = 10,
    ):
        """
        Initialize the orchestrator.

        Args:
            model: Model to use (e.g., 'glm-5', 'claude-sonnet', 'gpt-4o')
            api_key: OpenRouter API key
            max_turns: Maximum tool-use turns
        """
        self.model = model
        self.max_turns = max_turns

        self.client = OpenRouterClient(
            api_key=api_key,
            model=model,
        )

        # Conversation state
        self.conversation_history: list[dict] = []
        self.current_patient_id: str | None = None
        self.current_patient_context: dict | None = None

        # Load system prompt
        self.system_prompt = self._build_system_prompt()

        # Import tool handlers
        self._import_handlers()

    def _import_handlers(self):
        """Import FHIR tool handlers."""
        try:
            # Import from handlers module (no MCP dependency)
            from handlers import (
                handle_search_patient,
                handle_get_patient,
                handle_get_patient_summary,
                handle_search_medications,
                handle_create_medication_request,
                handle_list_pending_actions,
                handle_approve_action,
                handle_reject_action,
                handle_update_medication_status,
                handle_delete_medication_request,
                handle_reconcile_medications,
                # Phase 8: Comprehensive Clinical Tools
                handle_create_allergy_intolerance,
                handle_update_allergy_intolerance,
                handle_add_condition,
                handle_update_condition_status,
                handle_create_procedure,
                handle_search_procedures,
                handle_get_lab_results_with_trends,
                handle_check_renal_function,
                handle_document_counseling,
                handle_create_work_note,
                handle_create_phone_encounter,
                handle_create_referral,
                handle_search_referrals,
                handle_get_immunization_status,
            )

            self.handlers = {
                "search_patient": handle_search_patient,
                "get_patient": handle_get_patient,
                "get_patient_summary": handle_get_patient_summary,
                "search_medications": handle_search_medications,
                "create_medication_request": handle_create_medication_request,
                "list_pending_actions": handle_list_pending_actions,
                "approve_action": handle_approve_action,
                "reject_action": handle_reject_action,
                "update_medication_status": handle_update_medication_status,
                "delete_medication_request": handle_delete_medication_request,
                "reconcile_medications": handle_reconcile_medications,
                # Phase 8: Comprehensive Clinical Tools
                "create_allergy_intolerance": handle_create_allergy_intolerance,
                "update_allergy_intolerance": handle_update_allergy_intolerance,
                "add_condition": handle_add_condition,
                "update_condition_status": handle_update_condition_status,
                "create_procedure": handle_create_procedure,
                "search_procedures": handle_search_procedures,
                "get_lab_results_with_trends": handle_get_lab_results_with_trends,
                "check_renal_function": handle_check_renal_function,
                "document_counseling": handle_document_counseling,
                "create_work_note": handle_create_work_note,
                "create_phone_encounter": handle_create_phone_encounter,
                "create_referral": handle_create_referral,
                "search_referrals": handle_search_referrals,
                "get_immunization_status": handle_get_immunization_status,
            }
            logger.info("Tool handlers imported successfully")

        except Exception as e:
            logger.error(f"Failed to import handlers: {e}")
            self.handlers = {}

    def _build_system_prompt(self) -> str:
        """Build the system prompt."""
        clinical_prompt = load_clinical_reasoning_prompt()

        return f"""You are a clinical AI assistant for AgentEHR, helping clinicians interact with their Electronic Health Record system.

{clinical_prompt}

## Important Guidelines

1. **Patient Safety First**: All clinical actions require explicit clinician approval. Never auto-approve orders.

2. **Evidence Grounding**: When presenting information, cite the source data.

3. **Structured Responses**: Format clinical information clearly using markdown.

4. **Context Maintenance**: Remember the current patient context across the conversation.

Current Time: {datetime.now().isoformat()}
Model: {self.model}
"""

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call."""
        handler = self.handlers.get(tool_call.name)

        if not handler:
            return ToolResult(
                tool_use_id=tool_call.id,
                success=False,
                result=None,
                error=f"Unknown tool: {tool_call.name}",
            )

        try:
            # Handle search_patient specially (convert 'query' to expected format)
            args = tool_call.arguments
            if tool_call.name == "search_patient" and "query" in args:
                args = {"name": args["query"]}

            result = await handler(args)

            return ToolResult(
                tool_use_id=tool_call.id,
                success=True,
                result=result,
            )

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return ToolResult(
                tool_use_id=tool_call.id,
                success=False,
                result=None,
                error=str(e),
            )

    async def process_message(self, user_message: str) -> OrchestratorResponse:
        """
        Process a user message.

        Args:
            user_message: Natural language request

        Returns:
            OrchestratorResponse with content and metadata
        """
        # Add to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message,
        })

        tool_calls_made = []
        tool_results = []
        warnings = []
        pending_actions = []

        # Agentic loop
        for turn in range(self.max_turns):
            # Call the model
            response = await self.client.create_message(
                messages=self.conversation_history,
                system=self.system_prompt,
                tools=FHIR_TOOLS,
            )

            # Check if tools need to be called
            if response.tool_calls:
                # Build assistant message with tool calls
                assistant_content = []
                if response.content:
                    assistant_content.append({"type": "text", "text": response.content})

                for tc in response.tool_calls:
                    assistant_content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                    tool_calls_made.append({
                        "name": tc.name,
                        "input": tc.arguments,
                        "id": tc.id,
                    })

                self.conversation_history.append({
                    "role": "assistant",
                    "content": assistant_content,
                })

                # Execute tools
                tool_result_blocks = []
                for tc in response.tool_calls:
                    result = await self.execute_tool(tc)
                    tool_results.append({
                        "tool": tc.name,
                        "success": result.success,
                        "result": result.result,
                    })

                    # Update patient context
                    if tc.name == "get_patient_summary" and result.success:
                        self.current_patient_context = result.result
                        if "patient" in result.result:
                            self.current_patient_id = result.result["patient"].get("id")
                    elif tc.name == "search_patient" and result.success:
                        if result.result.get("total") == 1:
                            self.current_patient_id = result.result["patients"][0]["id"]

                    # Extract warnings
                    if result.success and isinstance(result.result, dict):
                        if "warnings" in result.result:
                            warnings.extend(result.result["warnings"])
                        if "action_id" in result.result:
                            pending_actions.append({
                                "action_id": result.result["action_id"],
                                "status": result.result.get("status"),
                            })

                    # Add tool result
                    content = json.dumps(result.result) if result.success else result.error
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": content,
                    })

                self.conversation_history.append({
                    "role": "user",
                    "content": tool_result_blocks,
                })

            else:
                # No tool calls - final response
                final_content = response.content or ""

                self.conversation_history.append({
                    "role": "assistant",
                    "content": final_content,
                })

                return OrchestratorResponse(
                    content=final_content,
                    tool_calls=tool_calls_made,
                    tool_results=tool_results,
                    warnings=warnings,
                    pending_actions=pending_actions,
                )

        # Max turns reached
        return OrchestratorResponse(
            content="I apologize, but I wasn't able to complete your request within the allowed number of steps. Please try breaking down your request into smaller parts.",
            tool_calls=tool_calls_made,
            tool_results=tool_results,
            warnings=warnings,
            pending_actions=pending_actions,
        )

    def reset_conversation(self):
        """Reset conversation history and patient context."""
        self.conversation_history = []
        self.current_patient_id = None
        self.current_patient_context = None

    async def close(self):
        """Close the client."""
        await self.client.close()
