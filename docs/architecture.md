# AgentEHR Architecture

## Overview

AgentEHR is an agent-based Electronic Health Record interface that allows clinicians and patients to interact with EHR systems through natural language rather than traditional GUI navigation. It supports two portal modes — clinician and patient — with different AI behaviors, tool access, and UI layouts.

## Design Philosophy

**"Embed, Don't Replace"** — Following the Wellsheet model, AgentEHR integrates with existing EHR infrastructure via FHIR R4 APIs rather than replacing clinical systems.

**"Approve, Then Execute"** — All clinical write operations (orders, care plans, appointments) are created in draft status and require explicit clinician approval before execution.

**"Evidence Grounding"** — All AI recommendations include supporting data from patient records, ensuring transparency and verifiability.

**"Dual Persona"** — The same infrastructure serves both clinicians (proactive decision support) and patients (health literacy and self-service) through mode-aware system prompts, tool filtering, and UI rendering.

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                     1. USER INTERFACE LAYER                     │
│    Next.js 15 + React 19 + Tailwind CSS (port 3010)            │
│    Dual-mode: Clinician Portal / Patient Portal                │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     2. HTTP API LAYER                           │
│    FastAPI (port 8000) — Chat, Patient, Action, Narrative       │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                  3. AGENT ORCHESTRATION LAYER                   │
│    OpenRouter multi-model LLM + agentic tool-calling loop      │
│    Dynamic system prompt with patient context injection         │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    4. FHIR TOOL HANDLER LAYER                  │
│    47 async handlers: read, write (draft), approve, validate   │
│    Approval queue + drug interaction validation                │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      5. FHIR R4 BACKEND                        │
│    Medplum Server (port 8103) + PostgreSQL + Redis              │
└─────────────────────────────────────────────────────────────────┘
```

## Layer Details

### Layer 1: User Interface

**File:** `frontend/src/app/page.tsx` (~1050 lines)

The frontend is a single-page React application with three-panel layout:

```
┌──────────┬──────────────────────┬──────────┐
│  Sidebar │  Center Panel        │  Right   │
│  (264px) │  (flex-1)            │  Panel   │
│          │                      │  (288px) │
│ Search/  │ Patient Header       │ Actions/ │
│ Threads  │ + AI Narrative       │ Care     │
│ or       │ + Data Sections      │ Gaps     │
│ My Health│ + Chat Interface     │ or       │
│          │                      │ Requests │
└──────────┴──────────────────────┴──────────┘
```

**Dual-Mode Rendering:**

| Element | Clinician Mode | Patient Mode |
|---------|----------------|--------------|
| Sidebar | Patient search + chat threads | "My Health" navigation links |
| Header | Full demographics + MRN | Friendly name, no MRN |
| Narrative | Clinical third-person | Warm "you/your" language |
| Data sections | Clinical labels | Patient-friendly labels ("My Medications") |
| Right panel | Suggested actions + approval queue + care gaps | My requests + upcoming + quick actions |
| Chat bubble color | Cyan | Emerald |
| Incomplete data alert | Shown | Hidden |

**Key Components:**
- `CollapsibleSection` — Accordion sections with anchored IDs for sidebar navigation
- `StatusPill` — Color-coded count badges (allergies, conditions, care gaps)
- `ActionCard` — Pending action with approve/reject/queue buttons
- `CareGapCard` — Care gap alert with priority-based styling

**State Management:** React hooks (useState/useEffect), no external state library. Patient threads stored in `Map<string, PatientThread>` for O(1) lookup. Conversation IDs cached per patient for multi-turn chat continuity.

### Layer 2: HTTP API

**File:** `api/main.py`

FastAPI server that wraps the orchestrator for web access. Manages one orchestrator instance per conversation.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chat` | POST | Send message to AI (accepts `mode`, `patient_id`, `model`) |
| `/api/chat/{id}` | DELETE | Reset conversation |
| `/api/patients/search` | GET | Search patients by name/MRN |
| `/api/patients/{id}` | GET | Get patient demographics |
| `/api/patients/{id}/summary` | GET | Comprehensive patient summary (parallel FHIR fetches) |
| `/api/patients/{id}/narrative` | GET | AI-generated narrative (mode-aware, cached) |
| `/api/actions` | GET | List pending actions |
| `/api/actions/{id}/approve` | POST | Approve and execute action |
| `/api/actions/{id}/reject` | POST | Reject and delete action |
| `/health` | GET | Health check |

**Auto-context loading:** When `patient_id` is included in a chat request, the API auto-fetches the patient summary and injects it into the orchestrator's system prompt before the LLM processes the message.

**Narrative generation** (`api/narrative.py`): Uses Gemini 3 Flash to generate concise clinical narratives. In-memory cache with MD5 hash-based invalidation. Separate cache entries and prompts per mode (clinician vs patient).

### Layer 3: Agent Orchestration

**File:** `agents/openrouter_orchestrator.py` (~1050 lines)

The orchestrator implements a multi-turn agentic loop:

```
1. User sends message
2. Message added to conversation_history
3. Loop (up to 10 turns):
   a. Call LLM with: system prompt + conversation history + available tools
   b. If LLM returns tool_calls:
      - Execute each tool handler async
      - If tool was get_patient_summary: update patient context + rebuild system prompt
      - Append tool results to conversation history
      - Continue loop
   c. If LLM returns text only:
      - Return final response
4. Return OrchestratorResponse (content, tool_calls, tool_results, warnings, pending_actions)
```

**Dynamic System Prompt:** The system prompt is rebuilt whenever patient context changes. It includes:
- Base instructions from markdown file (clinician or patient prompt)
- Patient demographics
- Active conditions, medications, allergies
- Care gaps (auto-identified)
- Incomplete data flags
- Instruction to auto-use loaded patient_id (never ask)

**Mode-Aware Tool Filtering:**

```python
# Patient mode: restricted to 14 read-only tools + appointment requests
PATIENT_ALLOWED_TOOLS = {
    "get_patient", "get_patient_summary",
    "search_medications", "search_conditions", "search_observations",
    "search_procedures", "search_encounters", "search_appointments",
    "get_immunization_status", "get_lab_results_with_trends",
    "check_renal_function", "search_clinical_notes", "get_clinical_note",
    "create_appointment",  # Self-service only
}

# Clinician mode: all 47 tools available
```

**System Prompt Variants:**
- `agents/prompts/clinical_reasoning.md` — Proactive clinical decision support, care gap identification, evidence-based recommendations, safety warnings
- `agents/prompts/patient_portal.md` — Health literacy, plain language, "you/your" addressing, never provides medical advice, emergency protocol

**OpenRouter Client** (`agents/openrouter_client.py`): Wraps the OpenRouter API (OpenAI-compatible format). Converts between Anthropic-style tool use blocks and OpenAI-style function calling. Supports model aliases for easy switching.

### Layer 4: FHIR Tool Handlers

**File:** `fhir-mcp-server/src/handlers.py` (~2700 lines)

47 async handler functions organized by FHIR resource type:

| Category | Read Tools | Write Tools (Draft) |
|----------|-----------|-------------------|
| Patient | search_patient, get_patient, get_patient_summary | — |
| Medications | search_medications | create_medication_request, update_medication_status, delete_medication_request, reconcile_medications |
| Conditions | search_conditions | add_condition, update_condition_status |
| Allergies | — | create_allergy_intolerance, update_allergy_intolerance |
| Labs/Vitals | search_observations, get_lab_results_with_trends, check_renal_function | — |
| Procedures | search_procedures | create_procedure |
| Encounters | search_encounters | create_encounter_note, create_phone_encounter |
| Appointments | search_appointments | create_appointment |
| Clinical Notes | search_clinical_notes, get_clinical_note | — |
| Immunizations | get_immunization_status | — |
| Orders | — | create_diagnostic_order, create_care_plan |
| Referrals | search_referrals | create_referral |
| Communication | — | create_communication |
| Documentation | — | document_counseling, create_work_note |
| Action Queue | list_pending_actions | approve_action, reject_action |

**get_patient_summary** is the most complex handler — it fetches 9 FHIR resource types in parallel via `asyncio.gather`, then runs automated analysis:

- **Care gap analysis**: Checks immunization history against age-based guidelines, identifies missing screenings (A1C for diabetics, eye exams, etc.)
- **Incomplete data identification**: Flags undocumented allergies (high priority), missing vitals, no encounters

**Approval Queue** (`approval_queue.py`): In-memory action queue with UUID-based tracking. Actions progress: `PENDING → APPROVED → EXECUTED` or `PENDING → REJECTED`. All create operations queue through here.

**Drug Interaction Validation** (`validation/drug_interactions.py`): Called automatically on `create_medication_request`. Checks 15+ drug-drug rules and allergy cross-reactivity. Returns severity-graded warnings (contraindicated, severe, moderate, info).

### Layer 5: FHIR R4 Backend

**Medplum** (self-hosted via Docker Compose):
- FHIR R4 compliant server on port 8103
- PostgreSQL for persistence
- Redis for caching
- OAuth2 authentication (password grant, auto-refreshing tokens)

**FHIR Resources Used:**

| Resource | Purpose |
|----------|---------|
| Patient | Demographics, identifiers |
| Condition | Problem list (SNOMED + ICD-10 codes) |
| MedicationRequest | Active/draft medication orders (RxNorm codes) |
| AllergyIntolerance | Allergy documentation |
| Observation | Labs and vitals (LOINC codes) |
| Procedure | Procedure history (CPT + SNOMED codes) |
| Immunization | Vaccine records (CVX codes) |
| Encounter | Visit history |
| Appointment | Scheduled visits |
| DocumentReference | Clinical notes (base64-encoded content) |
| ServiceRequest | Lab/imaging orders, referrals |
| CarePlan | Care coordination plans |
| Communication | Letters and notifications |

## Data Flow

### Read Operations (Safe)

```
User asks question
  → API receives message
  → Orchestrator calls LLM
  → LLM issues tool_call (e.g., search_medications)
  → Handler queries FHIR server
  → Structured result returned to LLM
  → LLM formulates human-readable response
  → Response returned to frontend
```

### Write Operations (Approval Required)

```
User requests action (e.g., "Order metformin")
  → LLM issues create_medication_request tool_call
  → Handler:
      1. Builds draft FHIR MedicationRequest (status=draft)
      2. POSTs to FHIR server → gets resource ID
      3. Validates drug interactions
      4. Queues in ApprovalQueue (status=PENDING)
  → Returns action_id + warnings to LLM
  → LLM presents order summary to user
  → User clicks Approve or Reject in UI
  → approve_action handler:
      1. Updates FHIR resource (draft → active)
      2. PUTs to FHIR server
      3. Marks action EXECUTED
      4. Invalidates narrative cache
```

### Narrative Generation

```
Patient loaded → Frontend requests /api/patients/{id}/narrative?mode={mode}
  → API fetches patient summary
  → Hashes summary data (MD5)
  → Cache check: if hash matches cached → return cached narrative
  → If miss: format data → call Gemini 3 Flash with mode-specific prompt
  → Cache result (keyed by patient_id:mode)
  → Return narrative + metadata
```

## Portal Mode Architecture

The mode switch affects every layer:

| Layer | Clinician Mode | Patient Mode |
|-------|----------------|--------------|
| **Frontend** | Dark slate theme, patient search, multi-patient threads, care gaps, approval queue | Emerald theme, single-patient "My Health" navigation, quick actions |
| **API** | `mode=clinician` passed to orchestrator | `mode=patient` passed to orchestrator |
| **Orchestrator** | 47 tools, clinical reasoning prompt, proactive care gap identification | 14 tools (read-only + appointments), patient portal prompt, health literacy focus |
| **Narrative** | Third-person clinical style | Second-person plain language |
| **Tool access** | Full CRUD on all resources | Read-only + self-service appointment requests |

## Safety Mechanisms

1. **Approval Queue** — All create operations produce draft FHIR resources queued for clinician review
2. **Drug Interaction Checking** — Automatic validation on medication orders with severity-graded warnings
3. **Renal Dosing** — `check_renal_function` provides eGFR/creatinine for medication dosing decisions
4. **Care Gap Identification** — Auto-analyzed in `get_patient_summary`, surfaced proactively in system prompt
5. **Mode-Based Tool Restrictions** — Patient portal limited to read-only tools
6. **System Prompt Enforcement** — "Never auto-approve orders", "Always use patient_id automatically"
7. **Emergency Protocol** — Patient mode AI advises calling 911 for described emergencies

## Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| FHIR Server | Medplum | FHIR-native, open source, modern stack, self-hosted |
| API Framework | FastAPI | Async-native Python, auto-docs, Pydantic validation |
| LLM Access | OpenRouter | Multi-model support, single API key, cost optimization |
| Frontend | Next.js 15 + React 19 | Modern React with server components, Tailwind for styling |
| Tool Framework | Direct async handlers | Simple, testable, no framework overhead |
| State Management | React hooks | Sufficient for current complexity, no external deps |

## Scalability

**Current (Demo/MVP):**
- Single Medplum instance
- Single API server process
- In-memory approval queue and narrative cache
- Per-conversation orchestrator instances

**Production Considerations:**
- Medplum cluster with read replicas
- Redis-backed approval queue and narrative cache
- Persistent conversation storage (database)
- Horizontal API scaling with shared state
- Rate limiting and token budgets per conversation
- SMART on FHIR (OAuth 2.0) for production auth
- Audit logging via FHIR AuditEvent resources
