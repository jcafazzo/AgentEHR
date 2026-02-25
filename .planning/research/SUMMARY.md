# Research Summary

## Key Findings

### Stack Decisions (Settled)
- **Keep entire existing stack** — Python 3.12/FastAPI, Next.js 15/React 19, Medplum FHIR R4, OpenRouter
- **Add Claude Agent SDK** for supervisor→sub-agent orchestration (native hierarchical delegation)
- **Add ChromaDB** for knowledge base RAG (local, free, sufficient for clinical guidelines corpus)
- **Add ReactFlow + Recharts** for agent visualization and vital signs charting
- **WebSocket first** for real-time streaming; FHIR Subscriptions deferred to Phase 4
- **LangFuse + OpenTelemetry** for agent observability (Phase 4)

### Feature Prioritization
**Critical path**: FHIR inpatient tools → Supervisor agent → Command center dashboard → Specialist sub-agents

**Table stakes** (must ship first):
- Patient census sorted by acuity (NEWS2)
- Real-time vital signs display
- FHIR inpatient resource access (~35 new handlers)
- Supervisor agent with patient state monitoring

**Differentiators** (competitive moat):
- Multi-specialist agent reasoning (no competitor has this)
- Admin-configurable agent templates
- Evidence-grounded recommendations with citations
- Comprehensive simulation + agent testing engine

**Deferrable** (Phase 3-4):
- eCART ML scoring, FHIR Subscriptions, A/B comparison, discharge planning agent, CMS tracking

### Architecture Principles
1. **Simulation uses same agent pipeline as production** — no separate code paths; FHIR data written by simulation flows through identical supervisor→sub-agent chain
2. **Deterministic scoring, non-deterministic reasoning** — NEWS2/qSOFA/SOFA/KDIGO are Python code; only clinical reasoning and synthesis are LLM-driven
3. **Agent isolation** — each specialist gets only domain-relevant data; supervisor is sole aggregation/escalation point
4. **Data freshness enforcement** — timestamp every FHIR fetch; never reason about stale vitals

### Top Pitfalls to Guard Against
1. **Agent hallucination** — strict tool-call-only data access; agents never generate clinical values from training data
2. **Alarm fatigue** — start with only CRITICAL/URGENT tiers active; aggressive deduplication and contextual suppression
3. **Agent coordination deadlocks** — supervisor-mediated conflict resolution; independent agent contexts; timeout enforcement
4. **FHIR data freshness** — polling with freshness indicators; subscription fallback
5. **Simulation-production divergence** — same code paths; MIMIC-IV validated physiology models; realistic noise injection
6. **Context window overflow** — structured summaries (not raw FHIR); domain-scoped agent data; rolling summarization

### Build Order
```
Wave 1: FHIR Tools + Supervisor + Dashboard + Seed Data
Wave 2: Sub-Agents + Knowledge Base + Alert Integration + Scenarios
Wave 3: Admin UI + Clinical Trials + Assertions + Reporting + Sim UI
Wave 4: WebSocket + FHIR Subscriptions + Observability + Scale Testing
```

## Implications for Roadmap

### Phase Count: 8-10 phases (comprehensive depth)
Given the scope (35 new FHIR handlers, supervisor agent, 5 specialist agents, 2 new frontend apps, simulation integration, admin interface), this should be broken into 8-10 focused phases with clear deliverables.

### Parallelization Opportunities
- FHIR handlers and supervisor agent can develop in parallel (different files)
- Frontend dashboard and backend API can develop in parallel
- Simulation scenarios (YAML authoring) can happen alongside agent development
- Knowledge base setup (ChromaDB + embeddings) independent of agent code

### Risk Mitigation Built Into Phases
- Phase 1 includes Medplum subscription spike (early validation of FHIR capability)
- Phase 2 includes conflict resolution testing (catch coordination bugs early)
- Phase 3 includes assertion framework (formalize agent behavior testing before scaling)
- Phase 4 is explicitly about hardening and real-time — don't rush here

---
*Synthesized: 2026-02-25*
