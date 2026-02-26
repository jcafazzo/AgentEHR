---
phase: 03-supervisor-agent
plan: 01
subsystem: agents
tags: [dataclass, patient-state, freshness-tracking, system-prompt, clinical-scoring, NFR-04, NFR-05]

# Dependency graph
requires:
  - phase: 01-fhir-inpatient-resource-expansion
    provides: "FHIR handlers for observations, conditions, medications, encounters"
  - phase: 01-fhir-inpatient-resource-expansion
    provides: "Clinical scoring (clinical_scores.py) and alert management (alert_manager.py)"
provides:
  - "PatientState container with typed clinical data and freshness tracking"
  - "VitalSigns, LabResult, Finding, EvaluationResult data models"
  - "get_vitals_dict() and get_labs_dict() for scoring system integration"
  - "to_clinical_summary() for LLM context generation"
  - "Supervisor system prompt with safety constraints and evidence citation requirements"
affects: [03-supervisor-agent, 04-command-center-dashboard, 06-specialist-sub-agents]

# Tech tracking
tech-stack:
  added: []
  patterns: [dataclass-containers-over-pydantic, per-category-freshness-timestamps, structured-llm-prompt-with-template-placeholders]

key-files:
  created:
    - agents/patient_state.py
    - agents/prompts/supervisor.md
  modified: []

key-decisions:
  - "Used dataclasses (not pydantic) for lightweight containers per research recommendation"
  - "Freshness thresholds: vitals 60s, meds/conditions/labs 300s per NFR-05"
  - "get_vitals_dict() maps directly to calculate_all_available_scores() parameter keys"
  - "to_clinical_summary() produces concise text to avoid context window overflow"
  - "Supervisor prompt uses {patient_clinical_summary} and {scores_summary} template placeholders"

patterns-established:
  - "PatientState freshness pattern: is_*_fresh(max_age_seconds) checks fetched_at timestamp against UTC now"
  - "Scoring integration pattern: get_vitals_dict()/get_labs_dict() produce dicts matching scoring API"
  - "LLM context pattern: to_clinical_summary() compresses clinical data into structured text"
  - "System prompt pattern: safety rules + data rules + output format + context injection placeholders"

requirements-completed: [FR-02, FR-04, NFR-04, NFR-05]

# Metrics
duration: 19min
completed: 2026-02-26
---

# Phase 3 Plan 1: PatientState Data Model and Supervisor Prompt Summary

**PatientState dataclass with per-category freshness tracking, scoring-compatible data extraction, and supervisor LLM prompt with safety/citation constraints**

## Performance

- **Duration:** 19 min
- **Started:** 2026-02-26T04:12:17Z
- **Completed:** 2026-02-26T04:31:28Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- PatientState container with 5 data models (VitalSigns, LabResult, Finding, EvaluationResult, PatientState) holding typed clinical data with FHIR provenance IDs
- Per-category freshness tracking: vitals at 60s, meds/conditions/labs at 300s thresholds with is_*_fresh() methods
- Scoring integration via get_vitals_dict() and get_labs_dict() that produce dicts matching calculate_all_available_scores() parameter format
- Clinical summary generator (to_clinical_summary()) producing concise LLM context avoiding context window overflow
- Supervisor system prompt with explicit safety constraints (NFR-03), data integrity rules (NFR-04), structured JSON output format, and template placeholders

## Task Commits

Each task was committed atomically:

1. **Task 1: Create PatientState data model with freshness tracking** - `4baddba` (feat)
2. **Task 2: Create supervisor system prompt with safety constraints** - `e07354b` (feat)

## Files Created/Modified
- `agents/patient_state.py` - PatientState container, VitalSigns, LabResult, Finding, EvaluationResult data models with freshness methods and scoring integration
- `agents/prompts/supervisor.md` - Supervisor agent system prompt with safety constraints, data rules, JSON output format, and template placeholders

## Decisions Made
- Used dataclasses instead of pydantic for lightweight containers (per research recommendation -- these are internal data containers, not API models)
- Freshness defaults match NFR-05 requirements: 60s for vitals, 300s for everything else
- get_vitals_dict() includes supplemental_o2 always (boolean default False) even when other None fields are excluded
- to_clinical_summary() shows only latest vitals (not full history) and groups labs by name (most recent per name) to minimize context size
- Supervisor prompt uses explicit "NEVER generate" and "CANNOT directly modify" language for unambiguous safety constraints

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PatientState and data models ready for SupervisorAgent (Plan 02) to compose into evaluation cycle
- Supervisor prompt ready for LLM call injection with {patient_clinical_summary} and {scores_summary} placeholders
- get_vitals_dict()/get_labs_dict() interfaces match existing calculate_all_available_scores() API
- spawn_trigger field in Finding and EvaluationResult ready for Phase 6 specialist agent hooks

## Self-Check: PASSED

- [x] agents/patient_state.py exists
- [x] agents/prompts/supervisor.md exists
- [x] 03-01-SUMMARY.md exists
- [x] Commit 4baddba found (Task 1)
- [x] Commit e07354b found (Task 2)

---
*Phase: 03-supervisor-agent*
*Completed: 2026-02-26*
