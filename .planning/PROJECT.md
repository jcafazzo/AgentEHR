# AgentEHR — Inpatient Care Oversight Platform

## What This Is

AgentEHR is an AI-powered inpatient care oversight platform that monitors hospitalized patients through autonomous clinical agents. When a patient is admitted, a supervisor agent begins continuous monitoring and spawns specialized sub-agents (cardiology, infectious disease, medication safety, etc.) based on the patient's clinical needs. These agents access EHR data via FHIR R4 through MCP servers, monitor real-time vital signs, identify care gaps, flag escalations, and proactively recommend interventions — ensuring every patient receives timely, guideline-compliant care.

## Core Value

**Intelligent clinical surveillance that catches what clinicians miss** — agents that never sleep, never forget a guideline, and escalate only actionable findings with evidence and recommendations, functioning as a tireless clinical safety net.

## Requirements

### Validated

- ✓ FHIR R4 CRUD operations via 47+ tool handlers (patients, conditions, medications, observations, encounters, allergies, appointments, referrals, clinical notes) — existing
- ✓ AI agent orchestration with multi-model support (OpenRouter gateway routing to Claude, Gemini, GPT-4, GLM) — existing
- ✓ Human-in-the-loop approval queue for all clinical write actions (create → approve/reject → execute) — existing
- ✓ Dual portal mode: clinician (full read/write) and patient (read-only + limited self-service) — existing
- ✓ Drug interaction and medication safety validation (drug-drug, drug-allergy checks) — existing
- ✓ Patient search and clinical data browsing (conditions, medications, allergies, vitals, care gaps) — existing
- ✓ AI-generated patient narratives with caching and hash-based invalidation — existing
- ✓ Clinician chat interface with context-aware tool calling — existing
- ✓ Clinical scoring systems: NEWS2, qSOFA, SOFA, KDIGO — existing
- ✓ 4-tier alert classification (Critical/Urgent/Routine/Informational) with deduplication and escalation lifecycle — existing
- ✓ Simulation engine core: asyncio-based with physiology models, lab engine, event processing, checkpoint save/restore — existing
- ✓ Physiological vital sign generation: age/sex-stratified baselines, trend engine, intervention effects, variability — existing
- ✓ 5 seeded test patients covering different clinical scenarios — existing
- ✓ Docker Compose infrastructure: Medplum FHIR server + PostgreSQL + Redis — existing

### Active

- [ ] Expand FHIR MCP server with ~35 new inpatient resource tools (Encounter management, Flag, ClinicalImpression, RiskAssessment, Task, CareTeam, Goal, AdverseEvent, Communication)
- [ ] Supervisor agent: per-patient continuous monitoring, specialist agent spawning/retirement based on conditions
- [ ] Specialist sub-agents: Cardiology, Infectious Disease, Medication Safety, Renal, Pulmonary (each with knowledge base, escalation triggers)
- [ ] Clinician command center dashboard: patient census sorted by acuity, real-time vital signs, tiered escalation feed
- [ ] Admin interface: agent template creation/editing, knowledge base management, escalation rule configuration
- [ ] Simulation control panel UI: play/pause/speed/inject events, scenario timeline, agent visualization
- [ ] YAML/JSON scenario authoring with conditional branching for simulation
- [ ] Sepsis detection pathway: qSOFA + SOFA evaluation, Hour-1 Bundle compliance tracking
- [ ] Clinical trials matching agent: proactive patient screening against ClinicalTrials.gov eligibility
- [ ] Knowledge base architecture: RAG (vector store) + structured guidelines for agent reasoning
- [ ] Real-time FHIR Subscriptions for vital signs, labs, ADT events
- [ ] WebSocket streaming for live vital signs to dashboard
- [ ] Agent observability: LangFuse + OpenTelemetry tracing for every agent turn
- [ ] Seed inpatient encounter data (extend seed_patients.py with inpatient scenarios)
- [ ] 8 pre-built simulation scenarios (sepsis, MI, DKA, CHF, AKI, PE, stroke, post-op)
- [ ] Post-simulation reporting: alert timing, agent accuracy, comparison metrics
- [ ] CMS core measure tracking: SEP-1, stroke, MI, VTE prophylaxis compliance

### Out of Scope

- Production deployment infrastructure (Dockerfile, cloud config) — development platform first
- End-user authentication on API/frontend — internal tool, not patient-facing deployment
- eCART ML scoring — rule-based initially, ML deferred to Phase 4
- Load/performance testing — deferred until multi-patient stress testing phase
- Mobile/responsive UI — desktop command center only for now
- Voice input/output — declared dependencies exist but not active; defer

## Context

**Problem:** Clinical inertia in inpatient settings leads to delayed interventions, missed care gaps, and preventable adverse events. 95% of hospital alerts are non-actionable (alarm fatigue), sepsis bundle compliance averages only 48.9% nationally, and early warning signs are detected too late.

**Market gap:** No existing product combines comprehensive inpatient surveillance, multi-specialist agent reasoning, proactive care gap identification, intelligent escalation orchestration, and FHIR-native architecture. Current landscape is fragmented: Viz.ai (imaging only), CLEW (ICU prediction only), Qventus (operations only).

**Current state:** AgentEHR evolved from an outpatient EHR chat interface. The core infrastructure is solid — FHIR tool handlers, multi-model orchestrator, approval queue, frontend. Phase 1 foundation work (scoring systems, alert classification, simulation engine) is complete. Now extending to full inpatient oversight.

**Evidence base:** PRD references 28+ clinical research papers, validated scoring systems (NEWS2 AUC 0.833-0.880, qSOFA AUC 0.847), and active clinical trials (NCT06694181 at Penn Medicine with 300K patients).

## Constraints

- **Tech stack**: Python 3.12 + FastAPI backend, Next.js 15 + React 19 frontend, Medplum FHIR R4 — established, not negotiable
- **FHIR compliance**: All clinical data access must go through FHIR R4 standard resources — no direct DB queries
- **Human-in-the-loop**: All treatment-modifying actions require clinician approval — agents recommend, never directly modify treatment
- **LLM gateway**: OpenRouter for multi-model routing — already integrated, continue using
- **Infrastructure**: Docker Compose for local development (Medplum + PostgreSQL + Redis)
- **Evidence-grounded**: Every agent recommendation must cite specific guidelines, scoring systems, or patient data — no black-box decisions

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| OpenRouter as LLM gateway (not direct Anthropic SDK) | Multi-model flexibility, single API key, cost routing | ✓ Good — enables model experimentation |
| Supervisor → sub-agent pattern | Maps to clinical care team model; 3-5 agents optimal per research | — Pending |
| NEWS2 + qSOFA for initial scoring | NEWS2 best discriminator (AUC 0.833-0.880); qSOFA bedside sepsis screen | ✓ Good — implemented and tested |
| 4-tier alert classification | Evidence-based; reduces alarm fatigue vs binary alert/no-alert | ✓ Good — implemented with lifecycle management |
| Asyncio simulation engine | Enables accelerated-playback scenarios; consistent with existing async stack | ✓ Good — implemented with checkpoint support |
| ChromaDB for vector store (planned) | Local, free, sufficient for guideline RAG | — Pending |
| YAML scenario format (planned) | Human-readable, conditional branching, assertion framework | — Pending |
| ReactFlow for agent visualization (planned) | Interactive node graph, established React library | — Pending |

---
*Last updated: 2026-02-25 after initialization*
