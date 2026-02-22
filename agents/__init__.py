"""
AgentEHR Agents Module

Provides the agent orchestration layer connecting Claude to the FHIR MCP server.

Components:
- orchestrator: Main agent orchestrator for processing natural language requests
- workflows: Pre-built clinical workflows (post-encounter, medication ordering, etc.)
"""

from .orchestrator import (
    AgentOrchestrator,
    StreamingOrchestrator,
    ToolExecutor,
    OrchestratorResponse,
    ToolResult,
    create_orchestrator,
    create_streaming_orchestrator,
)

__all__ = [
    "AgentOrchestrator",
    "StreamingOrchestrator",
    "ToolExecutor",
    "OrchestratorResponse",
    "ToolResult",
    "create_orchestrator",
    "create_streaming_orchestrator",
]
