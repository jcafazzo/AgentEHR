# Requirements

## Functional Requirements

### FR-01: FHIR Inpatient Resource Access
Expand the MCP server with ~35 new FHIR R4 tool handlers for inpatient-specific resources: Encounter (inpatient lifecycle), Flag, ClinicalImpression, RiskAssessment, Task, CareTeam, Goal, DeviceMetric, AdverseEvent, Communication.

**Testable**: Each handler returns valid FHIR R4 JSON when called with valid arguments against a seeded Medplum instance. Coverage: all 11 resource types with CRUD operations.

### FR-02: Supervisor Agent
One supervisor agent per monitored patient. The supervisor continuously evaluates patient state via FHIR data, spawns specialist sub-agents based on active conditions, aggregates findings, and routes escalations through the alert system.

**Testable**: Given a seeded inpatient encounter with sepsis-qualifying conditions, the supervisor spawns an Infectious Disease agent within one evaluation cycle and generates an URGENT alert.

### FR-03: Specialist Sub-Agents (5 initial)
Five domain-specific sub-agents — Cardiology, Infectious Disease, Medication Safety, Renal, Pulmonary — each with dedicated knowledge base, spawn triggers, and escalation rules.

**Testable**: Each agent, given condition-appropriate FHIR data, produces at least one finding with guideline citation within 30 seconds.

### FR-04: Clinical Scoring Integration
Automated NEWS2, qSOFA, SOFA, and KDIGO scoring calculated on each vitals/lab update and surfaced in the patient state.

**Testable**: Already implemented and tested. Verify integration: supervisor recalculates NEWS2 when new vitals arrive; score appears in patient state within 5 seconds.

### FR-05: 4-Tier Alert Classification
Alerts classified as Critical (<5min), Urgent (15-30min), Routine (1-2hr), or Informational (4+hr) with deduplication, contextual suppression, and acknowledgment lifecycle.

**Testable**: Already implemented. Verify integration: alert appears in dashboard feed within tier-appropriate time. Duplicate alerts within suppression window are not shown.

### FR-06: Command Center Dashboard
Three-panel clinician dashboard: patient census sorted by acuity (left), selected patient detail with active agents and vitals (center), tiered escalation feed with chat (right).

**Testable**: Dashboard renders patient list sorted by NEWS2 score descending. Selecting a patient shows their active agents, vital signs, and recommendations. Alert feed displays by tier with color coding.

### FR-07: Knowledge Base (RAG)
ChromaDB vector store containing clinical guidelines per specialty. Agents retrieve relevant guidelines via semantic search when evaluating patient conditions.

**Testable**: Given a query "sepsis antibiotic timing", the knowledge base returns Surviving Sepsis Campaign Hour-1 Bundle guidelines with relevance score >0.8.

### FR-08: Admin Interface
Agent template editor (create/edit specialty, upload guidelines, configure thresholds), knowledge base manager, and performance metrics dashboard.

**Testable**: Admin can create a new agent template, upload a guideline PDF, set alert thresholds, and the new agent type appears in the spawn-eligible registry.

### FR-09: Simulation Integration
Simulation engine writes synthetic FHIR data to Medplum through the same handlers as production, triggering the same agent pipeline. Simulation control panel provides play/pause/speed/inject controls.

**Testable**: Running the "Sepsis - Delayed Antibiotics" scenario generates vitals in Medplum, triggers supervisor agent evaluation, and produces an URGENT sepsis alert at the appropriate timeline point.

### FR-10: Scenario Library
8 pre-built YAML scenarios (sepsis, MI, DKA, CHF, AKI, PE, stroke, post-op) with conditional branching and assertion definitions.

**Testable**: Each scenario parses without error, runs to completion in the simulation engine, and produces at least one expected alert type.

### FR-11: Clinical Trials Matching Agent
Specialist agent that screens admitted patients against ClinicalTrials.gov eligibility criteria and generates INFORMATIONAL alerts for matches.

**Testable**: Given a patient with AKI (stage 2+), the agent identifies at least one matching clinical trial from ClinicalTrials.gov within 60 seconds.

### FR-12: Agent Visualization
ReactFlow graph showing supervisor→sub-agent relationships with spawning/retirement animations. Real-time agent activity log with timestamped reasoning steps.

**Testable**: During simulation, the agent graph renders with correct node count matching active agents. Agent log shows timestamped entries for each evaluation cycle.

### FR-13: Test Assertions & Reporting
Automated assertion framework for simulation scenarios. Post-simulation reports with alert timing, agent accuracy (precision/recall), and comparison metrics.

**Testable**: Running a scenario with defined assertions produces a pass/fail report. Report includes: alerts generated vs expected, timing accuracy, and false positive count.

### FR-14: Inpatient Seed Data
Extend seed_patients.py with inpatient encounter scenarios covering sepsis, cardiac, renal, and multi-system patients.

**Testable**: After seeding, Medplum contains at least 5 inpatient encounters with complete Encounter + Condition + Observation + MedicationRequest + CareTeam resources.

### FR-15: Real-Time Vital Signs Streaming
WebSocket endpoint streaming vital signs and agent activity to the dashboard in real-time.

**Testable**: WebSocket client connected to `/ws/vitals/{patient_id}` receives vital sign updates within 2 seconds of FHIR Observation creation.

### FR-16: Sepsis Detection Pathway
qSOFA + SOFA evaluation with Hour-1 Bundle compliance tracking (blood cultures, antibiotics, lactate, fluid resuscitation).

**Testable**: Given a patient meeting qSOFA >=2, the system tracks each Hour-1 Bundle component and generates escalating alerts for any component not completed within target time.

### FR-17: CMS Core Measure Tracking
Automated tracking of SEP-1 (sepsis), stroke, MI, and VTE prophylaxis compliance measures.

**Testable**: Given a sepsis encounter, the system calculates SEP-1 compliance percentage and identifies specific non-compliant components.

## Non-Functional Requirements

### NFR-01: Agent Response Time
Supervisor evaluation cycle completes within 30 seconds for a patient with up to 5 active specialist agents.

### NFR-02: Alert Latency
Critical alerts appear in dashboard within 5 seconds of the triggering data being available in FHIR.

### NFR-03: Human-in-the-Loop Safety
No agent can directly modify treatment. All clinical write actions require explicit clinician approval through the existing approval queue.

### NFR-04: Evidence Citation
Every agent recommendation includes at least one citation: guideline name, scoring system result, or specific FHIR resource value.

### NFR-05: Data Freshness
Vital signs data used for scoring must be <60 seconds old. Medication/condition data must be <5 minutes old. Dashboard shows data age indicators.

### NFR-06: Simulation Fidelity
Simulation physiology models produce vital sign distributions within 1 standard deviation of MIMIC-IV/eICU reference data for each modeled condition.

### NFR-07: Audit Trail
Every agent evaluation, alert generation, and clinician response is logged with timestamp, agent ID, patient ID, data inputs, and outcome.

### NFR-08: Concurrent Patients
System monitors at least 20 patients concurrently with acceptable response times (NFR-01).

---
*Derived from PROJECT.md + research | 2026-02-25*
