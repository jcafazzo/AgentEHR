---
phase: 02-inpatient-seed-data
verified: 2026-02-25T00:00:00Z
status: gaps_found
score: 3/4 success criteria verified
re_verification: false
gaps:
  - truth: "Seed script is idempotent (re-runnable without duplicates)"
    status: partial
    reason: "Patient and Encounter resources have find_or_create guards preventing duplicates. Clinical resources (Conditions, Observations, MedicationRequests, CareTeam) have no duplicate prevention — they are unconditionally created on every run via fhir_client.create() inside seed_inpatient_patient()."
    artifacts:
      - path: "scripts/seed_patients.py"
        issue: "seed_inpatient_patient() always calls fhir_client.create() for all scenario resources without checking for existing Conditions, Observations, MedicationRequests, or CareTeam linked to the encounter"
    missing:
      - "Skip clinical resource creation when encounter already existed (detect on find_or_create_inpatient_encounter return path)"
      - "OR: add find_or_create guards for Conditions and MedicationRequests by identity (code + patient + encounter)"
      - "OR: clear existing encounter-linked resources before re-seeding (conditional delete on re-run)"
human_verification:
  - test: "Run seed script twice against live Medplum and check resource counts"
    expected: "5 inpatient encounters each with exactly 1 set of clinical resources (no duplicates) after second run"
    why_human: "Cannot verify actual Medplum state programmatically — requires a running Medplum instance and fhir_client authentication"
---

# Phase 2: Inpatient Seed Data Verification Report

**Phase Goal:** Create realistic inpatient encounter data in Medplum covering multiple clinical scenarios, enabling supervisor agent development and dashboard testing.
**Verified:** 2026-02-25
**Status:** gaps_found — 3 of 4 roadmap success criteria fully verified; 1 partial gap on idempotency scope
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 5+ inpatient encounters seeded: sepsis, cardiac (ACS/CHF), renal (AKI), pulmonary (PE/COPD), multi-system | VERIFIED | INPATIENT_PROFILES defines exactly 5 patient profiles at lines 1968-2009: Dorothy Turner/sepsis, Michael Romano/cardiac STEMI, Harold Washington/renal AKI, Susan Park/pulmonary PE/COPD, William Harris/multi-system sepsis+AKI+respiratory failure |
| 2 | Each encounter has: Encounter + Conditions + Observations (vitals + labs) + MedicationRequests + CareTeam | VERIFIED | All 5 scenario creators return resources of all 5 required types. Sepsis: 3 conditions, 36h vitals, 22 labs, 4 meds, CareTeam. Cardiac: 5 conditions, 24h vitals, 16 labs, 6 meds, CareTeam. Renal: 5 conditions, 48h vitals, 24 labs, 4 meds, CareTeam. Pulmonary: 4 conditions, 30h vitals, 16 labs, 4 meds, CareTeam. Multi-system: 6 conditions, 48h vitals, 29 labs, 6 meds, CareTeam. |
| 3 | Seed script is idempotent (re-runnable without duplicates) | PARTIAL | Patient creation is idempotent (find_or_create_patient, lines 2012-2039). Encounter creation is idempotent (find_or_create_inpatient_encounter, lines 473-500). Clinical resources (Conditions, Observations, MedicationRequests, CareTeam) are NOT idempotent — seed_inpatient_patient() unconditionally calls fhir_client.create() for all scenario resources on every run (lines 524-534), producing duplicates on re-run. |
| 4 | Vital signs observations span 24+ hours with realistic progression patterns | VERIFIED | All scenarios exceed 24 hours: sepsis=36h (line 587), cardiac=24h (line 690, exactly at boundary), renal=48h (line 799), pulmonary=30h (line 910), multi-system=48h (line 1012). Physiological clamping applied: HR 30-200, SBP 50-250, DBP 30-150, RR 4-60, Temp 33-42, SpO2 50-100. Progression dicts drive clinical deterioration/recovery curves. |

**Score:** 3/4 roadmap success criteria verified (1 partial gap)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/seed_patients.py` | Extended with 5 inpatient helpers, 5 scenario creators, INPATIENT_PROFILES, updated main() | VERIFIED | File is 2133 lines. All 5 functions exist at expected line numbers: make_inpatient_encounter (321), make_care_team (362), generate_vital_series (384), find_or_create_inpatient_encounter (473), seed_inpatient_patient (503), create_sepsis_scenario (545), create_cardiac_scenario (651), create_renal_scenario (763), create_pulmonary_scenario (874), create_multisystem_scenario (970), INPATIENT_PROFILES (1968), main() (2075). |

---

## Key Link Verification

### Plan 02-01 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `generate_vital_series` | `make_vital, make_bp` | function calls with encounter_id | WIRED | Lines 432-468 show make_vital and make_bp called with encounter_id=encounter_id inside generate_vital_series. 139 total encounter_id=encounter_id wiring points confirmed. |
| `create_sepsis_scenario, create_cardiac_scenario` | `make_condition, make_medication, make_observation, make_vital, make_bp, make_care_team` | helper calls with encounter_id | WIRED | Both scenario creators call all listed helpers with encounter_id parameter. Confirmed at lines 567-648 (sepsis) and 673-759 (cardiac). |

### Plan 02-02 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `INPATIENT_PROFILES` | `create_sepsis_scenario, create_cardiac_scenario, create_renal_scenario, create_pulmonary_scenario, create_multisystem_scenario` | scenario_creator field in profile dicts | WIRED | Lines 1975, 1983, 1991, 1999, 2007 confirm all 5 scenario creators referenced as scenario_creator values. |
| `main()` | `seed_inpatient_patient` | async iteration over INPATIENT_PROFILES | WIRED | Lines 2105-2106: `for profile in INPATIENT_PROFILES: result = await seed_inpatient_patient(profile)` — exact pattern confirmed. |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| FR-14 | 02-01, 02-02 | Extend seed_patients.py with inpatient encounter scenarios covering sepsis, cardiac, renal, and multi-system patients. After seeding, Medplum contains at least 5 inpatient encounters with complete Encounter + Condition + Observation + MedicationRequest + CareTeam resources. | SATISFIED (with note) | Script produces all required resource types across 5 scenarios. Runtime idempotency gap affects re-run behavior but not first-run completeness. FR-14 testability criterion focuses on post-seeding state which is fully delivered. |

---

## Plan Must-Have Verification (Combined)

### Plan 02-01 Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Existing make_* helpers accept optional encounter_id and produce encounter-linked FHIR resources | VERIFIED | Lines 57-81 (make_condition), 83-124 (make_medication), 156-193 (make_observation), 196-224 (make_vital), 227-242 (make_bp) all accept encounter_id and append `"encounter": {"reference": f"Encounter/{encounter_id}"}` when provided. |
| 2 | make_inpatient_encounter creates valid Encounter(class=IMP) with hospitalization, location, priority | VERIFIED | Lines 321-359: resource has class.code="IMP", hospitalization.admitSource, location array with status/period, priority.coding. |
| 3 | make_care_team creates valid CareTeam with participants linked to encounter and patient | VERIFIED | Lines 362-381: status, name, subject (patient), encounter, participant list with role codings. |
| 4 | generate_vital_series produces hourly vital sign observations over 24+ hours with progression and clamping | VERIFIED | Lines 384-470: loops over hours*60 minutes at interval_minutes=60, applies progression deltas, clamps to physiological bounds, emits HR/BP/RR/Temp/SpO2 per hour. |
| 5 | find_or_create_inpatient_encounter searches before creating, preventing duplicate encounters | VERIFIED | Lines 473-500: searches by patient+class=IMP, filters by reasonCode text, returns existing ID if found. |
| 6 | Sepsis scenario: Encounter + Conditions + 36h vitals + labs + medications + CareTeam | VERIFIED | Lines 545-648: 3 conditions, 36h vitals (36*5=180 vital observations), labs at h0/h4/h12/h24, 4 medications, CareTeam with 3 members. |
| 7 | Cardiac scenario: Encounter + Conditions + 24h vitals + labs (troponin series, BNP, BMP) + medications + CareTeam | VERIFIED | Lines 651-760: 5 conditions, 24h vitals (24*5=120 vital observations), troponin series at h0/h3/h6/h12/h24, 6 medications, CareTeam with 3 members. |

### Plan 02-02 Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Renal AKI scenario: 48h vitals, creatinine series (KDIGO staging), electrolytes, medications, CareTeam | VERIFIED | Lines 763-871: 5 conditions, 48h vitals, creatinine 1.8->2.6->3.4->2.8->2.1->1.6 mg/dL across 6 timepoints (KDIGO stage 3 peak at h16), K+ tracked, 4 medications, Renal CareTeam. |
| 2 | Pulmonary PE/COPD scenario: 30h vitals, D-dimer series, medications, CareTeam | VERIFIED | Lines 874-967: 4 conditions, 30h vitals (SpO2 88% start, tachypnea RR 28, tachycardia HR 118), D-dimer 4500->3800->2500->1200, 4 medications (heparin/warfarin/albuterol/O2), Pulmonary CareTeam. |
| 3 | Multi-system scenario: sepsis+AKI+respiratory failure conditions, 48h vitals, comprehensive labs, 6 meds, 5-member ICU CareTeam | VERIFIED | Lines 970-1104: 6 conditions, 48h vitals, 13 labs at h0 (WBC/Creatinine/Lactate/Platelets/Bilirubin/PCT/K+/Na+/Hgb/BUN/AST/ALT/Troponin), 6 timepoints total, 6 medications, 5-member ICU CareTeam (physician, nephrologist, ID specialist, RN, pharmacist). |
| 4 | INPATIENT_PROFILES list contains 5 patient profiles with encounter_builder and scenario_creator functions | VERIFIED | Lines 1968-2009: exactly 5 entries, each with given/family/gender/birthDate/phone/mrn/address/admit_dt/encounter_builder/scenario_creator. Lambda default argument capture used to avoid late-binding closure issues. |
| 5 | main() seeds all 5 inpatient patients after existing 5 outpatient patients | VERIFIED | Lines 2075-2129: outpatient PATIENT_PROFILES loop first (lines 2092-2096), then inpatient INPATIENT_PROFILES loop (lines 2105-2109), with structured summary output including encounter IDs. |
| 6 | Seed script is idempotent: re-running does not create duplicate inpatient encounters | VERIFIED (scope-limited) | Encounter-level idempotency confirmed. Clinical resources are out of scope for this truth (truth is scoped to "inpatient encounters"). |
| 7 | After seeding, 5+ inpatient encounters exist with complete resource sets | VERIFIED (structurally) | Script correctly seeds all 5 profiles. Actual Medplum state requires human verification. |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | — | — | No TODO/FIXME/placeholder/stub patterns found in scripts/seed_patients.py |

---

## Commits Verified

| Commit | Description | Status |
|--------|-------------|--------|
| `505d237` | feat(02-01): add inpatient helpers and extend existing helpers with encounter_id | VERIFIED |
| `9b4e192` | feat(02-01): implement sepsis and cardiac ACS scenario creators | VERIFIED |
| `f94fd0c` | feat(02-02): add renal, pulmonary, and multi-system scenario creators | VERIFIED |
| `3214736` | feat(02-02): add INPATIENT_PROFILES and wire inpatient seeding into main() | VERIFIED |

---

## Human Verification Required

### 1. Live Medplum State After Seeding

**Test:** Run `python scripts/seed_patients.py` against a running Medplum instance, then query `GET /fhir/R4/Encounter?class=IMP` to verify 5 inpatient encounters exist.
**Expected:** 5 encounters returned, each with patient reference, reasonCode, period.start, class=IMP, in-progress status.
**Why human:** Cannot query live Medplum instance from static code analysis. Actual FHIR server responses are not available.

### 2. Idempotency on Second Run

**Test:** Run `python scripts/seed_patients.py` twice. After the second run, check each encounter's Conditions, Observations, MedicationRequests, and CareTeam resource counts via Medplum.
**Expected:** Resource counts should ideally remain stable (no duplicates) or the script should gracefully skip already-created resources.
**Why human:** The gap in clinical resource idempotency (Conditions, Observations, MedicationRequests, CareTeam) can only be confirmed against a live FHIR server.

---

## Gaps Summary

**One gap found** blocking the ROADMAP success criterion "Seed script is idempotent (re-runnable without duplicates)":

The implementation is **partially idempotent**. Patient-level and Encounter-level resources are correctly protected by `find_or_create_patient()` and `find_or_create_inpatient_encounter()` — re-running will not create duplicate patients or encounters. However, `seed_inpatient_patient()` unconditionally calls `fhir_client.create()` for every scenario resource (Conditions, Observations, MedicationRequests, CareTeam) without checking whether they already exist. A second run will create duplicate clinical resources linked to the same encounter.

The PLAN's idempotency truth is scoped narrowly to encounters ("does not create duplicate inpatient encounters") and is satisfied. The ROADMAP success criterion is broader ("re-runnable without duplicates") and is only partially satisfied.

**Severity:** Warning, not a blocker for Phase 3 (Supervisor Agent) which primarily needs the data to exist after first run. However, the ROADMAP criterion is not fully met as written.

**Suggested fix:** Inside `seed_inpatient_patient()`, detect whether the encounter was newly created or pre-existing. If pre-existing, skip scenario resource creation. This can be done by comparing the return path of `find_or_create_inpatient_encounter()` (e.g., returning a `(encounter_id, is_new)` tuple).

---

_Verified: 2026-02-25_
_Verifier: Claude (gsd-verifier)_
