# Pitfalls Research

## Critical Pitfalls

### 1. Agent Hallucination in Clinical Context
**Risk**: LLM agents fabricate vital signs, lab values, or guidelines that don't exist in the actual FHIR data.

**Warning signs**:
- Agent recommendations reference data not in FHIR response
- Guideline citations that don't match knowledge base content
- Scores calculated with assumed (not retrieved) values

**Prevention**:
- Strict tool-call-only data access — agents NEVER generate clinical data from training knowledge
- Every recommendation must cite the specific FHIR resource ID and value it used
- Score calculations are deterministic Python (agents/scoring/), NOT LLM-generated
- System prompts include: "If data is unavailable, state 'DATA NOT AVAILABLE' — never estimate or assume clinical values"

**Phase**: Phase 1 (supervisor agent system prompt design) and ongoing

### 2. Alarm Fatigue from Over-Alerting
**Risk**: System generates too many alerts, clinicians ignore them, critical alerts get missed.

**Warning signs**:
- Alert acknowledgment rate drops below 50%
- Clinicians disable or mute alert categories
- Time-to-acknowledge increases over time
- Feedback ratings consistently negative

**Prevention**:
- 4-tier classification already implemented — enforce strict tier criteria
- Contextual suppression: adjust thresholds per patient baseline (e.g., chronically low BP patient)
- Multi-parameter fusion: combine vitals into single clinical decision, not individual alerts per parameter
- Smart deduplication: never re-alert for acknowledged conditions within suppression window
- Start conservative: only CRITICAL and URGENT tiers active initially, expand as trust builds
- Weekly alert accuracy review with override tracking

**Phase**: Phase 1-2 (alert tuning is continuous)

### 3. Agent Coordination Deadlocks
**Risk**: Multiple specialist agents make conflicting recommendations or enter circular dependencies.

**Warning signs**:
- Two agents recommend opposite actions (e.g., "give fluids" vs "restrict fluids")
- Agent processing time increases unboundedly
- Supervisor fails to synthesize conflicting findings

**Prevention**:
- Supervisor is the SOLE escalation pathway — sub-agents never directly alert
- Conflict resolution protocol: supervisor presents both recommendations with evidence, clinician decides
- Agent isolation: each sub-agent has independent context, cannot see other agents' state
- Timeout enforcement: each agent evaluation has a max processing time (30 seconds)
- Priority ordering: if two agents conflict, the one with higher clinical acuity wins default

**Phase**: Phase 2 (when sub-agents are introduced)

### 4. FHIR Data Freshness and Consistency
**Risk**: Agents reason about stale data, leading to incorrect assessments.

**Warning signs**:
- Alerts fire for conditions already addressed
- Scoring calculations use outdated vital signs
- Patient state shows medications that were discontinued

**Prevention**:
- Timestamp every data fetch; never cache FHIR data beyond 60 seconds for vitals, 5 minutes for medications/conditions
- Supervisor checks data freshness before each evaluation cycle
- "Data age" indicator in dashboard — amber if >2 min, red if >5 min for vitals
- Phase 4 FHIR Subscriptions replace polling for near-real-time

**Phase**: Phase 1 (polling), Phase 4 (subscriptions)

### 5. Simulation-Production Divergence
**Risk**: Agents behave differently in simulation vs. production because simulation data patterns don't match real clinical data.

**Warning signs**:
- High simulation test pass rate but poor production alert accuracy
- Synthetic vital signs lack realistic variability
- Lab turnaround times in simulation don't match reality

**Prevention**:
- Simulation writes FHIR data through SAME handlers as production — no separate code path
- Physiology models validated against MIMIC-IV/eICU statistical distributions
- Include realistic noise: data entry delays, missing values, out-of-order results
- Include adversarial scenarios: data entry errors, ambiguous presentations, borderline values
- Regularly compare simulation alert patterns to real-world EHR data distributions

**Phase**: Phase 1-2 (engine design), Phase 3 (validation)

### 6. Knowledge Base Staleness
**Risk**: Clinical guidelines in RAG are outdated; agents recommend based on superseded evidence.

**Warning signs**:
- Agent citations reference guidelines older than 2 years
- Clinical staff report recommendations contradict current practice
- New published guidelines not reflected in agent behavior

**Prevention**:
- Version all guidelines with publication date and review date
- Admin interface shows "last updated" for each knowledge base entry
- Automated staleness warnings: flag guidelines approaching 2-year review cycle
- Separate structured rules (JSON — deterministic) from guideline prose (RAG — semantic)
- Critical scoring thresholds (NEWS2, qSOFA, SOFA) are in deterministic code, NOT RAG

**Phase**: Phase 2-3 (knowledge base + admin interface)

### 7. Context Window Overflow
**Risk**: Complex patients with many conditions, medications, and active agents overflow the LLM context window, causing the agent to lose critical information.

**Warning signs**:
- Agent recommendations miss known conditions or medications
- Supervisor fails to spawn agents for qualifying conditions
- Quality degrades as patient complexity increases

**Prevention**:
- Structured patient state summary (not raw FHIR dumps) — compress into key facts
- Each specialist agent gets ONLY its domain-relevant data (not full patient record)
- Rolling summarization: supervisor maintains a concise running assessment
- Token budget per agent turn: monitor and alert if approaching limits
- Use haiku/flash models for simple checks, opus/sonnet for complex reasoning

**Phase**: Phase 1-2 (system prompt design)

### 8. Medplum FHIR Server Limitations
**Risk**: Medplum may not support all FHIR R4 features needed (Subscriptions, specific search parameters, custom operations).

**Warning signs**:
- Subscription creation returns errors or doesn't trigger callbacks
- Search queries don't support needed parameters (e.g., _lastUpdated with precision)
- Performance degrades with many concurrent resource queries

**Prevention**:
- Test Medplum Subscription support early (Phase 1 spike, don't wait until Phase 4)
- Document known Medplum limitations and workarounds
- Polling fallback for every subscription-dependent feature
- Consider HAPI FHIR as backup server if Medplum limitations block progress

**Phase**: Phase 1 (early validation), Phase 4 (subscriptions)

## Moderate Pitfalls

### 9. Frontend Performance Under Load
**Risk**: Dashboard becomes sluggish with many patients, streaming vitals, and agent activity.

**Prevention**:
- Virtualize patient census list (only render visible rows)
- Throttle vital signs chart updates (max 1 render per second)
- Agent activity log: keep only last 100 entries in DOM, full log in memory
- WebSocket messages batched (not one per vital sign)

**Phase**: Phase 3-4

### 10. Test Data Seeding Complexity
**Risk**: Inpatient scenarios need complex interconnected FHIR resources (Encounter + Conditions + Observations + MedicationRequests + CareTeam + etc.) — seed scripts become fragile.

**Prevention**:
- Scenario-based seeding: each scenario is a self-contained FHIR Bundle
- Synthea generates complete bundles automatically
- Validation script: after seeding, verify all required resources exist and reference correctly

**Phase**: Phase 1

### 11. Multi-Model Inconsistency
**Risk**: Different LLM models (Claude, Gemini, GPT-4) produce inconsistent agent behavior, making testing unreliable.

**Prevention**:
- Pin model per agent type (don't randomly route)
- Deterministic operations (scoring, alerting) are Python code, not LLM calls
- Structured output schemas for agent findings (not free-text)
- Regression test suite per model

**Phase**: Phase 2-3

---
*Research: 2026-02-25*
