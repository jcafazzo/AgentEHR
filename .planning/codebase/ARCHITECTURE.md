# Architecture

**Analysis Date:** 2026-02-25

## Pattern Overview

**Overall:** AI-mediated EHR platform using a 5-layer service architecture with a human-in-the-loop approval gate for all write operations.

**Key Characteristics:**
- Clinical AI agents translate natural language into FHIR R4 operations via an agentic tool-calling loop
- All state-changing clinical actions (medications, orders, appointments) are queued as drafts requiring explicit clinician approval before execution
- Dual portal mode: `clinician` (full read/write) and `patient` (read-only + limited self-service)
- Frontend proxies all `/api/*` calls to the Python backend — the Next.js app never directly calls the FHIR server
- An in-process simulation engine (new) provides accelerated-playback inpatient scenario support alongside the primary outpatient EHR flows

## Layers

**Frontend (UI Layer):**
- Purpose: React/Next.js interface for clinicians and patients
- Location: `frontend/src/`
- Contains: Pages (`app/`), shared UI components (`components/`), type definitions (`lib/types.ts`)
- Depends on: AgentEHR API (`api/`) via Next.js rewrites
- Used by: End users (clinicians, patients)

**API Gateway:**
- Purpose: FastAPI HTTP server that exposes chat, patient, and action endpoints to the frontend
- Location: `api/main.py`
- Contains: Route handlers, Pydantic request/response models, per-conversation orchestrator registry, narrative caching service (`api/narrative.py`)
- Depends on: `agents/openrouter_orchestrator.py`, `fhir-mcp-server/src/handlers.py`
- Used by: Frontend via Next.js proxy rewrites

**Agent Orchestration Layer:**
- Purpose: Manages the LLM conversation loop, dispatches FHIR tool calls, and enforces clinical safety rules
- Location: `agents/`
- Contains: `openrouter_orchestrator.py` (primary, stateful per-conversation), `orchestrator.py` (original Anthropic SDK version), `openrouter_client.py` (OpenRouter HTTP client), `workflows/` (pre-built clinical workflows), `prompts/` (system prompt markdown files), `alerts/alert_manager.py` (4-tier alert classification), `scoring/clinical_scores.py` (NEWS2, qSOFA, etc.)
- Depends on: `fhir-mcp-server/src/handlers.py`, OpenRouter API (external)
- Used by: `api/main.py`

**FHIR Tool Handlers:**
- Purpose: Business logic for all FHIR R4 operations; split from MCP server so it can be imported without MCP dependencies
- Location: `fhir-mcp-server/src/handlers.py`
- Contains: 30+ `handle_*` async functions covering patients, medications, conditions, observations, appointments, referrals, clinical notes, etc.; `approval_queue.py` (in-memory action queue); `auth.py` (Medplum OAuth); `validation/drug_interactions.py` (rule-based drug safety checks)
- Depends on: Medplum FHIR server (HTTP, `localhost:8103/fhir/R4`)
- Used by: `agents/openrouter_orchestrator.py`, `fhir-mcp-server/src/server.py`

**FHIR MCP Server:**
- Purpose: Exposes the same FHIR tool handlers via the MCP stdio protocol for use with Claude Desktop and other MCP clients
- Location: `fhir-mcp-server/src/server.py`
- Contains: MCP `Server` definition, tool registration wrapping handlers from `handlers.py`
- Depends on: `fhir-mcp-server/src/handlers.py`
- Used by: Claude Desktop (MCP client), separate from the web API path

**Data / Infrastructure Layer:**
- Purpose: FHIR R4 datastore running as a Medplum server backed by PostgreSQL and Redis
- Location: `docker-compose.yml` defines all services; seed data in `data/synthea/fhir/`
- Contains: Medplum server (`localhost:8103`), PostgreSQL 16, Redis 7, Medplum web app (`localhost:3001`)
- Depends on: Docker; loaded via `scripts/load_synthea.sh` and `scripts/seed_patients.py`
- Used by: `fhir-mcp-server/src/handlers.py`

## Data Flow

**Clinician Chat Request:**

1. User types message in `frontend/src/app/page.tsx` → `fetch('/api/chat')`
2. Next.js rewrite (`frontend/next.config.js`) proxies to `http://localhost:8000/api/chat`
3. `api/main.py` `POST /api/chat` gets or creates an `OpenRouterOrchestrator` for the `conversation_id`
4. If `patient_id` provided, API auto-loads patient context via `handle_get_patient_summary` and injects it into the orchestrator system prompt
5. `OpenRouterOrchestrator.process_message()` appends message to `conversation_history`, enters agentic loop
6. `OpenRouterClient.create_message()` sends conversation + tools to OpenRouter API (external LLM)
7. LLM response may contain tool calls; orchestrator dispatches each to the matching `handle_*` function from `handlers.py`
8. Write-intent tools (`create_medication_request`, `create_appointment`, etc.) create FHIR draft resources and enqueue them in `ApprovalQueue` — they do NOT activate the resource
9. Tool results are appended to conversation history; loop continues until LLM emits a final text response
10. `OrchestratorResponse` (content, tool_calls, warnings, pending_actions) returned to `api/main.py`, then to frontend

**Action Approval Flow:**

1. Frontend renders pending actions returned in chat response (or via `GET /api/actions`)
2. Clinician clicks Approve in `frontend/src/app/queue/page.tsx` → `POST /api/actions/{id}/approve`
3. `api/main.py` calls `handle_approve_action` which calls `ApprovalQueue.approve()` then executes the FHIR PATCH/PUT to set status from `draft` to `active`
4. Narrative cache is invalidated for the patient via `api/narrative.py:invalidate_narrative()`

**Patient Narrative Generation:**

1. `GET /api/patients/{id}/narrative` → `api/narrative.py:get_or_generate_narrative()`
2. Checks in-memory cache keyed by `{patient_id}:{mode}` and content hash of conditions/medications/allergies/careGaps
3. Cache miss: calls `OpenRouterClient` with Gemini 3 Flash model, returns AI-generated prose
4. Cache hit: returns stored narrative with `cached: true`

**State Management:**
- Orchestrator instances are stored in a process-level dict (`orchestrators: dict[str, OpenRouterOrchestrator]`) keyed by `conversation_id`
- `ApprovalQueue` is a process-level singleton in `fhir-mcp-server/src/approval_queue.py` (in-memory, no persistence)
- Narrative cache is a process-level dict in `api/narrative.py` with hash-based invalidation
- Frontend holds UI state locally in React `useState`; no Redux or persistent client store

## Key Abstractions

**OpenRouterOrchestrator:**
- Purpose: Stateful conversation manager that wraps the LLM loop, tool dispatch, and patient context injection
- Examples: `agents/openrouter_orchestrator.py` class `OpenRouterOrchestrator`
- Pattern: Tool-calling agentic loop with max 10 turns; mode-gated tool list (clinician vs. patient)

**ApprovalQueue:**
- Purpose: Safety gate ensuring no clinical write action executes without clinician sign-off
- Examples: `fhir-mcp-server/src/approval_queue.py` class `ApprovalQueue`
- Pattern: Singleton in-memory queue; actions progress through PENDING → APPROVED → EXECUTED lifecycle

**FHIR Handlers:**
- Purpose: Thin async functions that translate structured tool arguments into FHIR R4 HTTP calls against Medplum
- Examples: `fhir-mcp-server/src/handlers.py` functions like `handle_create_medication_request`, `handle_approve_action`
- Pattern: Each handler is an async function accepting a `dict` and returning a `dict`; shared across both MCP server and API/orchestrator paths

**FHIRClient:**
- Purpose: Authenticated HTTP client for Medplum, auto-renews OAuth tokens
- Examples: `fhir-mcp-server/src/handlers.py` class `FHIRClient`, `fhir-mcp-server/src/auth.py` class `MedplumAuth`
- Pattern: Lazy token acquisition with 60-second refresh buffer; httpx async client

**Clinical Scoring / Alerts:**
- Purpose: Deterministic clinical scoring (NEWS2, qSOFA, SOFA, AKI) and 4-tier alert management used by simulation and inpatient workflows
- Examples: `agents/scoring/clinical_scores.py`, `agents/alerts/alert_manager.py`
- Pattern: Pure functions for scoring; singleton `AlertManager` with deduplication, acknowledgement, and escalation lifecycle

**SimulationEngine:**
- Purpose: Asyncio-based engine that drives virtual inpatient patient journeys with configurable time acceleration
- Examples: `simulation/engine.py`, `simulation/models.py`, `simulation/physiology.py`
- Pattern: Event-driven with registered callbacks; checkpoint save/restore for branching scenarios

## Entry Points

**FastAPI API Server:**
- Location: `api/main.py`
- Triggers: `uvicorn api.main:app --port 8000` (or `python api/main.py`)
- Responsibilities: Routes all HTTP traffic from frontend; manages orchestrator lifecycle; exposes `/api/chat`, `/api/actions/*`, `/api/patients/*`, `/health`

**Next.js Frontend:**
- Location: `frontend/src/app/page.tsx` (chat/main view), `frontend/src/app/queue/page.tsx` (approval queue)
- Triggers: `npm run dev` in `frontend/`
- Responsibilities: Patient search, conversation UI, action approval UI, narrative display

**FHIR MCP Server (standalone):**
- Location: `fhir-mcp-server/src/server.py`
- Triggers: Claude Desktop config (`fhir-mcp-server/`) via MCP stdio protocol
- Responsibilities: Exposes identical FHIR tools to Claude Desktop without going through the web API

**CLI Agent:**
- Location: `scripts/cli_agent.py`
- Triggers: `python scripts/cli_agent.py`
- Responsibilities: Terminal-based interface for testing orchestrator without the frontend

**Data Seeding:**
- Location: `scripts/seed_patients.py`, `scripts/load_synthea.sh`
- Triggers: Manual execution during setup
- Responsibilities: Loads Synthea-generated FHIR bundles from `data/synthea/fhir/` into Medplum

## Error Handling

**Strategy:** Surface errors to callers with HTTP status codes; log all exceptions via Python `logging`; agentic tool errors are returned as tool result strings (not raised), allowing the LLM to recover gracefully.

**Patterns:**
- `api/main.py` wraps all route handlers in try/except and raises `HTTPException(500)` with `str(e)` as detail
- `OpenRouterOrchestrator.execute_tool()` catches all exceptions and returns `ToolResult(success=False, error=str(e))` so the LLM sees the error as a tool result
- `ApprovalQueue` logs warnings for invalid state transitions but does not raise
- `MedplumAuth` raises `Exception` on login/token failures, which propagates to the handler and then to the API error boundary

## Cross-Cutting Concerns

**Logging:** Python `logging` module throughout; loggers are named by module (e.g., `agentehr.api`, `fhir-mcp-server.handlers`); configured to `INFO` level at server startup in `api/main.py` and `fhir-mcp-server/src/server.py`

**Validation:** Drug-drug and drug-allergy interactions checked in `fhir-mcp-server/src/validation/drug_interactions.py` before queuing medication requests; warnings are surfaced to the LLM and returned to the frontend in `ChatResponse.warnings`

**Authentication:** Medplum OAuth password flow implemented in `fhir-mcp-server/src/auth.py`; OpenRouter API key from `OPENROUTER_API_KEY` env var; no end-user authentication on the AgentEHR API itself (development state)

---

*Architecture analysis: 2026-02-25*
