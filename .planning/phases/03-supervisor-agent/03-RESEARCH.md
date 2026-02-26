# Phase 3: Supervisor Agent - Research

**Researched:** 2026-02-25
**Domain:** Agent orchestration, clinical scoring integration, patient state management
**Confidence:** HIGH

## Summary

The supervisor agent is the central intelligence of the inpatient care oversight platform. It runs as one instance per monitored patient, continuously polling FHIR for the patient's clinical state (encounter, conditions, vitals, meds, labs), recalculating deterministic clinical scores (NEWS2, qSOFA, SOFA, KDIGO), generating alerts through the existing AlertManager, and producing evidence-cited recommendations for clinician review. The supervisor does NOT directly modify treatment -- all actions route through the existing approval queue.

The existing codebase provides strong foundations: `OpenRouterOrchestrator` (1580 lines) demonstrates the LLM-tool-loop pattern; `clinical_scores.py` (748 lines) provides all four scoring systems with `calculate_all_available_scores()` as the aggregate entry point; `AlertManager` (999 lines) provides full 4-tier classification with deduplication, suppression, escalation, and lifecycle management; and `AlertClassifier` provides static methods to convert score results directly to severity levels. The FHIR handlers from Phases 1-2 provide complete inpatient data access (encounter lifecycle, conditions, observations, medications, care teams, flags, tasks). Phase 2 seeded 5 inpatient patients with realistic clinical scenarios (sepsis, cardiac, renal, pulmonary, multi-system).

**Primary recommendation:** Build the supervisor as a new `SupervisorAgent` class in `agents/supervisor.py` that follows the existing orchestrator pattern (async, OpenRouterClient for LLM calls, FHIR handlers for data access) but adds a `PatientState` container and an `evaluate()` cycle that separates deterministic scoring from LLM-driven clinical reasoning. The supervisor should NOT subclass `OpenRouterOrchestrator` -- it has a fundamentally different lifecycle (continuous monitoring vs. request-response).

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FR-02 | Supervisor agent: one per patient, evaluates state via FHIR, spawns specialist triggers, routes escalations | Core deliverable. `SupervisorAgent` class with `PatientState` container, `evaluate()` cycle, FHIR data loading, and stub spawn hooks for Phase 6 |
| FR-04 | Clinical scoring integration: NEWS2, qSOFA, SOFA, KDIGO on each update | `calculate_all_available_scores()` already exists in `agents/scoring/clinical_scores.py`. Supervisor calls it with extracted vitals/labs dicts. No new scoring code needed. |
| FR-05 | 4-tier alert classification with dedup, suppression, lifecycle | `AlertManager` + `AlertClassifier` fully implemented in `agents/alerts/alert_manager.py`. Supervisor calls `AlertClassifier.classify_from_news2()` / `classify_from_qsofa()` to determine severity, then `AlertManager.create_alert()` to generate alerts. |
| NFR-01 | Evaluation cycle completes within 30 seconds | FHIR queries via `asyncio.gather()` for parallel fetching. Scoring is pure Python (<1ms). LLM call is the bottleneck -- use fast model (glm-flash or gemini-3-flash) for routine evaluations, reserve heavier models for complex synthesis. |
| NFR-03 | No direct treatment modifications -- all through approval queue | Supervisor's FHIR tool set is read-only for clinical data. Write operations (create flag, create clinical impression, create task) route through the existing approval queue as established in Phases 1-2. |
| NFR-04 | Every recommendation cites specific data | System prompt enforces citation format. `PatientState` tracks data provenance (FHIR resource IDs, timestamps). LLM receives structured data with IDs, not raw text. |
| NFR-05 | Data freshness: vitals <60s, meds/conditions <5min | `PatientState` timestamps every data category. Evaluation cycle checks freshness before scoring. Stale data triggers re-fetch before proceeding. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12 | Runtime | Already in use across project |
| httpx | >=0.27.0 | Async HTTP for FHIR + OpenRouter calls | Already used by `OpenRouterClient` and `fhir_client` |
| pydantic | >=2.0 | Data validation for `PatientState` and related models | Already a dependency; `BaseModel` for structured state |
| asyncio | stdlib | Concurrent FHIR queries, evaluation loop scheduling | Already used throughout; `asyncio.gather()` for parallel fetches |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| dataclasses | stdlib | Lightweight data containers for internal models | For `Finding`, `EvaluationResult`, `SpawnTrigger` where pydantic validation overhead is unnecessary |
| logging | stdlib | Structured logging for evaluation cycles | Every evaluation cycle logs inputs, scores, decisions |
| uuid | stdlib | Unique IDs for evaluation cycles and findings | Already used by `AlertManager` for alert IDs |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Polling FHIR | FHIR Subscriptions | Subscriptions deferred to Phase 4 dashboard; polling is simpler and sufficient for <20 patients |
| In-memory PatientState | Redis/DB-backed state | In-memory is fine for single-process; persistence only needed for multi-process in Phase 11 |
| Custom eval loop | Claude Agent SDK | Agent SDK adds complexity; the existing OpenRouterClient + tool loop pattern is proven and sufficient |

### No New Dependencies Required
All functionality can be built with existing project dependencies. No `pip install` needed.

## Architecture Patterns

### Recommended Project Structure
```
agents/
├── supervisor.py           # SupervisorAgent class (NEW)
├── patient_state.py        # PatientState container + data models (NEW)
├── prompts/
│   ├── clinical_reasoning.md    # Existing clinician prompt
│   ├── patient_portal.md        # Existing portal prompt
│   └── supervisor.md            # Supervisor system prompt (NEW)
├── scoring/
│   └── clinical_scores.py       # Existing — no changes needed
├── alerts/
│   └── alert_manager.py         # Existing — no changes needed
├── openrouter_client.py         # Existing LLM client
└── openrouter_orchestrator.py   # Existing chat orchestrator (reference pattern)
```

### Pattern 1: PatientState Container
**What:** A dataclass/pydantic model that holds all clinical data for a single patient, with timestamps for freshness tracking.
**When to use:** Every evaluation cycle reads from and updates this container.
**Example:**
```python
# agents/patient_state.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass
class VitalSigns:
    """A single vitals measurement from FHIR Observation."""
    timestamp: datetime
    heart_rate: float | None = None
    systolic_bp: float | None = None
    diastolic_bp: float | None = None
    respiratory_rate: float | None = None
    spo2: float | None = None
    temperature_c: float | None = None
    consciousness: str = "A"
    gcs: int | None = None
    supplemental_o2: bool = False
    fhir_observation_ids: list[str] = field(default_factory=list)

@dataclass
class PatientState:
    """Complete clinical state for a monitored patient."""
    patient_id: str
    encounter_id: str
    last_updated: datetime | None = None

    # Clinical data with freshness timestamps
    vitals_history: list[VitalSigns] = field(default_factory=list)
    vitals_fetched_at: datetime | None = None

    lab_results: dict[str, Any] = field(default_factory=dict)
    labs_fetched_at: datetime | None = None

    active_conditions: list[dict] = field(default_factory=list)
    conditions_fetched_at: datetime | None = None

    active_medications: list[dict] = field(default_factory=list)
    medications_fetched_at: datetime | None = None

    # Computed scores (recalculated each cycle)
    scores: dict[str, dict] = field(default_factory=dict)

    # Alert tracking
    active_alert_ids: list[str] = field(default_factory=list)

    # Sub-agent spawn triggers (hooks for Phase 6)
    spawn_triggers: list[str] = field(default_factory=list)

    def is_vitals_fresh(self, max_age_seconds: int = 60) -> bool:
        """Check if vitals data is within freshness window."""
        if self.vitals_fetched_at is None:
            return False
        age = (datetime.now(timezone.utc) - self.vitals_fetched_at).total_seconds()
        return age < max_age_seconds

    def is_meds_fresh(self, max_age_seconds: int = 300) -> bool:
        """Check if medication data is within freshness window."""
        if self.medications_fetched_at is None:
            return False
        age = (datetime.now(timezone.utc) - self.medications_fetched_at).total_seconds()
        return age < max_age_seconds
```

### Pattern 2: Supervisor Evaluation Cycle
**What:** A three-phase evaluation cycle: (1) fetch data from FHIR, (2) deterministic scoring, (3) LLM-driven clinical reasoning.
**When to use:** On each evaluation tick (configurable interval, default 60 seconds).
**Example:**
```python
# agents/supervisor.py — evaluate() method
async def evaluate(self) -> EvaluationResult:
    """Run one evaluation cycle for this patient."""
    cycle_start = datetime.now(timezone.utc)

    # Phase 1: Fetch/refresh FHIR data (parallel)
    await self._refresh_patient_data()

    # Phase 2: Deterministic scoring (pure Python, <1ms)
    vitals_dict = self._extract_vitals_dict()
    labs_dict = self._extract_labs_dict()
    self.state.scores = calculate_all_available_scores(vitals_dict, labs_dict)

    # Phase 3: Score-based alerting (deterministic)
    new_alerts = self._evaluate_score_alerts()

    # Phase 4: LLM clinical reasoning (async, ~5-15s)
    findings = await self._llm_evaluate(vitals_dict, labs_dict)

    # Phase 5: Generate alerts from LLM findings
    for finding in findings:
        alert = self._finding_to_alert(finding)
        if alert:
            new_alerts.append(alert)

    cycle_duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
    return EvaluationResult(
        cycle_duration_seconds=cycle_duration,
        scores=self.state.scores,
        alerts_generated=new_alerts,
        findings=findings,
    )
```

### Pattern 3: Parallel FHIR Data Fetching
**What:** Use `asyncio.gather()` to fetch vitals, conditions, meds, and labs simultaneously rather than sequentially.
**When to use:** During the data refresh phase of each evaluation cycle.
**Example:**
```python
async def _refresh_patient_data(self):
    """Fetch all FHIR data for the patient in parallel."""
    tasks = []

    if not self.state.is_vitals_fresh():
        tasks.append(self._fetch_vitals())
    if not self.state.is_meds_fresh():
        tasks.append(self._fetch_medications())
    if not self.state.is_conditions_fresh():
        tasks.append(self._fetch_conditions())
    # Labs always fetched (may have new results)
    tasks.append(self._fetch_labs())

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"FHIR fetch failed: {result}")
```

### Pattern 4: Supervisor System Prompt
**What:** A dedicated system prompt that constrains the LLM to analyze structured data, cite evidence, and never fabricate values.
**When to use:** Every LLM call within the supervisor evaluation cycle.
**Key elements:**
- Role definition: "You are a clinical supervisor agent monitoring patient {name}"
- Structured patient state injected as context (not raw FHIR JSON)
- Explicit instruction: "NEVER generate, estimate, or assume clinical values. Only reference data provided."
- Output format: structured findings with severity, category, evidence citations, and recommended actions
- Approval queue constraint: "You cannot modify treatment. Recommend actions for clinician review."

### Pattern 5: Spawn Trigger Hooks (Phase 6 Preparation)
**What:** During evaluation, the supervisor identifies conditions that would warrant specialist sub-agents and records them as spawn triggers, but does NOT actually spawn agents until Phase 6.
**When to use:** After scoring and initial analysis.
**Example:**
```python
def _evaluate_spawn_triggers(self) -> list[str]:
    """Identify conditions warranting specialist agents (Phase 6 hooks)."""
    triggers = []

    # Sepsis pathway -> Infectious Disease agent
    qsofa = self.state.scores.get("qSOFA", {})
    if qsofa.get("sepsis_risk"):
        triggers.append("infectious_disease")

    # AKI -> Renal agent
    kdigo = self.state.scores.get("KDIGO", {})
    if kdigo.get("stage", 0) >= 1:
        triggers.append("renal")

    # Cardiac conditions -> Cardiology agent
    for condition in self.state.active_conditions:
        code = condition.get("code", {}).get("coding", [{}])[0].get("code", "")
        if code in CARDIAC_SNOMED_CODES:
            triggers.append("cardiology")

    self.state.spawn_triggers = list(set(triggers))
    return self.state.spawn_triggers
```

### Anti-Patterns to Avoid
- **Subclassing OpenRouterOrchestrator:** The existing orchestrator is a request-response chat agent. The supervisor is a continuous monitoring loop. Different lifecycle, different state model. Compose, don't inherit.
- **Raw FHIR JSON to LLM:** FHIR bundles are verbose. Extract structured summaries into the system prompt. A single Observation resource is ~30 lines of JSON; a vitals summary is 1 line.
- **LLM-generated scores:** NEWS2, qSOFA, SOFA, KDIGO are deterministic math. Never ask the LLM to calculate them. Pass the results to the LLM for interpretation only.
- **Blocking evaluation loop:** The evaluate() method must be async. FHIR fetches and LLM calls are I/O-bound. Use `asyncio.gather()` for parallel operations.
- **Global mutable state for patient data:** Each supervisor instance owns its `PatientState`. No shared mutable dictionaries between patient supervisors.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Clinical scoring | Custom score calculators | `agents/scoring/clinical_scores.py` — `calculate_all_available_scores()` | Already implemented, tested, correct thresholds per medical guidelines |
| Alert classification from scores | Severity lookup tables | `AlertClassifier.classify_from_news2()`, `classify_from_qsofa()`, `classify_vital_sign()`, `classify_lab_result()` | Full threshold tables already coded with medical references |
| Alert lifecycle (dedup, suppress, escalate) | Custom alert tracking | `AlertManager` singleton via `get_alert_manager()` | Thread-safe, dedup windows, suppression rules, escalation checks all implemented |
| LLM API calls | Direct HTTP to OpenRouter | `OpenRouterClient` — `create_message()` with tools | Message format conversion, tool call parsing, error handling built in |
| FHIR data access | Direct HTTP to Medplum | Existing handler functions (`handle_search_observations`, `handle_get_patient_summary`, etc.) | Auth, error handling, FHIR search params, response parsing all implemented |

**Key insight:** Phase 3 is primarily an integration phase. The scoring, alerting, LLM client, and FHIR access layers all exist. The supervisor's job is to wire them together with a `PatientState` container and an evaluation loop. The new code is the orchestration logic, not the underlying capabilities.

## Common Pitfalls

### Pitfall 1: Context Window Overflow with Complex Patients
**What goes wrong:** Multi-system patients (like the seeded William Harris) have many conditions, medications, lab results, and vital sign series. Dumping all this into the LLM prompt exceeds context limits or degrades reasoning quality.
**Why it happens:** Developers format all FHIR data as verbose JSON for the LLM context.
**How to avoid:** Build a structured patient summary function that compresses raw FHIR data into a concise clinical narrative. Latest vitals as a single table row, not individual Observation resources. Active conditions as a comma-separated list, not full Condition resources. Only include the most recent 4-6 vitals measurements, not the full 24-hour history.
**Warning signs:** LLM responses miss known conditions or medications; token counts approaching model limits.

### Pitfall 2: Stale Data Leading to Incorrect Alerts
**What goes wrong:** The supervisor calculates scores from cached vitals that are >60 seconds old, generating alerts for conditions that have already been addressed.
**Why it happens:** No freshness check before scoring; fetch happens at start of cycle but scoring happens after LLM call (which takes 5-15s).
**How to avoid:** Timestamp every data category in `PatientState`. Check freshness immediately before scoring. If vitals are stale, re-fetch before calculating. The 30-second cycle budget allows for one re-fetch.
**Warning signs:** Alerts fire for conditions that were corrected; same alert keeps regenerating despite treatment.

### Pitfall 3: Alert Fatigue from Score-Based Over-Alerting
**What goes wrong:** Every evaluation cycle recalculates scores, and every borderline-abnormal score generates an alert, flooding clinicians.
**Why it happens:** Naive mapping of scores to alerts without considering that AlertManager's deduplication window is per-category, not per-score-value.
**How to avoid:** Use `AlertManager`'s dedup windows (5 min CRITICAL, 30 min URGENT, 120 min ROUTINE). Design alert categories carefully -- "news2_high" not "news2_score_7" vs "news2_score_8". Let AlertManager handle suppression. Do NOT create custom dedup logic outside AlertManager.
**Warning signs:** Alert count per patient per hour exceeds 5; clinicians ignore alerts.

### Pitfall 4: LLM Hallucinating Clinical Values
**What goes wrong:** The LLM generates fabricated vital signs, lab values, or guideline references in its recommendations.
**Why it happens:** The LLM fills gaps in its context with training data rather than stating "data not available."
**How to avoid:** System prompt must include explicit instruction: "NEVER generate, estimate, or assume clinical values. If data is not provided, state 'DATA NOT AVAILABLE'." Provide data as structured key-value pairs, not prose. Post-process LLM output to verify that any cited values match the actual PatientState.
**Warning signs:** Recommendations reference lab values not in the FHIR data; guideline citations are vague or nonexistent.

### Pitfall 5: Blocking the Event Loop with Synchronous Scoring
**What goes wrong:** Developer accidentally calls scoring functions in a blocking way that holds up the async event loop.
**Why it happens:** Scoring functions are synchronous Python. While they're fast (<1ms), wrapping them incorrectly (e.g., in a thread pool executor unnecessarily) adds overhead.
**How to avoid:** Call scoring functions directly in the async method -- they're pure CPU functions that complete in microseconds. No need for `run_in_executor()`. Reserve async patterns for I/O operations (FHIR fetches, LLM calls).
**Warning signs:** Evaluation cycles take longer than expected; event loop blocked warnings in logs.

### Pitfall 6: FHIR Search Parameter Mismatches
**What goes wrong:** FHIR searches return empty results because search parameters don't match Medplum's supported params.
**Why it happens:** FHIR search parameters vary by server implementation. Medplum may not support all standard FHIR search params.
**How to avoid:** Use the proven search patterns from Phase 1-2 handlers. For Observations, use `patient={id}&category=vital-signs&_sort=-date&_count=10`. For Conditions, use `patient={id}&clinical-status=active`. Test each query against seeded data before building the evaluation cycle.
**Warning signs:** Empty results from FHIR queries that should return data; `PatientState` has no vitals despite seeded data existing.

## Code Examples

### Extracting Vitals Dict for Scoring
```python
# Source: agents/scoring/clinical_scores.py — calculate_all_available_scores() expects this format
def _extract_vitals_dict(self) -> dict[str, Any]:
    """Convert latest VitalSigns to the dict format expected by clinical_scores."""
    if not self.state.vitals_history:
        return {}
    latest = self.state.vitals_history[-1]
    vitals = {}
    if latest.heart_rate is not None:
        vitals["heart_rate"] = latest.heart_rate
    if latest.systolic_bp is not None:
        vitals["systolic_bp"] = latest.systolic_bp
    if latest.diastolic_bp is not None:
        vitals["diastolic_bp"] = latest.diastolic_bp
    if latest.respiratory_rate is not None:
        vitals["respiratory_rate"] = latest.respiratory_rate
    if latest.spo2 is not None:
        vitals["spo2"] = latest.spo2
    if latest.temperature_c is not None:
        vitals["temperature_c"] = latest.temperature_c
    if latest.consciousness:
        vitals["consciousness"] = latest.consciousness
    if latest.gcs is not None:
        vitals["gcs"] = latest.gcs
    vitals["supplemental_o2"] = latest.supplemental_o2
    return vitals
```

### Creating Alerts from Score Results
```python
# Source: agents/alerts/alert_manager.py — AlertClassifier + AlertManager pattern
from agents.alerts.alert_manager import (
    get_alert_manager, AlertClassifier, AlertSeverity
)

def _evaluate_score_alerts(self) -> list[Alert]:
    """Generate alerts based on clinical score results."""
    alerts = []
    mgr = get_alert_manager()

    # NEWS2-based alerts
    news2 = self.state.scores.get("NEWS2")
    if news2:
        any_3 = any(v == 3 for v in news2.get("scores", {}).values())
        severity = AlertClassifier.classify_from_news2(
            news2["total_score"], any_3
        )
        if severity in (AlertSeverity.CRITICAL, AlertSeverity.URGENT):
            alert = mgr.create_alert(
                patient_id=self.state.patient_id,
                severity=severity,
                category="early_warning",
                title=f"NEWS2 {news2['risk_level']}: Score {news2['total_score']}",
                description=news2["clinical_response"],
                source_agent="supervisor",
                evidence=[{
                    "type": "clinical_score",
                    "name": "NEWS2",
                    "total_score": news2["total_score"],
                    "risk_level": news2["risk_level"],
                    "component_scores": news2["scores"],
                }],
                recommended_actions=[news2["clinical_response"]],
            )
            if alert:  # None means deduped/suppressed
                alerts.append(alert)

    # qSOFA-based alerts
    qsofa = self.state.scores.get("qSOFA")
    if qsofa and qsofa.get("sepsis_risk"):
        severity = AlertClassifier.classify_from_qsofa(qsofa["score"])
        alert = mgr.create_alert(
            patient_id=self.state.patient_id,
            severity=severity,
            category="sepsis",
            title=f"qSOFA >= 2: Sepsis Risk",
            description=qsofa["recommendation"],
            source_agent="supervisor",
            evidence=[{
                "type": "clinical_score",
                "name": "qSOFA",
                "score": qsofa["score"],
                "criteria_met": qsofa["criteria_met"],
            }],
            recommended_actions=[qsofa["recommendation"]],
        )
        if alert:
            alerts.append(alert)

    return alerts
```

### Using OpenRouterClient for Supervisor LLM Calls
```python
# Source: agents/openrouter_client.py — same pattern as OpenRouterOrchestrator
from agents.openrouter_client import OpenRouterClient

client = OpenRouterClient(model="gemini-3-flash")  # Fast model for routine evals

response = await client.create_message(
    messages=[{
        "role": "user",
        "content": f"Evaluate this patient state and identify any clinical concerns:\n{patient_summary}",
    }],
    system=supervisor_system_prompt,
    tools=None,  # Supervisor initial eval doesn't need tools — it has the data
    max_tokens=2048,
    temperature=0.3,  # Lower temperature for clinical analysis
)
```

### Fetching FHIR Data Using Existing Handlers
```python
# Source: fhir-mcp-server/src/handlers.py — reuse existing handler functions
from handlers import (
    handle_search_observations,
    handle_get_patient_summary,
    handle_search_medications,
    handle_get_active_flags,
)

async def _fetch_vitals(self):
    """Fetch recent vital signs from FHIR."""
    result = await handle_search_observations({
        "patient_id": self.state.patient_id,
        "category": "vital-signs",
        "count": 20,  # Last 20 observations
    })
    # Parse FHIR Observation bundle into VitalSigns objects
    self.state.vitals_history = self._parse_observations(result)
    self.state.vitals_fetched_at = datetime.now(timezone.utc)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single-model orchestration | Multi-model via OpenRouter | Already in codebase | Supervisor can use fast models for routine checks, heavy models for complex reasoning |
| FHIR Subscriptions for real-time | Polling with freshness checks | Phase 3 decision (subscriptions deferred) | Simpler implementation; sufficient for <20 patients |
| Claude Agent SDK for agent hierarchy | Direct OpenRouterClient + custom orchestration | Research recommendation | Avoids SDK lock-in; keeps multi-model flexibility through OpenRouter |
| Stateless request-response agents | Stateful PatientState per supervised patient | Phase 3 new pattern | Enables temporal reasoning (vitals trending, score changes over time) |

**Deprecated/outdated:**
- Claude Agent SDK was considered in early research for supervisor-sub-agent delegation. Deferred to Phase 6 evaluation. For Phase 3, direct OpenRouterClient calls are sufficient since no sub-agents exist yet.

## Open Questions

1. **Evaluation cycle interval tuning**
   - What we know: 30-second budget per cycle (NFR-01). FHIR fetches take ~1-3s. LLM call takes ~5-15s.
   - What's unclear: Optimal polling interval. Too frequent wastes API calls; too infrequent misses deterioration.
   - Recommendation: Default to 60-second interval. Make it configurable per patient acuity (30s for CRITICAL NEWS2, 120s for stable patients). Implement as a parameter, not a constant.

2. **LLM model selection for supervisor**
   - What we know: OpenRouter supports multiple models. Fast models (gemini-3-flash, glm-flash) are ~2-5s. Heavier models (claude-sonnet, gpt-4o) are ~10-20s.
   - What's unclear: Which model provides best clinical reasoning quality within the 30s budget.
   - Recommendation: Start with `gemini-3-flash` for routine evaluation cycles. Make model configurable. Test against seeded scenarios to validate recommendation quality.

3. **PatientState persistence across restarts**
   - What we know: In-memory PatientState is lost on process restart.
   - What's unclear: Whether Phase 3 needs persistence or if re-fetching from FHIR on startup is sufficient.
   - Recommendation: No persistence needed for Phase 3. On startup, rebuild PatientState from FHIR. Persistence is a Phase 11 concern (NFR-08 concurrent patients).

4. **Supervisor API endpoints**
   - What we know: `api/main.py` currently serves chat orchestrator endpoints.
   - What's unclear: Whether Phase 3 needs new API endpoints or if supervisor runs as a background service.
   - Recommendation: Add minimal API endpoints: `POST /api/supervisor/start/{patient_id}`, `GET /api/supervisor/state/{patient_id}`, `POST /api/supervisor/stop/{patient_id}`. These enable Phase 4 dashboard to interact with supervisors.

5. **Handling missing data gracefully**
   - What we know: Scoring functions handle optional parameters (SOFA calculates partial scores). Not all patients have all vitals.
   - What's unclear: How should the supervisor behave when critical vitals are missing (e.g., no GCS for qSOFA)?
   - Recommendation: Calculate available scores only. Log missing parameters. Generate INFORMATIONAL alert for data gaps ("Missing GCS for qSOFA calculation"). Never fabricate values.

## Sources

### Primary (HIGH confidence)
- `agents/scoring/clinical_scores.py` — Full scoring implementations reviewed; function signatures, input formats, and return types verified
- `agents/alerts/alert_manager.py` — Full AlertManager + AlertClassifier reviewed; API, dedup windows, severity mapping verified
- `agents/openrouter_client.py` — LLM client API reviewed; message format, tool support, model aliases verified
- `agents/openrouter_orchestrator.py` — Orchestration pattern reviewed; tool dispatch, conversation loop, handler imports verified
- `fhir-mcp-server/src/handlers.py` — FHIR handler functions verified; inpatient encounter handlers, observation search confirmed
- `scripts/seed_patients.py` — Seeded patient data reviewed; 5 inpatient scenarios with full clinical data confirmed

### Secondary (MEDIUM confidence)
- `.planning/research/ARCHITECTURE.md` — Architecture decisions (PatientState design, agent isolation, data flow)
- `.planning/research/PITFALLS.md` — Documented pitfalls (hallucination, alarm fatigue, context overflow)
- `.planning/research/SUMMARY.md` — Stack decisions (OpenRouter, deterministic scoring, agent isolation)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in project; no new dependencies needed
- Architecture: HIGH - Patterns directly extend existing orchestrator; scoring and alerting APIs verified from source code
- Pitfalls: HIGH - Pitfalls grounded in actual codebase review (e.g., AlertManager dedup windows, scoring function signatures)

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable — no external library changes expected)
