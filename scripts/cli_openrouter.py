#!/usr/bin/env python3
"""
AgentEHR CLI with OpenRouter

Uses OpenRouter to access various LLMs including GLM-5, Claude, GPT-4.

Usage:
    export ANTHROPIC_API_KEY='sk-or-v1-...'  # Your OpenRouter key
    python scripts/cli_openrouter.py --model glm-5

Available models:
    glm-5         - Zhipu GLM-5 (flagship)
    glm-4         - Zhipu GLM-4.5
    glm-flash     - Zhipu GLM-4.7 Flash (fast/cheap)
    claude-sonnet - Anthropic Claude 3.5 Sonnet
    gpt-4o        - OpenAI GPT-4o
    gemini        - Google Gemini 2.0 Flash (free)
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "agents"))
sys.path.insert(0, str(PROJECT_ROOT / "fhir-mcp-server" / "src"))


# ANSI colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_colored(text: str, color: str = Colors.ENDC):
    print(f"{color}{text}{Colors.ENDC}")


HELP_TEXT = """
Commands:
  /help     - Show this help
  /reset    - Reset conversation
  /pending  - List pending actions
  /exit     - Exit

Examples:
  Find patient John Smith
  Show me their medications
  Order metformin 500mg twice daily
  List pending actions
  Approve action <id>
"""


async def main():
    parser = argparse.ArgumentParser(description="AgentEHR CLI with OpenRouter")
    parser.add_argument(
        "--model", "-m",
        default="glm-5",
        choices=["glm-5", "glm-4", "glm-flash", "claude-sonnet", "gpt-4o", "gemini"],
        help="Model to use (default: glm-5)"
    )
    args = parser.parse_args()

    print_colored(f"\n{'='*60}", Colors.BLUE)
    print_colored("AgentEHR Clinical Assistant", Colors.BOLD + Colors.BLUE)
    print_colored(f"Model: {args.model}", Colors.BLUE)
    print_colored('='*60, Colors.BLUE)
    print("Type /help for commands, /exit to quit.\n")

    # Import and initialize orchestrator
    try:
        from openrouter_orchestrator import OpenRouterOrchestrator

        orchestrator = OpenRouterOrchestrator(model=args.model)
        print_colored(f"✓ Connected to OpenRouter ({args.model})", Colors.GREEN)

    except Exception as e:
        print_colored(f"✗ Failed to initialize: {e}", Colors.FAIL)
        return

    # Main loop
    running = True
    while running:
        try:
            user_input = input(f"{Colors.GREEN}You: {Colors.ENDC}").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                cmd = user_input.lower().split()[0]

                if cmd in ["/exit", "/quit"]:
                    running = False
                elif cmd == "/help":
                    print(HELP_TEXT)
                elif cmd == "/reset":
                    orchestrator.reset_conversation()
                    print_colored("Conversation reset.", Colors.GREEN)
                elif cmd == "/pending":
                    response = await orchestrator.process_message("List all pending actions")
                    print(f"\n{Colors.CYAN}Assistant: {Colors.ENDC}{response.content}\n")
                else:
                    print_colored(f"Unknown command: {cmd}", Colors.WARNING)
                continue

            # Process message
            print()
            response = await orchestrator.process_message(user_input)
            print(f"{Colors.CYAN}Assistant: {Colors.ENDC}{response.content}")

            # Show warnings
            if response.warnings:
                print_colored("\n⚠️  Safety Warnings:", Colors.WARNING)
                for w in response.warnings:
                    severity = w.get("severity", "warning").upper()
                    message = w.get("message", str(w))
                    print_colored(f"  [{severity}] {message}", Colors.WARNING)

            # Show pending actions
            if response.pending_actions:
                print_colored("\n📋 Actions created (pending approval):", Colors.CYAN)
                for action in response.pending_actions:
                    print(f"  • {action.get('action_id', 'unknown')[:8]}... ({action.get('status', 'pending')})")

            print()

        except KeyboardInterrupt:
            print("\n")
            running = False
        except Exception as e:
            print_colored(f"Error: {e}", Colors.FAIL)

    await orchestrator.close()
    print("Goodbye!")


if __name__ == "__main__":
    asyncio.run(main())
