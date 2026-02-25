# Architecture Research

## Component Boundaries

### Layer 1: FHIR Data Access Layer
**Boundary**: All clinical data access flows through FHIR R4 handlers. No direct DB queries.
- Expand `fhir-mcp-server/src/handlers.py` with ~35 new inpatient handlers
- Group by domain: encounter management, clinical assessment, task/workflow, communication
- Each handler: async function, dict in → dict out, shared FHIRClient

### Layer 2: Agent Orchestration Layer
**Boundary**: Agents reason about patient state but never directly modify treatment.

```
agents/
├── supervisor.py           # Supervisor agent (1 per patient)
├── agent_registry.py       # Agent template registry + lifecycle management
├── patient_state.py        # Shared patient state container
├── knowledge_base.py       # ChromaDB RAG interface
├── specialists/
│   ├── base_agent.py       # Abstract specialist agent base class
│   ├── cardiology.py       # ACC/AHA guidelines
│   ├── infectious_disease.py  # Surviving Sepsis Campaign
│   ├── medication_safety.py   # Drug interactions, renal dosing
│   ├── renal.py            # KDIGO guidelines
│   ├── pulmonary.py        # GOLD, PE protocols
│   └── clinical_trials.py  # ClinicalTrials.gov matching
├── scoring/                # Clinical scoring (existing)
│   └── clinical_scores.py
├── alerts/                 # Alert management (existing)
│   └── alert_manager.py
└── prompts/                # System prompt templates (existing)
```

### Layer 3: API Gateway
**Boundary**: HTTP/WebSocket interface between frontend and backend.
- Extend `api/main.py` with new endpoints: census, alerts, agent admin, simulation
- New `api/simulation.py` for simulation-specific endpoints
- New `api/websocket.py` for real-time vital signs and agent activity streaming

### Layer 4: Frontend (Command Center)
**Boundary**: UI renders state, sends commands. No clinical logic in frontend.

```
frontend/src/app/
├── dashboard/              # Command center (new)
│   └── page.tsx            # Patient census + vitals + alerts
├── admin/                  # Agent administration (new)
│   ├── page.tsx            # Agent template management
│   └── knowledge/page.tsx  # Knowledge base management
├── simulation/             # Simulation control (new)
│   └── page.tsx            # Play/pause/inject/visualize
├── page.tsx                # Chat (existing)
└── queue/page.tsx          # Approval queue (existing)
```

### Layer 5: Simulation Engine
**Boundary**: Isolated from production data path. Generates synthetic FHIR data that flows through the same agent pipeline.

```
simulation/
├── engine.py               # Core engine (existing - 1183 lines)
├── models.py               # Data models (existing - 288 lines)
├── physiology.py           # Vital/lab generation (existing - 787 lines)
├── scenarios/              # YAML scenario definitions (new)
│   ├── sepsis_delayed.yaml
│   ├── acute_mi.yaml
│   └── ...
├── assertions.py           # Test assertion framework (new)
├── reporting.py            # Post-simulation reports (new)
└── synthetic_patients.py   # Synthea + LLM patient generation (new)
```

## Data Flow Architecture

### Patient Monitoring Flow (Production)
```
FHIR Server → [Subscription/Poll] → Supervisor Agent
    Supervisor → spawns Specialist Agents based on conditions
    Each Specialist:
        1. Reads relevant FHIR data (via handlers)
        2. Calculates scores (scoring module)
        3. Evaluates against knowledge base (ChromaDB RAG)
        4. Generates findings
    Supervisor → aggregates findings → AlertManager → Dashboard
```

### Simulation Flow
```
Scenario YAML → SimulationEngine
    Engine → generates vitals/labs via PhysiologyModel
    Engine → writes synthetic FHIR resources to Medplum
    Engine → triggers same Supervisor Agent pipeline
    Agent responses → captured by Assertion framework
    Results → Reporting module → Dashboard display
```

### Key Insight: Simulation uses the SAME agent pipeline
The simulation engine generates FHIR data and writes it to Medplum. From the agents' perspective, this is indistinguishable from real patient data. This means:
- No separate "simulation mode" in agent code
- Agent bugs caught in simulation will be the same bugs in production
- Only the data source differs (synthetic vs. real)

## Build Order (Critical Path)

```
Wave 1: FHIR Inpatient Handlers + Supervisor Agent + Dashboard Shell
    ├── FHIR handlers (no agent dependency)
    ├── Supervisor agent (needs FHIR handlers)
    └── Dashboard (needs API endpoints)

Wave 2: Specialist Agents + Knowledge Base + Alert Integration
    ├── Knowledge base setup (ChromaDB, embeddings)
    ├── Base agent class + 5 specialists
    └── Alert manager integration with dashboard

Wave 3: Simulation UI + Scenarios + Admin Interface
    ├── Simulation control panel (frontend)
    ├── 8 YAML scenarios
    ├── Agent visualization (ReactFlow)
    └── Admin agent template editor

Wave 4: Real-Time + Testing + Observability
    ├── WebSocket streaming
    ├── Test assertions + reporting
    ├── LangFuse integration
    └── FHIR Subscriptions
```

## State Management Architecture

### Patient State (Backend)
```python
class PatientState:
    patient_id: str
    encounter_id: str
    vitals_history: list[VitalSigns]      # Rolling window (last 24h)
    lab_results: list[LabResult]           # Rolling window
    active_conditions: list[Condition]
    active_medications: list[MedicationRequest]
    active_agents: dict[str, AgentInstance]
    alerts: list[Alert]
    scores: dict[str, ScoreResult]         # NEWS2, qSOFA, etc.
    care_gaps: list[CareGap]
```

- One `PatientState` per monitored patient
- Stored in-memory (process-level dict, keyed by patient_id)
- Updated on each FHIR poll/subscription event
- Shared (read-only) with specialist agents

### Agent State
```python
class AgentInstance:
    agent_id: str
    specialty: str
    patient_id: str
    status: AgentStatus  # SPAWNING, ACTIVE, IDLE, RETIRING
    conversation_history: list[Message]
    last_evaluation: datetime
    findings: list[Finding]
```

### Frontend State
- Patient census: fetched via API, refreshed on interval or WebSocket
- Selected patient: local React state
- Vital signs: WebSocket stream → local buffer → Recharts
- Alert feed: WebSocket stream → append to local list
- Simulation: WebSocket stream → update timeline + agent graph

## Integration Points

### Existing Code Integration
| Existing Component | How It Integrates | Modifications Needed |
|-------------------|-------------------|---------------------|
| `handlers.py` (47 tools) | Add ~35 new handlers alongside existing | Extend, don't restructure |
| `openrouter_orchestrator.py` | Supervisor agent uses it for LLM calls | May need refactor for multi-agent |
| `alert_manager.py` | Supervisor routes alerts through it | Add dashboard notification hooks |
| `clinical_scores.py` | Called by supervisor on each vitals update | No changes needed |
| `simulation/engine.py` | Writes FHIR data → triggers agent pipeline | Add FHIR write integration |
| `api/main.py` | Add new route groups | Extend with new routers |

### New Integration Points
| From | To | Mechanism |
|------|-----|-----------|
| Simulation engine | Medplum FHIR server | FHIR create/update via handlers |
| Supervisor agent | Specialist agents | Claude Agent SDK delegation |
| Knowledge base | Specialist agents | ChromaDB similarity search |
| Alert manager | Dashboard | WebSocket push |
| Agent activity | Dashboard | WebSocket push |
| Admin interface | Agent registry | REST API CRUD |

---
*Research: 2026-02-25*
