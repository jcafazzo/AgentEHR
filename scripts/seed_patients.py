#!/usr/bin/env python3
"""
Seed Medplum FHIR Server with Rich Synthetic Patient Data

Creates 5 patients with comprehensive, realistic clinical histories:
1. John Smith (56M) - Metabolic Syndrome
2. Maria Garcia (68F) - Cardiopulmonary
3. Robert Johnson (45M) - Chronic Kidney Disease
4. Emily Chen (72F) - Autoimmune/Endocrine
5. James Wilson (62M) - Post-Cardiac Event

Idempotent: searches for existing patients before creating.
Uses proper FHIR R4 with SNOMED CT, LOINC, RxNorm, CVX codes.
"""

import asyncio
import base64
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Add FHIR MCP server source to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "fhir-mcp-server" / "src"))

from handlers import fhir_client

random.seed(42)  # Deterministic noise for reproducible vital sign data


# =============================================================================
# Helper Functions
# =============================================================================

def make_patient(given: str, family: str, gender: str, birth_date: str,
                 phone: str = None, address: dict = None, mrn: str = None) -> dict:
    resource = {
        "resourceType": "Patient",
        "active": True,
        "name": [{"given": [given], "family": family, "use": "official"}],
        "gender": gender,
        "birthDate": birth_date,
    }
    if phone:
        resource["telecom"] = [{"system": "phone", "value": phone, "use": "home"}]
    if address:
        resource["address"] = [address]
    if mrn:
        resource["identifier"] = [
            {"system": "http://agentehr.local/mrn", "value": mrn}
        ]
    return resource


def make_condition(patient_id: str, code: str, display: str,
                   onset: str, status: str = "active",
                   icd10_code: str = None, icd10_display: str = None,
                   encounter_id: str = None) -> dict:
    coding = [{"system": "http://snomed.info/sct", "code": code, "display": display}]
    if icd10_code:
        coding.append({"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": icd10_code, "display": icd10_display or display})
    resource = {
        "resourceType": "Condition",
        "clinicalStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": status}]
        },
        "verificationStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed"}]
        },
        "category": [
            {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "problem-list-item", "display": "Problem List Item"}]}
        ],
        "code": {"coding": coding, "text": display},
        "subject": {"reference": f"Patient/{patient_id}"},
        "onsetDateTime": onset,
    }
    if encounter_id:
        resource["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    return resource


def make_medication(patient_id: str, rxnorm_code: str, display: str,
                    dosage_text: str, frequency: str = None,
                    status: str = "active",
                    encounter_id: str = None, authored_on: str = None) -> dict:
    timing = {}
    if frequency:
        freq_map = {
            "daily": {"frequency": 1, "period": 1, "periodUnit": "d"},
            "BID": {"frequency": 2, "period": 1, "periodUnit": "d"},
            "TID": {"frequency": 3, "period": 1, "periodUnit": "d"},
            "weekly": {"frequency": 1, "period": 1, "periodUnit": "wk"},
            "biweekly": {"frequency": 1, "period": 2, "periodUnit": "wk"},
            "PRN": {},
        }
        if frequency in freq_map and freq_map[frequency]:
            timing = {"repeat": freq_map[frequency]}

    resource = {
        "resourceType": "MedicationRequest",
        "status": status,
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": rxnorm_code, "display": display}],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": authored_on if authored_on else str(date.today()),
        "dosageInstruction": [
            {
                "text": dosage_text,
                "timing": timing if timing else None,
            }
        ],
    }
    # Clean up None values in dosageInstruction
    resource["dosageInstruction"] = [
        {k: v for k, v in d.items() if v is not None}
        for d in resource["dosageInstruction"]
    ]
    if encounter_id:
        resource["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    return resource


def make_allergy(patient_id: str, substance: str, substance_code: str = None,
                 reaction: str = None, severity: str = "moderate",
                 criticality: str = "low", category: str = "medication",
                 code_system: str = "http://www.nlm.nih.gov/research/umls/rxnorm") -> dict:
    coding = []
    if substance_code:
        coding.append({"system": code_system, "code": substance_code, "display": substance})
    resource = {
        "resourceType": "AllergyIntolerance",
        "clinicalStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]
        },
        "verificationStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", "code": "confirmed"}]
        },
        "type": "allergy",
        "category": [category],
        "criticality": criticality,
        "code": {"coding": coding, "text": substance} if coding else {"text": substance},
        "patient": {"reference": f"Patient/{patient_id}"},
    }
    if reaction:
        resource["reaction"] = [{
            "manifestation": [{"coding": [{"system": "http://snomed.info/sct", "display": reaction}], "text": reaction}],
            "severity": severity,
        }]
    return resource


def make_observation(patient_id: str, loinc_code: str, display: str,
                     value: float, unit: str, date_str: str,
                     category_code: str = "laboratory",
                     ref_low: float = None, ref_high: float = None,
                     value_string: str = None,
                     encounter_id: str = None) -> dict:
    resource = {
        "resourceType": "Observation",
        "status": "final",
        "category": [
            {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": category_code, "display": category_code.replace("-", " ").title()}]}
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": loinc_code, "display": display}],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": date_str,
    }
    if value_string:
        resource["valueString"] = value_string
    elif value is not None:
        resource["valueQuantity"] = {
            "value": value,
            "unit": unit,
            "system": "http://unitsofmeasure.org",
            "code": unit,
        }
    if ref_low is not None or ref_high is not None:
        ref_range = {}
        if ref_low is not None:
            ref_range["low"] = {"value": ref_low, "unit": unit}
        if ref_high is not None:
            ref_range["high"] = {"value": ref_high, "unit": unit}
        resource["referenceRange"] = [ref_range]
    if encounter_id:
        resource["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    return resource


def make_vital(patient_id: str, loinc_code: str, display: str,
               value: float, unit: str, date_str: str,
               component: list = None,
               encounter_id: str = None) -> dict:
    resource = {
        "resourceType": "Observation",
        "status": "final",
        "category": [
            {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs", "display": "Vital Signs"}]}
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": loinc_code, "display": display}],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": date_str,
    }
    if component:
        resource["component"] = component
    elif value is not None:
        resource["valueQuantity"] = {
            "value": value,
            "unit": unit,
            "system": "http://unitsofmeasure.org",
            "code": unit,
        }
    if encounter_id:
        resource["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    return resource


def make_bp(patient_id: str, systolic: int, diastolic: int, date_str: str,
            encounter_id: str = None) -> dict:
    return make_vital(
        patient_id, "85354-9", "Blood Pressure", None, "mmHg", date_str,
        component=[
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic Blood Pressure"}]},
                "valueQuantity": {"value": systolic, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic Blood Pressure"}]},
                "valueQuantity": {"value": diastolic, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
            },
        ],
        encounter_id=encounter_id,
    )


def make_immunization(patient_id: str, cvx_code: str, vaccine_name: str,
                      date_str: str, status: str = "completed") -> dict:
    return {
        "resourceType": "Immunization",
        "status": status,
        "vaccineCode": {
            "coding": [{"system": "http://hl7.org/fhir/sid/cvx", "code": cvx_code, "display": vaccine_name}],
            "text": vaccine_name,
        },
        "patient": {"reference": f"Patient/{patient_id}"},
        "occurrenceDateTime": date_str,
    }


def make_procedure(patient_id: str, snomed_code: str, display: str,
                   date_str: str, cpt_code: str = None, outcome: str = None) -> dict:
    coding = [{"system": "http://snomed.info/sct", "code": snomed_code, "display": display}]
    if cpt_code:
        coding.append({"system": "http://www.ama-assn.org/go/cpt", "code": cpt_code, "display": display})
    resource = {
        "resourceType": "Procedure",
        "status": "completed",
        "code": {"coding": coding, "text": display},
        "subject": {"reference": f"Patient/{patient_id}"},
        "performedDateTime": date_str,
    }
    if outcome:
        resource["outcome"] = {"text": outcome}
    return resource


def make_encounter(patient_id: str, enc_type: str, date_str: str,
                   reason: str = None, status: str = "finished",
                   enc_class: str = "AMB") -> dict:
    class_map = {
        "AMB": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"},
        "EMER": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER", "display": "emergency"},
        "IMP": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient encounter"},
    }
    resource = {
        "resourceType": "Encounter",
        "status": status,
        "class": class_map.get(enc_class, class_map["AMB"]),
        "type": [{"coding": [{"system": "http://snomed.info/sct", "display": enc_type}], "text": enc_type}],
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": date_str},
    }
    if reason:
        resource["reasonCode"] = [{"text": reason}]
    return resource


def make_document(patient_id: str, title: str, content_text: str,
                  date_str: str, doc_type: str = "Clinical Note") -> dict:
    encoded = base64.b64encode(content_text.encode("utf-8")).decode("ascii")
    return {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {"coding": [{"system": "http://loinc.org", "code": "11506-3", "display": doc_type}], "text": doc_type},
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": f"{date_str}T12:00:00Z",
        "description": title,
        "content": [{
            "attachment": {
                "contentType": "text/plain",
                "data": encoded,
                "title": title,
            }
        }],
    }


# =============================================================================
# Inpatient Helper Functions
# =============================================================================

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


def make_care_team(patient_id: str, encounter_id: str, name: str,
                    participants: list[tuple[str, str, str]]) -> dict:
    """Create a CareTeam resource.

    participants: [(member_name, snomed_code, role_display), ...]
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


def generate_vital_series(
    patient_id: str,
    encounter_id: str,
    start_dt: datetime,
    hours: int,
    base_vitals: dict,
    progression: list[dict],
    interval_minutes: int = 60,
) -> list[tuple[str, dict]]:
    """Generate hourly vital signs with clinical progression.

    base_vitals: {"hr": 88, "sbp": 120, "dbp": 78, "rr": 18, "temp": 37.0, "spo2": 97}
    progression: [{"hour": N, "deltas": {"param": val}}, ...]

    Returns list of (resource_type, resource_dict) tuples.
    """
    resources = []
    current = dict(base_vitals)

    # Physiological clamp bounds
    clamps = {
        "hr": (30, 200),
        "sbp": (50, 250),
        "dbp": (30, 150),
        "rr": (4, 60),
        "temp": (33, 42),
        "spo2": (50, 100),
    }

    for minute in range(0, hours * 60, interval_minutes):
        dt = start_dt + timedelta(minutes=minute)
        hour = minute / 60

        # Apply progression changes
        for prog in progression:
            if abs(hour - prog["hour"]) < 0.5:
                for param, delta in prog["deltas"].items():
                    current[param] = current.get(param, 0) + delta

        # Clamp to physiological bounds
        for param, (lo, hi) in clamps.items():
            if param in current:
                current[param] = max(lo, min(hi, current[param]))

        dt_str = dt.isoformat()

        # Heart rate
        hr_val = round(max(clamps["hr"][0], min(clamps["hr"][1], current["hr"] + random.uniform(-2, 2))), 1)
        resources.append(("Observation", make_vital(
            patient_id, "8867-4", "Heart Rate",
            hr_val, "/min", dt_str,
            encounter_id=encounter_id,
        )))

        # Blood pressure
        sbp_val = int(max(clamps["sbp"][0], min(clamps["sbp"][1], current["sbp"] + random.uniform(-3, 3))))
        dbp_val = int(max(clamps["dbp"][0], min(clamps["dbp"][1], current["dbp"] + random.uniform(-2, 2))))
        resources.append(("Observation", make_bp(
            patient_id, sbp_val, dbp_val, dt_str,
            encounter_id=encounter_id,
        )))

        # Respiratory rate
        rr_val = round(max(clamps["rr"][0], min(clamps["rr"][1], current["rr"] + random.uniform(-1, 1))), 1)
        resources.append(("Observation", make_vital(
            patient_id, "9279-1", "Respiratory Rate",
            rr_val, "/min", dt_str,
            encounter_id=encounter_id,
        )))

        # Temperature
        temp_val = round(max(clamps["temp"][0], min(clamps["temp"][1], current["temp"] + random.uniform(-0.1, 0.1))), 1)
        resources.append(("Observation", make_vital(
            patient_id, "8310-5", "Body Temperature",
            temp_val, "Cel", dt_str,
            encounter_id=encounter_id,
        )))

        # SpO2
        spo2_val = round(max(clamps["spo2"][0], min(clamps["spo2"][1], current["spo2"] + random.uniform(-0.5, 0.5))), 1)
        resources.append(("Observation", make_vital(
            patient_id, "2708-6", "Oxygen Saturation",
            spo2_val, "%", dt_str,
            encounter_id=encounter_id,
        )))

    return resources


async def find_or_create_inpatient_encounter(patient_id: str, encounter_resource: dict) -> str:
    """Search for existing inpatient encounter, or create new one."""
    reason_text = encounter_resource.get("reasonCode", [{}])[0].get("text", "")

    # Search for existing inpatient encounters for this patient
    result = await fhir_client.search("Encounter", {
        "patient": patient_id,
        "class": "IMP",
    })
    entries = result.get("entry", [])

    # Filter client-side by matching reason text
    if entries:
        for entry in entries:
            resource = entry["resource"]
            existing_reason = ""
            if resource.get("reasonCode"):
                existing_reason = resource["reasonCode"][0].get("text", "")
            if existing_reason == reason_text:
                encounter_id = resource["id"]
                print(f"  Found existing inpatient encounter (ID: {encounter_id})")
                return encounter_id

    # Create new encounter
    result = await fhir_client.create("Encounter", encounter_resource)
    encounter_id = result["id"]
    print(f"  Created inpatient encounter (ID: {encounter_id})")
    return encounter_id


async def seed_inpatient_patient(profile: dict) -> dict:
    """Seed an inpatient patient with encounter and linked resources."""
    given = profile["given"]
    family = profile["family"]

    print(f"\n{'='*60}")
    print(f"Seeding Inpatient: {given} {family}")
    print(f"{'='*60}")

    # 1. Find or create patient
    patient_id = await find_or_create_patient(profile)

    # 2. Create encounter FIRST (need encounter_id for linked resources)
    encounter_resource = profile["encounter_builder"](patient_id)
    encounter_id = await find_or_create_inpatient_encounter(patient_id, encounter_resource)

    # 3. Generate linked resources with encounter_id
    admit_dt = profile.get("admit_dt")
    resources = await profile["scenario_creator"](patient_id, encounter_id, admit_dt=admit_dt)
    print(f"  Generating {len(resources)} clinical resources...")

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

    print(f"  Created: {created}/{len(resources)} resources ({errors} errors)")
    return {"patient_id": patient_id, "encounter_id": encounter_id,
            "name": f"{given} {family}", "created": created, "errors": errors}


# =============================================================================
# Inpatient Scenario Creators
# =============================================================================

async def create_sepsis_scenario(patient_id: str, encounter_id: str, admit_dt: datetime = None) -> list[tuple[str, dict]]:
    """
    72yo female, UTI -> SIRS -> sepsis progression over 36 hours.
    Timeline: ED presentation (hour 0), antibiotics (hour 1), ICU transfer (hour 4),
    peak severity (hour 6-8), improvement starts (hour 12), step-down (hour 24).

    Key scoring targets:
    - qSOFA >= 2 at hour 4 (SBP <= 100, RR >= 22, altered mental status)
    - NEWS2 >= 7 (HIGH risk) at hour 4-8
    - SOFA change >= 2 from baseline at hour 4-8
    """
    resources = []
    if admit_dt is None:
        admit_dt = datetime(2026, 2, 24, 14, 0, tzinfo=timezone.utc)

    # --- Conditions (all linked to encounter) ---
    conditions = [
        ("91302008", "Sepsis", admit_dt.isoformat(), "active", "A41.9", "Sepsis, unspecified organism"),
        ("68566005", "Urinary tract infection", admit_dt.isoformat(), "active", "N39.0", "UTI, site not specified"),
        ("386661006", "Fever", admit_dt.isoformat(), "active", "R50.9", "Fever, unspecified"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(
            patient_id, code, display, onset, status, icd, icd_display,
            encounter_id=encounter_id)))

    # --- Vital sign progression over 36 hours ---
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

    # --- Labs ---
    # Hour 0: Initial labs
    h0 = admit_dt.isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 18.5, "10*3/uL", h0, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.8, "mg/dL", h0, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 3.2, "mmol/L", h0, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 165, "10*3/uL", h0, ref_low=150, ref_high=400, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "1975-2", "Total Bilirubin", 1.2, "mg/dL", h0, ref_high=1.2, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "75241-0", "Procalcitonin", 8.5, "ng/mL", h0, ref_high=0.5, encounter_id=encounter_id)))

    # Hour 4: Repeat labs showing deterioration
    h4 = (admit_dt + timedelta(hours=4)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 22.1, "10*3/uL", h4, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 2.4, "mg/dL", h4, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 4.8, "mmol/L", h4, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 130, "10*3/uL", h4, ref_low=150, ref_high=400, encounter_id=encounter_id)))

    # Hour 12: Improvement
    h12 = (admit_dt + timedelta(hours=12)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 15.2, "10*3/uL", h12, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.9, "mg/dL", h12, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 2.1, "mmol/L", h12, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 155, "10*3/uL", h12, ref_low=150, ref_high=400, encounter_id=encounter_id)))

    # Hour 24: Near-resolution
    h24 = (admit_dt + timedelta(hours=24)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 10.5, "10*3/uL", h24, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.4, "mg/dL", h24, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 1.5, "mmol/L", h24, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 175, "10*3/uL", h24, ref_low=150, ref_high=400, encounter_id=encounter_id)))

    # --- Medications ---
    h1 = (admit_dt + timedelta(hours=1)).isoformat()
    resources.append(("MedicationRequest", make_medication(
        patient_id, "82122", "Piperacillin-tazobactam",
        "4.5g IV every 6 hours", None,
        encounter_id=encounter_id, authored_on=h1)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "313002", "Normal Saline",
        "30mL/kg IV bolus", None,
        encounter_id=encounter_id, authored_on=h1)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "11124", "Vancomycin",
        "25mg/kg IV loading dose", None,
        encounter_id=encounter_id, authored_on=h1)))
    h4_med = (admit_dt + timedelta(hours=4)).isoformat()
    resources.append(("MedicationRequest", make_medication(
        patient_id, "7512", "Norepinephrine",
        "0.1mcg/kg/min titrate to MAP >65", None,
        encounter_id=encounter_id, authored_on=h4_med)))

    # --- CareTeam ---
    resources.append(("CareTeam", make_care_team(
        patient_id, encounter_id, "Sepsis Care Team",
        [("Dr. Patel", "309343006", "Physician"),
         ("RN Thompson", "224535009", "Registered nurse"),
         ("PharmD Lee", "46255001", "Pharmacist")])))

    return resources


async def create_cardiac_scenario(patient_id: str, encounter_id: str, admit_dt: datetime = None) -> list[tuple[str, dict]]:
    """
    58yo male presenting with acute STEMI.
    Timeline: Chest pain onset (hour 0), cath lab activation (hour 1),
    PCI (hour 2), CCU admission (hour 3), stable post-PCI (hour 12-24).

    Key scoring targets:
    - NEWS2 MEDIUM->HIGH if cardiogenic shock develops
    - Troponin series: rising to peak at hour 6, then declining
    """
    resources = []
    if admit_dt is None:
        admit_dt = datetime(2026, 2, 25, 2, 30, tzinfo=timezone.utc)

    # --- Conditions (all linked to encounter) ---
    conditions = [
        ("401303003", "ST elevation myocardial infarction", admit_dt.isoformat(), "active", "I21.0", "Acute transmural MI of anterior wall"),
        ("394659003", "Acute coronary syndrome", admit_dt.isoformat(), "active", "I24.9", "Acute ischemic heart disease, unspecified"),
        ("89138009", "Cardiogenic shock", admit_dt.isoformat(), "active", "R57.0", "Cardiogenic shock"),
        ("55822004", "Hyperlipidemia", "2020-05-15", "active", "E78.5", "Hyperlipidemia, unspecified"),
        ("38341003", "Essential hypertension", "2018-03-10", "active", "I10", "Essential hypertension"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(
            patient_id, code, display, onset, status, icd, icd_display,
            encounter_id=encounter_id)))

    # --- Vital sign progression over 24 hours ---
    base_vitals = {"hr": 105, "sbp": 95, "dbp": 60, "rr": 20, "temp": 37.2, "spo2": 95}
    progression = [
        # Pre-PCI deterioration
        {"hour": 1, "deltas": {"hr": 10, "sbp": -8, "rr": 2, "spo2": -2}},
        # Post-PCI improvement
        {"hour": 3, "deltas": {"hr": -5, "sbp": 8, "rr": -1, "spo2": 1}},
        {"hour": 6, "deltas": {"hr": -8, "sbp": 10, "rr": -2, "spo2": 2}},
        {"hour": 12, "deltas": {"hr": -10, "sbp": 8, "rr": -3, "spo2": 2}},
        {"hour": 18, "deltas": {"hr": -5, "sbp": 5, "rr": -1, "spo2": 1}},
        {"hour": 24, "deltas": {"hr": -3, "sbp": 3, "rr": -1, "spo2": 1}},
    ]
    vitals = generate_vital_series(patient_id, encounter_id, admit_dt, 24, base_vitals, progression)
    resources.extend(vitals)

    # --- Labs ---
    # Hour 0: Initial labs
    h0 = admit_dt.isoformat()
    resources.append(("Observation", make_observation(patient_id, "49563-0", "Troponin I", 12.5, "ng/mL", h0, ref_high=0.04, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "30934-4", "BNP", 450, "pg/mL", h0, ref_high=100, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.1, "mg/dL", h0, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 4.5, "mmol/L", h0, ref_low=3.5, ref_high=5.1, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 11.2, "10*3/uL", h0, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "718-7", "Hemoglobin", 13.5, "g/dL", h0, ref_low=13.5, ref_high=17.5, encounter_id=encounter_id)))

    # Hour 3: Post-PCI labs
    h3 = (admit_dt + timedelta(hours=3)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "49563-0", "Troponin I", 28.3, "ng/mL", h3, ref_high=0.04, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 2.8, "mmol/L", h3, ref_high=2.0, encounter_id=encounter_id)))

    # Hour 6: Peak troponin
    h6 = (admit_dt + timedelta(hours=6)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "49563-0", "Troponin I", 45.2, "ng/mL", h6, ref_high=0.04, encounter_id=encounter_id)))

    # Hour 12: Declining troponin
    h12 = (admit_dt + timedelta(hours=12)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "49563-0", "Troponin I", 32.1, "ng/mL", h12, ref_high=0.04, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "30934-4", "BNP", 380, "pg/mL", h12, ref_high=100, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.0, "mg/dL", h12, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))

    # Hour 24: Further decline
    h24 = (admit_dt + timedelta(hours=24)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "49563-0", "Troponin I", 15.5, "ng/mL", h24, ref_high=0.04, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "30934-4", "BNP", 290, "pg/mL", h24, ref_high=100, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 0.9, "mg/dL", h24, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))

    # --- Medications ---
    h0_med = admit_dt.isoformat()
    resources.append(("MedicationRequest", make_medication(
        patient_id, "243670", "Aspirin",
        "325mg by mouth stat", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "32968", "Clopidogrel",
        "600mg loading then 75mg daily", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "5224", "Heparin",
        "IV bolus per protocol", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "259255", "Atorvastatin",
        "80mg by mouth daily", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    h6_med = (admit_dt + timedelta(hours=6)).isoformat()
    resources.append(("MedicationRequest", make_medication(
        patient_id, "866924", "Metoprolol",
        "25mg by mouth twice daily", "BID",
        encounter_id=encounter_id, authored_on=h6_med)))
    h12_med = (admit_dt + timedelta(hours=12)).isoformat()
    resources.append(("MedicationRequest", make_medication(
        patient_id, "314076", "Lisinopril",
        "5mg by mouth daily", "daily",
        encounter_id=encounter_id, authored_on=h12_med)))

    # --- CareTeam ---
    resources.append(("CareTeam", make_care_team(
        patient_id, encounter_id, "Cardiac Care Team",
        [("Dr. Rodriguez", "309343006", "Physician"),
         ("Dr. Kim", "17561000", "Cardiologist"),
         ("RN Adams", "224535009", "Registered nurse")])))

    return resources


async def create_renal_scenario(patient_id: str, encounter_id: str, admit_dt: datetime = None) -> list[tuple[str, dict]]:
    """
    67yo male with CKD baseline, admitted with AKI from dehydration + NSAID use.
    Creatinine progression 1.2 (baseline) -> 1.8 -> 2.6 -> 3.4 (peak, KDIGO stage 3)
    -> 2.8 -> 2.1 (recovering). 48 hours total.

    Key scoring targets:
    - KDIGO Stage 3 at hour 16 (creatinine 3.4, >3x baseline)
    - Hyperkalemia requiring treatment at hour 16 (K+ 5.9)
    """
    resources = []
    if admit_dt is None:
        admit_dt = datetime(2026, 2, 24, 8, 0, tzinfo=timezone.utc)

    # --- Conditions (all linked to encounter) ---
    conditions = [
        ("14669001", "Acute kidney injury", admit_dt.isoformat(), "active", "N17.9", "Acute kidney failure, unspecified"),
        ("433144002", "Chronic kidney disease stage 3", admit_dt.isoformat(), "active", "N18.3", "Chronic kidney disease, stage 3"),
        ("34095006", "Dehydration", admit_dt.isoformat(), "active", "E86.0", "Dehydration"),
        ("38341003", "Essential hypertension", "2018-06-10", "active", "I10", "Essential hypertension"),
        ("44054006", "Type 2 diabetes mellitus", "2019-03-20", "active", "E11.9", "Type 2 diabetes mellitus"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(
            patient_id, code, display, onset, status, icd, icd_display,
            encounter_id=encounter_id)))

    # --- Vital sign progression over 48 hours ---
    base_vitals = {"hr": 88, "sbp": 148, "dbp": 92, "rr": 18, "temp": 37.1, "spo2": 97}
    progression = [
        {"hour": 6, "deltas": {"hr": 5, "sbp": 8}},
        {"hour": 12, "deltas": {"hr": 8, "sbp": 12, "rr": 2}},
        {"hour": 24, "deltas": {"hr": -3, "sbp": -5, "rr": -1}},
        {"hour": 36, "deltas": {"hr": -5, "sbp": -8, "rr": -1}},
        {"hour": 48, "deltas": {"hr": -3, "sbp": -5}},
    ]
    vitals = generate_vital_series(patient_id, encounter_id, admit_dt, 48, base_vitals, progression)
    resources.extend(vitals)

    # --- Labs (creatinine series is the key data for KDIGO staging) ---
    # Hour 0: Baseline
    h0 = admit_dt.isoformat()
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.8, "mg/dL", h0, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "3094-0", "BUN", 32, "mg/dL", h0, ref_low=7, ref_high=20, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 5.2, "mmol/L", h0, ref_low=3.5, ref_high=5.1, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2951-2", "Sodium", 134, "mmol/L", h0, ref_low=136, ref_high=145, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "33914-3", "eGFR", 38, "mL/min/1.73m2", h0, ref_low=60, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 9.5, "10*3/uL", h0, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "718-7", "Hemoglobin", 11.8, "g/dL", h0, ref_low=13.5, ref_high=17.5, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2777-1", "Phosphorus", 5.5, "mg/dL", h0, ref_low=2.5, ref_high=4.5, encounter_id=encounter_id)))

    # Hour 8: Worsening
    h8 = (admit_dt + timedelta(hours=8)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 2.6, "mg/dL", h8, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "3094-0", "BUN", 45, "mg/dL", h8, ref_low=7, ref_high=20, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 5.6, "mmol/L", h8, ref_low=3.5, ref_high=5.1, encounter_id=encounter_id)))

    # Hour 16: Peak -- KDIGO Stage 3
    h16 = (admit_dt + timedelta(hours=16)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 3.4, "mg/dL", h16, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "3094-0", "BUN", 58, "mg/dL", h16, ref_low=7, ref_high=20, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 5.9, "mmol/L", h16, ref_low=3.5, ref_high=5.1, encounter_id=encounter_id)))

    # Hour 24: Improving
    h24 = (admit_dt + timedelta(hours=24)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 2.8, "mg/dL", h24, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "3094-0", "BUN", 48, "mg/dL", h24, ref_low=7, ref_high=20, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 5.3, "mmol/L", h24, ref_low=3.5, ref_high=5.1, encounter_id=encounter_id)))

    # Hour 36: Recovery
    h36 = (admit_dt + timedelta(hours=36)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 2.1, "mg/dL", h36, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "3094-0", "BUN", 35, "mg/dL", h36, ref_low=7, ref_high=20, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 4.8, "mmol/L", h36, ref_low=3.5, ref_high=5.1, encounter_id=encounter_id)))

    # Hour 48: Near-recovery
    h48 = (admit_dt + timedelta(hours=48)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.6, "mg/dL", h48, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "3094-0", "BUN", 28, "mg/dL", h48, ref_low=7, ref_high=20, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 4.3, "mmol/L", h48, ref_low=3.5, ref_high=5.1, encounter_id=encounter_id)))

    # --- Medications ---
    h0_med = admit_dt.isoformat()
    resources.append(("MedicationRequest", make_medication(
        patient_id, "313002", "Normal Saline",
        "125mL/hr IV continuous", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "4295", "Calcium Gluconate",
        "1g IV over 10 minutes", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "9524", "Sodium Polystyrene Sulfonate",
        "15g by mouth", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    h16_med = (admit_dt + timedelta(hours=16)).isoformat()
    resources.append(("MedicationRequest", make_medication(
        patient_id, "197417", "Furosemide",
        "40mg IV once", None,
        encounter_id=encounter_id, authored_on=h16_med)))

    # --- CareTeam ---
    resources.append(("CareTeam", make_care_team(
        patient_id, encounter_id, "Renal Care Team",
        [("Dr. Nguyen", "11911009", "Nephrologist"),
         ("Dr. Martinez", "309343006", "Physician"),
         ("RN Davis", "224535009", "Registered nurse")])))

    return resources


async def create_pulmonary_scenario(patient_id: str, encounter_id: str, admit_dt: datetime = None) -> list[tuple[str, dict]]:
    """
    55yo female with COPD presenting with acute PE confirmed by CT-PA.
    Tachypnea, hypoxia, tachycardia. Anticoagulation started. 30 hours total.

    Key scoring targets:
    - NEWS2 HIGH at admission (SpO2 88% + RR 28 + HR 118)
    - D-dimer series showing treatment response
    """
    resources = []
    if admit_dt is None:
        admit_dt = datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc)

    # --- Conditions (all linked to encounter) ---
    conditions = [
        ("59282003", "Pulmonary embolism", admit_dt.isoformat(), "active", "I26.99", "Other pulmonary embolism without acute cor pulmonale"),
        ("13645005", "Chronic obstructive pulmonary disease", "2020-08-15", "active", "J44.1", "COPD with acute exacerbation"),
        ("128053003", "Deep vein thrombosis", admit_dt.isoformat(), "active", "I82.90", "Acute embolism and thrombosis of unspecified deep veins"),
        ("2237002", "Pleuritic chest pain", admit_dt.isoformat(), "active", "R09.89", "Other specified symptoms involving respiratory system"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(
            patient_id, code, display, onset, status, icd, icd_display,
            encounter_id=encounter_id)))

    # --- Vital sign progression over 30 hours ---
    base_vitals = {"hr": 118, "sbp": 105, "dbp": 68, "rr": 28, "temp": 37.5, "spo2": 88}
    progression = [
        {"hour": 2, "deltas": {"hr": 5, "sbp": -5, "rr": 3, "spo2": -2}},
        {"hour": 4, "deltas": {"hr": 3, "rr": 1, "spo2": -1}},
        {"hour": 8, "deltas": {"hr": -8, "sbp": 5, "rr": -3, "spo2": 3}},
        {"hour": 12, "deltas": {"hr": -10, "sbp": 5, "rr": -4, "spo2": 3}},
        {"hour": 18, "deltas": {"hr": -8, "sbp": 3, "rr": -3, "spo2": 2}},
        {"hour": 24, "deltas": {"hr": -5, "sbp": 2, "rr": -2, "spo2": 2}},
        {"hour": 30, "deltas": {"hr": -3, "rr": -1, "spo2": 1}},
    ]
    vitals = generate_vital_series(patient_id, encounter_id, admit_dt, 30, base_vitals, progression)
    resources.extend(vitals)

    # --- Labs ---
    # Hour 0: Initial labs
    h0 = admit_dt.isoformat()
    resources.append(("Observation", make_observation(patient_id, "48065-7", "D-dimer", 4500, "ng/mL", h0, ref_high=500, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "49563-0", "Troponin I", 0.08, "ng/mL", h0, ref_high=0.04, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "30934-4", "BNP", 220, "pg/mL", h0, ref_high=100, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 10.5, "10*3/uL", h0, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "718-7", "Hemoglobin", 13.2, "g/dL", h0, ref_low=12.0, ref_high=16.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 0.9, "mg/dL", h0, ref_low=0.6, ref_high=1.1, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 2.5, "mmol/L", h0, ref_high=2.0, encounter_id=encounter_id)))

    # Hour 6: Improvement with treatment
    h6 = (admit_dt + timedelta(hours=6)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "48065-7", "D-dimer", 3800, "ng/mL", h6, ref_high=500, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "49563-0", "Troponin I", 0.06, "ng/mL", h6, ref_high=0.04, encounter_id=encounter_id)))

    # Hour 12: Further improvement
    h12 = (admit_dt + timedelta(hours=12)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "48065-7", "D-dimer", 2500, "ng/mL", h12, ref_high=500, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "49563-0", "Troponin I", 0.04, "ng/mL", h12, ref_high=0.04, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 1.8, "mmol/L", h12, ref_high=2.0, encounter_id=encounter_id)))

    # Hour 24: Significant improvement
    h24 = (admit_dt + timedelta(hours=24)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "48065-7", "D-dimer", 1200, "ng/mL", h24, ref_high=500, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "30934-4", "BNP", 150, "pg/mL", h24, ref_high=100, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 0.8, "mg/dL", h24, ref_low=0.6, ref_high=1.1, encounter_id=encounter_id)))

    # --- Medications ---
    h0_med = admit_dt.isoformat()
    resources.append(("MedicationRequest", make_medication(
        patient_id, "5224", "Heparin",
        "IV infusion per protocol", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "855288", "Warfarin",
        "5mg by mouth daily", "daily",
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "630208", "Albuterol",
        "2.5mg nebulizer every 4 hours", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "1536577", "Supplemental Oxygen",
        "2-4L nasal cannula titrate SpO2 >92%", None,
        encounter_id=encounter_id, authored_on=h0_med)))

    # --- CareTeam ---
    resources.append(("CareTeam", make_care_team(
        patient_id, encounter_id, "Pulmonary Care Team",
        [("Dr. Singh", "41672002", "Pulmonologist"),
         ("Dr. Chen", "309343006", "Physician"),
         ("RN Williams", "224535009", "Registered nurse")])))

    return resources


async def create_multisystem_scenario(patient_id: str, encounter_id: str, admit_dt: datetime = None) -> list[tuple[str, dict]]:
    """
    75yo male with sepsis (pneumonia) complicated by AKI and respiratory failure.
    Most complex scenario. 48 hours total.

    Key scoring targets:
    - qSOFA >= 2 at hours 3-10 (SBP <= 100, RR >= 22, altered mental status)
    - NEWS2 HIGH throughout first 24h
    - SOFA elevated (multi-organ: renal, hepatic, coagulation, respiratory)
    """
    resources = []
    if admit_dt is None:
        admit_dt = datetime(2026, 2, 23, 20, 0, tzinfo=timezone.utc)

    # --- Conditions (all linked to encounter) ---
    conditions = [
        ("91302008", "Sepsis", admit_dt.isoformat(), "active", "A41.9", "Sepsis, unspecified organism"),
        ("385093006", "Community-acquired pneumonia", admit_dt.isoformat(), "active", "J18.9", "Pneumonia, unspecified organism"),
        ("14669001", "Acute kidney injury", admit_dt.isoformat(), "active", "N17.9", "Acute kidney failure, unspecified"),
        ("65710008", "Acute respiratory failure", admit_dt.isoformat(), "active", "J96.00", "Acute respiratory failure, unspecified"),
        ("44054006", "Type 2 diabetes mellitus", "2016-09-10", "active", "E11.9", "Type 2 diabetes mellitus"),
        ("49436004", "Atrial fibrillation", "2021-04-15", "active", "I48.91", "Unspecified atrial fibrillation"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(
            patient_id, code, display, onset, status, icd, icd_display,
            encounter_id=encounter_id)))

    # --- Vital sign progression over 48 hours ---
    base_vitals = {"hr": 110, "sbp": 100, "dbp": 58, "rr": 26, "temp": 39.2, "spo2": 89}
    progression = [
        {"hour": 3, "deltas": {"hr": 8, "sbp": -10, "rr": 4, "temp": 0.3, "spo2": -3}},
        {"hour": 6, "deltas": {"hr": 5, "sbp": -8, "rr": 2, "temp": 0.2, "spo2": -2}},
        {"hour": 10, "deltas": {"hr": 3, "sbp": -5, "rr": 1, "spo2": -1}},
        {"hour": 14, "deltas": {"hr": -3, "sbp": 3, "rr": -1, "temp": -0.2, "spo2": 1}},
        {"hour": 18, "deltas": {"hr": -5, "sbp": 5, "rr": -2, "temp": -0.3, "spo2": 2}},
        {"hour": 24, "deltas": {"hr": -8, "sbp": 8, "rr": -3, "temp": -0.5, "spo2": 3}},
        {"hour": 30, "deltas": {"hr": -5, "sbp": 5, "rr": -2, "temp": -0.3, "spo2": 2}},
        {"hour": 36, "deltas": {"hr": -5, "sbp": 5, "rr": -2, "temp": -0.3, "spo2": 2}},
        {"hour": 42, "deltas": {"hr": -3, "sbp": 3, "rr": -1, "temp": -0.2, "spo2": 1}},
        {"hour": 48, "deltas": {"hr": -2, "sbp": 2, "rr": -1, "spo2": 1}},
    ]
    vitals = generate_vital_series(patient_id, encounter_id, admit_dt, 48, base_vitals, progression)
    resources.extend(vitals)

    # --- Labs (comprehensive for multi-organ tracking) ---
    # Hour 0: Initial labs
    h0 = admit_dt.isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 24.0, "10*3/uL", h0, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 2.1, "mg/dL", h0, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 4.5, "mmol/L", h0, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 140, "10*3/uL", h0, ref_low=150, ref_high=400, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "1975-2", "Total Bilirubin", 1.8, "mg/dL", h0, ref_high=1.2, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "75241-0", "Procalcitonin", 12.0, "ng/mL", h0, ref_high=0.5, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 5.4, "mmol/L", h0, ref_low=3.5, ref_high=5.1, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2951-2", "Sodium", 132, "mmol/L", h0, ref_low=136, ref_high=145, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "718-7", "Hemoglobin", 12.0, "g/dL", h0, ref_low=13.5, ref_high=17.5, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "3094-0", "BUN", 42, "mg/dL", h0, ref_low=7, ref_high=20, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "1920-8", "AST", 85, "U/L", h0, ref_low=10, ref_high=40, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "1742-6", "ALT", 68, "U/L", h0, ref_low=7, ref_high=56, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "49563-0", "Troponin I", 0.12, "ng/mL", h0, ref_high=0.04, encounter_id=encounter_id)))

    # Hour 6: Worsening
    h6 = (admit_dt + timedelta(hours=6)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 26.5, "10*3/uL", h6, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 2.8, "mg/dL", h6, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 5.8, "mmol/L", h6, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 115, "10*3/uL", h6, ref_low=150, ref_high=400, encounter_id=encounter_id)))

    # Hour 12: Peak AKI, platelet nadir
    h12 = (admit_dt + timedelta(hours=12)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 22.0, "10*3/uL", h12, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 3.2, "mg/dL", h12, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 4.2, "mmol/L", h12, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 98, "10*3/uL", h12, ref_low=150, ref_high=400, encounter_id=encounter_id)))

    # Hour 24: Improving
    h24 = (admit_dt + timedelta(hours=24)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 16.5, "10*3/uL", h24, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 2.5, "mg/dL", h24, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 2.8, "mmol/L", h24, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 120, "10*3/uL", h24, ref_low=150, ref_high=400, encounter_id=encounter_id)))

    # Hour 36: Recovery
    h36 = (admit_dt + timedelta(hours=36)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 12.0, "10*3/uL", h36, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.9, "mg/dL", h36, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 1.8, "mmol/L", h36, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 145, "10*3/uL", h36, ref_low=150, ref_high=400, encounter_id=encounter_id)))

    # Hour 48: Near-resolution
    h48 = (admit_dt + timedelta(hours=48)).isoformat()
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 9.5, "10*3/uL", h48, ref_low=4.5, ref_high=11.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.5, "mg/dL", h48, ref_low=0.7, ref_high=1.3, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "32693-4", "Lactate", 1.2, "mmol/L", h48, ref_high=2.0, encounter_id=encounter_id)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 168, "10*3/uL", h48, ref_low=150, ref_high=400, encounter_id=encounter_id)))

    # --- Medications ---
    h0_med = admit_dt.isoformat()
    resources.append(("MedicationRequest", make_medication(
        patient_id, "29561", "Meropenem",
        "1g IV every 8 hours", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "11124", "Vancomycin",
        "25mg/kg IV loading dose", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "7512", "Norepinephrine",
        "0.2mcg/kg/min titrate to MAP >65", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "313002", "Normal Saline",
        "30mL/kg IV bolus", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    resources.append(("MedicationRequest", make_medication(
        patient_id, "5856", "Insulin Regular",
        "Sliding scale IV per protocol", None,
        encounter_id=encounter_id, authored_on=h0_med)))
    h24_med = (admit_dt + timedelta(hours=24)).isoformat()
    resources.append(("MedicationRequest", make_medication(
        patient_id, "197417", "Furosemide",
        "40mg IV once AKI stabilizes", None,
        encounter_id=encounter_id, authored_on=h24_med)))

    # --- CareTeam ---
    resources.append(("CareTeam", make_care_team(
        patient_id, encounter_id, "Multi-System ICU Team",
        [("Dr. Anderson", "309343006", "Physician"),
         ("Dr. Park", "11911009", "Nephrologist"),
         ("Dr. Brown", "76231001", "Infectious disease specialist"),
         ("RN Garcia", "224535009", "Registered nurse"),
         ("PharmD Wilson", "46255001", "Pharmacist")])))

    return resources


# =============================================================================
# Patient Definitions
# =============================================================================

async def create_john_smith(patient_id: str):
    """John Smith - 56yo M - Metabolic Syndrome"""
    resources = []

    # --- Conditions ---
    conditions = [
        ("44054006", "Type 2 Diabetes Mellitus", "2016-03-15", "active", "E11.9", "Type 2 diabetes mellitus without complications"),
        ("38341003", "Hypertension", "2014-08-20", "active", "I10", "Essential hypertension"),
        ("55822004", "Hyperlipidemia", "2015-11-10", "active", "E78.5", "Hyperlipidemia, unspecified"),
        ("414916001", "Obesity", "2012-06-01", "active", "E66.9", "Obesity, unspecified"),
        ("302226006", "Peripheral Neuropathy", "2020-09-12", "active", "G62.9", "Polyneuropathy, unspecified"),
        ("235595009", "Gastroesophageal Reflux Disease", "2018-04-22", "active", "K21.0", "GERD with esophagitis"),
        ("700379002", "Chronic Kidney Disease Stage 2", "2022-01-15", "active", "N18.2", "CKD stage 2"),
        ("267036007", "Obstructive Sleep Apnea", "2019-07-30", "active", "G47.33", "Obstructive sleep apnea"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(patient_id, code, display, onset, status, icd, icd_display)))

    # --- Medications ---
    medications = [
        ("860975", "Metformin 1000mg", "1000mg by mouth twice daily", "BID"),
        ("314076", "Lisinopril 20mg", "20mg by mouth daily", "daily"),
        ("259255", "Atorvastatin 40mg", "40mg by mouth at bedtime", "daily"),
        ("196474", "Gabapentin 300mg", "300mg by mouth three times daily", "TID"),
        ("198211", "Omeprazole 20mg", "20mg by mouth daily before breakfast", "daily"),
        ("243670", "Aspirin 81mg", "81mg by mouth daily", "daily"),
        ("849727", "Empagliflozin 10mg", "10mg by mouth daily", "daily"),
        ("1249056", "Semaglutide 0.5mg", "0.5mg subcutaneous injection weekly", "weekly"),
    ]
    for rxnorm, display, dosage, freq in medications:
        resources.append(("MedicationRequest", make_medication(patient_id, rxnorm, display, dosage, freq)))

    # --- Allergies ---
    allergies = [
        ("Penicillin", "70618", "Urticaria (hives)", "moderate", "high"),
        ("Sulfonamide", "76169", "Rash", "mild", "low"),
        ("Iodinated contrast dye", None, "Nausea and flushing", "mild", "low"),
    ]
    for substance, code, reaction, severity, crit in allergies:
        resources.append(("AllergyIntolerance", make_allergy(patient_id, substance, code, reaction, severity, crit)))

    # --- Labs (with trends) ---
    # A1C trend: 8.5 → 8.0 → 7.8 → 7.2 → 6.9
    a1c_values = [
        ("2024-01-15", 8.5), ("2024-06-20", 8.0), ("2024-12-10", 7.8),
        ("2025-06-15", 7.2), ("2025-12-01", 6.9),
    ]
    for dt, val in a1c_values:
        resources.append(("Observation", make_observation(patient_id, "4548-4", "Hemoglobin A1c", val, "%", dt, ref_high=5.7)))

    # Fasting glucose
    glucose_values = [("2024-06-20", 156), ("2024-12-10", 142), ("2025-06-15", 128), ("2025-12-01", 118)]
    for dt, val in glucose_values:
        resources.append(("Observation", make_observation(patient_id, "1558-6", "Fasting Glucose", val, "mg/dL", dt, ref_low=70, ref_high=100)))

    # Lipid panel
    lipids = [
        ("2024-06-20", [("2093-3", "Total Cholesterol", 248, "mg/dL"), ("2571-8", "Triglycerides", 210, "mg/dL"), ("2085-9", "HDL", 38, "mg/dL"), ("13457-7", "LDL Calculated", 168, "mg/dL")]),
        ("2025-06-15", [("2093-3", "Total Cholesterol", 198, "mg/dL"), ("2571-8", "Triglycerides", 165, "mg/dL"), ("2085-9", "HDL", 42, "mg/dL"), ("13457-7", "LDL Calculated", 123, "mg/dL")]),
        ("2025-12-01", [("2093-3", "Total Cholesterol", 185, "mg/dL"), ("2571-8", "Triglycerides", 148, "mg/dL"), ("2085-9", "HDL", 45, "mg/dL"), ("13457-7", "LDL Calculated", 110, "mg/dL")]),
    ]
    for dt, panels in lipids:
        for loinc, name, val, unit in panels:
            ref_high = {"Total Cholesterol": 200, "Triglycerides": 150, "LDL Calculated": 100}.get(name)
            ref_low = {"HDL": 40}.get(name)
            resources.append(("Observation", make_observation(patient_id, loinc, name, val, unit, dt, ref_low=ref_low, ref_high=ref_high)))

    # BMP / Renal
    creatinine_vals = [("2024-06-20", 1.1), ("2025-01-10", 1.2), ("2025-06-15", 1.3), ("2025-12-01", 1.3)]
    for dt, val in creatinine_vals:
        resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", val, "mg/dL", dt, ref_low=0.7, ref_high=1.3)))

    egfr_vals = [("2024-06-20", 78), ("2025-01-10", 72), ("2025-06-15", 68), ("2025-12-01", 67)]
    for dt, val in egfr_vals:
        resources.append(("Observation", make_observation(patient_id, "33914-3", "eGFR", val, "mL/min/1.73m2", dt, ref_low=60)))

    # CBC
    resources.append(("Observation", make_observation(patient_id, "718-7", "Hemoglobin", 14.2, "g/dL", "2025-12-01", ref_low=13.5, ref_high=17.5)))
    resources.append(("Observation", make_observation(patient_id, "4544-3", "Hematocrit", 42.1, "%", "2025-12-01", ref_low=38.3, ref_high=48.6)))
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 7.8, "10*3/uL", "2025-12-01", ref_low=4.5, ref_high=11.0)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 245, "10*3/uL", "2025-12-01", ref_low=150, ref_high=400)))

    # BMP electrolytes
    resources.append(("Observation", make_observation(patient_id, "2951-2", "Sodium", 140, "mmol/L", "2025-12-01", ref_low=136, ref_high=145)))
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 4.3, "mmol/L", "2025-12-01", ref_low=3.5, ref_high=5.1)))
    resources.append(("Observation", make_observation(patient_id, "3094-0", "BUN", 22, "mg/dL", "2025-12-01", ref_low=7, ref_high=20)))

    # Urine microalbumin
    resources.append(("Observation", make_observation(patient_id, "14959-1", "Urine Microalbumin/Creatinine Ratio", 45, "mg/g", "2025-06-15", ref_high=30)))

    # --- Vitals ---
    bp_readings = [
        ("2024-06-20", 148, 92), ("2024-12-10", 140, 88),
        ("2025-06-15", 134, 84), ("2025-12-01", 130, 82),
    ]
    for dt, sys, dia in bp_readings:
        resources.append(("Observation", make_bp(patient_id, sys, dia, dt)))

    weight_readings = [("2024-06-20", 102), ("2024-12-10", 100), ("2025-06-15", 97), ("2025-12-01", 95)]
    for dt, val in weight_readings:
        resources.append(("Observation", make_vital(patient_id, "29463-7", "Body Weight", val, "kg", dt)))

    resources.append(("Observation", make_vital(patient_id, "8302-2", "Body Height", 178, "cm", "2025-06-15")))
    resources.append(("Observation", make_vital(patient_id, "39156-5", "BMI", 30.0, "kg/m2", "2025-12-01")))
    resources.append(("Observation", make_vital(patient_id, "8867-4", "Heart Rate", 78, "/min", "2025-12-01")))

    # --- Immunizations ---
    immunizations = [
        ("158", "Influenza Vaccine", "2025-10-15"),
        ("158", "Influenza Vaccine", "2024-10-20"),
        ("213", "COVID-19 mRNA Bivalent Booster", "2024-11-05"),
        ("213", "COVID-19 mRNA Vaccine", "2023-09-20"),
        ("115", "Tdap", "2022-03-10"),
        ("33", "Pneumococcal Conjugate PCV20", "2025-01-20"),
    ]
    for cvx, name, dt in immunizations:
        resources.append(("Immunization", make_immunization(patient_id, cvx, name, dt)))

    # --- Procedures ---
    procedures = [
        ("73761001", "Colonoscopy", "2023-04-15", "45378", "Normal - no polyps. Repeat in 10 years."),
        ("252779009", "Diabetic Retinal Screening", "2025-03-20", "92250", "Mild non-proliferative diabetic retinopathy. Follow up in 6 months."),
        ("401191002", "Diabetic Foot Examination", "2025-06-15", None, "Diminished sensation bilateral feet. Monofilament testing 5/10 sites."),
        ("252565008", "Carotid Doppler Ultrasound", "2024-08-10", "93880", "Mild bilateral stenosis <50%. No intervention needed."),
        ("241615005", "Sleep Study (Polysomnography)", "2019-07-15", "95810", "AHI 22 events/hr. Moderate OSA. CPAP recommended."),
        ("710824005", "CPAP Titration", "2019-08-20", None, "Optimal pressure 10 cm H2O. Good mask fit."),
    ]
    for snomed, name, dt, cpt, outcome in procedures:
        resources.append(("Procedure", make_procedure(patient_id, snomed, name, dt, cpt, outcome)))

    # --- Encounters ---
    encounters = [
        ("Diabetes Follow-Up", "2025-12-01", "Quarterly diabetes management review", "AMB"),
        ("Diabetes Follow-Up", "2025-06-15", "A1C improved, adjusting medications", "AMB"),
        ("Annual Physical Exam", "2025-01-20", "Annual wellness visit with preventive screening", "AMB"),
        ("Diabetes Follow-Up", "2024-12-10", "Review of diabetes management and labs", "AMB"),
        ("Emergency Visit", "2024-03-05", "Hypoglycemic episode - glucose 52 mg/dL", "EMER"),
        ("Ophthalmology Consult", "2025-03-20", "Diabetic retinal screening", "AMB"),
        ("Neurology Consult", "2020-09-12", "Evaluation of peripheral neuropathy", "AMB"),
        ("Sleep Medicine", "2019-07-15", "Sleep study for suspected OSA", "AMB"),
    ]
    for enc_type, dt, reason, cls in encounters:
        resources.append(("Encounter", make_encounter(patient_id, enc_type, dt, reason, enc_class=cls)))

    # --- Clinical Notes ---
    notes = [
        ("Progress Note - Diabetes Follow-Up", "2025-12-01",
         "A1C improved to 6.9% from 7.2%. Patient compliant with metformin and semaglutide. Weight down 2kg. "
         "Continue current regimen. Mild non-proliferative retinopathy noted - ophthalmology follow-up in 6 months. "
         "eGFR stable at 67 - CKD stage 2 stable."),
        ("Annual Physical Exam Note", "2025-01-20",
         "56yo male with metabolic syndrome. Diabetes control improving. BP at goal. "
         "Administered PCV20 vaccine. Discussed colon cancer screening - last colonoscopy 2023, normal. "
         "Missing shingrix vaccination - discussed. Patient deferred to next visit."),
        ("ED Visit Note - Hypoglycemia", "2024-03-05",
         "Patient presented with confusion, diaphoresis, glucose 52 mg/dL. Given D50W IV with resolution of symptoms. "
         "Cause: skipped meals while on semaglutide + metformin. Counseled on hypoglycemia awareness. "
         "Adjusted medication timing. Discharged in stable condition."),
    ]
    for title, dt, content in notes:
        resources.append(("DocumentReference", make_document(patient_id, title, content, dt)))

    return resources


async def create_maria_garcia(patient_id: str):
    """Maria Garcia - 68yo F - Cardiopulmonary"""
    resources = []

    # --- Conditions ---
    conditions = [
        ("13645005", "Chronic Obstructive Pulmonary Disease", "2015-05-20", "active", "J44.1", "COPD with acute exacerbation"),
        ("42343007", "Congestive Heart Failure, Class II", "2019-11-15", "active", "I50.22", "Chronic systolic heart failure"),
        ("49436004", "Atrial Fibrillation", "2020-06-08", "active", "I48.91", "Unspecified atrial fibrillation"),
        ("38341003", "Essential Hypertension", "2010-02-14", "active", "I10", "Essential hypertension"),
        ("396275006", "Osteoarthritis of Both Knees", "2017-09-25", "active", "M17.0", "Bilateral primary osteoarthritis of knee"),
        ("197480006", "Generalized Anxiety Disorder", "2021-03-10", "active", "F41.1", "Generalized anxiety disorder"),
        ("44054006", "Type 2 Diabetes Mellitus", "2022-08-15", "active", "E11.9", "Type 2 diabetes mellitus"),
        ("73211009", "Iron Deficiency Anemia", "2023-04-10", "active", "D50.9", "Iron deficiency anemia"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(patient_id, code, display, onset, status, icd, icd_display)))

    # --- Medications ---
    medications = [
        ("855332", "Apixaban (Eliquis) 5mg", "5mg by mouth twice daily", "BID"),
        ("866924", "Metoprolol Succinate 50mg", "50mg by mouth twice daily", "BID"),
        ("197417", "Furosemide 40mg", "40mg by mouth daily", "daily"),
        ("1658087", "Tiotropium (Spiriva) 18mcg", "1 inhalation daily", "daily"),
        ("630208", "Albuterol Inhaler 90mcg", "2 puffs every 4-6 hours as needed", "PRN"),
        ("314076", "Lisinopril 10mg", "10mg by mouth daily", "daily"),
        ("248642", "Sertraline 50mg", "50mg by mouth daily", "daily"),
        ("860975", "Metformin 500mg", "500mg by mouth twice daily", "BID"),
        ("310436", "Potassium Chloride 20mEq", "20mEq by mouth daily", "daily"),
        ("259130", "Ferrous Sulfate 325mg", "325mg by mouth daily", "daily"),
    ]
    for rxnorm, display, dosage, freq in medications:
        resources.append(("MedicationRequest", make_medication(patient_id, rxnorm, display, dosage, freq)))

    # --- Allergies ---
    allergies = [
        ("Codeine", "2670", "Nausea and vomiting", "moderate", "low"),
        ("Latex", None, "Contact dermatitis", "mild", "low"),
        ("ACE Inhibitors class note", None, "Angioedema (historical - tolerating lisinopril)", "severe", "high"),
    ]
    for substance, code, reaction, severity, crit in allergies:
        resources.append(("AllergyIntolerance", make_allergy(patient_id, substance, code, reaction, severity, crit)))

    # --- Labs ---
    # BNP trend (CHF monitoring)
    bnp_vals = [("2024-03-10", 580), ("2024-09-15", 420), ("2025-03-20", 350), ("2025-09-10", 310), ("2025-12-15", 285)]
    for dt, val in bnp_vals:
        resources.append(("Observation", make_observation(patient_id, "42637-9", "BNP", val, "pg/mL", dt, ref_high=100)))

    # BMP
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 3.8, "mmol/L", "2025-12-15", ref_low=3.5, ref_high=5.1)))
    resources.append(("Observation", make_observation(patient_id, "2951-2", "Sodium", 138, "mmol/L", "2025-12-15", ref_low=136, ref_high=145)))
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.0, "mg/dL", "2025-12-15", ref_low=0.6, ref_high=1.1)))
    resources.append(("Observation", make_observation(patient_id, "3094-0", "BUN", 18, "mg/dL", "2025-12-15", ref_low=7, ref_high=20)))
    resources.append(("Observation", make_observation(patient_id, "33914-3", "eGFR", 62, "mL/min/1.73m2", "2025-12-15", ref_low=60)))

    # CBC
    resources.append(("Observation", make_observation(patient_id, "718-7", "Hemoglobin", 10.8, "g/dL", "2025-12-15", ref_low=12.0, ref_high=16.0)))
    resources.append(("Observation", make_observation(patient_id, "4544-3", "Hematocrit", 33.2, "%", "2025-12-15", ref_low=36.0, ref_high=46.0)))
    resources.append(("Observation", make_observation(patient_id, "787-2", "MCV", 76, "fL", "2025-12-15", ref_low=80, ref_high=100)))
    resources.append(("Observation", make_observation(patient_id, "2498-4", "Iron", 35, "ug/dL", "2025-12-15", ref_low=60, ref_high=170)))
    resources.append(("Observation", make_observation(patient_id, "2276-4", "Ferritin", 12, "ng/mL", "2025-12-15", ref_low=12, ref_high=150)))

    # TSH
    resources.append(("Observation", make_observation(patient_id, "3016-3", "TSH", 2.4, "mIU/L", "2025-06-10", ref_low=0.4, ref_high=4.0)))

    # A1C
    a1c_vals = [("2023-02-10", 6.8), ("2023-08-15", 6.5), ("2024-02-20", 6.3), ("2025-06-10", 6.4), ("2025-12-15", 6.2)]
    for dt, val in a1c_vals:
        resources.append(("Observation", make_observation(patient_id, "4548-4", "Hemoglobin A1c", val, "%", dt, ref_high=5.7)))

    # INR (historical before Eliquis)
    resources.append(("Observation", make_observation(patient_id, "6301-6", "INR", 1.0, "{ratio}", "2025-12-15", ref_low=0.8, ref_high=1.2)))

    # --- Vitals ---
    bp_readings = [("2024-09-15", 142, 86), ("2025-03-20", 136, 82), ("2025-09-10", 132, 80), ("2025-12-15", 128, 78)]
    for dt, sys, dia in bp_readings:
        resources.append(("Observation", make_bp(patient_id, sys, dia, dt)))

    o2_readings = [("2024-09-15", 92), ("2025-03-20", 93), ("2025-09-10", 94), ("2025-12-15", 95)]
    for dt, val in o2_readings:
        resources.append(("Observation", make_vital(patient_id, "2708-6", "Oxygen Saturation", val, "%", dt)))

    weight_readings = [("2024-09-15", 75), ("2025-03-20", 73), ("2025-09-10", 72), ("2025-12-15", 71)]
    for dt, val in weight_readings:
        resources.append(("Observation", make_vital(patient_id, "29463-7", "Body Weight", val, "kg", dt)))

    resources.append(("Observation", make_vital(patient_id, "8302-2", "Body Height", 160, "cm", "2025-03-20")))
    resources.append(("Observation", make_vital(patient_id, "8867-4", "Heart Rate", 82, "/min", "2025-12-15")))

    # --- Immunizations ---
    immunizations = [
        ("158", "Influenza Vaccine", "2025-10-10"),
        ("158", "Influenza Vaccine", "2024-10-12"),
        ("213", "COVID-19 mRNA Booster", "2024-10-12"),
        ("33", "Pneumococcal PCV20", "2023-11-15"),
        ("121", "Zoster (Shingrix) Dose 1", "2024-01-20"),
        ("121", "Zoster (Shingrix) Dose 2", "2024-04-20"),
        ("115", "Tdap", "2020-06-15"),
    ]
    for cvx, name, dt in immunizations:
        resources.append(("Immunization", make_immunization(patient_id, cvx, name, dt)))

    # --- Procedures ---
    procedures = [
        ("40701008", "Echocardiogram", "2025-09-10", "93306", "EF 40%, mild mitral regurgitation, dilated LA"),
        ("127783003", "Pulmonary Function Test (Spirometry)", "2025-06-10", "94010", "FEV1 55% predicted, FEV1/FVC 0.62. Moderate obstruction."),
        ("180256009", "Cardioversion", "2020-06-15", "92960", "Successful DC cardioversion. NSR restored."),
        ("18286008", "Right Heart Catheterization", "2019-12-01", "93451", "Elevated RA/RV pressures. mPAP 32mmHg. Confirmed CHF diagnosis."),
        ("363680008", "Bilateral Knee X-ray", "2024-05-10", "73562", "Moderate bilateral knee OA. Joint space narrowing. Osteophytes."),
        ("73761001", "Colonoscopy", "2022-11-20", "45378", "Two tubular adenomas removed. Repeat in 3 years."),
        ("252416005", "CT Chest", "2025-01-10", "71260", "No pulmonary embolism. Mild emphysematous changes. Cardiomegaly."),
    ]
    for snomed, name, dt, cpt, outcome in procedures:
        resources.append(("Procedure", make_procedure(patient_id, snomed, name, dt, cpt, outcome)))

    # --- Encounters ---
    encounters = [
        ("CHF Clinic Follow-Up", "2025-12-15", "Monthly CHF monitoring. BNP improving. Weight stable.", "AMB"),
        ("CHF Clinic Follow-Up", "2025-09-10", "Echo shows stable EF 40%. Diuretics adjusted.", "AMB"),
        ("Pulmonology Follow-Up", "2025-06-10", "COPD management review. PFTs stable.", "AMB"),
        ("Emergency Visit - CHF Exacerbation", "2024-03-10", "Acute CHF exacerbation with dyspnea. IV furosemide. Admitted.", "EMER"),
        ("Inpatient - CHF", "2024-03-10", "3-day admission for CHF exacerbation. Diuresis, stabilized.", "IMP"),
        ("Cardiology Consult", "2024-09-15", "Routine AFib/CHF management review", "AMB"),
        ("Annual Physical Exam", "2025-01-10", "Annual wellness visit", "AMB"),
        ("Rheumatology Consult", "2024-05-10", "Knee OA evaluation", "AMB"),
    ]
    for enc_type, dt, reason, cls in encounters:
        resources.append(("Encounter", make_encounter(patient_id, enc_type, dt, reason, enc_class=cls)))

    # --- Clinical Notes ---
    notes = [
        ("CHF Clinic Progress Note", "2025-12-15",
         "68yo F with CHF class II, COPD, AFib. BNP trending down 580→285 over 18 months. "
         "EF 40% stable on last echo. Weight 71kg (dry weight 70kg). O2 sat 95% on RA. "
         "Tolerating Eliquis, metoprolol, furosemide. K+ 3.8 on supplement. "
         "Iron deficiency anemia - Hgb 10.8, ferritin 12. Started ferrous sulfate. "
         "Plan: Continue current CHF regimen. Recheck CBC in 6 weeks. Colonoscopy due in 2025 (last 2022, adenomas)."),
        ("ED Note - CHF Exacerbation", "2024-03-10",
         "68yo F presenting with progressive dyspnea, orthopnea x3 days, 4kg weight gain. "
         "BNP 580. CXR showing pulmonary edema. O2 sat 89% on RA. "
         "Treated with IV furosemide 80mg, improved to 93%. Admitted to cardiology service."),
    ]
    for title, dt, content in notes:
        resources.append(("DocumentReference", make_document(patient_id, title, content, dt)))

    return resources


async def create_robert_johnson(patient_id: str):
    """Robert Johnson - 45yo M - Chronic Kidney Disease"""
    resources = []

    # --- Conditions ---
    conditions = [
        ("431857002", "Chronic Kidney Disease Stage 3b", "2020-04-15", "active", "N18.32", "CKD stage 3b"),
        ("38341003", "Essential Hypertension", "2015-06-10", "active", "I10", "Essential hypertension"),
        ("90560007", "Gout", "2019-01-20", "active", "M10.9", "Gout, unspecified"),
        ("691401000119104", "Anemia of Chronic Kidney Disease", "2022-03-15", "active", "D63.1", "Anemia in CKD"),
        ("35489007", "Major Depressive Disorder", "2021-08-10", "active", "F33.1", "MDD, recurrent, moderate"),
        ("84114007", "Heart Failure", "2023-11-01", "active", "I50.9", "Heart failure, unspecified"),
        ("68566005", "Urinary Tract Infection", "2025-08-20", "resolved", "N39.0", "UTI, site not specified"),
        ("44054006", "Type 2 Diabetes Mellitus", "2023-05-15", "active", "E11.65", "T2DM with hyperglycemia"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(patient_id, code, display, onset, status, icd, icd_display)))

    # --- Medications ---
    medications = [
        ("329526", "Amlodipine 10mg", "10mg by mouth daily", "daily"),
        ("979480", "Losartan 100mg", "100mg by mouth daily", "daily"),
        ("197319", "Allopurinol 200mg", "200mg by mouth daily", "daily"),
        ("198144", "Sodium Bicarbonate 650mg", "650mg by mouth three times daily", "TID"),
        ("727711", "Epoetin Alfa 4000 units", "4000 units subcutaneous three times weekly", "TID"),
        ("352304", "Escitalopram 10mg", "10mg by mouth daily", "daily"),
        ("311671", "Calcitriol 0.25mcg", "0.25mcg by mouth daily", "daily"),
        ("310798", "Sevelamer 800mg", "800mg by mouth three times daily with meals", "TID"),
        ("860975", "Metformin 500mg", "500mg by mouth daily (reduced dose for CKD)", "daily"),
    ]
    for rxnorm, display, dosage, freq in medications:
        resources.append(("MedicationRequest", make_medication(patient_id, rxnorm, display, dosage, freq)))

    # --- Allergies ---
    allergies = [
        ("NSAIDs (Ibuprofen, Naproxen)", "5640", "Contraindicated - acute kidney injury risk", "severe", "high"),
        ("Iodinated Contrast Dye", None, "Prior contrast nephropathy", "severe", "high"),
        ("Trimethoprim", "10829", "Hyperkalemia", "moderate", "high"),
    ]
    for substance, code, reaction, severity, crit in allergies:
        resources.append(("AllergyIntolerance", make_allergy(patient_id, substance, code, reaction, severity, crit)))

    # --- Labs (with CKD progression) ---
    # Creatinine trend: 1.8 → 2.0 → 2.1 → 2.3 → 2.4
    creat_vals = [("2023-06-10", 1.8), ("2024-01-15", 2.0), ("2024-07-20", 2.1), ("2025-03-10", 2.3), ("2025-12-05", 2.4)]
    for dt, val in creat_vals:
        resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", val, "mg/dL", dt, ref_low=0.7, ref_high=1.3)))

    # eGFR trend: 42 → 39 → 38 → 36 → 35
    egfr_vals = [("2023-06-10", 42), ("2024-01-15", 39), ("2024-07-20", 38), ("2025-03-10", 36), ("2025-12-05", 35)]
    for dt, val in egfr_vals:
        resources.append(("Observation", make_observation(patient_id, "33914-3", "eGFR", val, "mL/min/1.73m2", dt, ref_low=60)))

    # Potassium (needs monitoring on Losartan)
    k_vals = [("2024-01-15", 4.8), ("2024-07-20", 5.0), ("2025-03-10", 4.9), ("2025-12-05", 5.1)]
    for dt, val in k_vals:
        resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", val, "mmol/L", dt, ref_low=3.5, ref_high=5.1)))

    # Hemoglobin (CKD anemia)
    hgb_vals = [("2023-06-10", 10.2), ("2024-01-15", 9.8), ("2024-07-20", 10.5), ("2025-03-10", 11.0), ("2025-12-05", 11.2)]
    for dt, val in hgb_vals:
        resources.append(("Observation", make_observation(patient_id, "718-7", "Hemoglobin", val, "g/dL", dt, ref_low=13.5, ref_high=17.5)))

    # Uric acid
    ua_vals = [("2024-01-15", 8.5), ("2024-07-20", 7.2), ("2025-03-10", 6.8), ("2025-12-05", 6.5)]
    for dt, val in ua_vals:
        resources.append(("Observation", make_observation(patient_id, "3084-1", "Uric Acid", val, "mg/dL", dt, ref_low=3.5, ref_high=7.2)))

    # Urine ACR
    uacr_vals = [("2024-01-15", 180), ("2024-07-20", 165), ("2025-03-10", 155), ("2025-12-05", 150)]
    for dt, val in uacr_vals:
        resources.append(("Observation", make_observation(patient_id, "14959-1", "Urine Albumin/Creatinine Ratio", val, "mg/g", dt, ref_high=30)))

    # PTH
    resources.append(("Observation", make_observation(patient_id, "2731-8", "PTH", 95, "pg/mL", "2025-12-05", ref_low=15, ref_high=65)))

    # Phosphorus
    resources.append(("Observation", make_observation(patient_id, "2777-1", "Phosphorus", 5.2, "mg/dL", "2025-12-05", ref_low=2.5, ref_high=4.5)))

    # Calcium
    resources.append(("Observation", make_observation(patient_id, "17861-6", "Calcium", 9.0, "mg/dL", "2025-12-05", ref_low=8.5, ref_high=10.5)))

    # Bicarbonate
    bicarb_vals = [("2024-07-20", 19), ("2025-03-10", 21), ("2025-12-05", 22)]
    for dt, val in bicarb_vals:
        resources.append(("Observation", make_observation(patient_id, "1963-8", "Bicarbonate", val, "mmol/L", dt, ref_low=22, ref_high=29)))

    # A1C
    a1c_vals = [("2023-08-15", 7.5), ("2024-02-10", 7.1), ("2024-08-20", 6.9), ("2025-06-10", 6.8), ("2025-12-05", 6.7)]
    for dt, val in a1c_vals:
        resources.append(("Observation", make_observation(patient_id, "4548-4", "Hemoglobin A1c", val, "%", dt, ref_high=5.7)))

    # --- Vitals ---
    bp_readings = [("2024-07-20", 148, 92), ("2025-03-10", 140, 86), ("2025-12-05", 136, 84)]
    for dt, sys, dia in bp_readings:
        resources.append(("Observation", make_bp(patient_id, sys, dia, dt)))

    resources.append(("Observation", make_vital(patient_id, "29463-7", "Body Weight", 95, "kg", "2025-12-05")))
    resources.append(("Observation", make_vital(patient_id, "8302-2", "Body Height", 182, "cm", "2025-03-10")))
    resources.append(("Observation", make_vital(patient_id, "8867-4", "Heart Rate", 76, "/min", "2025-12-05")))

    # --- Immunizations ---
    immunizations = [
        ("158", "Influenza Vaccine", "2025-10-20"),
        ("213", "COVID-19 mRNA Booster", "2024-10-15"),
        ("33", "Pneumococcal PCV20", "2024-03-10"),
        ("10", "Hepatitis B Vaccine (dose 1)", "2024-05-10"),
        ("10", "Hepatitis B Vaccine (dose 2)", "2024-06-10"),
        ("10", "Hepatitis B Vaccine (dose 3)", "2024-11-10"),
    ]
    for cvx, name, dt in immunizations:
        resources.append(("Immunization", make_immunization(patient_id, cvx, name, dt)))

    # --- Procedures ---
    procedures = [
        ("105376000", "Renal Ultrasound", "2025-06-10", "76770", "Bilateral kidneys 9.5cm. Increased cortical echogenicity consistent with CKD. No hydronephrosis."),
        ("232717009", "AV Fistula Evaluation", "2025-09-15", None, "Vessel mapping completed. Suitable for left radiocephalic fistula when eGFR <20."),
        ("58797008", "Renal Biopsy", "2020-06-01", "50200", "Focal segmental glomerulosclerosis. Moderate interstitial fibrosis/tubular atrophy (40%)."),
        ("252416005", "CT Abdomen/Pelvis without contrast", "2025-08-20", "74176", "No renal calculi. Simple renal cysts bilateral. No masses."),
        ("40701008", "Echocardiogram", "2023-11-01", "93306", "EF 50%, mild LVH. Mild diastolic dysfunction."),
    ]
    for snomed, name, dt, cpt, outcome in procedures:
        resources.append(("Procedure", make_procedure(patient_id, snomed, name, dt, cpt, outcome)))

    # --- Encounters ---
    encounters = [
        ("Nephrology Follow-Up", "2025-12-05", "CKD progression review. eGFR 35. Discussed dialysis preparation.", "AMB"),
        ("Nephrology Follow-Up", "2025-06-10", "CKD monitoring. Renal US ordered.", "AMB"),
        ("PCP Visit", "2025-03-10", "Comprehensive review. Depression stable on escitalopram.", "AMB"),
        ("Emergency Visit - Gout Flare", "2024-07-20", "Acute gout flare left great toe. Colchicine given.", "EMER"),
        ("Nephrology Follow-Up", "2024-01-15", "CKD 3b stable. Anemia management.", "AMB"),
        ("Vascular Surgery Consult", "2025-09-15", "AV fistula planning for future dialysis access.", "AMB"),
        ("Urology Visit", "2025-08-20", "UTI treatment and workup", "AMB"),
    ]
    for enc_type, dt, reason, cls in encounters:
        resources.append(("Encounter", make_encounter(patient_id, enc_type, dt, reason, enc_class=cls)))

    # --- Clinical Notes ---
    notes = [
        ("Nephrology Progress Note", "2025-12-05",
         "45yo M with CKD 3b (FSGS), progressing. eGFR now 35 (was 42 in 2023). Creatinine 2.4. "
         "K+ 5.1 - at upper limit. Consider reducing losartan if rises further. "
         "Anemia improving on EPO - Hgb 11.2. PTH 95 (elevated) - on calcitriol. "
         "Phosphorus 5.2 (high) - sevelamer dose increased. Bicarbonate 22 on supplement. "
         "A1C 6.7 on reduced-dose metformin. Will need transition to non-metformin regimen as eGFR declines. "
         "AV fistula mapping completed - surgical planning when eGFR <20. "
         "Discussed CKD 4 preparation and dialysis modalities. Patient prefers peritoneal dialysis."),
        ("ED Note - Gout Flare", "2024-07-20",
         "45yo M with CKD presents with acute left 1st MTP joint pain, erythema, swelling x2 days. "
         "Uric acid 8.5. NSAIDs contraindicated due to CKD. Given colchicine 1.2mg then 0.6mg. "
         "Pain improved. Allopurinol increased from 100mg to 200mg after flare resolves. "
         "Counseled on dietary modifications, hydration."),
    ]
    for title, dt, content in notes:
        resources.append(("DocumentReference", make_document(patient_id, title, content, dt)))

    return resources


async def create_emily_chen(patient_id: str):
    """Emily Chen - 72yo F - Autoimmune/Endocrine"""
    resources = []

    # --- Conditions ---
    conditions = [
        ("69896004", "Rheumatoid Arthritis", "2008-03-20", "active", "M06.9", "Rheumatoid arthritis, unspecified"),
        ("64859006", "Osteoporosis", "2018-11-15", "active", "M81.0", "Age-related osteoporosis without pathological fracture"),
        ("40930008", "Hypothyroidism", "2012-07-10", "active", "E03.9", "Hypothyroidism, unspecified"),
        ("44054006", "Type 2 Diabetes Mellitus", "2020-01-25", "active", "E11.9", "Type 2 diabetes mellitus"),
        ("233703007", "Interstitial Lung Disease", "2022-06-15", "active", "J84.9", "Interstitial pulmonary disease"),
        ("193570009", "Cataract", "2023-02-10", "resolved", "H26.9", "Cataract - surgically corrected"),
        ("37796009", "Migraine", "2005-01-15", "inactive", "G43.909", "Migraine, unspecified"),
        ("396275006", "Osteoarthritis of Hands", "2015-05-20", "active", "M19.041", "Primary OA of hands"),
        ("13644009", "Hypercholesterolemia", "2016-09-10", "active", "E78.0", "Pure hypercholesterolemia"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(patient_id, code, display, onset, status, icd, icd_display)))

    # --- Medications ---
    medications = [
        ("105586", "Methotrexate 15mg", "15mg by mouth weekly (Monday)", "weekly"),
        ("315362", "Folic Acid 1mg", "1mg by mouth daily (not on MTX day)", "daily"),
        ("352056", "Adalimumab (Humira) 40mg", "40mg subcutaneous injection every two weeks", "biweekly"),
        ("966247", "Levothyroxine 75mcg", "75mcg by mouth daily on empty stomach", "daily"),
        ("996756", "Alendronate 70mg", "70mg by mouth weekly (Sunday), 30min before food", "weekly"),
        ("860975", "Metformin 500mg", "500mg by mouth twice daily", "BID"),
        ("312617", "Prednisone 5mg", "5mg by mouth daily", "daily"),
        ("1364430", "Calcium + Vitamin D 600/400", "600mg calcium with 400IU vitamin D daily", "daily"),
        ("259255", "Atorvastatin 20mg", "20mg by mouth daily at bedtime", "daily"),
        ("261106", "Hydroxychloroquine 200mg", "200mg by mouth twice daily", "BID"),
    ]
    for rxnorm, display, dosage, freq in medications:
        resources.append(("MedicationRequest", make_medication(patient_id, rxnorm, display, dosage, freq)))

    # --- Allergies ---
    allergies = [
        ("Sulfasalazine", "9524", "Hepatotoxicity (elevated LFTs)", "severe", "high"),
        ("Shellfish", None, "Anaphylaxis", "severe", "high", "food", "http://snomed.info/sct"),
        ("Leflunomide", "27169", "Severe diarrhea and nausea", "moderate", "low"),
    ]
    for item in allergies:
        substance, code, reaction, severity, crit = item[:5]
        cat = item[5] if len(item) > 5 else "medication"
        sys = item[6] if len(item) > 6 else "http://www.nlm.nih.gov/research/umls/rxnorm"
        resources.append(("AllergyIntolerance", make_allergy(patient_id, substance, code, reaction, severity, crit, cat, sys)))

    # --- Labs ---
    # ESR/CRP (inflammation markers)
    esr_vals = [("2024-03-15", 42), ("2024-09-20", 35), ("2025-03-10", 28), ("2025-09-15", 22), ("2025-12-10", 20)]
    for dt, val in esr_vals:
        resources.append(("Observation", make_observation(patient_id, "30341-2", "ESR", val, "mm/h", dt, ref_high=20)))

    crp_vals = [("2024-03-15", 18), ("2024-09-20", 12), ("2025-03-10", 8), ("2025-09-15", 5), ("2025-12-10", 4)]
    for dt, val in crp_vals:
        resources.append(("Observation", make_observation(patient_id, "1988-5", "CRP", val, "mg/L", dt, ref_high=3)))

    # CBC w/ diff (MTX monitoring)
    resources.append(("Observation", make_observation(patient_id, "6690-2", "WBC", 5.2, "10*3/uL", "2025-12-10", ref_low=4.5, ref_high=11.0)))
    resources.append(("Observation", make_observation(patient_id, "718-7", "Hemoglobin", 12.5, "g/dL", "2025-12-10", ref_low=12.0, ref_high=16.0)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 198, "10*3/uL", "2025-12-10", ref_low=150, ref_high=400)))
    resources.append(("Observation", make_observation(patient_id, "770-8", "Neutrophils", 3.2, "10*3/uL", "2025-12-10", ref_low=1.5, ref_high=7.0)))
    resources.append(("Observation", make_observation(patient_id, "731-0", "Lymphocytes", 1.5, "10*3/uL", "2025-12-10", ref_low=1.0, ref_high=4.0)))

    # LFTs (MTX monitoring)
    resources.append(("Observation", make_observation(patient_id, "1742-6", "ALT", 28, "U/L", "2025-12-10", ref_low=7, ref_high=56)))
    resources.append(("Observation", make_observation(patient_id, "1920-8", "AST", 25, "U/L", "2025-12-10", ref_low=10, ref_high=40)))
    resources.append(("Observation", make_observation(patient_id, "1975-2", "Bilirubin Total", 0.8, "mg/dL", "2025-12-10", ref_low=0.1, ref_high=1.2)))
    resources.append(("Observation", make_observation(patient_id, "6768-6", "Alkaline Phosphatase", 72, "U/L", "2025-12-10", ref_low=44, ref_high=147)))

    # TSH
    tsh_vals = [("2024-06-15", 5.8), ("2024-12-20", 3.2), ("2025-06-10", 2.8), ("2025-12-10", 2.5)]
    for dt, val in tsh_vals:
        resources.append(("Observation", make_observation(patient_id, "3016-3", "TSH", val, "mIU/L", dt, ref_low=0.4, ref_high=4.0)))

    # Free T4
    resources.append(("Observation", make_observation(patient_id, "3024-7", "Free T4", 1.1, "ng/dL", "2025-12-10", ref_low=0.8, ref_high=1.8)))

    # A1C
    a1c_vals = [("2024-03-15", 7.0), ("2024-09-20", 6.8), ("2025-03-10", 6.6), ("2025-12-10", 6.5)]
    for dt, val in a1c_vals:
        resources.append(("Observation", make_observation(patient_id, "4548-4", "Hemoglobin A1c", val, "%", dt, ref_high=5.7)))

    # RF and Anti-CCP (RA markers)
    resources.append(("Observation", make_observation(patient_id, "11572-5", "Rheumatoid Factor", 85, "IU/mL", "2025-03-10", ref_high=14)))
    resources.append(("Observation", make_observation(patient_id, "53027-9", "Anti-CCP Antibodies", 142, "U/mL", "2025-03-10", ref_high=5)))

    # Vitamin D
    resources.append(("Observation", make_observation(patient_id, "1989-3", "Vitamin D 25-OH", 32, "ng/mL", "2025-12-10", ref_low=30, ref_high=100)))

    # DEXA T-scores (as string values)
    resources.append(("Observation", make_observation(patient_id, "80943-5", "DEXA T-score Lumbar Spine", -2.8, "{T-score}", "2025-01-20")))
    resources.append(("Observation", make_observation(patient_id, "80945-0", "DEXA T-score Femoral Neck", -2.5, "{T-score}", "2025-01-20")))

    # Lipids
    resources.append(("Observation", make_observation(patient_id, "2093-3", "Total Cholesterol", 215, "mg/dL", "2025-12-10", ref_high=200)))
    resources.append(("Observation", make_observation(patient_id, "13457-7", "LDL Calculated", 130, "mg/dL", "2025-12-10", ref_high=100)))

    # --- Vitals ---
    resources.append(("Observation", make_bp(patient_id, 128, 76, "2025-12-10")))
    resources.append(("Observation", make_bp(patient_id, 132, 78, "2025-06-10")))
    resources.append(("Observation", make_vital(patient_id, "29463-7", "Body Weight", 58, "kg", "2025-12-10")))
    resources.append(("Observation", make_vital(patient_id, "8302-2", "Body Height", 155, "cm", "2025-03-10")))
    resources.append(("Observation", make_vital(patient_id, "39156-5", "BMI", 24.1, "kg/m2", "2025-12-10")))
    resources.append(("Observation", make_vital(patient_id, "8867-4", "Heart Rate", 72, "/min", "2025-12-10")))
    resources.append(("Observation", make_vital(patient_id, "2708-6", "Oxygen Saturation", 96, "%", "2025-12-10")))

    # --- Immunizations ---
    immunizations = [
        ("158", "Influenza Vaccine", "2025-10-08"),
        ("158", "Influenza Vaccine", "2024-10-10"),
        ("213", "COVID-19 mRNA Booster", "2024-09-15"),
        ("121", "Zoster (Shingrix) Dose 1", "2023-06-15"),
        ("121", "Zoster (Shingrix) Dose 2", "2023-08-20"),
        ("33", "Pneumococcal PCV20", "2022-12-10"),
        ("115", "Tdap", "2019-04-20"),
    ]
    for cvx, name, dt in immunizations:
        resources.append(("Immunization", make_immunization(patient_id, cvx, name, dt)))

    # --- Procedures ---
    procedures = [
        ("312681000", "DEXA Scan", "2025-01-20", "77080", "Lumbar T-score -2.8, Femoral neck -2.5. Osteoporosis. Continue alendronate."),
        ("168537006", "Hand X-rays Bilateral", "2025-03-10", "73120", "Periarticular erosions MCP 2-4 bilateral. Joint space narrowing. Consistent with RA."),
        ("252416005", "CT Chest High Resolution", "2025-06-10", "71250", "Ground-glass opacities bilateral lower lobes. Mild traction bronchiectasis. Consistent with ILD/UIP pattern."),
        ("54298000", "Cataract Surgery Left Eye", "2023-05-15", "66984", "Phacoemulsification with IOL implant. Uncomplicated."),
        ("54298000", "Cataract Surgery Right Eye", "2023-07-20", "66984", "Phacoemulsification with IOL implant. Uncomplicated."),
        ("399010001", "Corticosteroid Joint Injection - Right Knee", "2025-09-15", "20611", "Triamcinolone 40mg injected into right knee. Good relief."),
        ("127783003", "Pulmonary Function Tests", "2025-06-10", "94010", "FVC 68% predicted. DLCO 62% predicted. Restrictive pattern consistent with ILD."),
        ("312681000", "DEXA Scan", "2023-01-15", "77080", "Lumbar T-score -2.5, Femoral neck -2.2. Osteoporosis diagnosed."),
    ]
    for snomed, name, dt, cpt, outcome in procedures:
        resources.append(("Procedure", make_procedure(patient_id, snomed, name, dt, cpt, outcome)))

    # --- Encounters ---
    encounters = [
        ("Rheumatology Follow-Up", "2025-12-10", "RA disease activity assessment. DAS28 improving.", "AMB"),
        ("Rheumatology Follow-Up", "2025-09-15", "Joint injection right knee. RA management review.", "AMB"),
        ("Pulmonology Follow-Up", "2025-06-10", "ILD monitoring. HRCT and PFTs performed.", "AMB"),
        ("Endocrinology Visit", "2025-03-10", "Thyroid and diabetes management. TSH normalizing.", "AMB"),
        ("DEXA Scan Visit", "2025-01-20", "Bone density assessment", "AMB"),
        ("Ophthalmology Follow-Up", "2024-12-15", "Post-cataract check. Visual acuity 20/25 OU.", "AMB"),
        ("Annual Physical", "2025-01-10", "Annual wellness visit with comprehensive labs", "AMB"),
        ("Rheumatology Follow-Up", "2024-09-20", "Started adalimumab. MTX continued.", "AMB"),
    ]
    for enc_type, dt, reason, cls in encounters:
        resources.append(("Encounter", make_encounter(patient_id, enc_type, dt, reason, enc_class=cls)))

    # --- Clinical Notes ---
    notes = [
        ("Rheumatology Progress Note", "2025-12-10",
         "72yo F with seropositive RA (RF 85, Anti-CCP 142) on MTX 15mg/week + adalimumab + prednisone 5mg. "
         "ESR improved from 42→20, CRP 18→4 over 18 months since adding adalimumab. "
         "Hand X-rays show stable erosions. No new joint damage. "
         "ILD stable on HRCT - ground-glass opacities unchanged. PFTs: FVC 68%, DLCO 62%. "
         "Continue current regimen. Monitor for MTX hepatotoxicity - LFTs normal. "
         "Osteoporosis: T-score -2.8 lumbar. On alendronate + calcium/D. "
         "Cataracts surgically corrected 2023. Steroid-related - monitoring IOP."),
        ("Pulmonology Note", "2025-06-10",
         "72yo F with RA-associated ILD. HRCT shows stable UIP pattern. "
         "FVC 68% predicted (stable from 70% 12 months ago). DLCO 62%. "
         "No oxygen requirement at rest. Desaturates to 91% with exertion. "
         "Continue monitoring Q6 months. Consider nintedanib if progression."),
    ]
    for title, dt, content in notes:
        resources.append(("DocumentReference", make_document(patient_id, title, content, dt)))

    return resources


async def create_james_wilson(patient_id: str):
    """James Wilson - 62yo M - Post-Cardiac Event"""
    resources = []

    # --- Conditions ---
    conditions = [
        ("53741008", "Coronary Artery Disease", "2022-10-15", "active", "I25.10", "Atherosclerotic heart disease of native coronary artery"),
        ("22298006", "Myocardial Infarction (prior)", "2022-10-15", "resolved", "I21.09", "ST elevation MI involving other coronary artery of anterior wall"),
        ("44054006", "Type 2 Diabetes Mellitus", "2018-05-10", "active", "E11.9", "Type 2 diabetes mellitus"),
        ("55822004", "Hyperlipidemia", "2015-03-20", "active", "E78.5", "Hyperlipidemia, unspecified"),
        ("38341003", "Essential Hypertension", "2013-09-15", "active", "I10", "Essential hypertension"),
        ("78275009", "Obstructive Sleep Apnea", "2020-02-10", "active", "G47.33", "Obstructive sleep apnea"),
        ("89765005", "Tobacco Use Disorder (in remission)", "2010-01-01", "inactive", "F17.210", "Nicotine dependence, cigarettes, in remission"),
        ("35489007", "Major Depressive Disorder", "2023-01-20", "active", "F33.0", "MDD, recurrent, mild"),
        ("84114007", "Heart Failure with Reduced EF", "2022-11-01", "active", "I50.22", "Chronic systolic heart failure"),
    ]
    for code, display, onset, status, icd, icd_display in conditions:
        resources.append(("Condition", make_condition(patient_id, code, display, onset, status, icd, icd_display)))

    # --- Medications ---
    medications = [
        ("243670", "Aspirin 81mg", "81mg by mouth daily", "daily"),
        ("309362", "Clopidogrel (Plavix) 75mg", "75mg by mouth daily", "daily"),
        ("866924", "Metoprolol Succinate 50mg", "50mg by mouth twice daily", "BID"),
        ("259255", "Atorvastatin 80mg", "80mg by mouth daily at bedtime", "daily"),
        ("314076", "Lisinopril 20mg", "20mg by mouth daily", "daily"),
        ("860975", "Metformin 1000mg", "1000mg by mouth twice daily", "BID"),
        ("310430", "Nitroglycerin 0.4mg SL", "0.4mg sublingual PRN chest pain", "PRN"),
        ("1232680", "Empagliflozin 10mg", "10mg by mouth daily", "daily"),
        ("248642", "Sertraline 50mg", "50mg by mouth daily", "daily"),
        ("904420", "Ezetimibe 10mg", "10mg by mouth daily", "daily"),
        ("313185", "Spironolactone 25mg", "25mg by mouth daily", "daily"),
    ]
    for rxnorm, display, dosage, freq in medications:
        resources.append(("MedicationRequest", make_medication(patient_id, rxnorm, display, dosage, freq)))

    # --- Allergies ---
    allergies = [
        ("Morphine", "7052", "Severe pruritus and nausea", "moderate", "low"),
        ("Simvastatin", "36567", "Myalgia (switched to atorvastatin)", "mild", "low"),
    ]
    for substance, code, reaction, severity, crit in allergies:
        resources.append(("AllergyIntolerance", make_allergy(patient_id, substance, code, reaction, severity, crit)))

    # --- Labs ---
    # Troponin history (MI event)
    trop_vals = [("2022-10-15T06:00:00", 0.02), ("2022-10-15T10:00:00", 12.5), ("2022-10-15T18:00:00", 28.3), ("2022-10-16T06:00:00", 18.1), ("2022-10-17T06:00:00", 5.2)]
    for dt, val in trop_vals:
        resources.append(("Observation", make_observation(patient_id, "6598-7", "Troponin T", val, "ng/mL", dt, ref_high=0.04)))

    # Lipid panel trend (post-statin)
    lipids = [
        ("2022-10-20", [("2093-3", "Total Cholesterol", 280, "mg/dL"), ("13457-7", "LDL Calculated", 185, "mg/dL"), ("2085-9", "HDL", 35, "mg/dL"), ("2571-8", "Triglycerides", 300, "mg/dL")]),
        ("2023-04-15", [("2093-3", "Total Cholesterol", 195, "mg/dL"), ("13457-7", "LDL Calculated", 110, "mg/dL"), ("2085-9", "HDL", 38, "mg/dL"), ("2571-8", "Triglycerides", 235, "mg/dL")]),
        ("2024-04-20", [("2093-3", "Total Cholesterol", 165, "mg/dL"), ("13457-7", "LDL Calculated", 78, "mg/dL"), ("2085-9", "HDL", 42, "mg/dL"), ("2571-8", "Triglycerides", 180, "mg/dL")]),
        ("2025-04-15", [("2093-3", "Total Cholesterol", 152, "mg/dL"), ("13457-7", "LDL Calculated", 62, "mg/dL"), ("2085-9", "HDL", 45, "mg/dL"), ("2571-8", "Triglycerides", 155, "mg/dL")]),
        ("2025-12-10", [("2093-3", "Total Cholesterol", 148, "mg/dL"), ("13457-7", "LDL Calculated", 58, "mg/dL"), ("2085-9", "HDL", 46, "mg/dL"), ("2571-8", "Triglycerides", 142, "mg/dL")]),
    ]
    for dt, panels in lipids:
        for loinc, name, val, unit in panels:
            ref_high = {"Total Cholesterol": 200, "LDL Calculated": 70, "Triglycerides": 150}.get(name)
            ref_low = {"HDL": 40}.get(name)
            resources.append(("Observation", make_observation(patient_id, loinc, name, val, unit, dt, ref_low=ref_low, ref_high=ref_high)))

    # A1C
    a1c_vals = [("2022-10-20", 8.2), ("2023-04-15", 7.5), ("2024-04-20", 7.0), ("2025-04-15", 6.8), ("2025-12-10", 6.6)]
    for dt, val in a1c_vals:
        resources.append(("Observation", make_observation(patient_id, "4548-4", "Hemoglobin A1c", val, "%", dt, ref_high=5.7)))

    # BNP
    bnp_vals = [("2022-11-01", 850), ("2023-04-15", 420), ("2024-04-20", 280), ("2025-04-15", 210), ("2025-12-10", 180)]
    for dt, val in bnp_vals:
        resources.append(("Observation", make_observation(patient_id, "42637-9", "BNP", val, "pg/mL", dt, ref_high=100)))

    # BMP
    resources.append(("Observation", make_observation(patient_id, "2160-0", "Creatinine", 1.0, "mg/dL", "2025-12-10", ref_low=0.7, ref_high=1.3)))
    resources.append(("Observation", make_observation(patient_id, "33914-3", "eGFR", 82, "mL/min/1.73m2", "2025-12-10", ref_low=60)))
    resources.append(("Observation", make_observation(patient_id, "2823-3", "Potassium", 4.5, "mmol/L", "2025-12-10", ref_low=3.5, ref_high=5.1)))
    resources.append(("Observation", make_observation(patient_id, "2951-2", "Sodium", 141, "mmol/L", "2025-12-10", ref_low=136, ref_high=145)))

    # CBC
    resources.append(("Observation", make_observation(patient_id, "718-7", "Hemoglobin", 14.8, "g/dL", "2025-12-10", ref_low=13.5, ref_high=17.5)))
    resources.append(("Observation", make_observation(patient_id, "777-3", "Platelets", 220, "10*3/uL", "2025-12-10", ref_low=150, ref_high=400)))

    # --- Vitals ---
    bp_readings = [("2022-10-15", 168, 98), ("2023-04-15", 142, 88), ("2024-04-20", 132, 82), ("2025-04-15", 128, 78), ("2025-12-10", 126, 76)]
    for dt, sys, dia in bp_readings:
        resources.append(("Observation", make_bp(patient_id, sys, dia, dt)))

    weight_readings = [("2022-10-20", 105), ("2023-04-15", 100), ("2024-04-20", 96), ("2025-04-15", 93), ("2025-12-10", 91)]
    for dt, val in weight_readings:
        resources.append(("Observation", make_vital(patient_id, "29463-7", "Body Weight", val, "kg", dt)))

    resources.append(("Observation", make_vital(patient_id, "8302-2", "Body Height", 180, "cm", "2023-04-15")))
    resources.append(("Observation", make_vital(patient_id, "39156-5", "BMI", 28.1, "kg/m2", "2025-12-10")))
    resources.append(("Observation", make_vital(patient_id, "8867-4", "Heart Rate", 62, "/min", "2025-12-10")))
    resources.append(("Observation", make_vital(patient_id, "2708-6", "Oxygen Saturation", 97, "%", "2025-12-10")))

    # --- Immunizations ---
    immunizations = [
        ("158", "Influenza Vaccine", "2025-10-12"),
        ("158", "Influenza Vaccine", "2024-10-15"),
        ("213", "COVID-19 mRNA Booster", "2024-10-15"),
        ("33", "Pneumococcal PCV20", "2023-12-10"),
        ("115", "Tdap", "2021-05-20"),
    ]
    for cvx, name, dt in immunizations:
        resources.append(("Immunization", make_immunization(patient_id, cvx, name, dt)))

    # --- Procedures ---
    procedures = [
        ("36969009", "Cardiac Catheterization with PCI", "2022-10-15", "92920",
         "2-vessel CAD. Stents placed in LAD (DES) and RCA (DES). LVEF 35% acutely."),
        ("441829007", "Exercise Stress Test", "2023-10-15", "93015",
         "Bruce protocol 9 minutes. No ischemic ST changes. Adequate exercise capacity. HR 142 (86% predicted)."),
        ("40701008", "Echocardiogram", "2025-04-15", "93306",
         "LVEF 45% (improved from 35% post-MI). Anterior wall hypokinesis. Mild MR."),
        ("40701008", "Echocardiogram", "2023-04-15", "93306",
         "LVEF 40%. Anterior wall hypokinesis. Trace MR. Improved from 35%."),
        ("241615005", "Sleep Study (Polysomnography)", "2020-02-10", "95810",
         "AHI 35 events/hr. Severe OSA. CPAP prescribed at 12 cm H2O."),
        ("252416005", "CT Coronary Calcium Score", "2022-09-01", "75571",
         "Agatston score 450. Moderate coronary calcification."),
        ("431314004", "Cardiac Rehabilitation (completed)", "2023-01-15", "93798",
         "12-week program completed. Improved exercise tolerance. 6MWT: 320→450 meters."),
    ]
    for snomed, name, dt, cpt, outcome in procedures:
        resources.append(("Procedure", make_procedure(patient_id, snomed, name, dt, cpt, outcome)))

    # --- Encounters ---
    encounters = [
        ("Cardiology Follow-Up", "2025-12-10", "Annual cardiology review. EF improved to 45%. Stable.", "AMB"),
        ("Cardiology Follow-Up", "2025-04-15", "Echo performed. EF 45%. Lipids at goal.", "AMB"),
        ("PCP Visit", "2025-06-20", "Diabetes management. A1C 6.8. Weight loss counseling.", "AMB"),
        ("Cardiology Follow-Up", "2024-04-20", "1-year post-MI. Stress test negative.", "AMB"),
        ("Emergency Visit - STEMI", "2022-10-15", "Chest pain, diaphoresis. STEMI confirmed. Emergent cath lab.", "EMER"),
        ("Inpatient - MI", "2022-10-15", "5-day admission for STEMI. PCI with 2 stents. Started GDMT.", "IMP"),
        ("Cardiac Rehab", "2023-01-15", "12-week cardiac rehabilitation program completion", "AMB"),
        ("Sleep Medicine", "2020-02-10", "Sleep study for snoring and daytime somnolence", "AMB"),
        ("Psychiatry Consult", "2023-01-20", "Post-MI depression screening. Started sertraline.", "AMB"),
    ]
    for enc_type, dt, reason, cls in encounters:
        resources.append(("Encounter", make_encounter(patient_id, enc_type, dt, reason, enc_class=cls)))

    # --- Clinical Notes ---
    notes = [
        ("Cardiology Progress Note", "2025-12-10",
         "62yo M with CAD s/p STEMI (2022) with PCI to LAD and RCA, HFrEF (EF 45%, improved from 35%), "
         "T2DM, hyperlipidemia, OSA on CPAP. "
         "Doing well. No chest pain, dyspnea, or palpitations. Exercising 30 min 5x/week. "
         "Weight 91kg (down from 105 post-MI). BP 126/76. HR 62. "
         "Labs: LDL 58 (goal <70 ✓), A1C 6.6, BNP 180 (trending down). "
         "Echo: EF 45%, anterior hypokinesis, mild MR - stable. "
         "Continue DAPT (aspirin + clopidogrel) through 2024-10, then aspirin monotherapy. "
         "Continue atorvastatin 80mg + ezetimibe. Goal LDL <55 achieved. "
         "Continue GDMT: metoprolol, lisinopril, spironolactone, empagliflozin. "
         "Tobacco cessation: quit 2022, no relapse. Excellent commitment. "
         "CPAP compliance >6hrs/night. OSA well-controlled."),
        ("ED Note - STEMI", "2022-10-15",
         "62yo M presenting with crushing substernal chest pain radiating to left arm x2 hours. "
         "Diaphoretic, nauseous. ECG: ST elevation V1-V4. Troponin 12.5 (repeat 28.3). "
         "Activated cath lab. Heparin bolus, aspirin 325mg, clopidogrel 600mg loading. "
         "Cath: 95% LAD stenosis, 80% RCA stenosis. DES placed in both. "
         "Post-PCI: TIMI 3 flow. EF 35% on ventriculogram. "
         "Admitted to CCU. Started metoprolol, lisinopril, atorvastatin 80mg."),
        ("Cardiac Rehab Completion Note", "2023-01-15",
         "62yo M completed 12-week cardiac rehabilitation post-STEMI. "
         "6-minute walk test improved from 320m to 450m. Peak VO2 improved 22%. "
         "HR recovery improved. No ischemic symptoms during exercise. "
         "Patient motivated. Plans to continue independent exercise program."),
    ]
    for title, dt, content in notes:
        resources.append(("DocumentReference", make_document(patient_id, title, content, dt)))

    return resources


# =============================================================================
# Main Seeding Logic
# =============================================================================

PATIENT_PROFILES = [
    {
        "given": "John", "family": "Smith", "gender": "male", "birthDate": "1970-01-15",
        "phone": "555-0101", "mrn": "MRN-10001",
        "address": {"line": ["123 Oak Street"], "city": "Springfield", "state": "IL", "postalCode": "62701", "country": "US"},
        "creator": create_john_smith,
    },
    {
        "given": "Maria", "family": "Garcia", "gender": "female", "birthDate": "1958-04-22",
        "phone": "555-0102", "mrn": "MRN-10002",
        "address": {"line": ["456 Elm Avenue"], "city": "Chicago", "state": "IL", "postalCode": "60614", "country": "US"},
        "creator": create_maria_garcia,
    },
    {
        "given": "Robert", "family": "Johnson", "gender": "male", "birthDate": "1981-09-08",
        "phone": "555-0103", "mrn": "MRN-10003",
        "address": {"line": ["789 Pine Road"], "city": "Evanston", "state": "IL", "postalCode": "60201", "country": "US"},
        "creator": create_robert_johnson,
    },
    {
        "given": "Emily", "family": "Chen", "gender": "female", "birthDate": "1954-06-30",
        "phone": "555-0104", "mrn": "MRN-10004",
        "address": {"line": ["321 Maple Drive"], "city": "Naperville", "state": "IL", "postalCode": "60540", "country": "US"},
        "creator": create_emily_chen,
    },
    {
        "given": "James", "family": "Wilson", "gender": "male", "birthDate": "1964-03-12",
        "phone": "555-0105", "mrn": "MRN-10005",
        "address": {"line": ["654 Cedar Lane"], "city": "Aurora", "state": "IL", "postalCode": "60502", "country": "US"},
        "creator": create_james_wilson,
    },
]

INPATIENT_PROFILES = [
    {
        "given": "Dorothy", "family": "Turner", "gender": "female", "birthDate": "1954-03-18",
        "phone": "555-0201", "mrn": "MRN-20001",
        "address": {"line": ["100 Hospital Drive"], "city": "Springfield", "state": "IL", "postalCode": "62701", "country": "US"},
        "admit_dt": datetime(2026, 2, 24, 14, 0, tzinfo=timezone.utc),
        "encounter_builder": lambda pid, adt=datetime(2026, 2, 24, 14, 0, tzinfo=timezone.utc): make_inpatient_encounter(pid, "Fever, altered mental status, UTI", "ED Bay 4", "EM", adt, "emd"),
        "scenario_creator": create_sepsis_scenario,
    },
    {
        "given": "Michael", "family": "Romano", "gender": "male", "birthDate": "1968-07-22",
        "phone": "555-0202", "mrn": "MRN-20002",
        "address": {"line": ["225 State Street"], "city": "Chicago", "state": "IL", "postalCode": "60601", "country": "US"},
        "admit_dt": datetime(2026, 2, 25, 2, 30, tzinfo=timezone.utc),
        "encounter_builder": lambda pid, adt=datetime(2026, 2, 25, 2, 30, tzinfo=timezone.utc): make_inpatient_encounter(pid, "Acute chest pain, ST elevation", "ED Bay 1 - Trauma/Cardiac", "EM", adt, "emd"),
        "scenario_creator": create_cardiac_scenario,
    },
    {
        "given": "Harold", "family": "Washington", "gender": "male", "birthDate": "1959-11-05",
        "phone": "555-0203", "mrn": "MRN-20003",
        "address": {"line": ["890 Lakeview Blvd"], "city": "Evanston", "state": "IL", "postalCode": "60201", "country": "US"},
        "admit_dt": datetime(2026, 2, 24, 8, 0, tzinfo=timezone.utc),
        "encounter_builder": lambda pid, adt=datetime(2026, 2, 24, 8, 0, tzinfo=timezone.utc): make_inpatient_encounter(pid, "Acute kidney injury, dehydration, hyperkalemia", "Medicine Ward 3B", "UR", adt),
        "scenario_creator": create_renal_scenario,
    },
    {
        "given": "Susan", "family": "Park", "gender": "female", "birthDate": "1971-05-14",
        "phone": "555-0204", "mrn": "MRN-20004",
        "address": {"line": ["412 Magnolia Court"], "city": "Naperville", "state": "IL", "postalCode": "60540", "country": "US"},
        "admit_dt": datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc),
        "encounter_builder": lambda pid, adt=datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc): make_inpatient_encounter(pid, "Acute dyspnea, pleuritic chest pain, hypoxia", "ED Bay 6", "EM", adt, "emd"),
        "scenario_creator": create_pulmonary_scenario,
    },
    {
        "given": "William", "family": "Harris", "gender": "male", "birthDate": "1951-01-28",
        "phone": "555-0205", "mrn": "MRN-20005",
        "address": {"line": ["567 Oak Park Avenue"], "city": "Aurora", "state": "IL", "postalCode": "60502", "country": "US"},
        "admit_dt": datetime(2026, 2, 23, 20, 0, tzinfo=timezone.utc),
        "encounter_builder": lambda pid, adt=datetime(2026, 2, 23, 20, 0, tzinfo=timezone.utc): make_inpatient_encounter(pid, "Sepsis, pneumonia, respiratory failure, AKI", "ICU Room 12", "EM", adt, "emd"),
        "scenario_creator": create_multisystem_scenario,
    },
]


async def find_or_create_patient(profile: dict) -> str:
    """Search for existing patient by name, or create new one."""
    given = profile["given"]
    family = profile["family"]

    # Search for existing patient
    result = await fhir_client.search("Patient", {"given": given, "family": family})
    entries = result.get("entry", [])

    if entries:
        patient_id = entries[0]["resource"]["id"]
        print(f"  Found existing patient: {given} {family} (ID: {patient_id})")
        return patient_id

    # Create new patient
    patient_resource = make_patient(
        given=given,
        family=family,
        gender=profile["gender"],
        birth_date=profile["birthDate"],
        phone=profile.get("phone"),
        address=profile.get("address"),
        mrn=profile.get("mrn"),
    )
    result = await fhir_client.create("Patient", patient_resource)
    patient_id = result["id"]
    print(f"  Created new patient: {given} {family} (ID: {patient_id})")
    return patient_id


async def seed_patient(profile: dict) -> dict:
    """Seed a single patient with all their clinical data."""
    given = profile["given"]
    family = profile["family"]
    creator = profile["creator"]

    print(f"\n{'='*60}")
    print(f"Seeding: {given} {family}")
    print(f"{'='*60}")

    # Find or create patient
    patient_id = await find_or_create_patient(profile)

    # Generate all resources
    resources = await creator(patient_id)
    print(f"  Generating {len(resources)} clinical resources...")

    # Create resources in batches
    created = 0
    errors = 0
    for resource_type, resource in resources:
        try:
            await fhir_client.create(resource_type, resource)
            created += 1
        except Exception as e:
            errors += 1
            if errors <= 3:  # Only print first few errors per patient
                print(f"  ERROR creating {resource_type}: {e}")

    print(f"  Created: {created}/{len(resources)} resources ({errors} errors)")
    return {"patient_id": patient_id, "name": f"{given} {family}", "created": created, "errors": errors}


async def main():
    print("=" * 60)
    print("AgentEHR - Synthetic Patient Data Seeder")
    print("=" * 60)
    print(f"FHIR Server: {fhir_client.base_url}")
    print(f"Outpatient patients to seed: {len(PATIENT_PROFILES)}")
    print(f"Inpatient scenarios to seed: {len(INPATIENT_PROFILES)}")

    results = []
    total_created = 0
    total_errors = 0

    # Seed outpatient patients
    print(f"\n{'='*60}")
    print("Seeding Outpatient Patients")
    print(f"{'='*60}")

    for profile in PATIENT_PROFILES:
        result = await seed_patient(profile)
        results.append(result)
        total_created += result["created"]
        total_errors += result["errors"]

    # Seed inpatient patients
    print(f"\n{'='*60}")
    print("Seeding Inpatient Encounters")
    print(f"{'='*60}")
    print(f"Inpatient scenarios to seed: {len(INPATIENT_PROFILES)}")

    inpatient_results = []
    for profile in INPATIENT_PROFILES:
        result = await seed_inpatient_patient(profile)
        inpatient_results.append(result)
        total_created += result["created"]
        total_errors += result["errors"]

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"\n  Outpatient patients:")
    for r in results:
        status = "OK" if r["errors"] == 0 else f"{r['errors']} ERRORS"
        print(f"    {r['name']}: {r['created']} resources [{status}]")

    print(f"\n  Inpatient encounters:")
    for r in inpatient_results:
        status = "OK" if r["errors"] == 0 else f"{r['errors']} ERRORS"
        print(f"    {r['name']}: {r['created']} resources, Encounter ID: {r['encounter_id']} [{status}]")

    print(f"\n  Total: {total_created} resources created, {total_errors} errors")
    print(f"{'='*60}")

    # Cleanup
    await fhir_client.close()


if __name__ == "__main__":
    asyncio.run(main())
