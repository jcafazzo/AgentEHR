# Features Research

## Feature Categories

### Table Stakes (Must have for MVP credibility)

| Feature | Why Table Stakes | Existing? |
|---------|-----------------|-----------|
| Patient census with acuity sorting | Core clinician workflow — "who needs me most?" | Partial (patient list exists, no acuity sort) |
| Real-time vital signs display | Every inpatient monitoring system has this | No (chat-based only) |
| NEWS2 automated scoring | Most widely validated EWS (AUC 0.833-0.880) | Yes (agents/scoring/) |
| 4-tier alert classification | Binary alerts cause alarm fatigue; tiered is minimum | Yes (agents/alerts/) |
| FHIR inpatient resource access | Can't monitor patients without Encounter, Flag, Task data | No (outpatient resources only) |
| Human-in-the-loop for actions | Clinical safety non-negotiable | Yes (approval queue) |
| Audit trail | Regulatory requirement for any clinical decision support | Partial (logging, no structured audit) |

### Differentiators (Competitive advantage)

| Feature | Why Differentiating | Complexity |
|---------|-------------------|------------|
| Multi-specialist agent reasoning | No competitor does this — maps to clinical care team | HIGH |
| Supervisor→sub-agent orchestration | Unique architecture enabling specialty-aware monitoring | HIGH |
| Admin-configurable agent templates | Clinical teams define agents without engineering | MEDIUM |
| Guideline-grounded recommendations with citations | Every recommendation cites evidence | MEDIUM |
| Clinical trials matching | Proactive screening reduces manual chart review by 40-57% | MEDIUM |
| Comprehensive simulation engine | No competitor has simulation + agent testing | HIGH |
| Scenario-based agent validation | Reproducible testing of clinical surveillance | MEDIUM |

### Nice-to-Have (Valuable but deferrable)

| Feature | Why Deferrable | Target Phase |
|---------|---------------|-------------|
| eCART ML scoring | Rule-based scoring sufficient initially | Phase 4 |
| FHIR Subscriptions (real-time) | Polling works for dev; subscriptions for production | Phase 4 |
| A/B comparison mode | Useful for optimization, not MVP | Phase 3-4 |
| Discharge planning agent | Important but not core surveillance | Phase 4 |
| CMS core measure tracking | Quality reporting, not acute monitoring | Phase 4 |
| Stress testing (multi-patient) | Single patient works first | Phase 4 |
| LLM-generated patient journeys | Pre-built scenarios sufficient | Phase 3 |

## Feature Dependencies Map

```
FHIR Inpatient Tools ──────────────┐
                                    ├──> Supervisor Agent ──> Sub-Agents
Clinical Scoring (NEWS2/qSOFA) ────┘         |                  |
                                              v                  v
                                    Patient Census          Knowledge Base
                                    Dashboard               RAG (ChromaDB)
                                         |                       |
                                         v                       v
                                    Alert Feed             Admin Interface
                                    (4-tier)               (agent config)
                                         |
                                         v
                                    Simulation Engine ──> Scenarios ──> Assertions
                                         |
                                         v
                                    Agent Visualization
```

**Critical path**: FHIR tools → Supervisor agent → Dashboard → Sub-agents

## Feature Sizing Estimates

| Feature Group | Files to Create/Modify | Relative Effort |
|--------------|----------------------|-----------------|
| FHIR inpatient tools (~35 new handlers) | handlers.py, server.py, orchestrator.py | LARGE |
| Supervisor agent | New: agents/supervisor.py, agents/agent_registry.py | LARGE |
| Specialist sub-agents (5) | New: agents/specialists/*.py, knowledge base setup | LARGE |
| Command center dashboard | New: frontend pages + components (6-8 files) | LARGE |
| Admin interface | New: frontend pages + API endpoints (8-10 files) | MEDIUM |
| Simulation scenarios (8) | New: simulation/scenarios/*.yaml | MEDIUM |
| Knowledge base (ChromaDB) | New: agents/knowledge_base.py, embeddings setup | MEDIUM |
| WebSocket vital streaming | api/main.py, new frontend component | MEDIUM |
| Clinical trials agent | New: agents/specialists/clinical_trials.py | SMALL |
| Simulation control UI | New: frontend/src/app/simulation/ | MEDIUM |
| Agent visualization | New: frontend components (ReactFlow) | MEDIUM |
| Test assertions | New: simulation/assertions.py | SMALL |
| Reporting | New: simulation/reporting.py | SMALL |

## What Existing Code Covers

Already built and tested:
- **Clinical scoring**: NEWS2, qSOFA, SOFA, KDIGO in agents/scoring/clinical_scores.py
- **Alert classification**: 4-tier with lifecycle in agents/alerts/alert_manager.py
- **Simulation engine core**: engine.py (1183 lines), physiology.py (787 lines), models.py (288 lines)
- **FHIR CRUD**: 47+ tool handlers in fhir-mcp-server/src/handlers.py
- **Multi-model orchestrator**: OpenRouter-based in agents/openrouter_orchestrator.py
- **Approval queue**: In-memory with lifecycle in fhir-mcp-server/src/approval_queue.py
- **Frontend shell**: Next.js app with chat, patient browser, approval queue pages

What needs to be built from scratch:
- Supervisor agent architecture
- Specialist sub-agents with knowledge bases
- Inpatient FHIR resource handlers
- Command center dashboard
- Admin interface
- Simulation UI and scenarios
- Agent visualization

---
*Research: 2026-02-25*
