#!/usr/bin/env python3
"""
AgentEHR CLI Test Script

Interactive command-line interface for testing the AgentEHR orchestrator.
Provides a conversational interface to interact with the EHR system using
natural language.

Usage:
    python scripts/cli_agent.py [--stream] [--model MODEL]

Examples:
    > Find patient John Smith
    > Show me their current medications
    > Order metformin 500mg twice daily
    > List pending actions
    > Approve action <action_id>

Commands:
    /help     - Show this help message
    /reset    - Reset conversation context
    /context  - Show current patient context
    /pending  - List all pending actions
    /history  - Show conversation history
    /workflow - Run post-encounter workflow
    /exit     - Exit the CLI
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "agents"))
sys.path.insert(0, str(PROJECT_ROOT / "fhir-mcp-server" / "src"))

from orchestrator import AgentOrchestrator, StreamingOrchestrator, ToolExecutor
from workflows.post_encounter import PostEncounterWorkflow


# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def print_colored(text: str, color: str = Colors.ENDC):
    """Print colored text."""
    print(f"{color}{text}{Colors.ENDC}")


def print_header(text: str):
    """Print a header."""
    print_colored(f"\n{'='*60}", Colors.BLUE)
    print_colored(text, Colors.BOLD + Colors.BLUE)
    print_colored('='*60, Colors.BLUE)


def print_section(title: str):
    """Print a section header."""
    print_colored(f"\n--- {title} ---", Colors.CYAN)


def print_error(text: str):
    """Print an error message."""
    print_colored(f"Error: {text}", Colors.FAIL)


def print_warning(text: str):
    """Print a warning message."""
    print_colored(f"Warning: {text}", Colors.WARNING)


def print_success(text: str):
    """Print a success message."""
    print_colored(f"Success: {text}", Colors.GREEN)


HELP_TEXT = """
AgentEHR CLI - Interactive Clinical Assistant

COMMANDS:
  /help          Show this help message
  /reset         Reset conversation and patient context
  /context       Show current patient context
  /pending       List all pending actions
  /history       Show conversation history
  /workflow      Run post-encounter workflow with sample data
  /exit, /quit   Exit the CLI

EXAMPLES:
  Find patient John Smith
  Show me their medications and conditions
  Order metformin 500mg twice daily for this patient
  Create a follow-up appointment in 2 weeks
  Order a hemoglobin A1c test
  List pending actions
  Approve action <action_id>
  Reject action <action_id> because "patient preference"

TIPS:
  - The assistant remembers patient context across messages
  - All orders are created as DRAFTS requiring approval
  - Use /pending to see all actions awaiting approval
  - Safety warnings are displayed for drug interactions
"""


class AgentCLI:
    """Interactive CLI for the AgentEHR orchestrator."""

    def __init__(self, stream: bool = False, model: str = "claude-sonnet-4-20250514"):
        """
        Initialize the CLI.

        Args:
            stream: Whether to use streaming responses
            model: Claude model to use
        """
        self.stream = stream
        self.model = model
        self.orchestrator = None
        self.workflow = None
        self.running = True

    async def initialize(self):
        """Initialize the orchestrator and workflow."""
        print("Initializing AgentEHR CLI...")

        try:
            # Create tool executor
            tool_executor = ToolExecutor(mode="direct")

            # Create orchestrator
            if self.stream:
                self.orchestrator = StreamingOrchestrator(
                    model=self.model,
                    tool_executor=tool_executor,
                )
            else:
                self.orchestrator = AgentOrchestrator(
                    model=self.model,
                    tool_executor=tool_executor,
                )

            # Create workflow
            self.workflow = PostEncounterWorkflow(
                model=self.model,
                tool_executor=tool_executor,
            )

            # Initialize tool executor
            await tool_executor.initialize()

            print_success("Orchestrator initialized successfully!")

        except Exception as e:
            print_error(f"Failed to initialize: {e}")
            raise

    async def run(self):
        """Run the interactive CLI loop."""
        print_header("AgentEHR Clinical Assistant")
        print("Type /help for available commands, /exit to quit.\n")

        while self.running:
            try:
                # Get user input
                user_input = input(f"{Colors.GREEN}You: {Colors.ENDC}").strip()

                if not user_input:
                    continue

                # Handle commands
                if user_input.startswith("/"):
                    await self.handle_command(user_input)
                else:
                    await self.process_message(user_input)

            except KeyboardInterrupt:
                print("\n")
                self.running = False
            except EOFError:
                self.running = False
            except Exception as e:
                print_error(f"Error: {e}")

        print("\nGoodbye!")

    async def handle_command(self, command: str):
        """Handle CLI commands."""
        cmd = command.lower().split()[0]
        args = command.split()[1:] if len(command.split()) > 1 else []

        if cmd in ["/exit", "/quit"]:
            self.running = False

        elif cmd == "/help":
            print(HELP_TEXT)

        elif cmd == "/reset":
            self.orchestrator.reset_conversation()
            print_success("Conversation and patient context reset.")

        elif cmd == "/context":
            await self.show_context()

        elif cmd == "/pending":
            await self.list_pending_actions()

        elif cmd == "/history":
            self.show_history()

        elif cmd == "/workflow":
            await self.run_workflow_demo()

        else:
            print_warning(f"Unknown command: {cmd}. Type /help for available commands.")

    async def process_message(self, message: str):
        """Process a natural language message."""
        print()  # Blank line for readability

        try:
            if self.stream and isinstance(self.orchestrator, StreamingOrchestrator):
                print(f"{Colors.CYAN}Assistant: {Colors.ENDC}", end="", flush=True)
                async for chunk in self.orchestrator.process_message_stream(message):
                    print(chunk, end="", flush=True)
                print()  # Newline after streaming
            else:
                response = await self.orchestrator.process_message(message)
                print(f"{Colors.CYAN}Assistant: {Colors.ENDC}{response.content}")

                # Show warnings
                if response.warnings:
                    print_section("Safety Warnings")
                    for warning in response.warnings:
                        severity = warning.get("severity", "warning").upper()
                        msg = warning.get("message", "Unknown warning")
                        print_warning(f"[{severity}] {msg}")

                # Show pending actions created
                if response.pending_actions:
                    print_section("Pending Actions Created")
                    for action in response.pending_actions:
                        print(f"  - {action.get('summary', 'Unknown')}")
                        print(f"    Action ID: {action.get('action_id', 'N/A')}")

        except Exception as e:
            print_error(f"Failed to process message: {e}")

        print()  # Blank line after response

    async def show_context(self):
        """Show current patient context."""
        print_section("Current Context")

        if self.orchestrator.current_patient_id:
            print(f"Patient ID: {self.orchestrator.current_patient_id}")
        else:
            print("No patient selected.")

        if self.orchestrator.current_patient_context:
            print("\nPatient Summary:")
            context = self.orchestrator.current_patient_context

            if "patient" in context:
                patient = context["patient"]
                print(f"  Name: {patient.get('name', 'Unknown')}")
                print(f"  DOB: {patient.get('birthDate', 'Unknown')}")
                print(f"  Gender: {patient.get('gender', 'Unknown')}")

            if "activeConditions" in context:
                print(f"\n  Active Conditions ({len(context['activeConditions'])}):")
                for condition in context["activeConditions"][:5]:
                    print(f"    - {condition.get('code', 'Unknown')}")

            if "activeMedications" in context:
                print(f"\n  Active Medications ({len(context['activeMedications'])}):")
                for med in context["activeMedications"][:5]:
                    print(f"    - {med.get('medication', 'Unknown')}: {med.get('dosage', '')}")

            if "allergies" in context:
                print(f"\n  Allergies ({len(context['allergies'])}):")
                for allergy in context["allergies"][:5]:
                    print(f"    - {allergy.get('substance', 'Unknown')}")

    async def list_pending_actions(self):
        """List all pending actions."""
        print_section("Pending Actions")

        try:
            # Initialize tool executor if needed
            await self.orchestrator.tool_executor.initialize()

            # Call the list_pending_actions handler directly
            from server import handle_list_pending_actions
            result = await handle_list_pending_actions({})

            if result.get("count", 0) == 0:
                print("No pending actions.")
                return

            print(f"Found {result['count']} pending action(s):\n")

            for action in result.get("actions", []):
                print(f"  Action ID: {action['action_id']}")
                print(f"  Type: {action['action_type']}")
                print(f"  Patient: {action['patient_id']}")
                print(f"  Summary: {action['summary']}")
                print(f"  Status: {action['status']}")

                if action.get("warnings"):
                    print(f"  Warnings: {len(action['warnings'])}")
                    for w in action["warnings"]:
                        print(f"    - [{w['severity']}] {w['message']}")

                print()

        except Exception as e:
            print_error(f"Failed to list pending actions: {e}")

    def show_history(self):
        """Show conversation history."""
        print_section("Conversation History")

        history = self.orchestrator.get_conversation_history()

        if not history:
            print("No conversation history.")
            return

        for i, msg in enumerate(history, 1):
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")

            # Handle different content types
            if isinstance(content, str):
                # Truncate long messages
                if len(content) > 200:
                    content = content[:200] + "..."
                print(f"\n[{i}] {role}:")
                print(f"    {content}")
            elif isinstance(content, list):
                # Handle tool results or complex content
                print(f"\n[{i}] {role}: [Complex content with {len(content)} items]")

    async def run_workflow_demo(self):
        """Run a demo of the post-encounter workflow."""
        print_section("Post-Encounter Workflow Demo")

        sample_encounter = """
PATIENT ENCOUNTER NOTE
Date: Today

Chief Complaint: Diabetes follow-up

History of Present Illness:
58-year-old male with type 2 diabetes presents for routine follow-up.
Patient reports good compliance with current medications. Occasional
elevated fasting sugars in the 140-150 range. No hypoglycemia.
Patient interested in weight management options.

Current Medications:
- Metformin 1000mg BID
- Lisinopril 10mg daily

Assessment and Plan:
1. Type 2 Diabetes - Consider adding Ozempic for glycemic control and weight
   - Order HbA1c, fasting glucose, kidney function
2. Hypertension - Well controlled on current regimen
3. Follow-up in 3 months
"""

        print("Processing sample encounter note...")
        print(f"\n{'-'*40}")
        print(sample_encounter)
        print(f"{'-'*40}\n")

        # Check for patient context
        patient_id = self.orchestrator.current_patient_id
        if not patient_id:
            print_warning("No patient in context. Using demo patient ID.")
            patient_id = "demo-patient-001"

        try:
            result = await self.workflow.process_encounter(
                patient_id=patient_id,
                encounter_notes=sample_encounter,
                encounter_type="follow_up",
                auto_create_actions=False,  # Don't actually create in demo
            )

            print(result.summary)

            if result.analysis:
                print_section("Proposed Actions")
                for i, action in enumerate(result.analysis.proposed_actions, 1):
                    print(f"\n{i}. [{action.category.value}] {action.summary}")
                    print(f"   Priority: {action.priority.value}")
                    print(f"   Tool: {action.tool_name}")
                    print(f"   Rationale: {action.rationale}")

            print("\nNote: Actions were not created (demo mode).")
            print("To create actions, use the orchestrator with specific commands.")

        except Exception as e:
            print_error(f"Workflow failed: {e}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AgentEHR CLI - Interactive Clinical Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_TEXT,
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Use streaming responses",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Claude model to use (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )

    args = parser.parse_args()

    # Disable colors if requested
    if args.no_color:
        for attr in dir(Colors):
            if not attr.startswith("_"):
                setattr(Colors, attr, "")

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print_error("ANTHROPIC_API_KEY environment variable is required.")
        print("Set it with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    # Create and run CLI
    cli = AgentCLI(stream=args.stream, model=args.model)

    try:
        await cli.initialize()
        await cli.run()
    except Exception as e:
        print_error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
