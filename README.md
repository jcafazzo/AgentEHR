# AgentEHR

An agent-based Electronic Health Record interface that allows clinicians and patients to interact with EHR systems through natural language instead of traditional GUI navigation.

AgentEHR interprets clinical intent, orchestrates AI agents to perform tasks via FHIR R4, and presents action items for clinician approval. It supports two modes: a **clinician portal** for clinical decision support and a **patient portal** for health literacy and self-service.

## Architecture

```
┌─────────────────┐    HTTP     ┌──────────────────┐    OpenRouter    ┌───────────┐
│   Next.js UI    │ ──────────► │   FastAPI Server  │ ──────────────► │  LLM API  │
│  localhost:3010  │            │  localhost:8000   │                 │ (multi-model)│
└─────────────────┘            └────────┬─────────┘                 └───────────┘
                                        │ Tool calls
                               ┌────────▼─────────┐
                               │   FHIR Handlers   │
                               │   (47 tools)      │
                               └────────┬─────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
           ┌────────▼──────┐  ┌────────▼──────┐  ┌────────▼──────┐
           │ Approval Queue│  │ Drug Interact. │  │  FHIR Client  │
           │  (in-memory)  │  │  Validation    │  │  (OAuth2)     │
           └───────────────┘  └───────────────┘  └────────┬──────┘
                                                          │
                                                 ┌────────▼──────┐
                                                 │ Medplum FHIR  │
                                                 │ localhost:8103 │
                                                 └───────────────┘
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- Node.js 18+
- An [OpenRouter](https://openrouter.ai/) API key

### 1. Start Medplum FHIR Server

```bash
docker-compose up -d
```

Wait for healthy status, then access Medplum at http://localhost:8103.

### 2. Seed Patient Data

```bash
python3 scripts/seed_patients.py
```

Creates 5 realistic test patients with comprehensive clinical histories:

| Patient | Age/Gender | Profile |
|---------|------------|---------|
| John Smith | 56M | Metabolic syndrome (diabetes, hypertension, hyperlipidemia) |
| Maria Garcia | 68F | Cardiopulmonary (AFib, heart failure, COPD) |
| Robert Johnson | 45M | Chronic kidney disease + diabetes |
| Emily Chen | 72F | Autoimmune/endocrine (RA, hypothyroidism, osteoporosis) |
| James Wilson | 62M | Post-cardiac event (recent MI, dual antiplatelet) |

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env and set:
# OPENROUTER_API_KEY=your_key_here
```

### 4. Start the API Server

```bash
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Start the Frontend

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:3010 in your browser.

### 6. Verify

```bash
curl http://localhost:8000/health
```

## Features

### Dual Portal Modes

**Clinician Portal** (default) — One-to-many model for clinical decision support:
- Search and manage multiple patients
- Full clinical data with all FHIR resource types
- AI-powered proactive care gap identification
- Medication ordering with drug interaction validation
- Approval queue for all clinical actions
- 47 FHIR tools available

**Patient Portal** — One-to-one model for patient engagement:
- Patients view their own health record
- Plain-language explanations of conditions, medications, and labs
- Self-service scheduling and refill requests
- Health literacy-focused AI assistant
- 14 read-only tools + appointment requests

### Safety & Approval Workflow

All clinical write operations (medications, orders, referrals, etc.) are created as **draft** FHIR resources and queued for explicit clinician approval before execution.

```
AI suggests action → Draft FHIR resource created → Queued for approval
                                                         │
                                          ┌──────────────┼──────────────┐
                                          │                             │
                                       Approve                       Reject
                                          │                             │
                                   Resource activated            Draft deleted
```

### Proactive Clinical Decision Support

When a patient is loaded, the AI automatically:
- Analyzes care gaps (missing vaccines, overdue screenings)
- Identifies incomplete data (undocumented allergies, outdated records)
- Flags clinical alerts (abnormal labs, drug interactions)
- Suggests actionable follow-ups

### Drug Interaction Validation

Medication orders are automatically checked against:
- 15+ drug-drug interaction rules (Warfarin+NSAIDs, Statins+Amiodarone, etc.)
- Allergy cross-reactivity (Penicillin→Cephalosporins, Sulfa→Thiazides, etc.)
- Renal dosing considerations

### AI-Generated Narratives

Concise clinical summaries generated per patient with mode-specific language:
- **Clinician mode**: Third-person clinical style ("62yo male presenting with...")
- **Patient mode**: Second-person plain language ("You have Type 2 diabetes, which means...")

### Multi-Model Support

Switchable LLM backends via OpenRouter:

| Alias | Model | Notes |
|-------|-------|-------|
| `gemini` | Gemini 2.5 Flash Lite | Default, fast |
| `glm-5` | GLM-5 | Strong tool use |
| `claude-sonnet` | Claude 3.5 Sonnet | Anthropic |
| `gpt-4o` | GPT-4o | OpenAI |

## Project Structure

```
AgentEHR/
├── api/                          # FastAPI HTTP server
│   ├── main.py                   # API endpoints (chat, patients, actions, narrative)
│   └── narrative.py              # AI narrative generation with caching
├── agents/                       # Agent orchestration layer
│   ├── openrouter_orchestrator.py # Multi-model agentic loop with tool calling
│   ├── openrouter_client.py      # OpenRouter API client
│   ├── orchestrator.py           # Anthropic SDK orchestrator (alternative)
│   ├── prompts/
│   │   ├── clinical_reasoning.md # Clinician system prompt
│   │   └── patient_portal.md     # Patient portal system prompt
│   └── workflows/
│       ├── medication_order.py   # Medication ordering workflow
│       └── post_encounter.py     # Post-encounter action generation
├── fhir-mcp-server/              # FHIR tool handlers
│   └── src/
│       ├── handlers.py           # 47 FHIR tool handler functions
│       ├── server.py             # MCP server entry point
│       ├── auth.py               # Medplum OAuth authentication
│       ├── approval_queue.py     # In-memory action queue
│       └── validation/
│           └── drug_interactions.py
├── frontend/                     # Next.js 15 + React 19 + Tailwind
│   └── src/
│       ├── app/
│       │   ├── page.tsx          # Main UI (chat, patient data, dual mode)
│       │   └── queue/page.tsx    # Standalone approval queue
│       ├── components/           # ActionCard, CareGapCard, StatusPill, etc.
│       └── lib/types.ts          # TypeScript type definitions
├── scripts/                      # Setup and seed scripts
│   ├── seed_patients.py          # Create 5 test patients in Medplum
│   ├── load_synthea.sh           # Load Synthea synthetic data
│   ├── cli_openrouter.py         # CLI chat interface
│   └── setup.sh                  # Environment setup
├── data/synthea/                 # Synthetic FHIR bundles
├── docs/                         # Architecture, API docs, diagrams
└── docker-compose.yml            # Medplum stack (PostgreSQL, Redis, FHIR server)
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| FHIR Backend | Medplum (self-hosted, Docker) |
| API Server | FastAPI (Python) |
| Agent Orchestration | OpenRouter (multi-model) |
| Frontend | Next.js 15, React 19, Tailwind CSS |
| Sample Data | Synthea + custom seed scripts |
| Drug Validation | Built-in interaction rules |

## Documentation

- [Architecture Deep-Dive](docs/architecture.md) — System layers, data flow, safety mechanisms
- [API Reference](docs/api-documentation.md) — HTTP endpoints + 47 FHIR tool specifications
- [UI Design Specs](docs/ui-design-specs.md) — Frontend design guidelines
- [Claude Desktop Setup](docs/claude-desktop-config.md) — MCP server configuration for Claude Desktop

## Use Cases

### Clinician Mode

```
"Show me John Smith's summary"
"Order metformin 500mg twice daily"
"Are there any drug interactions with his current medications?"
"Refer to ophthalmology for diabetic eye exam"
"Generate action items from today's encounter"
```

### Patient Mode

```
"What medications am I taking and why?"
"When is my next appointment?"
"Can you help me schedule a follow-up?"
"What does my A1C result mean?"
"Help me prepare questions for my next doctor visit"
```

## References

- [Medplum Documentation](https://www.medplum.com/docs)
- [FHIR R4 Specification](https://hl7.org/fhir/R4/)
- [OpenRouter API](https://openrouter.ai/docs)
- [Wellsheet](https://www.wellsheet.com/) — Commercial validation of the "embed, don't replace" approach
