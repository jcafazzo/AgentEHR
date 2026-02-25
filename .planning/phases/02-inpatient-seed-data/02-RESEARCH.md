# Phase 2: Inpatient Seed Data - Research

**Researched:** 2026-02-25
**Domain:** FHIR R4 inpatient encounter seeding, clinical scenario data modeling, idempotent script patterns
**Confidence:** HIGH

## Summary

Phase 2 extends the existing `scripts/seed_patients.py` with inpatient encounter scenarios that create realistic clinical data directly via httpx against Medplum. The existing script already demonstrates the complete pattern: helper functions (`make_patient`, `make_condition`, `make_observation`, `make_vital`, `make_medication`, `make_bp`, `make_encounter`) that build FHIR R4 resource dicts, a `find_or_create_patient` function for idempotency, and a `seed_patient` function that iterates through `(resource_type, resource_dict)` tuples creating them via `fhir_client.create()`. Five outpatient patients already exist (John Smith, Maria Garcia, Robert Johnson, Emily Chen, James Wilson).

The seed script creates FHIR resources DIRECTLY via the shared `fhir_client` (httpx against Medplum), NOT through the handler functions. This keeps seeding independent of the application layer. The existing script already imports `from handlers import fhir_client` for this purpose. New inpatient scenarios need: Encounter (class=IMP), Conditions, Observations (vitals spanning 24+ hours with progression), MedicationRequests (linked to encounter), and CareTeam resources. Each scenario must support the downstream supervisor agent (Phase 3) and clinical scoring systems (NEWS2, qSOFA, SOFA, KDIGO) that expect specific vital sign parameters.

**Primary recommendation:** Add 5-6 new `create_X_scenario(patient_id, encounter_id)` functions to `seed_patients.py` following the existing helper pattern. Create new inpatient-specific helpers (`make_inpatient_encounter`, `make_care_team`, `make_hourly_vitals`) and reuse existing helpers (`make_condition`, `make_medication`, `make_observation`, `make_vital`, `make_bp`). Use encounter-linked resources throughout. Idempotency via searching for existing inpatient encounters by patient + class=IMP before creating.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FR-14 | Extend seed_patients.py with inpatient encounter scenarios covering sepsis, cardiac, renal, and multi-system patients. After seeding, Medplum contains at least 5 inpatient encounters with complete Encounter + Condition + Observation + MedicationRequest + CareTeam resources. | Existing seed script pattern is clear. New helpers needed for Encounter(class=IMP), CareTeam, and hourly vital sign generation. Clinical scoring systems (NEWS2, qSOFA, SOFA, KDIGO) define which vital sign parameters must be present. Five scenarios identified: sepsis, cardiac (ACS/CHF), renal (AKI), pulmonary (PE/COPD), multi-system. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | (existing) | Async HTTP client for FHIR server | Already used by FHIRClient in handlers.py; seed script imports fhir_client |
| Python 3.12 | 3.12 | Runtime | Already in use; async/await for FHIR calls |
| datetime (stdlib) | - | ISO 8601 timestamps for encounter periods and vital sign progressions | Needed for generating hourly timestamps over 24-48h spans |
| random (stdlib) | - | Adding realistic noise to vital sign progressions | Small random variation on base values makes data look realistic |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json (stdlib) | - | JSON serialization if needed for debugging | Already available |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Inline vital progression functions | Synthea (synthetic patient generator) | Synthea generates full patient histories but is Java-based, overkill for 5-6 targeted scenarios, and hard to control specific clinical progressions |
| Manual timestamp generation | numpy/scipy for physiological models | Would add dependency for what is essentially linear interpolation with noise; stdlib random + datetime is sufficient |
| Direct fhir_client calls | FHIR transaction bundles (Bundle.type=transaction) | Bundles would be more efficient (single HTTP request) but the existing pattern uses individual creates, and Medplum transaction bundle support has quirks with reference resolution |

**Installation:**
No new packages needed. All dependencies are already installed.

## Architecture Patterns

### Recommended Script Structure
```
scripts/seed_patients.py (EXTEND existing file)
    # Existing helpers: make_patient, make_condition, make_observation, etc.
    # NEW helpers:
    #   make_inpatient_encounter(patient_id, reason, location, priority, admit_dt)
    #   make_care_team(patient_id, encounter_id, team_name, participants)
    #   generate_vital_series(patient_id, encounter_id, start_dt, hours, progression)
    #
    # NEW scenario creators:
    #   create_sepsis_scenario(patient_id) -> [(type, resource), ...]
    #   create_cardiac_scenario(patient_id) -> [(type, resource), ...]
    #   create_renal_scenario(patient_id) -> [(type, resource), ...]
    #   create_pulmonary_scenario(patient_id) -> [(type, resource), ...]
    #   create_multisystem_scenario(patient_id) -> [(type, resource), ...]
    #
    # NEW patient profiles in PATIENT_PROFILES list (or separate INPATIENT_PROFILES)
```

### Pattern 1: Inpatient Encounter with Encounter-Linked Resources
**What:** Create an Encounter(class=IMP) first, capture its ID, then create all linked resources (Conditions, Observations, MedicationRequests, CareTeam) with `encounter` references.
**When to use:** Every inpatient scenario.
**Example:**
```python
async def create_sepsis_scenario(patient_id: str) -> list[tuple[str, dict]]:
    """Sepsis scenario: UTI -> SIRS -> sepsis progression over 36 hours."""
    resources = []
    admit_dt = datetime(2026, 2, 24, 14, 0, tzinfo=timezone.utc)

    # 1. Create encounter FIRST to get encounter_id
    encounter = make_inpatient_encounter(
        patient_id, reason="Fever, altered mental status, UTI",
        location="ED Bay 4", priority="EM", admit_dt=admit_dt,
    )
    # Encounter is created separately and its ID captured before other resources
    # (see seed_inpatient_patient function pattern below)

    # 2. Conditions linked to encounter
    resources.append(("Condition", make_condition(
        patient_id, "91302008", "Sepsis", admit_dt.isoformat(),
        encounter_id=encounter_id,  # Will be populated after encounter creation
    )))

    # 3. Vitals spanning 24+ hours with progression
    vitals = generate_vital_series(patient_id, start_dt=admit_dt, hours=36,
        progression="sepsis_deterioration")
    resources.extend(vitals)

    # 4. Medications linked to encounter
    resources.append(("MedicationRequest", make_medication(
        patient_id, "82122", "Piperacillin-tazobactam",
        "4.5g IV every 6 hours", encounter_id=encounter_id,
    )))

    # 5. CareTeam
    resources.append(("CareTeam", make_care_team(
        patient_id, encounter_id, "Sepsis Care Team",
        [("Dr. Williams", "Physician"), ("RN Johnson", "Registered nurse")],
    )))

    return resources
```

### Pattern 2: Vital Sign Progression Generator
**What:** Generate a time series of vital sign observations with clinically realistic progression patterns.
**When to use:** Every inpatient scenario needs vitals spanning 24+ hours.
**Example:**
```python
def generate_vital_series(
    patient_id: str,
    encounter_id: str,
    start_dt: datetime,
    hours: int,
    base_vitals: dict,
    progression: list[dict],  # [{hour: N, deltas: {param: val}}, ...]
    interval_minutes: int = 60,
) -> list[tuple[str, dict]]:
    """Generate hourly vital signs with clinical progression.

    base_vitals: {"hr": 88, "sbp": 120, "dbp": 78, "rr": 18, "temp": 37.0, "spo2": 97}
    progression: defines changes at specific hours
    """
    resources = []
    current = dict(base_vitals)

    for minute in range(0, hours * 60, interval_minutes):
        dt = start_dt + timedelta(minutes=minute)
        hour = minute / 60

        # Apply progression changes
        for prog in progression:
            if abs(hour - prog["hour"]) < 0.5:
                for param, delta in prog["deltas"].items():
                    current[param] = current.get(param, 0) + delta

        # Add small random noise
        dt_str = dt.isoformat()

        # Heart rate
        resources.append(("Observation", make_vital(
            patient_id, "8867-4", "Heart Rate",
            round(current["hr"] + random.uniform(-2, 2), 1),
            "/min", dt_str,
        )))
        # Blood pressure
        resources.append(("Observation", make_bp(
            patient_id,
            int(current["sbp"] + random.uniform(-3, 3)),
            int(current["dbp"] + random.uniform(-2, 2)),
            dt_str,
        )))
        # Respiratory rate
        resources.append(("Observation", make_vital(
            patient_id, "9279-1", "Respiratory Rate",
            round(current["rr"] + random.uniform(-1, 1), 1),
            "/min", dt_str,
        )))
        # Temperature
        resources.append(("Observation", make_vital(
            patient_id, "8310-5", "Body Temperature",
            round(current["temp"] + random.uniform(-0.1, 0.1), 1),
            "Cel", dt_str,
        )))
        # SpO2
        resources.append(("Observation", make_vital(
            patient_id, "2708-6", "Oxygen Saturation",
            min(100, round(current["spo2"] + random.uniform(-0.5, 0.5), 1)),
            "%", dt_str,
        )))

    return resources
```

### Pattern 3: Idempotent Inpatient Seeding
**What:** Search for existing inpatient encounters for a patient before creating new ones.
**When to use:** Must be applied to prevent duplicate encounters on re-runs.
**Example:**
```python
async def find_or_create_inpatient_encounter(patient_id: str, encounter_resource: dict) -> str:
    """Search for existing inpatient encounter, or create new one."""
    reason_text = encounter_resource.get("reasonCode", [{}])[0].get("text", "")

    # Search for existing inpatient encounters for this patient
    result = await fhir_client.search("Encounter", {
        "patient": patient_id,
        "class": "IMP",
        "reason-code:text": reason_text,
    })
    entries = result.get("entry", [])

    if entries:
        encounter_id = entries[0]["resource"]["id"]
        print(f"  Found existing inpatient encounter (ID: {encounter_id})")
        return encounter_id

    # Create new encounter
    result = await fhir_client.create("Encounter", encounter_resource)
    encounter_id = result["id"]
    print(f"  Created inpatient encounter (ID: {encounter_id})")
    return encounter_id
```

### Pattern 4: Encounter-Linked Resource Helpers
**What:** Extend existing `make_condition`, `make_medication`, `make_observation` helpers to accept optional `encounter_id` parameter.
**When to use:** All inpatient resources must link to their encounter.
**Example:**
```python
# Existing make_condition signature:
# def make_condition(patient_id, code, display, onset, status, icd10_code, icd10_display)
#
# Option A: Add encounter_id parameter (preferred - backward compatible)
def make_condition(patient_id: str, code: str, display: str,
                   onset: str, status: str = "active",
                   icd10_code: str = None, icd10_display: str = None,
                   encounter_id: str = None) -> dict:
    # ... existing code ...
    if encounter_id:
        resource["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    return resource

# Same pattern for make_medication, make_observation, make_vital, make_bp
```

### Anti-Patterns to Avoid
- **Creating resources through handler functions:** The seed script must use `fhir_client.create()` directly, NOT `handle_create_inpatient_encounter()` or similar handlers. Handlers route through the approval queue, which is inappropriate for seeding.
- **Hardcoded encounter IDs:** Encounter IDs are assigned by Medplum on creation. Must create encounter first, capture ID, then use it in subsequent resources.
- **Vitals without encounter linkage:** Every inpatient Observation must include `"encounter": {"reference": f"Encounter/{encounter_id}"}` to enable the encounter timeline handler and supervisor agent queries.
- **Vitals at a single timestamp:** The success criteria explicitly requires vitals spanning 24+ hours. Single-point-in-time vitals are insufficient.
- **Non-deterministic random seed:** Use `random.seed(42)` or similar to make re-runs produce identical vital sign noise. This aids debugging and reproducibility.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| FHIR resource construction | Custom resource builder class | Extend existing `make_*` helper functions | Helpers already proven; adding encounter_id param is trivial |
| Vital sign ranges | Research all normal/abnormal ranges from scratch | Reference clinical scoring code in `agents/scoring/clinical_scores.py` | NEWS2/qSOFA/SOFA/KDIGO functions define exact thresholds for scoring -- seed data must align |
| Encounter lifecycle management | Custom state machine | Simple status field: "in-progress" for active encounters | Seed data is a snapshot, not a simulation |
| Time series generation | Complex physiological simulation engine | Linear interpolation with progression waypoints + random noise | 5-6 scenarios with known clinical patterns; don't need true physiology models |
| LOINC/SNOMED/RxNorm codes | Manual code lookups per resource | Reuse codes from existing patient definitions in seed_patients.py | The 5 outpatient patients already define dozens of correct codes for vitals, labs, conditions, and medications |

**Key insight:** The seed data is a one-time setup step, not a simulation engine. Complexity should be in the clinical accuracy of the scenarios, not in the tooling. Reuse everything that exists.

## Common Pitfalls

### Pitfall 1: Encounter-Observation Linkage Mismatch
**What goes wrong:** Observations created without `encounter` reference, or with wrong encounter ID, making `encounter_id`-based queries return empty results.
**Why it happens:** Existing outpatient observations in `seed_patients.py` do NOT include encounter references (they're standalone). Inpatient observations MUST have them.
**How to avoid:** Add `encounter_id` parameter to `make_observation` and `make_vital` helpers. Verify by searching `Observation?encounter={id}` after seeding.
**Warning signs:** `handle_get_encounter_timeline` returns no observations for seeded encounters.

### Pitfall 2: Vital Signs Not Triggering Scoring
**What goes wrong:** Seeded vitals use wrong LOINC codes or units, so the clinical scoring system can't find/parse them.
**Why it happens:** NEWS2 needs specific parameters: respiratory_rate (LOINC 9279-1), spo2 (LOINC 2708-6), systolic_bp (LOINC 8480-6 as BP component), pulse (LOINC 8867-4), temperature (LOINC 8310-5). qSOFA needs systolic_bp, respiratory_rate, GCS (LOINC 9269-2).
**How to avoid:** Use the exact LOINC codes already established in the existing `make_vital` and `make_bp` helpers. Cross-reference with `agents/scoring/clinical_scores.py` parameter names.
**Warning signs:** NEWS2/qSOFA calculations return None or unexpected scores for seeded patients.

### Pitfall 3: Idempotency Failure -- Duplicate Encounters
**What goes wrong:** Running the seed script twice creates duplicate inpatient encounters for the same patient.
**Why it happens:** Existing `find_or_create_patient` only checks patient existence by name, not encounter existence. Encounters need separate idempotency logic.
**How to avoid:** Before creating each inpatient encounter, search by `patient + class=IMP + reason-code:text`. If Medplum doesn't support `reason-code:text` search, use `patient + class=IMP` and filter client-side by reason text.
**Warning signs:** After running seed twice, duplicate encounters appear in the patient's encounter list.

### Pitfall 4: Unrealistic Vital Sign Values
**What goes wrong:** Random noise pushes values out of physiologically plausible range (e.g., SpO2 > 100%, negative heart rate, temperature below 30C without intentional hypothermia).
**Why it happens:** Adding unbounded random variation to progression values.
**How to avoid:** Clamp values to physiological bounds: HR (30-200), SBP (50-250), DBP (30-150), RR (4-60), Temp (33-42 C), SpO2 (50-100%).
**Warning signs:** Dashboard shows impossible vital sign values.

### Pitfall 5: MedicationRequest Missing Encounter Reference
**What goes wrong:** Medications created for inpatient scenarios but without encounter linkage. Phase 3 supervisor agent can't find medications associated with the encounter.
**Why it happens:** Existing `make_medication` helper doesn't include encounter reference (outpatient pattern). Must be extended.
**How to avoid:** Add `encounter_id` param to `make_medication`. All inpatient MedicationRequests must include `"encounter": {"reference": f"Encounter/{encounter_id}"}`.
**Warning signs:** `MedicationRequest?encounter={id}` returns empty bundle.

### Pitfall 6: Insufficient Lab Data for SOFA/KDIGO
**What goes wrong:** Only vitals are seeded, but SOFA needs: PaO2/FiO2, platelets, bilirubin, creatinine, GCS. KDIGO needs: baseline creatinine, current creatinine, creatinine from 48h ago.
**Why it happens:** Focus on vital signs and forgetting the lab components needed for scoring.
**How to avoid:** Each scenario must include relevant labs: CBC (platelets, WBC), BMP (creatinine, BUN), liver function (bilirubin, AST/ALT), lactate, blood cultures, troponin (cardiac), D-dimer (pulmonary), ABG (respiratory). The existing `make_observation` helper handles labs with category "laboratory".
**Warning signs:** SOFA score returns None for organ components; KDIGO can't calculate without creatinine history.

## Code Examples

### Clinical Scenario: Sepsis (UTI -> Sepsis -> Improvement)
```python
async def create_sepsis_scenario(patient_id: str, encounter_id: str) -> list[tuple[str, dict]]:
    """
    72yo female, UTI -> SIRS -> sepsis progression.
    Timeline: ED presentation (hour 0), antibiotics (hour 1), ICU transfer (hour 4),
    improvement starts (hour 12), step-down (hour 24).

    Key scoring targets:
    - qSOFA >= 2 at hour 4 (SBP <= 100, RR >= 22, altered mental status)
    - NEWS2 >= 7 (HIGH risk) at hour 4-8
    - SOFA change >= 2 from baseline at hour 4-8
    """
    resources = []
    admit_dt = datetime(2026, 2, 24, 14, 0, tzinfo=timezone.utc)

    # Conditions
    conditions = [
        ("91302008", "Sepsis", admit_dt.isoformat(), "active", "A41.9", "Sepsis, unspecified organism"),
        ("68566005", "Urinary tract infection", admit_dt.isoformat(), "active", "N39.0", "UTI, site not specified"),
        ("386661006", "Fever", admit_dt.isoformat(), "active", "R50.9", "Fever, unspecified"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(
            patient_id, code, display, onset, status, icd, icd_display,
            encounter_id=encounter_id)))

    # Vital sign progression over 36 hours
    base_vitals = {"hr": 102, "sbp": 110, "dbp": 65, "rr": 22, "temp": 38.8, "spo2": 94}
    progression = [
        # Deterioration hours 0-4
        {"hour": 2, "deltas": {"hr": 10, "sbp": -12, "rr": 4, "temp": 0.5, "spo2": -3}},
        {"hour": 4, "deltas": {"hr": 5, "sbp": -8, "rr": 2, "temp": 0.3, "spo2": -2}},
        # Peak severity hours 4-8
        {"hour": 6, "deltas": {"hr": 3, "sbp": -5, "rr": 1, "temp": 0.2, "spo2": -1}},
        # Antibiotics taking effect hours 8-12
        {"hour": 10, "deltas": {"hr": -5, "sbp": 5, "rr": -2, "temp": -0.3, "spo2": 1}},
        {"hour": 12, "deltas": {"hr": -8, "sbp": 8, "rr": -3, "temp": -0.5, "spo2": 2}},
        # Recovery hours 12-36
        {"hour": 18, "deltas": {"hr": -10, "sbp": 10, "rr": -4, "temp": -0.5, "spo2": 3}},
        {"hour": 24, "deltas": {"hr": -5, "sbp": 5, "rr": -2, "temp": -0.3, "spo2": 2}},
        {"hour": 30, "deltas": {"hr": -3, "sbp": 3, "rr": -1, "temp": -0.2, "spo2": 1}},
    ]
    vitals = generate_vital_series(patient_id, encounter_id, admit_dt, 36, base_vitals, progression)
    resources.extend(vitals)

    # Labs
    # Hour 0: Initial labs
    h0 = admit_dt.isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 18.5, "10*3/uL", h0, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.8, "mg/dL", h0, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 3.2, "mmol/L", h0, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 165, "10*3/uL", h0, ref_low=150, ref_high=400, encounter_id=encounter_id)))

    # Hour 4: Repeat labs showing deterioration
    h4 = (admit_dt + timedelta(hours=4)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 22.1, "10*3/uL", h4, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 2.4, "mg/dL", h4, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 4.8, "mmol/L", h4, ref_high=2.0, encounter_id=encounter_id)))

    # Hour 12: Improvement
    h12 = (admit_dt + timedelta(hours=12)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 15.2, "10*3/uL", h12, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.9, "mg/dL", h12, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 2.1, "mmol/L", h12, ref_high=2.0, encounter_id=encounter_id)))

    # Medications -- Hour-1 Bundle compliance
    h1 = (admit_dt + timedelta(hours=1)).isoformat()
    medications = [
        ("82122", "Piperacillin-tazobactam", "4.5g IV every 6 hours", None),
        ("313002", "Normal Saline", "30mL/kg IV bolus", None),
    ]
    for rxnorm, display, dosage, freq in medications:
        resources.append(("MedicationRequest", make_medication(
            patient_id, rxnorm, display, dosage, freq,
            encounter_id=encounter_id, authored_on=h1)))

    # CareTeam
    resources.append(("CareTeam", make_care_team(
        patient_id, encounter_id, "Sepsis Care Team",
        [("Dr. Patel", "309343006", "Physician"),
         ("RN Thompson", "224535009", "Registered nurse"),
         ("PharmD Lee", "46255001", "Pharmacist")])))

    return resources
```

### Clinical Scenario: Cardiac (ACS/STEMI)
```python
# Key vitals: tachycardia (HR 100-120), hypotension if cardiogenic shock (SBP 85-95),
# normal RR initially then tachypnea if CHF develops, normal SpO2 initially then drops
# Key labs: troponin series (rising), BNP, CBC, BMP, coagulation
# Scoring targets: NEWS2 MEDIUM->HIGH if shock develops
```

### Clinical Scenario: Renal (AKI)
```python
# Key: Creatinine progression 1.0 -> 1.5 -> 2.2 -> 3.1 (KDIGO stage 2-3)
# Key labs: creatinine series, BUN, electrolytes (hyperkalemia risk), urine output
# Base vitals: relatively stable with mild tachycardia and hypertension
# Scoring targets: KDIGO staging, SOFA renal component
```

### Clinical Scenario: Pulmonary (PE/COPD exacerbation)
```python
# Key vitals: tachypnea (RR 24-32), hypoxia (SpO2 85-92), tachycardia (HR 110-130)
# Key labs: D-dimer, ABG (low PaO2, respiratory alkalosis), troponin (right heart strain)
# Scoring targets: NEWS2 HIGH (SpO2 + RR), qSOFA >= 2 if hypotensive
```

### Clinical Scenario: Multi-System
```python
# Combination: sepsis + AKI + respiratory failure
# Most complex scenario for testing multi-agent coordination
# Key: overlapping deterioration patterns triggering multiple scoring thresholds
```

### Vital Sign LOINC Codes (Critical Reference)
```python
# These LOINC codes MUST be used -- they align with existing helpers and scoring expectations
VITAL_LOINC = {
    "heart_rate":        ("8867-4", "Heart Rate", "/min"),
    "blood_pressure":    ("85354-9", "Blood Pressure", "mmHg"),  # BP is a composite
    "sbp_component":     ("8480-6", "Systolic Blood Pressure", "mm[Hg]"),
    "dbp_component":     ("8462-4", "Diastolic Blood Pressure", "mm[Hg]"),
    "respiratory_rate":  ("9279-1", "Respiratory Rate", "/min"),
    "temperature":       ("8310-5", "Body Temperature", "Cel"),
    "spo2":              ("2708-6", "Oxygen Saturation", "%"),
    "body_weight":       ("29463-7", "Body Weight", "kg"),
    "body_height":       ("8302-2", "Body Height", "cm"),
    "bmi":               ("39156-5", "BMI", "kg/m2"),
    "gcs":               ("9269-2", "Glasgow Coma Scale", "{score}"),
}

# Lab LOINC codes for scoring systems
LAB_LOINC = {
    "wbc":          ("6690-2", "WBC", "10*3/uL"),
    "hemoglobin":   ("718-7", "Hemoglobin", "g/dL"),
    "platelets":    ("777-3", "Platelets", "10*3/uL"),
    "creatinine":   ("2160-0", "Creatinine", "mg/dL"),
    "bun":          ("3094-0", "BUN", "mg/dL"),
    "sodium":       ("2951-2", "Sodium", "mmol/L"),
    "potassium":    ("2823-3", "Potassium", "mmol/L"),
    "lactate":      ("32693-4", "Lactate", "mmol/L"),
    "bilirubin":    ("1975-2", "Total Bilirubin", "mg/dL"),
    "troponin":     ("49563-0", "Troponin I", "ng/mL"),
    "bnp":          ("30934-4", "BNP", "pg/mL"),
    "d_dimer":      ("48065-7", "D-dimer", "ng/mL"),
    "ast":          ("1920-8", "AST", "U/L"),
    "alt":          ("1742-6", "ALT", "U/L"),
    "egfr":         ("33914-3", "eGFR", "mL/min/1.73m2"),
    "procalcitonin":("75241-0", "Procalcitonin", "ng/mL"),
}
```

### New Helper: make_inpatient_encounter
```python
def make_inpatient_encounter(patient_id: str, reason: str, location: str,
                              priority: str = "EM", admit_dt: datetime = None,
                              admit_source: str = "emd") -> dict:
    """Create an inpatient encounter resource (class=IMP)."""
    if admit_dt is None:
        admit_dt = datetime.now(timezone.utc)
    dt_str = admit_dt.isoformat()

    return {
        "resourceType": "Encounter",
        "status": "in-progress",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "IMP",
            "display": "inpatient encounter",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": dt_str},
        "reasonCode": [{"text": reason}],
        "hospitalization": {
            "admitSource": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/admit-source",
                    "code": admit_source,
                }]
            }
        },
        "location": [{
            "location": {"display": location},
            "status": "active",
            "period": {"start": dt_str},
        }],
        "priority": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
                "code": priority,
            }]
        },
    }
```

### New Helper: make_care_team
```python
def make_care_team(patient_id: str, encounter_id: str, name: str,
                    participants: list[tuple[str, str, str]]) -> dict:
    """Create a CareTeam resource.

    participants: [(name, snomed_code, role_display), ...]
    """
    return {
        "resourceType": "CareTeam",
        "status": "active",
        "name": name,
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "participant": [
            {
                "role": [{"coding": [{"system": "http://snomed.info/sct", "code": code, "display": display}]}],
                "member": {"display": member_name},
            }
            for member_name, code, display in participants
        ],
    }
```

### Seeding Flow for Inpatient Encounters
```python
async def seed_inpatient_patient(profile: dict) -> dict:
    """Seed an inpatient patient with encounter and linked resources."""
    given = profile["given"]
    family = profile["family"]
    scenario_creator = profile["scenario_creator"]

    # 1. Find or create patient
    patient_id = await find_or_create_patient(profile)

    # 2. Create encounter FIRST (need encounter_id for linked resources)
    encounter_resource = profile["encounter_resource"](patient_id)
    encounter_id = await find_or_create_inpatient_encounter(patient_id, encounter_resource)

    # 3. Generate linked resources with encounter_id
    resources = await scenario_creator(patient_id, encounter_id)

    # 4. Create resources
    created = 0
    errors = 0
    for resource_type, resource in resources:
        try:
            await fhir_client.create(resource_type, resource)
            created += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  ERROR creating {resource_type}: {e}")

    return {"patient_id": patient_id, "encounter_id": encounter_id,
            "name": f"{given} {family}", "created": created, "errors": errors}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static seed data (single point in time) | Time-series seed data with progression patterns | Current best practice | Enables testing of trending/scoring systems |
| Encounter without linked resources | Encounter-centric resource bundles (all resources link back) | FHIR R4 convention | Required for encounter timeline queries |
| Separate seed scripts per resource type | Single script with scenario-based creation | Project convention | Matches existing seed_patients.py pattern |

**Deprecated/outdated:**
- Using FHIR transaction bundles for seeding: While technically valid, the existing codebase uses individual `fhir_client.create()` calls. Mixing patterns would create inconsistency.
- Synthea-generated data: Too generic for the specific clinical scenarios needed by the supervisor agent.

## Open Questions

1. **Existing patients vs. new patients for inpatient encounters**
   - What we know: 5 outpatient patients exist (John Smith, Maria Garcia, Robert Johnson, Emily Chen, James Wilson). Some have conditions that could warrant hospitalization (e.g., Robert Johnson has CKD, Maria Garcia has cardiopulmonary issues).
   - What's unclear: Should inpatient encounters be added to existing patients (extending their story) or should new patients be created specifically for inpatient scenarios?
   - Recommendation: Create new patients for inpatient scenarios. This avoids conflict with existing outpatient data and makes scenarios self-contained. Existing patients can have inpatient encounters added later if needed. New patients get MRN-20001 through MRN-20006 to distinguish from outpatient cohort (MRN-10001 through MRN-10005).

2. **Encounter admission timestamps: static vs. relative to now**
   - What we know: Existing outpatient data uses static dates (e.g., "2025-12-01"). Inpatient encounters should feel "current" for dashboard testing.
   - What's unclear: Should admission times be relative to `datetime.now()` (always recent) or static dates?
   - Recommendation: Use static dates anchored to a recent date (e.g., 2026-02-24 for the earliest admission). This is deterministic, reproducible, and close enough to "now" for dashboard display. The vital sign progression timestamps are derived from the admission time, so everything stays consistent.

3. **How many resources per scenario (resource count budget)**
   - What we know: Vital signs at hourly intervals for 36 hours = 36 * 5 vital parameters = 180 Observation resources per scenario, plus labs, conditions, meds, care team.
   - What's unclear: Will 200+ resources per scenario cause slow seeding or Medplum performance issues?
   - Recommendation: Start with hourly vitals. If seeding is too slow, switch to every-2-hour vitals (90 Observations per scenario). Total across 5 scenarios: ~1,000-1,200 resources. The existing seed script creates ~200-300 resources for 5 patients without issues, so ~1,200 should be manageable.

4. **Medplum search parameter support for idempotency**
   - What we know: Need to search Encounter by `patient + class + reason-code:text` for idempotency. Medplum supports most FHIR R4 search parameters.
   - What's unclear: Whether `reason-code:text` modifier works in Medplum search.
   - Recommendation: If `reason-code:text` search doesn't work, fall back to `patient + class=IMP` and filter results client-side by checking `reasonCode[0].text`. This is safe because each patient will have at most 1-2 inpatient encounters.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `scripts/seed_patients.py` (1,257 lines) -- complete seed pattern analysis including helpers, idempotency, and patient profiles
- Existing codebase: `fhir-mcp-server/src/handlers.py` -- FHIRClient class, make_encounter helper, inpatient encounter resource structure from Phase 1
- Existing codebase: `agents/scoring/clinical_scores.py` -- NEWS2, qSOFA, SOFA, KDIGO parameter requirements and thresholds
- FHIR R4 specification -- Encounter(class=IMP), Observation, Condition, MedicationRequest, CareTeam resource structures

### Secondary (MEDIUM confidence)
- Vital sign progression patterns -- based on standard clinical literature for sepsis, ACS, AKI, PE/COPD trajectories
- LOINC codes -- verified against existing seed_patients.py usage and standard LOINC database

### Tertiary (LOW confidence)
- Medplum search parameter support for encounter idempotency (reason-code:text modifier) -- needs runtime verification
- Resource count performance at ~1,200 resources -- extrapolated from existing ~300 resource seeding; should be tested

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new dependencies, pure extension of existing seed script pattern
- Architecture: HIGH - pattern is established in seed_patients.py; encounter-linked resources follow FHIR R4 conventions
- Pitfalls: HIGH - identified from direct code analysis of existing helpers and scoring system requirements
- Clinical accuracy: MEDIUM - progression patterns based on standard clinical knowledge; not validated against MIMIC-IV reference data

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable -- seed data patterns and FHIR R4 conventions are settled)
