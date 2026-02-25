# Codebase Concerns

**Analysis Date:** 2026-02-25

## Security Considerations

**Live API Key Committed to Git:**
- Risk: A real OpenRouter API key (`sk-or-v1-d505ad...`) is committed in plaintext inside `/Users/jcafazzo/CODING/AgentEHR/.env`. Although `.env` is in `.gitignore`, the file exists in the working tree and has appeared in prior commits. It could be exposed in logs, shared environments, or if `.gitignore` is bypassed.
- Files: `/Users/jcafazzo/CODING/AgentEHR/.env`
- Current mitigation: `.gitignore` lists `.env`
- Recommendations: Rotate the key immediately. Audit git history with `git log --all -- .env`. Use secret scanning in CI. Confirm the key is not present in any committed snapshot.

**Hardcoded Default Admin Credentials:**
- Risk: `fhir_server_email = "admin@agentehr.local"` and `fhir_server_password = "medplum123"` are hardcoded as default values in two separate places. If environment variables are not explicitly set, the application uses these defaults in production.
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/handlers.py` (lines 26-27), `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/server.py` (lines 36-37)
- Current mitigation: Overridable via `FHIR_SERVER_EMAIL` and `FHIR_SERVER_PASSWORD` env vars
- Recommendations: Replace defaults with `None` and fail fast at startup if not set. Remove inline fallback values from code.

**No API Authentication on FastAPI Server:**
- Risk: The FastAPI server in `/Users/jcafazzo/CODING/AgentEHR/api/main.py` exposes all clinical endpoints (`/api/chat`, `/api/patients/*`, `/api/actions/*`) with no authentication middleware, API key check, or session validation. Any process that can reach port 8000 can read and write patient data.
- Files: `/Users/jcafazzo/CODING/AgentEHR/api/main.py`
- Current mitigation: CORS restricted to `localhost:3000` and `localhost:3010` only
- Recommendations: Add Bearer token or API key middleware before any production deployment. FastAPI's `Security` dependency injection is the appropriate mechanism.

**OAuth PKCE Code Challenge Uses Static Plain-Text Value:**
- Risk: The OAuth PKCE `code_challenge` is hardcoded as the string `"medplum_mcp_server_challenge"` and `codeChallengeMethod` is `"plain"`. This defeats the purpose of PKCE and is effectively equivalent to no challenge at all. Legitimate PKCE uses a random per-session verifier with SHA-256 hashing.
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/auth.py` (lines 60-69)
- Current mitigation: None
- Recommendations: Generate a cryptographically random verifier per login attempt and use `S256` challenge method via `hashlib.sha256`.

**Stray pip Output File Committed to Repo Root:**
- Risk: The file `/Users/jcafazzo/CODING/AgentEHR/=0.40.0` is a pip install log accidentally committed to the repo root. While not a security risk, it pollutes the repo and suggests careless state management.
- Files: `/Users/jcafazzo/CODING/AgentEHR/=0.40.0`
- Recommendations: Delete and add to `.gitignore`. Likely caused by running `pip install anthropic>=0.40.0` with the `>=` inadvertently interpreted as a file path redirect.

---

## Tech Debt

**Massive Code Duplication: `handlers.py` and `server.py`:**
- Issue: The FHIR tool handler logic is duplicated across two files. `handlers.py` (2,739 lines) contains 36 `handle_*` async functions. `server.py` (2,429 lines) contains 20 of the same `handle_*` functions as a separate implementation. Both maintain their own `FHIRClient` instance (`fhir_client`) and `Settings` class. Any bug fix or feature change must be applied in both files.
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/handlers.py`, `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/server.py`
- Impact: High maintenance burden. The two implementations can silently diverge. `server.py` does not have the Phase 8 clinical tools (allergy, condition, procedure, referral, etc.) — those only exist in `handlers.py`.
- Fix approach: `server.py` should import all handler functions from `handlers.py` rather than re-implementing them. Handlers already exist in `handlers.py` for this purpose per the module docstring.

**Unimplemented MCP Client and HTTP Client Modes:**
- Issue: `agents/orchestrator.py` defines three connection modes (`direct`, `mcp`, `http`) but two of them raise `NotImplementedError`. The TODO comments at lines 585 and 590 confirm they were never implemented. The file is 1,051 lines and appears to be a legacy version superseded by `openrouter_orchestrator.py`.
- Files: `/Users/jcafazzo/CODING/AgentEHR/agents/orchestrator.py` (lines 583-591)
- Impact: Dead code increases confusion about which orchestrator is canonical. The `agents/orchestrator.py` file may still be imported by scripts.
- Fix approach: Either complete the MCP/HTTP modes or delete `orchestrator.py` and update all imports to use `openrouter_orchestrator.py`.

**`sys.path.insert` Used Throughout as Packaging Workaround:**
- Issue: Nine separate files use `sys.path.insert(0, ...)` to resolve imports instead of proper Python packaging. This means the application only works when run from specific directories and makes refactoring error-prone.
- Files: `/Users/jcafazzo/CODING/AgentEHR/api/main.py` (lines 26-27), `/Users/jcafazzo/CODING/AgentEHR/agents/openrouter_orchestrator.py` (line 21), `/Users/jcafazzo/CODING/AgentEHR/scripts/cli_openrouter.py` (lines 27-28), `/Users/jcafazzo/CODING/AgentEHR/scripts/cli_agent.py` (lines 39-40), `/Users/jcafazzo/CODING/AgentEHR/scripts/seed_patients.py` (line 24), `/Users/jcafazzo/CODING/AgentEHR/scripts/test_approval_flow.py` (line 15), `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/test_server.py` (line 14)
- Impact: Fragile module resolution. Import errors are common when running from unexpected working directories.
- Fix approach: Add a `pyproject.toml` or `setup.py` with proper package declarations and install the packages in editable mode (`pip install -e .`).

**Inconsistent Default Model Between Frontend and Backend:**
- Issue: `ChatRequest` in `/Users/jcafazzo/CODING/AgentEHR/api/main.py` defaults `model` to `"gemini"`, but `get_or_create_orchestrator` defaults to `"glm-5"`. A request without an explicit model will use `"gemini"` (from the Pydantic model), which then overrides the orchestrator's `"glm-5"` default. The frontend does not appear to send a model field at all.
- Files: `/Users/jcafazzo/CODING/AgentEHR/api/main.py` (lines 49, 107)
- Impact: Confusing and potentially unintended model selection.
- Fix approach: Align defaults to a single canonical value and document it clearly. Consider making the default explicit in the frontend request.

**Import of Deprecated `asyncio` Pattern in `handlers.py`:**
- Issue: `handlers.py` uses `import asyncio` at line 9 but also does `from datetime import datetime` inside a local function scope at line 1335 (`handle_approve_action`). Additionally `import base64` and `import re` appear inside function bodies at lines 834 and 1675-1683 rather than at module level, breaking standard Python style and reducing readability.
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/handlers.py` (lines 1294, 1303, 1335, 1663, 1675)
- Impact: Minor but signals hasty incremental development. IDE static analysis tools will flag these.
- Fix approach: Move all imports to module-level.

---

## Performance Bottlenecks

**In-Memory Approval Queue Lost on Restart:**
- Problem: `ApprovalQueue` in `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/approval_queue.py` stores all pending clinical actions in process memory (`self._actions: dict`). A server restart or crash silently discards all pending approvals, including any drafted-but-not-yet-approved FHIR resources left in `draft` status with no way to recover them.
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/approval_queue.py` (line 93-100, docstring acknowledges this)
- Cause: By design for the prototype; the class docstring explicitly notes Redis or database is needed for production.
- Improvement path: Implement a Redis-backed or database-backed queue. The `ApprovalQueue` interface is clean and isolated; adding a persistence layer only requires replacing the internal `_actions` dict.

**In-Memory Conversation History Grows Without Bound:**
- Problem: Each `OpenRouterOrchestrator` instance accumulates `conversation_history` indefinitely as a plain list. Long sessions will grow the context window beyond model limits and consume increasing memory on the server. The `orchestrators` dict in `api/main.py` also never evicts old conversations.
- Files: `/Users/jcafazzo/CODING/AgentEHR/agents/openrouter_orchestrator.py` (line 648), `/Users/jcafazzo/CODING/AgentEHR/api/main.py` (line 46-61)
- Cause: No TTL, no LRU eviction, no conversation summarization.
- Improvement path: Add a TTL-based eviction for `orchestrators` dict entries. Add context window management (e.g., sliding window or summarization) to `process_message`.

**Narrative Cache Has No Size Limit or TTL:**
- Problem: The `_narrative_cache` dict in `/Users/jcafazzo/CODING/AgentEHR/api/narrative.py` stores generated narratives per `{patient_id}:{mode}` key forever. With many patients and modes, this cache can grow without bound.
- Files: `/Users/jcafazzo/CODING/AgentEHR/api/narrative.py` (line 19)
- Cause: No TTL or maximum entry count.
- Improvement path: Use `functools.lru_cache` with a size limit or add a TTL-based invalidation.

**No Retry Logic for OpenRouter API Calls:**
- Problem: The `OpenRouterClient.create_message` method makes a single HTTP request with no retry on transient failures (network timeout, 429 rate limit, 503 service unavailable). A single transient error aborts the entire chat request.
- Files: `/Users/jcafazzo/CODING/AgentEHR/agents/openrouter_client.py` (lines 229-238)
- Cause: Not implemented.
- Improvement path: Add exponential backoff with jitter using `tenacity` or a manual retry loop for `429` and `5xx` responses.

---

## Fragile Areas

**`handle_approve_action` Has Race Condition Potential:**
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/handlers.py` (lines 1248-1331)
- Why fragile: The approve flow reads the FHIR resource, modifies its status field, then writes it back with a PUT. There is no optimistic concurrency check (ETag/`If-Match` header). Two concurrent approvals for the same action could result in a lost update. The `ApprovalQueue` itself has no async locking, only thread locking via `threading.RLock`, which does not prevent asyncio-level interleaving.
- Safe modification: Add FHIR `If-Match` header support using the `meta.versionId` from the read response. Wrap approval queue mutations in `asyncio.Lock` rather than `threading.RLock` for the async context.
- Test coverage: No automated tests covering concurrent approval scenarios.

**`fhir_client` is a Module-Level Singleton Without Explicit Lifecycle:**
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/handlers.py` (line 150), `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/server.py` (line 162)
- Why fragile: `FHIRClient` is instantiated at module import time. There is no explicit `close()` call on application shutdown for the handlers module path. The `httpx.AsyncClient` inside `FHIRClient` may leak connections. The server.py lifespan context only closes the MCP server's own client, not the handlers module's client.
- Safe modification: Add explicit shutdown hook or use a dependency injection pattern (FastAPI's `Depends`) for the FHIR client.

**Drug Interaction Checker Uses Substring Matching:**
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/validation/drug_interactions.py` (lines 203-220)
- Why fragile: The interaction check uses substring containment (`drug_normalized in new_med_normalized or new_med_normalized in drug_normalized`) which produces false positives. For example, a search for "amoxicillin" could match "moxifloxacin" incorrectly. The knowledge base is also a hardcoded list of ~12 interactions — far below clinical requirements.
- Safe modification: Replace substring matching with exact normalized name matching. The module's own docstring acknowledges this is for demonstration only and should use RxNorm + FDA databases in production.
- Test coverage: No automated tests exist for this module.

**Patient Portal Mode Tool Filtering Relies on Set Membership:**
- Files: `/Users/jcafazzo/CODING/AgentEHR/agents/openrouter_orchestrator.py` (lines 611-620, 751-755)
- Why fragile: `PATIENT_ALLOWED_TOOLS` is a hard-coded set of tool names. If a new clinical tool is added to `FHIR_TOOLS` and is write-capable, it will automatically be available to patient portal users until someone remembers to update this set. There is no explicit deny-list enforcement test.
- Safe modification: Invert the logic to an explicit deny-list of privileged tools, or add a test that validates every new tool is explicitly categorized.

---

## Known Bugs

**Appointment Approval Uses Current Time as Fallback:**
- Symptoms: When approving an appointment that has no `requestedPeriod.start` set, the approve handler silently substitutes `datetime.now(UTC)` as the appointment start time. Clinicians see an appointment scheduled "right now" with no indication it was a placeholder.
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/handlers.py` (lines 1302-1306)
- Trigger: Approve any `Appointment` action where the AI created the appointment without specifying a preferred datetime.
- Workaround: Always include `preferred_datetime` when calling `create_appointment`.

**`search_patient` Tool Argument Normalization Diverges Between Orchestrators:**
- Symptoms: In `openrouter_orchestrator.py`, `search_patient` arguments are manually remapped from `query` to `name` at execution time (line 901-902). In `orchestrator.py` (legacy) this remapping does not exist. If any code path uses the legacy orchestrator, patient search will silently return empty results.
- Files: `/Users/jcafazzo/CODING/AgentEHR/agents/openrouter_orchestrator.py` (lines 899-903), `/Users/jcafazzo/CODING/AgentEHR/agents/orchestrator.py`
- Trigger: Using the legacy `orchestrator.py` path.
- Workaround: `handlers.py` itself also accepts `query` as an alias (line 164), so the remapping may be redundant; however the inconsistency remains.

---

## Missing Critical Features

**No Authentication or Authorization Layer:**
- Problem: The entire application — including creating medication orders, approving clinical actions, and reading PHI — has no user authentication. Any process or script that can connect to port 8000 has full write access.
- Blocks: Any production or multi-user deployment.

**Approval Queue Has No Persistence:**
- Problem: All pending clinical actions are lost on server restart. FHIR draft resources created before the restart remain orphaned in the FHIR server with no queue entry to approve or reject them.
- Blocks: Reliable clinical workflow in any environment that restarts servers.

**No Audit Trail for Clinical Actions:**
- Problem: When an action is approved or rejected, only a log line is emitted. There is no persistent audit record of who approved what and when. This is a compliance requirement for any clinical system (HIPAA, Joint Commission, etc.).
- Blocks: Regulatory compliance, clinical accountability.

**Drug Interaction Database Is a Demonstration Stub:**
- Problem: The drug interaction checker covers only ~12 drug pairs from a hardcoded list. It uses substring matching rather than normalized drug codes. As explicitly noted in the source, it does not integrate with RxNorm, FDA databases, or any clinical decision support system.
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/validation/drug_interactions.py`
- Blocks: Clinical safety in any real patient care scenario.

---

## Test Coverage Gaps

**Zero Automated Tests for Core Clinical Logic:**
- What's not tested: All FHIR handler functions, the approval workflow, medication safety checking, narrative generation, the orchestrator's tool execution loop, and the FastAPI endpoints.
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/handlers.py`, `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/approval_queue.py`, `/Users/jcafazzo/CODING/AgentEHR/api/main.py`, `/Users/jcafazzo/CODING/AgentEHR/agents/openrouter_orchestrator.py`
- The only test file is `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/test_server.py` which is an integration test requiring a live Medplum server — not a unit test.
- Risk: Regressions in the approval flow, drug interaction checks, or patient data parsing go completely undetected.
- Priority: High

**No Tests for Drug Interaction Logic:**
- What's not tested: `check_drug_interactions`, `check_allergy_interactions`, `validate_medication_safety` in the drug interactions module.
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/validation/drug_interactions.py`
- Risk: False negatives (missed interactions) or false positives (blocking safe medications) could harm patients in a real clinical setting.
- Priority: High

**No Tests for ApprovalQueue:**
- What's not tested: Concurrency behavior, race conditions between `approve` and `reject`, TTL-less growth, queue state after server crash recovery.
- Files: `/Users/jcafazzo/CODING/AgentEHR/fhir-mcp-server/src/approval_queue.py`
- Risk: Silent data loss or state corruption in the approval workflow.
- Priority: High

---

## Scaling Limits

**Single-Process State Management:**
- Current capacity: All state (approval queue, conversation history, narrative cache, alert manager) lives in a single Python process.
- Limit: Adding a second API server process immediately breaks the approval queue (two processes have separate in-memory queues), narrative cache (duplicate generation), and conversation history (requests may be routed to the wrong process).
- Scaling path: Externalize all state to Redis or a database before adding any second process.

---

*Concerns audit: 2026-02-25*
