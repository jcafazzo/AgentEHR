# Roadmap

## Milestone 1: Inpatient Care Oversight Platform

### Phase 1: FHIR Inpatient Resource Expansion
**Goal**: Extend the MCP server with ~35 new FHIR R4 tool handlers for inpatient-specific resources, providing the data access foundation for all subsequent agent work.

**Requirements**: FR-01

**Success criteria**:
- [ ] Encounter inpatient lifecycle handlers (create, update status, get timeline, transfer) working against Medplum
- [ ] Flag handlers (create, get active, resolve) for clinical alerts
- [ ] ClinicalImpression and RiskAssessment handlers for agent assessments
- [ ] Task handlers (create, assign, complete, get pending) for care coordination
- [ ] CareTeam, Goal, AdverseEvent, Communication handlers
- [ ] All handlers registered in both MCP server and orchestrator tool definitions
- [ ] Integration test: create full inpatient encounter with all resource types

---

### Phase 2: Inpatient Seed Data
**Goal**: Create realistic inpatient encounter data in Medplum covering multiple clinical scenarios, enabling supervisor agent development and dashboard testing.

**Requirements**: FR-14

**Success criteria**:
- [ ] 5+ inpatient encounters seeded: sepsis, cardiac (ACS/CHF), renal (AKI), pulmonary (PE/COPD), multi-system
- [ ] Each encounter has: Encounter + Conditions + Observations (vitals + labs) + MedicationRequests + CareTeam
- [ ] Seed script is idempotent (re-runnable without duplicates)
- [ ] Vital signs observations span 24+ hours with realistic progression patterns

---

### Phase 3: Supervisor Agent
**Goal**: Build the core supervisor agent that monitors a patient's state, calculates clinical scores, and manages the escalation pipeline — the central intelligence of the platform.

**Requirements**: FR-02, FR-04, FR-05, NFR-01, NFR-03, NFR-04, NFR-05

**Success criteria**:
- [ ] Supervisor agent loads patient state from FHIR (encounter, conditions, vitals, meds, labs)
- [ ] Recalculates NEWS2, qSOFA on each evaluation cycle
- [ ] Generates alerts through AlertManager based on scoring thresholds
- [ ] Patient state container tracks vitals history, active conditions, scores, and alerts
- [ ] Evaluation cycle completes within 30 seconds
- [ ] No direct treatment modifications — all actions go through approval queue
- [ ] Every recommendation cites specific data (FHIR resource values or score results)

---

### Phase 4: Command Center Dashboard
**Goal**: Build the three-panel clinician dashboard showing patient census by acuity, selected patient detail with vitals and agent activity, and tiered escalation feed.

**Requirements**: FR-06, NFR-02

**Success criteria**:
- [ ] Patient census panel: list of monitored patients sorted by NEWS2 score descending, color-coded by acuity tier
- [ ] Patient detail panel: active agents, real-time vital signs display, agent recommendations, clinical data sections
- [ ] Escalation feed panel: alerts displayed by tier (Critical red, Urgent orange, Routine yellow, Info blue)
- [ ] Selecting a patient in census loads their detail view
- [ ] API endpoints: GET /api/census, GET /api/patients/{id}/state, GET /api/alerts
- [ ] Dashboard renders with seeded inpatient data

---

### Phase 5: Knowledge Base & RAG
**Goal**: Set up ChromaDB vector store with clinical guidelines per specialty, enabling agents to retrieve evidence-based recommendations via semantic search.

**Requirements**: FR-07

**Success criteria**:
- [ ] ChromaDB initialized with collections per specialty (cardiology, infectious_disease, medication_safety, renal, pulmonary)
- [ ] At least 3 clinical guidelines embedded per specialty (Surviving Sepsis, ACC/AHA, KDIGO, GOLD, etc.)
- [ ] Semantic search returns relevant guidelines with relevance score
- [ ] Knowledge base Python interface: `query(specialty, question) -> list[GuidelineChunk]`
- [ ] Guideline retrieval completes within 2 seconds

---

### Phase 6: Specialist Sub-Agents
**Goal**: Implement 5 specialist sub-agents with knowledge base integration, spawn triggers, and escalation rules — enabling multi-specialist reasoning per patient.

**Requirements**: FR-03, FR-16, NFR-04

**Success criteria**:
- [ ] Base agent class with standard interface: evaluate(patient_state) -> list[Finding]
- [ ] 5 agents implemented: Cardiology, Infectious Disease, Medication Safety, Renal, Pulmonary
- [ ] Each agent retrieves relevant guidelines from ChromaDB during evaluation
- [ ] Supervisor spawns agents based on condition triggers (e.g., sepsis criteria -> ID agent)
- [ ] Supervisor retires agents when conditions resolve
- [ ] Infectious Disease agent implements sepsis detection pathway (qSOFA + SOFA + Hour-1 Bundle tracking)
- [ ] Conflict resolution: supervisor presents conflicting recommendations with evidence
- [ ] Each finding includes guideline citation

---

### Phase 7: Simulation FHIR Integration & Scenarios
**Goal**: Connect the simulation engine to Medplum so synthetic data flows through the real agent pipeline, and author 8 clinical scenarios with conditional branching.

**Requirements**: FR-09, FR-10, NFR-06

**Success criteria**:
- [ ] Simulation engine writes vitals/labs to Medplum via FHIR handlers (same code path as production)
- [ ] Running a simulation triggers supervisor agent evaluation cycle
- [ ] 8 YAML scenarios authored: sepsis, MI, DKA, CHF, AKI, PE, stroke, post-op
- [ ] Each scenario includes: patient template, timeline events, conditional branches, expected outcomes
- [ ] Scenario parser validates YAML schema before execution
- [ ] At least one scenario (sepsis) produces expected URGENT alert when run end-to-end

---

### Phase 8: Simulation Control Panel & Agent Visualization
**Goal**: Build the simulation UI with playback controls, event injection, and ReactFlow agent visualization so developers and clinicians can observe agent behavior.

**Requirements**: FR-12

**Success criteria**:
- [ ] Simulation page at /simulation with play/pause/speed/rewind controls
- [ ] Scenario selector dropdown listing available YAML scenarios
- [ ] Event injection: user can inject clinical events (vital change, lab result, medication) mid-simulation
- [ ] ReactFlow graph showing supervisor → sub-agent nodes with active/idle/spawning status
- [ ] Agent activity log: timestamped entries for each evaluation, tool call, and finding
- [ ] Timeline component showing events and alerts on a horizontal axis
- [ ] API endpoints: POST /api/simulation/start, POST /api/simulation/{id}/control, POST /api/simulation/{id}/inject

---

### Phase 9: Admin Interface & Clinical Trials Agent
**Goal**: Build the admin interface for agent template management and knowledge base uploads. Implement the clinical trials matching agent.

**Requirements**: FR-08, FR-11

**Success criteria**:
- [ ] Admin page at /admin with agent template CRUD (create, edit, delete specialty templates)
- [ ] Knowledge base upload: drag-and-drop PDF/markdown guidelines, auto-embed in ChromaDB
- [ ] Escalation rule editor: configure thresholds per agent template
- [ ] Agent template registry: new templates available for supervisor spawning
- [ ] Clinical trials agent: queries ClinicalTrials.gov API for matching trials based on patient conditions
- [ ] Clinical trials agent generates INFORMATIONAL alerts for matched trials with eligibility summary

---

### Phase 10: Test Assertions, Reporting & Real-Time Streaming
**Goal**: Formalize simulation testing with automated assertions and post-simulation reports. Add WebSocket streaming for live vital signs and agent activity.

**Requirements**: FR-13, FR-15, NFR-02, NFR-07

**Success criteria**:
- [ ] Assertion framework: YAML assertion definitions (alert_generated, scoring_calculated, escalation_timing, no_false_alarm)
- [ ] Assertion runner: executes assertions against simulation results, produces pass/fail report
- [ ] Post-simulation report: alert timeline, precision/recall, timing metrics, agent utilization
- [ ] WebSocket endpoint /ws/vitals/{patient_id}: streams vital signs in real-time
- [ ] WebSocket endpoint /ws/agents/{patient_id}: streams agent activity in real-time
- [ ] Dashboard consumes WebSocket streams (replaces polling)
- [ ] Audit trail: structured log of every agent evaluation, alert, and clinician response

---

### Phase 11: CMS Measures, Observability & Hardening
**Goal**: Add CMS core measure tracking, agent observability (LangFuse), and performance hardening for concurrent patient monitoring.

**Requirements**: FR-17, NFR-01, NFR-08

**Success criteria**:
- [ ] SEP-1 sepsis measure compliance calculator
- [ ] Stroke, MI, VTE prophylaxis measure tracking
- [ ] LangFuse integration: every agent turn traced with input/output/latency/tokens
- [ ] OpenTelemetry spans for FHIR operations and agent evaluation cycles
- [ ] System handles 20+ concurrent monitored patients with <30s evaluation cycles
- [ ] Data freshness indicators in dashboard (amber >2min, red >5min for vitals)
- [ ] Comprehensive audit trail queryable by patient, agent, time range

---

## Requirement Coverage Matrix

| Requirement | Phase(s) | Status |
|-------------|----------|--------|
| FR-01: FHIR Inpatient Resources | 1 | In Progress (1/4 plans) |
| FR-02: Supervisor Agent | 3 | Planned |
| FR-03: Specialist Sub-Agents | 6 | Planned |
| FR-04: Clinical Scoring Integration | 3 | Planned (code exists) |
| FR-05: 4-Tier Alert Classification | 3 | Planned (code exists) |
| FR-06: Command Center Dashboard | 4 | Planned |
| FR-07: Knowledge Base (RAG) | 5 | Planned |
| FR-08: Admin Interface | 9 | Planned |
| FR-09: Simulation Integration | 7 | Planned (engine exists) |
| FR-10: Scenario Library | 7 | Planned |
| FR-11: Clinical Trials Agent | 9 | Planned |
| FR-12: Agent Visualization | 8 | Planned |
| FR-13: Test Assertions & Reporting | 10 | Planned |
| FR-14: Inpatient Seed Data | 2 | Planned |
| FR-15: Real-Time Streaming | 10 | Planned |
| FR-16: Sepsis Detection Pathway | 6 | Planned |
| FR-17: CMS Core Measures | 11 | Planned |
| NFR-01: Agent Response Time | 3, 11 | Planned |
| NFR-02: Alert Latency | 4, 10 | Planned |
| NFR-03: Human-in-the-Loop | 3 | Planned (exists) |
| NFR-04: Evidence Citation | 3, 6 | Planned |
| NFR-05: Data Freshness | 3 | Planned |
| NFR-06: Simulation Fidelity | 7 | Planned (engine exists) |
| NFR-07: Audit Trail | 10 | Planned |
| NFR-08: Concurrent Patients | 11 | Planned |

---
*Roadmap created: 2026-02-25*
