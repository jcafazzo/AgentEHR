#!/usr/bin/env python3
"""
AgentEHR API Server

FastAPI HTTP server that wraps the OpenRouter orchestrator for web frontend access.
"""

import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Load environment variables from .env file
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Add project paths
sys.path.insert(0, str(PROJECT_ROOT / "agents"))
sys.path.insert(0, str(PROJECT_ROOT / "fhir-mcp-server" / "src"))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentehr.api")

# Import orchestrator and handlers
from openrouter_orchestrator import OpenRouterOrchestrator
from handlers import (
    handle_search_patient,
    handle_get_patient,
    handle_get_patient_summary,
    handle_list_pending_actions,
    handle_approve_action,
    handle_reject_action,
)
from api.narrative import get_or_generate_narrative, invalidate_narrative  # noqa: E402

# Store orchestrator instances per conversation
orchestrators: dict[str, OpenRouterOrchestrator] = {}


def get_or_create_orchestrator(conversation_id: str, model: str = "glm-5", mode: str = "clinician") -> OpenRouterOrchestrator:
    """Get or create an orchestrator for a conversation."""
    if conversation_id not in orchestrators:
        orchestrators[conversation_id] = OpenRouterOrchestrator(model=model, mode=mode)
        logger.info(f"Created new orchestrator for conversation {conversation_id} (mode={mode})")
    else:
        # Update mode if it changed
        orch = orchestrators[conversation_id]
        if orch.mode != mode:
            orch.mode = mode
            orch.system_prompt = orch._build_system_prompt()
            logger.info(f"Updated orchestrator mode to {mode} for conversation {conversation_id}")
    return orchestrators[conversation_id]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("AgentEHR API Server starting...")

    # Check for API key at startup
    if not os.environ.get("OPENROUTER_API_KEY"):
        logger.warning("⚠️  OPENROUTER_API_KEY not set. Chat feature will return 503 errors.")
        logger.warning("   Set it with: export OPENROUTER_API_KEY=your_key_here")
    else:
        logger.info("✓ OPENROUTER_API_KEY configured")

    yield
    # Cleanup orchestrators
    for conv_id, orch in orchestrators.items():
        await orch.close()
    logger.info("AgentEHR API Server stopped")


app = FastAPI(
    title="AgentEHR API",
    description="HTTP API for AgentEHR clinical AI assistant",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3010", "http://127.0.0.1:3010"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Request/Response Models
# =============================================================================

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    model: str = "gemini"
    patient_id: Optional[str] = None
    mode: str = "clinician"  # "clinician" or "patient"


class ChatResponse(BaseModel):
    content: str
    conversation_id: str
    tool_calls: list[dict] = []
    tool_results: list[dict] = []
    warnings: list[dict] = []
    pending_actions: list[dict] = []


class ApproveRequest(BaseModel):
    pass  # No body needed


class RejectRequest(BaseModel):
    reason: Optional[str] = None


class ActionResponse(BaseModel):
    status: str
    message: str
    action_id: str
    fhir_id: Optional[str] = None


class PatientSearchRequest(BaseModel):
    query: str


# =============================================================================
# Chat Endpoints
# =============================================================================

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Send a message to the AI assistant.

    Creates or continues a conversation with the clinical AI.
    """
    # Check for required API key
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENROUTER_API_KEY environment variable not set. Please set it before using the chat feature."
        )

    try:
        # Generate conversation ID if not provided
        conversation_id = request.conversation_id or str(uuid.uuid4())

        # Get or create orchestrator
        orchestrator = get_or_create_orchestrator(conversation_id, request.model, request.mode)

        # Auto-load patient context if frontend provides patient_id
        if request.patient_id and not orchestrator.current_patient_context:
            try:
                summary = await handle_get_patient_summary({"patient_id": request.patient_id})
                orchestrator.current_patient_context = summary
                orchestrator.current_patient_id = request.patient_id
                orchestrator.system_prompt = orchestrator._build_system_prompt()
                logger.info(f"Auto-loaded patient context for {request.patient_id}")
            except Exception as ctx_err:
                logger.warning(f"Failed to auto-load patient context for {request.patient_id}: {ctx_err}")

        # Process message
        response = await orchestrator.process_message(request.message)

        return ChatResponse(
            content=response.content,
            conversation_id=conversation_id,
            tool_calls=response.tool_calls,
            tool_results=response.tool_results,
            warnings=response.warnings,
            pending_actions=response.pending_actions,
        )

    except Exception as e:
        logger.exception(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/chat/{conversation_id}")
async def reset_conversation(conversation_id: str):
    """Reset a conversation, clearing history."""
    if conversation_id in orchestrators:
        orchestrators[conversation_id].reset_conversation()
        return {"status": "reset", "conversation_id": conversation_id}
    raise HTTPException(status_code=404, detail="Conversation not found")


# =============================================================================
# Action Queue Endpoints
# =============================================================================

@app.get("/api/actions")
async def list_actions(patient_id: Optional[str] = None):
    """List pending actions, optionally filtered by patient."""
    try:
        result = await handle_list_pending_actions({"patient_id": patient_id})
        return result
    except Exception as e:
        logger.exception(f"List actions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/actions/{action_id}/approve", response_model=ActionResponse)
async def approve_action(action_id: str):
    """Approve a pending clinical action."""
    try:
        result = await handle_approve_action({"action_id": action_id})

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        # Invalidate narrative cache — record changed
        if patient_id := result.get("patient_id"):
            invalidate_narrative(patient_id)

        return ActionResponse(
            status=result.get("status", "approved"),
            message=result.get("message", "Action approved"),
            action_id=action_id,
            fhir_id=result.get("fhir_id"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Approve action error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/actions/{action_id}/reject", response_model=ActionResponse)
async def reject_action(action_id: str, request: RejectRequest):
    """Reject a pending clinical action."""
    try:
        result = await handle_reject_action({
            "action_id": action_id,
            "reason": request.reason,
        })

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return ActionResponse(
            status=result.get("status", "rejected"),
            message=result.get("message", "Action rejected"),
            action_id=action_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Reject action error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Patient Endpoints
# =============================================================================

@app.get("/api/patients/search")
async def search_patients(q: str):
    """Search for patients by name or identifier."""
    try:
        result = await handle_search_patient({"query": q})
        return result
    except Exception as e:
        logger.exception(f"Patient search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/patients/{patient_id}")
async def get_patient(patient_id: str):
    """Get patient details by ID."""
    try:
        result = await handle_get_patient({"patient_id": patient_id})
        return result
    except Exception as e:
        logger.exception(f"Get patient error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/patients/{patient_id}/summary")
async def get_patient_summary(patient_id: str):
    """Get comprehensive patient summary."""
    try:
        result = await handle_get_patient_summary({"patient_id": patient_id})
        return result
    except Exception as e:
        logger.exception(f"Patient summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/patients/{patient_id}/narrative")
async def get_patient_narrative(patient_id: str, mode: str = "clinician"):
    """Get AI-generated narrative for a patient (clinical or patient-friendly)."""
    try:
        summary = await handle_get_patient_summary({"patient_id": patient_id})
        result = await get_or_generate_narrative(patient_id, summary, mode=mode)
        return result
    except Exception as e:
        logger.exception(f"Narrative generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "agentehr-api",
        "active_conversations": len(orchestrators),
        "openrouter_configured": bool(os.environ.get("OPENROUTER_API_KEY")),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
