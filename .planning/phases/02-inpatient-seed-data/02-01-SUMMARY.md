---
phase: 02-inpatient-seed-data
plan: 01
subsystem: data-seeding
tags: [fhir-r4, encounter, seed-data, sepsis, cardiac, vital-signs, inpatient]

# Dependency graph
requires:
  - phase: 01-fhir-inpatient-resource-expansion
    provides: "FHIR handlers for Encounter, CareTeam, and all inpatient resource types"
provides:
  - "Inpatient helper functions: make_inpatient_encounter, make_care_team, generate_vital_series"
  - "Encounter-linked resource creation via encounter_id parameter on all make_* helpers"
  - "Idempotent inpatient encounter creation via find_or_create_inpatient_encounter"
  - "Sepsis scenario creator with 36h vital progression, labs, medications, CareTeam"
  - "Cardiac ACS/STEMI scenario creator with 24h vital progression, troponin series, cardiac meds, CareTeam"
  - "seed_inpatient_patient async function for inpatient seeding flow"
affects: [02-inpatient-seed-data, 03-supervisor-agent, 04-command-center-dashboard]

# Tech tracking
tech-stack:
  added: [random (stdlib, deterministic seed 42), datetime/timedelta/timezone (stdlib)]
  patterns: [encounter-linked-resources, vital-sign-progression-generator, clinical-scenario-creator, physiological-clamping]

key-files:
  created: []
  modified: [scripts/seed_patients.py]

key-decisions:
  - "Extended existing make_* helpers with optional encounter_id rather than creating new inpatient-specific helpers -- preserves backward compatibility"
  - "Used static admit timestamps (2026-02-24 and 2026-02-25) for deterministic reproducibility"
  - "Physiological clamping bounds: HR 30-200, SBP 50-250, DBP 30-150, RR 4-60, Temp 33-42, SpO2 50-100"
  - "Client-side filtering for encounter idempotency (search by patient+class=IMP, filter by reason text)"

patterns-established:
  - "Pattern: encounter_id parameter -- all resource helpers accept optional encounter_id for inpatient linking"
  - "Pattern: scenario creator -- async function(patient_id, encounter_id) returns list[tuple[str, dict]] of (resource_type, resource)"
  - "Pattern: vital series progression -- base_vitals dict + progression list with hour/deltas for clinical deterioration/recovery curves"
  - "Pattern: seed_inpatient_patient -- find/create patient, find/create encounter, run scenario creator, bulk create resources"

requirements-completed: [FR-14]

# Metrics
duration: 11min
completed: 2026-02-26
---

# Phase 2 Plan 1: Inpatient Helpers & Sepsis/Cardiac Scenarios Summary

**Inpatient helper infrastructure (encounter-linked resources, vital series generator, idempotent encounter creation) plus sepsis 36h UTI-to-recovery and cardiac 24h STEMI-with-PCI scenario creators**

## Performance

- **Duration:** 11 min
- **Started:** 2026-02-26T01:48:19Z
- **Completed:** 2026-02-26T01:59:22Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Extended 5 existing make_* helpers with backward-compatible encounter_id parameter for encounter-linked resource creation
- Created 5 new inpatient helpers: make_inpatient_encounter, make_care_team, generate_vital_series, find_or_create_inpatient_encounter, seed_inpatient_patient
- Implemented sepsis scenario: 3 conditions, 36h hourly vitals (180 observations), 22 lab observations across 4 timepoints (WBC/Creatinine/Lactate/Platelets/Bilirubin/Procalcitonin), 4 medications, CareTeam
- Implemented cardiac ACS/STEMI scenario: 5 conditions, 24h hourly vitals (120 observations), 16 lab observations across 5 timepoints (Troponin series/BNP/Creatinine/Potassium/WBC/Hemoglobin/Lactate), 6 medications, CareTeam

## Task Commits

Each task was committed atomically:

1. **Task 1: Add inpatient helpers and extend existing helpers with encounter_id** - `505d237` (feat)
2. **Task 2: Implement sepsis and cardiac ACS scenario creators** - `9b4e192` (feat)

## Files Created/Modified
- `scripts/seed_patients.py` - Extended with inpatient helper functions, encounter_id support on all resource helpers, and sepsis + cardiac scenario creators

## Decisions Made
- Extended existing make_* helpers with optional encounter_id parameter rather than creating separate inpatient-specific versions. This preserves backward compatibility for all existing outpatient calls.
- Used static admit timestamps (2026-02-24T14:00:00Z for sepsis, 2026-02-25T02:30:00Z for cardiac) for deterministic reproducibility.
- Physiological clamping applied in generate_vital_series prevents impossible values (e.g., SpO2 > 100%, negative heart rate).
- Client-side filtering for encounter idempotency because Medplum may not support reason-code:text search modifier.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Helper infrastructure ready for remaining 3 scenarios (renal AKI, pulmonary PE/COPD, multi-system) in Plan 02-02
- seed_inpatient_patient function ready for INPATIENT_PROFILES list and main() integration
- Encounter-linked resource pattern established for all downstream scenario creators

## Self-Check: PASSED

- FOUND: scripts/seed_patients.py
- FOUND: 02-01-SUMMARY.md
- FOUND: commit 505d237
- FOUND: commit 9b4e192

---
*Phase: 02-inpatient-seed-data*
*Completed: 2026-02-26*
