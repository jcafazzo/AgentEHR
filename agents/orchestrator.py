#!/usr/bin/env python3
"""
AgentEHR Orchestrator

Central orchestration layer that connects Claude (via Anthropic SDK) to the
FHIR MCP server tools. Handles:
- Natural language processing of clinical requests
- Tool invocation and response handling
- Conversation context management
- Evidence-grounded response formatting

Usage:
    orchestrator = AgentOrchestrator()
    response = await orchestrator.process_message(
        "Find patient John Smith and show me their medications"
    )
"""

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import anthropic
from anthropic.types import Message, ToolUseBlock, TextBlock

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentehr.orchestrator")

# Load clinical reasoning prompt
PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_clinical_reasoning_prompt() -> str:
    """Load the clinical reasoning system prompt from file."""
    prompt_path = PROMPTS_DIR / "clinical_reasoning.md"
    if prompt_path.exists():
        return prompt_path.read_text()
    else:
        logger.warning(f"Clinical reasoning prompt not found at {prompt_path}")
        return ""


# Tool definitions matching the MCP server
FHIR_TOOLS = [
    # Read operations
    {
        "name": "search_patient",
        "description": "Search for patients by name, identifier, birthdate, or other criteria. Returns a list of matching patients with their IDs and basic demographics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Patient name (partial match supported)",
                },
                "identifier": {
                    "type": "string",
                    "description": "Medical record number or other identifier",
                },
                "birthdate": {
                    "type": "string",
                    "description": "Date of birth (YYYY-MM-DD)",
                },
                "gender": {
                    "type": "string",
                    "enum": ["male", "female", "other", "unknown"],
                    "description": "Patient gender",
                },
            },
        },
    },
    {
        "name": "get_patient",
        "description": "Get detailed information about a specific patient by their ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "get_patient_summary",
        "description": "Get a comprehensive summary of a patient including conditions, medications, allergies, and recent encounters. Use this for clinical context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "search_medications",
        "description": "Search for a patient's current and historical medications.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "completed", "stopped", "on-hold"],
                    "description": "Filter by medication status (default: active)",
                },
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "search_observations",
        "description": "Search for patient observations including vital signs and lab results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
                "category": {
                    "type": "string",
                    "enum": ["vital-signs", "laboratory", "social-history", "imaging"],
                    "description": "Category of observation",
                },
                "code": {
                    "type": "string",
                    "description": "LOINC code for specific observation type",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date for observation search (YYYY-MM-DD)",
                },
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "search_conditions",
        "description": "Search for patient conditions (diagnoses, problems).",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
                "clinical_status": {
                    "type": "string",
                    "enum": ["active", "resolved", "inactive"],
                    "description": "Clinical status filter",
                },
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "search_encounters",
        "description": "Search for patient encounters (visits, admissions).",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
                "status": {
                    "type": "string",
                    "enum": ["planned", "arrived", "in-progress", "finished", "cancelled"],
                    "description": "Encounter status filter",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date for encounter search (YYYY-MM-DD)",
                },
            },
            "required": ["patient_id"],
        },
    },
    # Write operations
    {
        "name": "create_medication_request",
        "description": "Create a new medication order for a patient. Returns a draft order for clinician approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
                "medication_name": {
                    "type": "string",
                    "description": "Name of the medication",
                },
                "dosage": {
                    "type": "string",
                    "description": "Dosage amount (e.g., '500 mg')",
                },
                "frequency": {
                    "type": "string",
                    "description": "How often to take (e.g., 'twice daily', 'every 8 hours')",
                },
                "route": {
                    "type": "string",
                    "enum": ["oral", "intravenous", "subcutaneous", "intramuscular", "topical", "inhaled"],
                    "description": "Route of administration",
                },
                "duration": {
                    "type": "string",
                    "description": "Duration of treatment (e.g., '7 days', '30 days')",
                },
                "instructions": {
                    "type": "string",
                    "description": "Additional instructions for the patient",
                },
            },
            "required": ["patient_id", "medication_name", "dosage", "frequency"],
        },
    },
    {
        "name": "create_care_plan",
        "description": "Create a care plan for a patient with goals and activities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
                "title": {
                    "type": "string",
                    "description": "Title of the care plan",
                },
                "description": {
                    "type": "string",
                    "description": "Description of the care plan",
                },
                "goals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of care plan goals",
                },
                "activities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of planned activities",
                },
            },
            "required": ["patient_id", "title"],
        },
    },
    {
        "name": "create_appointment",
        "description": "Create a follow-up appointment for a patient.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for the appointment",
                },
                "appointment_type": {
                    "type": "string",
                    "enum": ["routine", "followup", "urgent", "checkup"],
                    "description": "Type of appointment",
                },
                "preferred_date": {
                    "type": "string",
                    "description": "Preferred date (YYYY-MM-DD)",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Appointment duration in minutes",
                },
            },
            "required": ["patient_id", "reason"],
        },
    },
    {
        "name": "create_diagnostic_order",
        "description": "Create a diagnostic order (lab test or imaging study) for a patient. Order is created as draft and requires clinician approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
                "order_type": {
                    "type": "string",
                    "enum": ["lab", "imaging"],
                    "description": "Type of diagnostic order",
                },
                "test_name": {
                    "type": "string",
                    "description": "Name of the test or study (e.g., 'Complete Blood Count', 'Chest X-Ray')",
                },
                "reason": {
                    "type": "string",
                    "description": "Clinical reason for the order",
                },
                "priority": {
                    "type": "string",
                    "enum": ["routine", "urgent", "asap", "stat"],
                    "description": "Order priority (default: routine)",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional clinical notes for the order",
                },
            },
            "required": ["patient_id", "order_type", "test_name", "reason"],
        },
    },
    {
        "name": "create_encounter_note",
        "description": "Create a clinical encounter note or documentation for a patient. Created as draft and requires clinician approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
                "encounter_id": {
                    "type": "string",
                    "description": "The FHIR Encounter resource ID (optional)",
                },
                "note_type": {
                    "type": "string",
                    "enum": ["progress_note", "history_physical", "discharge_summary", "consultation", "procedure_note"],
                    "description": "Type of clinical note",
                },
                "title": {
                    "type": "string",
                    "description": "Title of the document",
                },
                "content": {
                    "type": "string",
                    "description": "The clinical note content (plain text or markdown)",
                },
                "author": {
                    "type": "string",
                    "description": "Name of the author (optional)",
                },
            },
            "required": ["patient_id", "note_type", "title", "content"],
        },
    },
    {
        "name": "create_communication",
        "description": "Create a communication such as a letter to a referring physician or patient notification. Created as draft and requires clinician approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID",
                },
                "recipient_type": {
                    "type": "string",
                    "enum": ["referring_physician", "patient", "specialist", "insurance"],
                    "description": "Type of recipient",
                },
                "recipient_name": {
                    "type": "string",
                    "description": "Name of the recipient",
                },
                "subject": {
                    "type": "string",
                    "description": "Subject of the communication",
                },
                "content": {
                    "type": "string",
                    "description": "Content of the communication/letter",
                },
                "category": {
                    "type": "string",
                    "enum": ["referral_response", "consultation_note", "lab_results", "follow_up", "general"],
                    "description": "Category of communication",
                },
            },
            "required": ["patient_id", "recipient_type", "subject", "content"],
        },
    },
    # Approval operations
    {
        "name": "list_pending_actions",
        "description": "List all pending clinical actions awaiting approval for a patient. Returns draft medications, orders, care plans, etc. that need clinician review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The FHIR Patient resource ID (optional - if omitted, returns all pending actions)",
                },
            },
        },
    },
    {
        "name": "approve_action",
        "description": "Approve a pending clinical action. This will change the resource status from draft to active and execute it in the EHR.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "string",
                    "description": "The action ID from list_pending_actions",
                },
            },
            "required": ["action_id"],
        },
    },
    {
        "name": "reject_action",
        "description": "Reject a pending clinical action. This will delete the draft resource from the EHR.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "string",
                    "description": "The action ID from list_pending_actions",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for rejection",
                },
            },
            "required": ["action_id"],
        },
    },
]


class MessageRole(str, Enum):
    """Role in conversation."""
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ConversationMessage:
    """A message in the conversation history."""
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ToolResult:
    """Result from executing a tool."""
    tool_name: str
    tool_use_id: str
    result: dict
    success: bool
    error: str | None = None


@dataclass
class OrchestratorResponse:
    """Structured response from the orchestrator."""
    content: str
    tool_calls: list[dict]
    tool_results: list[ToolResult]
    patient_context: dict | None = None
    pending_actions: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    raw_response: Message | None = None


class ToolExecutor:
    """
    Executes FHIR tools by calling the MCP server handlers.

    Can be configured to use:
    1. Direct function calls (for testing/in-process usage)
    2. MCP client connection (for production)
    3. HTTP API calls (for remote server)
    """

    def __init__(self, mode: str = "direct"):
        """
        Initialize the tool executor.

        Args:
            mode: Execution mode - "direct", "mcp", or "http"
        """
        self.mode = mode
        self._handlers: dict[str, Callable] = {}
        self._initialized = False

    async def initialize(self):
        """Initialize the tool executor with appropriate handlers."""
        if self._initialized:
            return

        if self.mode == "direct":
            await self._init_direct_handlers()
        elif self.mode == "mcp":
            await self._init_mcp_client()
        elif self.mode == "http":
            await self._init_http_client()
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

        self._initialized = True

    async def _init_direct_handlers(self):
        """Initialize direct function call handlers."""
        # Import server handlers
        try:
            # Add the fhir-mcp-server/src to path
            server_path = Path(__file__).parent.parent / "fhir-mcp-server" / "src"
            if str(server_path) not in sys.path:
                sys.path.insert(0, str(server_path))

            from server import (
                handle_search_patient,
                handle_get_patient,
                handle_get_patient_summary,
                handle_search_medications,
                handle_search_observations,
                handle_search_conditions,
                handle_search_encounters,
                handle_create_medication_request,
                handle_create_care_plan,
                handle_create_appointment,
                handle_create_diagnostic_order,
                handle_create_encounter_note,
                handle_create_communication,
                handle_list_pending_actions,
                handle_approve_action,
                handle_reject_action,
            )

            self._handlers = {
                "search_patient": handle_search_patient,
                "get_patient": handle_get_patient,
                "get_patient_summary": handle_get_patient_summary,
                "search_medications": handle_search_medications,
                "search_observations": handle_search_observations,
                "search_conditions": handle_search_conditions,
                "search_encounters": handle_search_encounters,
                "create_medication_request": handle_create_medication_request,
                "create_care_plan": handle_create_care_plan,
                "create_appointment": handle_create_appointment,
                "create_diagnostic_order": handle_create_diagnostic_order,
                "create_encounter_note": handle_create_encounter_note,
                "create_communication": handle_create_communication,
                "list_pending_actions": handle_list_pending_actions,
                "approve_action": handle_approve_action,
                "reject_action": handle_reject_action,
            }
            logger.info("Direct handlers initialized successfully")
        except ImportError as e:
            logger.error(f"Failed to import server handlers: {e}")
            raise

    async def _init_mcp_client(self):
        """Initialize MCP client connection."""
        # TODO: Implement MCP client connection
        raise NotImplementedError("MCP client mode not yet implemented")

    async def _init_http_client(self):
        """Initialize HTTP API client."""
        # TODO: Implement HTTP client
        raise NotImplementedError("HTTP client mode not yet implemented")

    async def execute(self, tool_name: str, tool_use_id: str, arguments: dict) -> ToolResult:
        """
        Execute a tool with the given arguments.

        Args:
            tool_name: Name of the tool to execute
            tool_use_id: Unique ID for this tool use
            arguments: Tool arguments

        Returns:
            ToolResult with the execution result
        """
        if not self._initialized:
            await self.initialize()

        if tool_name not in self._handlers:
            return ToolResult(
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                result={"error": f"Unknown tool: {tool_name}"},
                success=False,
                error=f"Unknown tool: {tool_name}",
            )

        try:
            handler = self._handlers[tool_name]
            result = await handler(arguments)

            # Check for error in result
            if isinstance(result, dict) and "error" in result:
                return ToolResult(
                    tool_name=tool_name,
                    tool_use_id=tool_use_id,
                    result=result,
                    success=False,
                    error=result["error"],
                )

            return ToolResult(
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                result=result,
                success=True,
            )
        except Exception as e:
            logger.exception(f"Error executing tool {tool_name}")
            return ToolResult(
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                result={"error": str(e)},
                success=False,
                error=str(e),
            )


class AgentOrchestrator:
    """
    Main orchestrator for AgentEHR.

    Connects Claude (via Anthropic SDK) to FHIR MCP server tools,
    managing conversation context and tool execution.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        tool_executor: ToolExecutor | None = None,
        max_turns: int = 10,
    ):
        """
        Initialize the orchestrator.

        Args:
            model: Claude model to use
            api_key: Anthropic API key (or from ANTHROPIC_API_KEY env var)
            tool_executor: Custom tool executor (defaults to direct mode)
            max_turns: Maximum conversation turns per request
        """
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_turns = max_turns

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable or api_key parameter required")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.tool_executor = tool_executor or ToolExecutor(mode="direct")

        # Conversation state
        self.conversation_history: list[dict] = []
        self.current_patient_id: str | None = None
        self.current_patient_context: dict | None = None

        # Load system prompt
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Build the complete system prompt."""
        clinical_prompt = load_clinical_reasoning_prompt()

        return f"""You are a clinical AI assistant for AgentEHR, helping clinicians interact with their Electronic Health Record system.

{clinical_prompt}

## Important Guidelines

1. **Patient Safety First**: All clinical actions require explicit clinician approval. Never auto-approve orders.

2. **Evidence Grounding**: When presenting information, always cite the source data. For example:
   - "Based on the patient's medication list (retrieved at [time])..."
   - "The lab result from [date] shows..."

3. **Structured Responses**: Format clinical information clearly using markdown.

4. **Error Handling**: If a tool call fails, explain the issue clearly and suggest alternatives.

5. **Context Maintenance**: Remember the current patient context across the conversation.

## Response Format

When presenting clinical data, use clear formatting:
- Use headers for sections
- Use bullet points for lists
- Highlight warnings prominently
- Include action items at the end

Current Time: {datetime.now().isoformat()}
"""

    async def process_message(
        self,
        user_message: str,
        stream: bool = False,
    ) -> OrchestratorResponse:
        """
        Process a user message and return a response.

        Args:
            user_message: The user's natural language request
            stream: Whether to stream the response (not yet implemented)

        Returns:
            OrchestratorResponse with the assistant's response and metadata
        """
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message,
        })

        tool_calls = []
        tool_results = []
        warnings = []
        citations = []
        pending_actions = []

        # Initialize tool executor
        await self.tool_executor.initialize()

        # Agentic loop - continue until assistant provides final response
        for turn in range(self.max_turns):
            # Call Claude
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                tools=FHIR_TOOLS,
                messages=self.conversation_history,
            )

            # Check if we need to execute tools
            if response.stop_reason == "tool_use":
                # Extract tool use blocks
                tool_use_blocks = [
                    block for block in response.content
                    if isinstance(block, ToolUseBlock)
                ]

                # Execute each tool
                tool_result_contents = []
                for tool_use in tool_use_blocks:
                    tool_call = {
                        "name": tool_use.name,
                        "input": tool_use.input,
                        "id": tool_use.id,
                    }
                    tool_calls.append(tool_call)

                    # Execute the tool
                    result = await self.tool_executor.execute(
                        tool_name=tool_use.name,
                        tool_use_id=tool_use.id,
                        arguments=tool_use.input,
                    )
                    tool_results.append(result)

                    # Update patient context if relevant
                    if tool_use.name == "get_patient_summary" and result.success:
                        self.current_patient_context = result.result
                        if "patient" in result.result:
                            self.current_patient_id = result.result["patient"].get("id")
                    elif tool_use.name == "search_patient" and result.success:
                        if result.result.get("total") == 1:
                            self.current_patient_id = result.result["patients"][0]["id"]

                    # Extract warnings
                    if result.success and isinstance(result.result, dict):
                        if "warnings" in result.result:
                            warnings.extend(result.result["warnings"])
                        if "action_id" in result.result:
                            pending_actions.append({
                                "action_id": result.result.get("action_id"),
                                "summary": result.result.get("message", ""),
                                "type": tool_use.name,
                            })

                    # Add citation
                    citations.append({
                        "tool": tool_use.name,
                        "timestamp": datetime.now().isoformat(),
                        "arguments": tool_use.input,
                    })

                    tool_result_contents.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(result.result),
                    })

                # Add assistant response and tool results to history
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response.content,
                })
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_result_contents,
                })

            else:
                # End of conversation - extract text response
                text_content = ""
                for block in response.content:
                    if isinstance(block, TextBlock):
                        text_content += block.text

                # Add final assistant response to history
                self.conversation_history.append({
                    "role": "assistant",
                    "content": text_content,
                })

                return OrchestratorResponse(
                    content=text_content,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    patient_context=self.current_patient_context,
                    pending_actions=pending_actions,
                    warnings=warnings,
                    citations=citations,
                    raw_response=response,
                )

        # Exceeded max turns
        return OrchestratorResponse(
            content="I apologize, but I was unable to complete the request within the allowed number of steps. Please try simplifying your request.",
            tool_calls=tool_calls,
            tool_results=tool_results,
            patient_context=self.current_patient_context,
            pending_actions=pending_actions,
            warnings=warnings,
            citations=citations,
        )

    def reset_conversation(self):
        """Reset the conversation history and patient context."""
        self.conversation_history = []
        self.current_patient_id = None
        self.current_patient_context = None

    def get_conversation_history(self) -> list[dict]:
        """Get the current conversation history."""
        return self.conversation_history.copy()

    def set_patient_context(self, patient_id: str, context: dict):
        """Manually set the patient context."""
        self.current_patient_id = patient_id
        self.current_patient_context = context


class StreamingOrchestrator(AgentOrchestrator):
    """
    Streaming version of the orchestrator that yields responses incrementally.
    """

    async def process_message_stream(
        self,
        user_message: str,
    ) -> AsyncIterator[str]:
        """
        Process a user message and stream the response.

        Args:
            user_message: The user's natural language request

        Yields:
            Chunks of the response text
        """
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message,
        })

        # Initialize tool executor
        await self.tool_executor.initialize()

        # Agentic loop
        for turn in range(self.max_turns):
            # Call Claude with streaming
            with self.client.messages.stream(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                tools=FHIR_TOOLS,
                messages=self.conversation_history,
            ) as stream:
                response_text = ""
                tool_use_blocks = []

                for event in stream:
                    if hasattr(event, 'delta'):
                        if hasattr(event.delta, 'text'):
                            chunk = event.delta.text
                            response_text += chunk
                            yield chunk

                # Get final message
                response = stream.get_final_message()

            # Check if we need to execute tools
            if response.stop_reason == "tool_use":
                tool_use_blocks = [
                    block for block in response.content
                    if isinstance(block, ToolUseBlock)
                ]

                tool_result_contents = []
                for tool_use in tool_use_blocks:
                    yield f"\n[Executing {tool_use.name}...]\n"

                    result = await self.tool_executor.execute(
                        tool_name=tool_use.name,
                        tool_use_id=tool_use.id,
                        arguments=tool_use.input,
                    )

                    # Update context
                    if tool_use.name == "get_patient_summary" and result.success:
                        self.current_patient_context = result.result
                        if "patient" in result.result:
                            self.current_patient_id = result.result["patient"].get("id")

                    tool_result_contents.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(result.result),
                    })

                # Add to history
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response.content,
                })
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_result_contents,
                })

            else:
                # Final response
                text_content = ""
                for block in response.content:
                    if isinstance(block, TextBlock):
                        text_content += block.text

                self.conversation_history.append({
                    "role": "assistant",
                    "content": text_content,
                })
                return

        yield "\nI apologize, but I was unable to complete the request within the allowed number of steps."


# Factory functions
def create_orchestrator(
    mode: str = "direct",
    model: str = "claude-sonnet-4-20250514",
    api_key: str | None = None,
) -> AgentOrchestrator:
    """
    Create an orchestrator instance.

    Args:
        mode: Tool execution mode ("direct", "mcp", or "http")
        model: Claude model to use
        api_key: Anthropic API key

    Returns:
        Configured AgentOrchestrator
    """
    tool_executor = ToolExecutor(mode=mode)
    return AgentOrchestrator(
        model=model,
        api_key=api_key,
        tool_executor=tool_executor,
    )


def create_streaming_orchestrator(
    mode: str = "direct",
    model: str = "claude-sonnet-4-20250514",
    api_key: str | None = None,
) -> StreamingOrchestrator:
    """
    Create a streaming orchestrator instance.

    Args:
        mode: Tool execution mode ("direct", "mcp", or "http")
        model: Claude model to use
        api_key: Anthropic API key

    Returns:
        Configured StreamingOrchestrator
    """
    tool_executor = ToolExecutor(mode=mode)
    return StreamingOrchestrator(
        model=model,
        api_key=api_key,
        tool_executor=tool_executor,
    )


# Simple test
async def _test():
    """Simple test of the orchestrator."""
    orchestrator = create_orchestrator()

    print("Testing orchestrator with search_patient...")
    response = await orchestrator.process_message("Search for patient John Smith")
    print(f"Response: {response.content}")
    print(f"Tool calls: {len(response.tool_calls)}")
    print(f"Patient context: {response.patient_context}")


if __name__ == "__main__":
    asyncio.run(_test())
