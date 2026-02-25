# External Integrations

**Analysis Date:** 2026-02-25

## APIs & External Services

**AI / LLM Gateway:**
- OpenRouter - Primary LLM gateway used for all chat and narrative generation in production
  - SDK/Client: `httpx` via custom `OpenRouterClient` class at `agents/openrouter_client.py`
  - Auth: `OPENROUTER_API_KEY` env var (falls back to `ANTHROPIC_API_KEY`)
  - Endpoint: `https://openrouter.ai/api/v1/chat/completions`
  - Models routed through OpenRouter:
    - `z-ai/glm-5` (alias: `glm-5`, default for orchestrator)
    - `google/gemini-2.5-flash-lite` (alias: `gemini`, default for chat API)
    - `google/gemini-3-flash-preview` (alias: `gemini-3-flash`, used for narrative generation)
    - `anthropic/claude-3.5-sonnet` (alias: `claude-sonnet`)
    - `anthropic/claude-3-opus` (alias: `claude-opus`)
    - `openai/gpt-4o` (alias: `gpt-4o`)
    - `z-ai/glm-4.5` (alias: `glm-4`)
    - `z-ai/glm-4.7-flash` (alias: `glm-flash`)

**AI / Direct Anthropic SDK:**
- Anthropic Claude API - Used by the secondary `AgentOrchestrator` in `agents/orchestrator.py`
  - SDK/Client: `anthropic` Python SDK (`anthropic.Anthropic`)
  - Auth: `ANTHROPIC_API_KEY` env var
  - Model: `claude-sonnet-4-20250514` (hardcoded default)
  - Note: This orchestrator is NOT the active path — `OpenRouterOrchestrator` in `agents/openrouter_orchestrator.py` is used by `api/main.py`

**Font CDN:**
- Google Fonts - Material Symbols Outlined icon font loaded via CDN in `frontend/src/app/layout.tsx`
  - URL: `https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined`
  - No API key required

## Data Storage

**Databases:**
- PostgreSQL 16 - Primary relational database for Medplum FHIR server
  - Connection: Managed by Medplum server container; configured via Docker Compose env vars
  - Container: `agentehr-postgres` on port 5432
  - Credentials: `MEDPLUM_DATABASE_USERNAME` / `MEDPLUM_DATABASE_PASSWORD` (default: `medplum/medplum`)
  - Volume: `agentehr-postgres-data` (persistent Docker volume)

**Caching:**
- Redis 7 - Session/cache store for Medplum server
  - Container: `agentehr-redis` on port 6379
  - Auth: `MEDPLUM_REDIS_PASSWORD` (default: `medplum`)
  - Note: Used internally by Medplum server; Python app does not connect to Redis directly

**In-Memory Caches (Python):**
- Narrative cache: `api/narrative.py` — hash-keyed dict `_narrative_cache` storing generated AI narratives per patient/mode
- Approval queue: `fhir-mcp-server/src/approval_queue.py` — in-memory pending action queue (lost on restart)
- Alert manager: `agents/alerts/alert_manager.py` — in-memory alert store with thread-safe singleton

**File Storage:**
- Medplum binary storage: local filesystem inside container (`MEDPLUM_BINARY_STORAGE=file:./binary/`)
- Test data: `data/synthea/fhir/` — Synthea-generated FHIR patient JSON files used for seeding

## Authentication & Identity

**Auth Provider: Medplum OAuth2**
- Implementation: Custom OAuth2 password flow in `fhir-mcp-server/src/auth.py` (`MedplumAuth` class)
- Flow: POST to `/auth/login` → receive auth code → POST to `/oauth2/token` → receive Bearer token
- Token refresh: Automatic with 60-second buffer before expiry
- Credentials: `FHIR_SERVER_EMAIL` / `FHIR_SERVER_PASSWORD` (default: `admin@agentehr.local` / `medplum123`)
- PKCE: Uses plain code challenge (`codeChallengeMethod: "plain"`) — not production-grade

**Frontend Auth:**
- None detected — no auth layer on the Next.js frontend or FastAPI API
- The API server is open (CORS restricted to localhost origins only)

## FHIR Server (Medplum)

**Medplum FHIR R4 Server:**
- Self-hosted via Docker: `medplum/medplum-server:latest` on port 8103
- FHIR base URL: `http://localhost:8103/fhir/R4`
- Admin UI: `medplum/medplum-app:latest` on port 3001
- FHIR Resources used:
  - Patient, Condition, MedicationRequest, Observation, Encounter, AllergyIntolerance
  - CarePlan, Appointment, ServiceRequest, DocumentReference, Communication
- VM Bots enabled: `MEDPLUM_VM_CONTEXT_BOTS_ENABLED=true`

**FHIR MCP Server (local):**
- Location: `fhir-mcp-server/src/server.py`
- Protocol: MCP (Model Context Protocol) over stdio
- Tools exposed: 16 FHIR tools (search, read, write operations)
- In production: tools are called directly via `ToolExecutor` in "direct" mode (not over MCP stdio)

## Monitoring & Observability

**Error Tracking:**
- None — no Sentry, Datadog, or similar integration detected

**Logs:**
- Python: `logging` module with `basicConfig(level=logging.INFO)` configured at startup
- Logger names: `agentehr.api`, `agentehr.orchestrator`, `agentehr.openrouter`, `agentehr.narrative`, `fhir-mcp-server`, `fhir-mcp-server.auth`
- Output: stdout/stderr only; no log aggregation configured

## CI/CD & Deployment

**Hosting:**
- Local development only — no production hosting configuration detected

**CI Pipeline:**
- None — no GitHub Actions, CircleCI, or similar CI config detected

**Container Orchestration:**
- Docker Compose (`docker-compose.yml`) for local infrastructure only (Postgres, Redis, Medplum server + app)
- No Dockerfile for the Python API or Next.js frontend (run directly, not containerized)

## Environment Configuration

**Required env vars:**
- `OPENROUTER_API_KEY` - Required for all AI chat and narrative features; API returns 503 without it
- `MEDPLUM_BASE_URL` - FHIR server base URL (default: `http://localhost:8103/fhir/R4`)

**Optional env vars:**
- `ANTHROPIC_API_KEY` - Used as fallback for OpenRouter key; also required if using `AgentOrchestrator` directly
- `FHIR_SERVER_BASE_URL` - Override FHIR server URL for MCP server
- `FHIR_SERVER_EMAIL` / `FHIR_SERVER_PASSWORD` - Medplum credentials for MCP server auth
- `FHIR_SERVER_ACCESS_TOKEN` - Static token bypass (skips OAuth flow if set)

**Secrets location:**
- `.env` file at project root (loaded by `api/main.py` via `python-dotenv`)
- `.env` is in `.gitignore` (confirmed by file listing — not committed)

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- None detected — Medplum VM Bots are enabled in config but no bot implementations found in the codebase

## Drug Safety (Rule-Based, Local)

**Drug Interaction Checker:**
- Implementation: `fhir-mcp-server/src/validation/drug_interactions.py` — hardcoded rule-based system
- No external CDS API integration (comments note future integration with RxNorm API and FDA databases)
- Triggered during `create_medication_request` tool calls

---

*Integration audit: 2026-02-25*
