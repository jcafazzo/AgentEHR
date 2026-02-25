# STRUCTURE - Directory Layout & Key Locations

## Directory Tree

```
AgentEHR/
├── api/                          # FastAPI HTTP server
│   ├── main.py                   # Entry point, all HTTP endpoints (334 lines)
│   ├── narrative.py              # AI narrative generation with caching
│   └── simulation.py             # (planned) Simulation API endpoints
│
├── agents/                       # Agent orchestration layer
│   ├── __init__.py               # Package exports (imports orchestrator)
│   ├── openrouter_orchestrator.py # PRIMARY: Multi-model orchestrator (1000+ lines)
│   ├── openrouter_client.py      # OpenRouter API client wrapper
│   ├── orchestrator.py           # Alternative Anthropic SDK orchestrator (legacy)
│   ├── requirements.txt          # Python dependencies
│   ├── prompts/
│   │   ├── clinical_reasoning.md # Clinician system prompt
│   │   └── patient_portal.md     # Patient portal system prompt
│   ├── scoring/                  # Clinical scoring systems (NEW)
│   │   ├── __init__.py
│   │   └── clinical_scores.py    # NEWS2, qSOFA, SOFA, KDIGO
│   ├── alerts/                   # Alert classification (NEW)
│   │   └── alert_manager.py      # 4-tier alert system
│   └── workflows/
│       ├── medication_order.py   # Medication ordering workflow
│       └── post_encounter.py     # Post-encounter action generation
│
├── fhir-mcp-server/              # FHIR MCP tool server
│   └── src/
│       ├── handlers.py           # 47+ FHIR tool handlers (2739 lines)
│       ├── server.py             # MCP server entry point
│       ├── auth.py               # Medplum OAuth authentication
│       ├── approval_queue.py     # In-memory action approval queue
│       ├── test_server.py        # Test suite
│       └── validation/
│           └── drug_interactions.py  # Drug interaction rules
│
├── frontend/                     # Next.js 15 + React 19 + Tailwind
│   ├── package.json              # Dependencies
│   └── src/
│       ├── app/
│       │   ├── layout.tsx        # Root layout
│       │   ├── page.tsx          # Main UI (chat, patient data, dual mode)
│       │   └── queue/page.tsx    # Standalone approval queue page
│       ├── components/
│       │   ├── ActionCard.tsx    # Actionable item card
│       │   ├── CareGapCard.tsx   # Care gap display
│       │   ├── CollapsibleSection.tsx
│       │   ├── StatusPill.tsx    # Status badge
│       │   └── index.ts         # Component exports
│       └── lib/
│           └── types.ts          # TypeScript type definitions
│
├── simulation/                   # Simulation engine (NEW)
│   ├── __init__.py               # Package exports
│   ├── engine.py                 # Core simulation engine (asyncio)
│   ├── models.py                 # Data models (VitalSigns, SimulationState, etc.)
│   ├── physiology.py             # Vital sign & lab generation models
│   └── scenarios/                # YAML scenario definitions (planned)
│
├── scripts/                      # Setup and data seeding
│   ├── seed_patients.py          # Create 5 test patients (70K lines)
│   ├── cli_agent.py              # CLI chat interface
│   ├── cli_openrouter.py         # CLI OpenRouter interface
│   ├── load_synthea.sh           # Load Synthea data
│   └── setup.sh                  # Environment setup
│
├── data/synthea/                 # Synthetic FHIR data files
├── docs/                         # Documentation
│   ├── PRD.md                    # Product Requirements Document (NEW)
│   ├── api-documentation.md      # Full API spec
│   ├── architecture.md           # System architecture
│   └── ui-design-specs.md        # UI/UX guidelines
│
├── docker-compose.yml            # Medplum FHIR stack
├── .env                          # Environment variables
└── README.md                     # Project documentation
```

## Key File Locations

| Purpose | File |
|---------|------|
| API entry point | `api/main.py` |
| Agent orchestrator | `agents/openrouter_orchestrator.py` |
| FHIR tool handlers | `fhir-mcp-server/src/handlers.py` |
| Main frontend page | `frontend/src/app/page.tsx` |
| TypeScript types | `frontend/src/lib/types.ts` |
| Clinical scoring | `agents/scoring/clinical_scores.py` |
| Alert system | `agents/alerts/alert_manager.py` |
| Simulation engine | `simulation/engine.py` |
| Physiology models | `simulation/physiology.py` |
| System prompts | `agents/prompts/clinical_reasoning.md` |
| Drug interactions | `fhir-mcp-server/src/validation/drug_interactions.py` |
| Patient seeding | `scripts/seed_patients.py` |

## Naming Conventions

- **Python**: `snake_case` for files, functions, variables
- **TypeScript/React**: `PascalCase` for components, `camelCase` for functions/variables
- **FHIR handlers**: `handle_<verb>_<resource>()` pattern (e.g., `handle_search_patient`)
- **API endpoints**: `/api/<resource>` REST pattern
- **Frontend pages**: Next.js App Router file-based routing

## Where to Add New Code

| Adding... | Location |
|-----------|----------|
| New API endpoint | `api/main.py` |
| New FHIR tool handler | `fhir-mcp-server/src/handlers.py` |
| New frontend page | `frontend/src/app/<name>/page.tsx` |
| New React component | `frontend/src/components/<Name>.tsx` |
| New agent workflow | `agents/workflows/<name>.py` |
| New scoring system | `agents/scoring/clinical_scores.py` |
| New simulation scenario | `simulation/scenarios/<name>.yaml` |
