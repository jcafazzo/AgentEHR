#!/usr/bin/env python3
"""
FHIR Tool Handlers for AgentEHR

This module contains the business logic for FHIR operations.
It's separate from server.py so it can be imported without MCP dependencies.
"""

import asyncio
import json
import logging
from typing import Any

import httpx
from pydantic_settings import BaseSettings

# Configure logging
logger = logging.getLogger("fhir-mcp-server.handlers")


class Settings(BaseSettings):
    """Server configuration from environment variables."""

    fhir_server_base_url: str = "http://localhost:8103/fhir/R4"
    fhir_server_access_token: str | None = None
    fhir_server_email: str = "admin@agentehr.local"
    fhir_server_password: str = "medplum123"

    class Config:
        env_prefix = "FHIR_SERVER_"


settings = Settings()

# Import auth module
from auth import MedplumAuth

# Import approval queue
from approval_queue import (
    get_approval_queue,
    ActionType,
    ActionStatus,
    ValidationWarning,
)

# Import drug interaction validation
from validation.drug_interactions import validate_medication_safety

# Initialize auth helper
_auth: MedplumAuth | None = None


async def get_auth() -> MedplumAuth:
    """Get or create auth instance."""
    global _auth
    if _auth is None:
        base_url = settings.fhir_server_base_url.replace("/fhir/R4", "")
        _auth = MedplumAuth(
            base_url=base_url,
            email=settings.fhir_server_email,
            password=settings.fhir_server_password,
        )
    return _auth


class FHIRClient:
    """HTTP client for FHIR R4 server operations."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        auth = await get_auth()
        access_token = await auth.get_access_token()

        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
            )

        self._client.headers.update({
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
            "Authorization": f"Bearer {access_token}",
        })

        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()

    async def search(
        self,
        resource_type: str,
        params: dict[str, Any] | None = None,
    ) -> dict:
        """Search for FHIR resources."""
        client = await self._get_client()
        response = await client.get(f"/{resource_type}", params=params or {})
        response.raise_for_status()
        return response.json()

    async def read(self, resource_type: str, resource_id: str) -> dict:
        """Read a specific FHIR resource by ID."""
        client = await self._get_client()
        response = await client.get(f"/{resource_type}/{resource_id}")
        response.raise_for_status()
        return response.json()

    async def create(self, resource_type: str, resource: dict) -> dict:
        """Create a new FHIR resource."""
        client = await self._get_client()
        response = await client.post(f"/{resource_type}", json=resource)
        response.raise_for_status()
        return response.json()

    async def update(
        self,
        resource_type: str,
        resource_id: str,
        resource: dict,
    ) -> dict:
        """Update an existing FHIR resource."""
        client = await self._get_client()
        response = await client.put(
            f"/{resource_type}/{resource_id}",
            json=resource,
        )
        response.raise_for_status()
        return response.json()

    async def delete(self, resource_type: str, resource_id: str) -> None:
        """Delete a FHIR resource."""
        client = await self._get_client()
        response = await client.delete(f"/{resource_type}/{resource_id}")
        response.raise_for_status()

    async def get_patient_everything(self, patient_id: str) -> dict:
        """Get all data for a patient ($everything operation)."""
        client = await self._get_client()
        response = await client.get(f"/Patient/{patient_id}/$everything")
        response.raise_for_status()
        return response.json()


# Initialize FHIR client
fhir_client = FHIRClient(
    base_url=settings.fhir_server_base_url,
)


# =============================================================================
# Tool Handlers
# =============================================================================

async def handle_search_patient(args: dict) -> dict:
    """Search for patients."""
    params = {}
    if name := args.get("name"):
        params["name"] = name
    if query := args.get("query"):  # Support 'query' parameter for CLI compatibility
        params["name"] = query
    if identifier := args.get("identifier"):
        params["identifier"] = identifier
    if birthdate := args.get("birthdate"):
        params["birthdate"] = birthdate
    if gender := args.get("gender"):
        params["gender"] = gender

    bundle = await fhir_client.search("Patient", params)

    patients = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        patient = {
            "id": resource.get("id"),
            "name": format_name(resource.get("name", [])),
            "birthDate": resource.get("birthDate"),
            "gender": resource.get("gender"),
            "identifier": format_identifiers(resource.get("identifier", [])),
        }
        patients.append(patient)

    return {
        "total": bundle.get("total", len(patients)),
        "patients": patients,
    }


async def handle_get_patient(args: dict) -> dict:
    """Get a specific patient."""
    patient_id = args["patient_id"]
    resource = await fhir_client.read("Patient", patient_id)

    return {
        "id": resource.get("id"),
        "name": format_name(resource.get("name", [])),
        "birthDate": resource.get("birthDate"),
        "gender": resource.get("gender"),
        "identifier": format_identifiers(resource.get("identifier", [])),
        "address": format_address(resource.get("address", [])),
        "telecom": format_telecom(resource.get("telecom", [])),
    }


async def handle_get_patient_summary(args: dict) -> dict:
    """Get comprehensive patient summary with all clinical data."""
    patient_id = args["patient_id"]
    from datetime import datetime, timedelta

    # Fetch all data in parallel
    patient_task = fhir_client.read("Patient", patient_id)
    conditions_task = fhir_client.search("Condition", {"patient": patient_id})
    medications_task = fhir_client.search("MedicationRequest", {"patient": patient_id, "status": "active"})
    allergies_task = fhir_client.search("AllergyIntolerance", {"patient": patient_id})
    observations_task = fhir_client.search("Observation", {
        "patient": patient_id,
        "_sort": "-date",
        "_count": "100"
    })
    procedures_task = fhir_client.search("Procedure", {
        "patient": patient_id,
        "_sort": "-date",
        "_count": "20"
    })
    immunizations_task = fhir_client.search("Immunization", {"patient": patient_id})
    encounters_task = fhir_client.search("Encounter", {
        "patient": patient_id,
        "_sort": "-date",
        "_count": "10"
    })
    documents_task = fhir_client.search("DocumentReference", {
        "patient": patient_id,
        "_sort": "-date",
        "_count": "10"
    })

    (patient, conditions, medications, allergies, observations,
     procedures, immunizations, encounters, documents) = await asyncio.gather(
        patient_task, conditions_task, medications_task, allergies_task,
        observations_task, procedures_task, immunizations_task,
        encounters_task, documents_task,
        return_exceptions=True,
    )

    # Calculate age
    age = None
    birth_date = patient.get("birthDate") if isinstance(patient, dict) else None
    if birth_date:
        try:
            birth = datetime.strptime(birth_date, "%Y-%m-%d")
            age = (datetime.now() - birth).days // 365
        except ValueError:
            pass

    summary = {
        "patient": {
            "id": patient.get("id") if isinstance(patient, dict) else patient_id,
            "name": format_name(patient.get("name", [])) if isinstance(patient, dict) else "Unknown",
            "birthDate": birth_date,
            "age": age,
            "gender": patient.get("gender") if isinstance(patient, dict) else None,
            "mrn": _extract_mrn(patient) if isinstance(patient, dict) else None,
        },
        "conditions": [],
        "medications": [],
        "allergies": [],
        "labs": [],
        "vitals": [],
        "immunizations": [],
        "procedures": [],
        "encounters": [],
        "clinicalNotes": [],
        "careGaps": [],
        "incompleteData": [],
    }

    # Process conditions
    if isinstance(conditions, dict):
        for entry in conditions.get("entry", []):
            resource = entry.get("resource", {})
            status = extract_code_display(resource.get("clinicalStatus"))
            condition = {
                "id": resource.get("id"),
                "code": extract_code_display(resource.get("code")),
                "status": status,
                "onsetDate": resource.get("onsetDateTime"),
                "isActive": status.lower() == "active",
            }
            summary["conditions"].append(condition)

    # Process medications
    if isinstance(medications, dict):
        for entry in medications.get("entry", []):
            resource = entry.get("resource", {})
            med = {
                "id": resource.get("id"),
                "medication": extract_medication_name(resource),
                "dosage": extract_dosage(resource),
                "status": resource.get("status"),
            }
            summary["medications"].append(med)

    # Process allergies
    if isinstance(allergies, dict):
        for entry in allergies.get("entry", []):
            resource = entry.get("resource", {})
            allergy = {
                "id": resource.get("id"),
                "substance": extract_code_display(resource.get("code")),
                "reaction": extract_reaction(resource),
                "criticality": resource.get("criticality"),
                "category": resource.get("category", [None])[0] if resource.get("category") else None,
            }
            summary["allergies"].append(allergy)

    # Process observations - separate labs from vitals
    if isinstance(observations, dict):
        for entry in observations.get("entry", []):
            resource = entry.get("resource", {})
            categories = resource.get("category", [])

            is_lab = False
            is_vital = False
            for cat in categories:
                for coding in cat.get("coding", []):
                    code = coding.get("code", "")
                    if code == "laboratory":
                        is_lab = True
                    elif code == "vital-signs":
                        is_vital = True

            obs = {
                "id": resource.get("id"),
                "code": extract_code_display(resource.get("code")),
                "value": extract_observation_value(resource),
                "date": resource.get("effectiveDateTime", "")[:10] if resource.get("effectiveDateTime") else None,
                "status": resource.get("status"),
            }

            if is_lab:
                summary["labs"].append(obs)
            elif is_vital:
                summary["vitals"].append(obs)

    # Process procedures
    if isinstance(procedures, dict):
        for entry in procedures.get("entry", []):
            resource = entry.get("resource", {})
            procedure = {
                "id": resource.get("id"),
                "name": extract_code_display(resource.get("code")),
                "date": resource.get("performedDateTime", "")[:10] if resource.get("performedDateTime") else None,
                "status": resource.get("status"),
            }
            summary["procedures"].append(procedure)

    # Process immunizations
    if isinstance(immunizations, dict):
        for entry in immunizations.get("entry", []):
            resource = entry.get("resource", {})
            immunization = {
                "id": resource.get("id"),
                "vaccine": extract_code_display(resource.get("vaccineCode")),
                "date": resource.get("occurrenceDateTime", "")[:10] if resource.get("occurrenceDateTime") else None,
                "status": resource.get("status"),
            }
            summary["immunizations"].append(immunization)

    # Process encounters
    if isinstance(encounters, dict):
        for entry in encounters.get("entry", []):
            resource = entry.get("resource", {})
            encounter = {
                "id": resource.get("id"),
                "type": extract_code_display(resource.get("type", [{}])[0] if resource.get("type") else {}),
                "status": resource.get("status"),
                "date": resource.get("period", {}).get("start", "")[:10] if resource.get("period") else None,
            }
            summary["encounters"].append(encounter)

    # Process clinical notes
    if isinstance(documents, dict):
        for entry in documents.get("entry", []):
            resource = entry.get("resource", {})
            note = {
                "id": resource.get("id"),
                "type": extract_code_display(resource.get("type")),
                "description": resource.get("description"),
                "date": resource.get("date", "")[:10] if resource.get("date") else None,
                "status": resource.get("status"),
            }
            summary["clinicalNotes"].append(note)

    # Analyze care gaps
    summary["careGaps"] = _analyze_care_gaps(summary, age)

    # Identify incomplete data
    summary["incompleteData"] = _identify_incomplete_data(summary)

    return summary


def _extract_mrn(patient: dict) -> str | None:
    """Extract MRN from patient identifiers."""
    for identifier in patient.get("identifier", []):
        if "MRN" in identifier.get("type", {}).get("text", "").upper():
            return identifier.get("value")
        if "MR" in (identifier.get("type", {}).get("coding", [{}])[0].get("code", "") or "").upper():
            return identifier.get("value")
    # Fall back to first identifier
    if patient.get("identifier"):
        return patient["identifier"][0].get("value")
    return None


def _analyze_care_gaps(summary: dict, age: int | None) -> list:
    """Identify care gaps based on clinical data."""
    gaps = []

    # Check immunizations
    vaccines_received = [(i.get("vaccine") or "").lower() for i in summary.get("immunizations", []) if i.get("status") == "completed"]

    # Flu vaccine
    if not any("influenza" in v or "flu" in v for v in vaccines_received):
        gaps.append({
            "type": "immunization",
            "description": "Flu vaccine may be due",
            "priority": "routine",
        })

    # COVID-19
    if not any("covid" in v or "sars-cov" in v for v in vaccines_received):
        gaps.append({
            "type": "immunization",
            "description": "COVID-19 vaccine may be due",
            "priority": "routine",
        })

    # Age-based recommendations
    if age and age >= 50:
        if not any("zoster" in v or "shingrix" in v for v in vaccines_received):
            gaps.append({
                "type": "immunization",
                "description": "Shingles vaccine recommended for age 50+",
                "priority": "routine",
            })

    if age and age >= 65:
        if not any("pneum" in v for v in vaccines_received):
            gaps.append({
                "type": "immunization",
                "description": "Pneumococcal vaccine recommended for age 65+",
                "priority": "routine",
            })

    # Check for diabetic care gaps
    conditions = [(c.get("code") or "").lower() for c in summary.get("conditions", []) if c.get("isActive")]
    if any("diabetes" in c or "dm" in c or "a1c" in c for c in conditions):
        # Check for recent A1C
        labs = summary.get("labs", [])
        a1c_labs = [l for l in labs if "a1c" in l.get("code", "").lower() or "hemoglobin" in l.get("code", "").lower()]
        if not a1c_labs:
            gaps.append({
                "type": "lab",
                "description": "A1C may be due (diabetic monitoring)",
                "priority": "routine",
            })

        # Check for eye exam (annually)
        if not any("eye" in p.get("name", "").lower() or "ophth" in p.get("name", "").lower()
                   for p in summary.get("procedures", [])):
            gaps.append({
                "type": "referral",
                "description": "Diabetic eye exam may be due",
                "priority": "routine",
            })

    return gaps


def _identify_incomplete_data(summary: dict) -> list:
    """Identify missing or incomplete data in the patient record."""
    incomplete = []

    # No allergies documented
    if not summary.get("allergies"):
        incomplete.append({
            "field": "allergies",
            "message": "No allergies documented - confirm NKDA or document allergies",
            "priority": "high",
        })

    # No conditions
    if not summary.get("conditions"):
        incomplete.append({
            "field": "conditions",
            "message": "No conditions documented",
            "priority": "medium",
        })

    # No recent vitals
    if not summary.get("vitals"):
        incomplete.append({
            "field": "vitals",
            "message": "No vital signs on record",
            "priority": "low",
        })

    return incomplete


async def handle_search_medications(args: dict) -> dict:
    """Search for patient medications."""
    patient_id = args["patient_id"]
    status = args.get("status", "active")

    params = {"patient": patient_id}
    if status:
        params["status"] = status

    bundle = await fhir_client.search("MedicationRequest", params)

    medications = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        med = {
            "id": resource.get("id"),
            "medication": extract_medication_name(resource),
            "status": resource.get("status"),
            "dosage": extract_dosage(resource),
            "authoredOn": resource.get("authoredOn"),
        }
        medications.append(med)

    return {
        "total": bundle.get("total", len(medications)),
        "medications": medications,
    }


async def handle_create_medication_request(args: dict) -> dict:
    """Create a medication request (draft for approval)."""
    patient_id = args["patient_id"]
    medication_name = args["medication_name"]

    current_meds_bundle = await fhir_client.search(
        "MedicationRequest",
        {"patient": patient_id, "status": "active"}
    )
    current_medications = []
    for entry in current_meds_bundle.get("entry", []):
        resource = entry.get("resource", {})
        med_name = extract_medication_name(resource)
        if med_name and med_name != "Unknown":
            current_medications.append(med_name)

    allergies_bundle = await fhir_client.search(
        "AllergyIntolerance",
        {"patient": patient_id}
    )
    allergies = []
    for entry in allergies_bundle.get("entry", []):
        resource = entry.get("resource", {})
        if code := resource.get("code"):
            allergy_name = extract_code_display(code)
            if allergy_name and allergy_name != "Unknown":
                allergies.append(allergy_name)

    safety_result = validate_medication_safety(
        medication_name=medication_name,
        current_medications=current_medications,
        allergies=allergies,
    )

    validation_warnings = []
    for warning in safety_result.get("warnings", []):
        validation_warnings.append(ValidationWarning(
            severity=warning["severity"],
            code=warning["code"],
            message=warning["message"],
            details=warning.get("details", {}),
        ))

    medication_request = {
        "resourceType": "MedicationRequest",
        "status": "draft",
        "intent": "order",
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "medicationCodeableConcept": {
            "text": medication_name,
        },
        "dosageInstruction": [
            {
                "text": f"{args['dosage']} {args['frequency']}",
                "doseAndRate": [
                    {
                        "doseQuantity": {
                            "value": parse_dose_value(args["dosage"]),
                            "unit": parse_dose_unit(args["dosage"]),
                        },
                    },
                ],
            },
        ],
    }

    if route := args.get("route"):
        medication_request["dosageInstruction"][0]["route"] = {
            "text": route,
        }

    if instructions := args.get("instructions"):
        medication_request["dosageInstruction"][0]["patientInstruction"] = instructions

    result = await fhir_client.create("MedicationRequest", medication_request)
    fhir_id = result.get("id")

    summary = f"Order {medication_name} {args['dosage']} {args['frequency']}"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.MEDICATION_REQUEST,
        patient_id=patient_id,
        resource=medication_request,
        fhir_id=fhir_id,
        summary=summary,
        warnings=validation_warnings,
        metadata={
            "requester": "agent",
            "current_medications": current_medications,
            "allergies": allergies,
        },
    )

    response = {
        "status": "draft",
        "message": "Medication order created as DRAFT. Requires clinician approval.",
        "action_id": action.action_id,
        "medicationRequest": {
            "id": fhir_id,
            "medication": medication_name,
            "dosage": args["dosage"],
            "frequency": args["frequency"],
            "route": args.get("route"),
            "instructions": args.get("instructions"),
        },
        "safety": {
            "checked": True,
            "safe": safety_result["safe"],
            "warning_count": safety_result["warning_count"],
        },
    }

    if validation_warnings:
        response["warnings"] = [
            {
                "severity": w.severity,
                "code": w.code,
                "message": w.message,
                "details": w.details,
            }
            for w in validation_warnings
        ]

        if safety_result["requires_override"]:
            response["message"] = "⚠️ CONTRAINDICATED: Medication order created but has serious safety concerns. Review warnings carefully."
        elif safety_result["requires_attention"]:
            response["message"] = "⚠️ WARNING: Medication order created with safety warnings. Review before approval."

    return response


async def handle_search_observations(args: dict) -> dict:
    """Search for patient observations."""
    patient_id = args["patient_id"]

    params = {"patient": patient_id}
    if category := args.get("category"):
        params["category"] = category
    if code := args.get("code"):
        params["code"] = code
    if date_from := args.get("date_from"):
        params["date"] = f"ge{date_from}"

    bundle = await fhir_client.search("Observation", params)

    observations = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        obs = {
            "id": resource.get("id"),
            "code": extract_code_display(resource.get("code")),
            "value": extract_observation_value(resource),
            "effectiveDateTime": resource.get("effectiveDateTime"),
            "status": resource.get("status"),
        }
        observations.append(obs)

    return {
        "total": bundle.get("total", len(observations)),
        "observations": observations,
    }


async def handle_search_conditions(args: dict) -> dict:
    """Search for patient conditions."""
    patient_id = args["patient_id"]

    params = {"patient": patient_id}
    if status := args.get("clinical_status"):
        params["clinical-status"] = status

    bundle = await fhir_client.search("Condition", params)

    conditions = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        condition = {
            "id": resource.get("id"),
            "code": extract_code_display(resource.get("code")),
            "clinicalStatus": extract_code_display(resource.get("clinicalStatus")),
            "onsetDateTime": resource.get("onsetDateTime"),
            "recordedDate": resource.get("recordedDate"),
        }
        conditions.append(condition)

    return {
        "total": bundle.get("total", len(conditions)),
        "conditions": conditions,
    }


async def handle_search_encounters(args: dict) -> dict:
    """Search for patient encounters."""
    patient_id = args["patient_id"]

    params = {"patient": patient_id}
    if status := args.get("status"):
        params["status"] = status
    if date_from := args.get("date_from"):
        params["date"] = f"ge{date_from}"

    bundle = await fhir_client.search("Encounter", params)

    encounters = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        encounter = {
            "id": resource.get("id"),
            "status": resource.get("status"),
            "class": resource.get("class", {}).get("display"),
            "type": extract_code_display(resource.get("type", [{}])[0] if resource.get("type") else {}),
            "period": resource.get("period"),
        }
        encounters.append(encounter)

    return {
        "total": bundle.get("total", len(encounters)),
        "encounters": encounters,
    }


async def handle_search_clinical_notes(args: dict) -> dict:
    """Search for clinical notes (DocumentReferences) for a patient."""
    patient_id = args["patient_id"]

    params = {
        "patient": patient_id,
        "_sort": "-date",
        "_count": args.get("count", "20"),
    }
    if note_type := args.get("note_type"):
        type_codes = {
            "progress_note": "11506-3",
            "history_physical": "34117-2",
            "discharge_summary": "18842-5",
            "consultation": "11488-4",
            "procedure_note": "28570-0",
        }
        if code := type_codes.get(note_type):
            params["type"] = f"http://loinc.org|{code}"

    bundle = await fhir_client.search("DocumentReference", params)

    notes = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        note = {
            "id": resource.get("id"),
            "type": extract_code_display(resource.get("type")),
            "description": resource.get("description"),
            "date": resource.get("date", "")[:10] if resource.get("date") else None,
            "status": resource.get("status"),
            "author": resource.get("author", [{}])[0].get("display") if resource.get("author") else None,
        }
        notes.append(note)

    return {
        "total": bundle.get("total", len(notes)),
        "notes": notes,
    }


async def handle_get_clinical_note(args: dict) -> dict:
    """Get a specific clinical note with its full content."""
    import base64

    note_id = args["note_id"]

    try:
        resource = await fhir_client.read("DocumentReference", note_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Clinical note {note_id} not found"}
        raise

    content_text = ""
    for content_item in resource.get("content", []):
        attachment = content_item.get("attachment", {})
        if data := attachment.get("data"):
            try:
                content_text = base64.b64decode(data).decode("utf-8")
            except Exception:
                content_text = "(Unable to decode note content)"
        elif url := attachment.get("url"):
            content_text = f"(Content at: {url})"

    return {
        "id": resource.get("id"),
        "type": extract_code_display(resource.get("type")),
        "description": resource.get("description"),
        "date": resource.get("date"),
        "status": resource.get("status"),
        "content": content_text,
        "author": resource.get("author", [{}])[0].get("display") if resource.get("author") else None,
    }


async def handle_create_care_plan(args: dict) -> dict:
    """Create a care plan."""
    patient_id = args["patient_id"]

    care_plan = {
        "resourceType": "CarePlan",
        "status": "draft",
        "intent": "plan",
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "title": args["title"],
    }

    if description := args.get("description"):
        care_plan["description"] = description

    if goals := args.get("goals"):
        care_plan["goal"] = [{"description": {"text": g}} for g in goals]

    if activities := args.get("activities"):
        care_plan["activity"] = [
            {"detail": {"description": a, "status": "not-started"}}
            for a in activities
        ]

    result = await fhir_client.create("CarePlan", care_plan)
    fhir_id = result.get("id")

    summary = f"Care plan: {args['title']}"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.CARE_PLAN,
        patient_id=patient_id,
        resource=care_plan,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent"},
    )

    return {
        "status": "draft",
        "message": "Care plan created as DRAFT. Requires clinician approval.",
        "action_id": action.action_id,
        "carePlan": {
            "id": fhir_id,
            "title": args["title"],
            "goals": args.get("goals", []),
            "activities": args.get("activities", []),
        },
    }


async def handle_create_appointment(args: dict) -> dict:
    """Create an appointment."""
    patient_id = args["patient_id"]
    reason = args["reason"]

    # Build description with notes if provided
    description = reason
    if notes := args.get("notes"):
        description += f" — {notes}"

    appointment = {
        "resourceType": "Appointment",
        "status": "proposed",
        "participant": [
            {
                "actor": {"reference": f"Patient/{patient_id}"},
                "status": "needs-action",
            },
        ],
        "description": description,
    }

    # Appointment type with specialty qualifier
    appt_type = args.get("appointment_type", "routine")
    specialty = args.get("specialty")
    type_text = appt_type
    if specialty:
        type_text = f"{appt_type} — {specialty}"
    appointment["appointmentType"] = {"text": type_text}

    if duration := args.get("duration_minutes"):
        appointment["minutesDuration"] = duration

    # Support full datetime (preferred_datetime) or date-only (preferred_date) for backward compat
    preferred_datetime = args.get("preferred_datetime")
    preferred_date = args.get("preferred_date")
    display_time = None

    if preferred_datetime:
        appointment["requestedPeriod"] = [{"start": preferred_datetime}]
        display_time = preferred_datetime
    elif preferred_date:
        appointment["requestedPeriod"] = [{"start": f"{preferred_date}T09:00:00Z"}]
        display_time = preferred_date

    result = await fhir_client.create("Appointment", appointment)
    fhir_id = result.get("id")

    summary = f"Appointment: {reason}"
    if specialty:
        summary += f" ({specialty})"
    if display_time:
        summary += f" on {display_time}"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.APPOINTMENT,
        patient_id=patient_id,
        resource=appointment,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent"},
    )

    return {
        "status": "proposed",
        "message": "Appointment request created. Requires clinician approval to confirm booking.",
        "action_id": action.action_id,
        "appointment": {
            "id": fhir_id,
            "reason": reason,
            "type": appt_type,
            "specialty": specialty,
            "preferredDatetime": display_time,
        },
    }


async def handle_search_appointments(args: dict) -> dict:
    """Search for patient's appointments."""
    patient_id = args["patient_id"]
    params = {"patient": f"Patient/{patient_id}"}
    if status := args.get("status"):
        params["status"] = status

    result = await fhir_client.search("Appointment", params)
    entries = result.get("entry", [])

    appointments = []
    for entry in entries:
        appt = entry.get("resource", {})
        appointments.append({
            "id": appt.get("id"),
            "status": appt.get("status"),
            "type": appt.get("appointmentType", {}).get("text"),
            "description": appt.get("description"),
            "duration": appt.get("minutesDuration"),
            "requestedPeriod": appt.get("requestedPeriod"),
            "start": appt.get("start"),
            "end": appt.get("end"),
        })

    return {
        "total": len(appointments),
        "appointments": appointments,
    }


async def handle_create_diagnostic_order(args: dict) -> dict:
    """Create a diagnostic order (lab or imaging)."""
    patient_id = args["patient_id"]
    order_type = args["order_type"]
    test_name = args["test_name"]
    reason = args["reason"]

    category_code = "108252007" if order_type == "lab" else "363679005"
    category_display = "Laboratory procedure" if order_type == "lab" else "Imaging"

    service_request = {
        "resourceType": "ServiceRequest",
        "status": "draft",
        "intent": "order",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": category_code,
                        "display": category_display,
                    }
                ]
            }
        ],
        "code": {
            "text": test_name,
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "reasonCode": [
            {
                "text": reason,
            }
        ],
        "priority": args.get("priority", "routine"),
    }

    if notes := args.get("notes"):
        service_request["note"] = [{"text": notes}]

    result = await fhir_client.create("ServiceRequest", service_request)
    fhir_id = result.get("id")

    summary = f"{order_type.capitalize()} order: {test_name}"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.SERVICE_REQUEST,
        patient_id=patient_id,
        resource=service_request,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent", "order_type": order_type},
    )

    return {
        "status": "draft",
        "message": f"{order_type.capitalize()} order created as DRAFT. Requires clinician approval.",
        "action_id": action.action_id,
        "diagnosticOrder": {
            "id": fhir_id,
            "type": order_type,
            "test": test_name,
            "reason": reason,
            "priority": args.get("priority", "routine"),
        },
    }


async def handle_create_encounter_note(args: dict) -> dict:
    """Create an encounter note (DocumentReference)."""
    patient_id = args["patient_id"]
    note_type = args["note_type"]
    title = args["title"]
    content = args["content"]

    note_type_codes = {
        "progress_note": ("11506-3", "Progress note"),
        "history_physical": ("34117-2", "History and physical note"),
        "discharge_summary": ("18842-5", "Discharge summary"),
        "consultation": ("11488-4", "Consultation note"),
        "procedure_note": ("28570-0", "Procedure note"),
    }

    loinc_code, loinc_display = note_type_codes.get(note_type, ("11506-3", "Progress note"))

    import base64
    content_b64 = base64.b64encode(content.encode()).decode()

    document_reference = {
        "resourceType": "DocumentReference",
        "status": "current",
        "docStatus": "preliminary",
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": loinc_code,
                    "display": loinc_display,
                }
            ],
            "text": title,
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "description": title,
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain",
                    "data": content_b64,
                    "title": title,
                }
            }
        ],
    }

    if encounter_id := args.get("encounter_id"):
        document_reference["context"] = {
            "encounter": [{"reference": f"Encounter/{encounter_id}"}]
        }

    if author := args.get("author"):
        document_reference["author"] = [{"display": author}]

    result = await fhir_client.create("DocumentReference", document_reference)
    fhir_id = result.get("id")

    summary = f"{note_type.replace('_', ' ').title()}: {title}"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.DOCUMENT_REFERENCE,
        patient_id=patient_id,
        resource=document_reference,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent", "note_type": note_type},
    )

    return {
        "status": "preliminary",
        "message": "Encounter note created as DRAFT. Requires clinician approval.",
        "action_id": action.action_id,
        "encounterNote": {
            "id": fhir_id,
            "type": note_type,
            "title": title,
            "contentLength": len(content),
        },
    }


async def handle_create_communication(args: dict) -> dict:
    """Create a communication (letter to referring physician, etc.)."""
    patient_id = args["patient_id"]
    recipient_type = args["recipient_type"]
    subject = args["subject"]
    content = args["content"]

    communication = {
        "resourceType": "Communication",
        "status": "preparation",
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "payload": [
            {
                "contentString": content,
            }
        ],
        "topic": {
            "text": subject,
        },
    }

    category_map = {
        "referral_response": "referral-response",
        "consultation_note": "consultation",
        "lab_results": "lab-results",
        "follow_up": "follow-up",
        "general": "general",
    }
    if category := args.get("category"):
        communication["category"] = [{"text": category_map.get(category, category)}]

    if recipient_name := args.get("recipient_name"):
        communication["recipient"] = [{"display": recipient_name}]

    communication["note"] = [{"text": f"Recipient type: {recipient_type}"}]

    result = await fhir_client.create("Communication", communication)
    fhir_id = result.get("id")

    summary = f"Letter to {recipient_type.replace('_', ' ')}: {subject}"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.COMMUNICATION,
        patient_id=patient_id,
        resource=communication,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent", "recipient_type": recipient_type},
    )

    return {
        "status": "preparation",
        "message": "Communication created as DRAFT. Requires clinician approval.",
        "action_id": action.action_id,
        "communication": {
            "id": fhir_id,
            "recipientType": recipient_type,
            "recipient": args.get("recipient_name"),
            "subject": subject,
            "contentLength": len(content),
        },
    }


# =============================================================================
# Approval Queue Handlers
# =============================================================================


async def handle_list_pending_actions(args: dict) -> dict:
    """List all pending clinical actions awaiting approval."""
    patient_id = args.get("patient_id")

    queue = get_approval_queue()
    pending = queue.list_pending(patient_id=patient_id)

    return {
        "count": len(pending),
        "actions": [action.to_dict() for action in pending],
        "message": f"Found {len(pending)} pending action(s)" + (f" for patient {patient_id}" if patient_id else ""),
    }


async def handle_approve_action(args: dict) -> dict:
    """Approve a pending clinical action and execute it."""
    action_id = args["action_id"]

    queue = get_approval_queue()
    action = queue.get_action(action_id)

    if not action:
        return {"error": f"Action {action_id} not found"}

    if action.status != ActionStatus.PENDING:
        return {"error": f"Action {action_id} is not pending (status: {action.status.value})"}

    queue.approve(action_id)

    try:
        resource_type = action.action_type.value
        fhir_id = action.fhir_id

        if not fhir_id:
            queue.mark_failed(action_id, "No FHIR resource ID")
            return {"error": "Action has no associated FHIR resource"}

        current = await fhir_client.read(resource_type, fhir_id)

        if resource_type == "MedicationRequest":
            current["status"] = "active"
        elif resource_type == "CarePlan":
            current["status"] = "active"
        elif resource_type == "Appointment":
            current["status"] = "booked"
            # FHIR constraint app-3: booked appointments must have start/end
            if not current.get("start"):
                requested = current.get("requestedPeriod", [{}])
                start_time = requested[0].get("start") if requested else None
                if start_time:
                    current["start"] = start_time
                    # Default 30 min duration if no end time
                    duration = current.get("minutesDuration", 30)
                    from datetime import datetime, timedelta
                    try:
                        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                        end_dt = dt + timedelta(minutes=duration)
                        current["end"] = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    except (ValueError, TypeError):
                        current["end"] = start_time
                else:
                    # No requested time — use now + 30 min as placeholder
                    from datetime import datetime, timedelta, timezone
                    now = datetime.now(timezone.utc)
                    current["start"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    current["end"] = (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif resource_type == "ServiceRequest":
            current["status"] = "active"
        elif resource_type == "DocumentReference":
            current["status"] = "current"
        elif resource_type == "Communication":
            current["status"] = "completed"
        else:
            current["status"] = "active"

        await fhir_client.update(resource_type, fhir_id, current)

        queue.mark_executed(action_id)

        return {
            "status": "approved",
            "message": f"Action approved and executed: {action.summary}",
            "action_id": action_id,
            "fhir_id": fhir_id,
            "resource_type": resource_type,
            "patient_id": action.patient_id,
        }

    except Exception as e:
        queue.mark_failed(action_id, str(e))
        return {"error": f"Failed to execute action: {str(e)}"}


async def handle_reject_action(args: dict) -> dict:
    """Reject a pending clinical action and delete the draft resource."""
    action_id = args["action_id"]
    reason = args.get("reason")

    queue = get_approval_queue()
    action = queue.get_action(action_id)

    if not action:
        return {"error": f"Action {action_id} not found"}

    if action.status != ActionStatus.PENDING:
        return {"error": f"Action {action_id} is not pending (status: {action.status.value})"}

    queue.reject(action_id, reason)

    deleted_fhir = False
    if action.fhir_id:
        try:
            resource_type = action.action_type.value
            await fhir_client.delete(resource_type, action.fhir_id)
            deleted_fhir = True
        except Exception as e:
            logger.warning(f"Failed to delete draft FHIR resource: {e}")

    queue.remove(action_id)

    return {
        "status": "rejected",
        "message": f"Action rejected: {action.summary}" + (f" (Reason: {reason})" if reason else ""),
        "action_id": action_id,
        "draft_deleted": deleted_fhir,
    }


# =============================================================================
# Helper Functions
# =============================================================================

def format_name(names: list) -> str:
    """Format FHIR HumanName to string."""
    if not names:
        return "Unknown"
    name = names[0]
    given = " ".join(name.get("given", []))
    family = name.get("family", "")
    return f"{given} {family}".strip() or "Unknown"


def format_identifiers(identifiers: list) -> list:
    """Format FHIR Identifier list."""
    return [
        {
            "system": i.get("system", "unknown"),
            "value": i.get("value"),
        }
        for i in identifiers
    ]


def format_address(addresses: list) -> str | None:
    """Format FHIR Address to string."""
    if not addresses:
        return None
    addr = addresses[0]
    parts = addr.get("line", []) + [
        addr.get("city"),
        addr.get("state"),
        addr.get("postalCode"),
    ]
    return ", ".join(p for p in parts if p)


def format_telecom(telecoms: list) -> list:
    """Format FHIR ContactPoint list."""
    return [
        {"system": t.get("system"), "value": t.get("value")}
        for t in telecoms
    ]


def extract_code_display(codeable_concept: dict | None) -> str:
    """Extract display text from CodeableConcept."""
    if not codeable_concept:
        return "Unknown"
    if display := codeable_concept.get("text"):
        return display
    codings = codeable_concept.get("coding", [])
    if codings:
        return codings[0].get("display") or codings[0].get("code", "Unknown")
    return "Unknown"


def extract_medication_name(med_request: dict) -> str:
    """Extract medication name from MedicationRequest."""
    if med_code := med_request.get("medicationCodeableConcept"):
        return extract_code_display(med_code)
    if med_ref := med_request.get("medicationReference"):
        return med_ref.get("display", "Unknown medication")
    return "Unknown medication"


def extract_dosage(med_request: dict) -> str | None:
    """Extract dosage instructions from MedicationRequest."""
    dosages = med_request.get("dosageInstruction", [])
    if dosages:
        return dosages[0].get("text")
    return None


def extract_reaction(allergy: dict) -> str | None:
    """Extract reaction from AllergyIntolerance."""
    reactions = allergy.get("reaction", [])
    if reactions:
        manifestations = reactions[0].get("manifestation", [])
        if manifestations:
            return extract_code_display(manifestations[0])
    return None


# =============================================================================
# Medication Management Handlers (Update/Delete)
# =============================================================================

async def handle_update_medication_status(args: dict) -> dict:
    """Update the status of an existing medication request."""
    medication_id = args["medication_id"]
    new_status = args["new_status"]
    reason = args["reason"]

    # Fetch the current medication request
    try:
        current_med = await fhir_client.read("MedicationRequest", medication_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Medication request {medication_id} not found"}
        raise

    old_status = current_med.get("status", "unknown")
    medication_name = extract_medication_name(current_med)

    # Update the status
    current_med["status"] = new_status

    # Add status reason extension if not already present
    if "statusReason" not in current_med:
        current_med["statusReason"] = {}
    current_med["statusReason"] = {
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/medicationrequest-status-reason",
            "code": "altchoice" if new_status in ["stopped", "cancelled"] else "change",
            "display": reason,
        }],
        "text": reason,
    }

    # Update the resource in FHIR server
    await fhir_client.update("MedicationRequest", medication_id, current_med)

    return {
        "status": "updated",
        "message": f"Medication status changed from '{old_status}' to '{new_status}'",
        "medication": {
            "id": medication_id,
            "name": medication_name,
            "old_status": old_status,
            "new_status": new_status,
            "reason": reason,
        },
    }


async def handle_delete_medication_request(args: dict) -> dict:
    """Delete a medication request (only draft or entered-in-error allowed)."""
    medication_id = args["medication_id"]
    reason = args["reason"]

    # Fetch the current medication request
    try:
        current_med = await fhir_client.read("MedicationRequest", medication_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Medication request {medication_id} not found"}
        raise

    current_status = current_med.get("status", "unknown")
    medication_name = extract_medication_name(current_med)

    # Safety check: only allow deletion of draft or entered-in-error records
    if current_status not in ["draft", "entered-in-error"]:
        return {
            "error": f"Cannot delete medication with status '{current_status}'. Only 'draft' or 'entered-in-error' medications can be deleted.",
            "suggestion": "Use update_medication_status to change the status to 'stopped', 'cancelled', or 'entered-in-error' first.",
            "medication": {
                "id": medication_id,
                "name": medication_name,
                "status": current_status,
            },
        }

    # Delete the resource
    await fhir_client.delete("MedicationRequest", medication_id)

    return {
        "status": "deleted",
        "message": f"Medication request deleted successfully",
        "medication": {
            "id": medication_id,
            "name": medication_name,
            "previous_status": current_status,
            "reason": reason,
        },
    }


async def handle_reconcile_medications(args: dict) -> dict:
    """Reconcile a patient's medication list."""
    patient_id = args["patient_id"]
    keep_ids = args.get("keep_medication_ids", [])
    discontinue_ids = args.get("discontinue_medication_ids", [])
    delete_ids = args.get("delete_medication_ids", [])
    reason = args["reason"]

    results = {
        "patient_id": patient_id,
        "reason": reason,
        "kept": [],
        "discontinued": [],
        "deleted": [],
        "errors": [],
    }

    # Keep medications active
    for med_id in keep_ids:
        try:
            current_med = await fhir_client.read("MedicationRequest", med_id)
            medication_name = extract_medication_name(current_med)

            if current_med.get("status") != "active":
                current_med["status"] = "active"
                await fhir_client.update("MedicationRequest", med_id, current_med)

            results["kept"].append({
                "id": med_id,
                "name": medication_name,
                "status": "active",
            })
        except Exception as e:
            results["errors"].append({
                "id": med_id,
                "action": "keep",
                "error": str(e),
            })

    # Discontinue medications
    for med_id in discontinue_ids:
        try:
            current_med = await fhir_client.read("MedicationRequest", med_id)
            medication_name = extract_medication_name(current_med)

            current_med["status"] = "stopped"
            current_med["statusReason"] = {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/medicationrequest-status-reason",
                    "code": "altchoice",
                    "display": reason,
                }],
                "text": reason,
            }
            await fhir_client.update("MedicationRequest", med_id, current_med)

            results["discontinued"].append({
                "id": med_id,
                "name": medication_name,
                "status": "stopped",
            })
        except Exception as e:
            results["errors"].append({
                "id": med_id,
                "action": "discontinue",
                "error": str(e),
            })

    # Delete medications
    for med_id in delete_ids:
        try:
            current_med = await fhir_client.read("MedicationRequest", med_id)
            medication_name = extract_medication_name(current_med)
            current_status = current_med.get("status", "unknown")

            if current_status not in ["draft", "entered-in-error"]:
                current_med["status"] = "entered-in-error"
                current_med["statusReason"] = {
                    "text": f"Marked for deletion: {reason}",
                }
                await fhir_client.update("MedicationRequest", med_id, current_med)

            await fhir_client.delete("MedicationRequest", med_id)

            results["deleted"].append({
                "id": med_id,
                "name": medication_name,
                "previous_status": current_status,
            })
        except Exception as e:
            results["errors"].append({
                "id": med_id,
                "action": "delete",
                "error": str(e),
            })

    # Build summary
    summary_parts = []
    if results["kept"]:
        summary_parts.append(f"{len(results['kept'])} kept active")
    if results["discontinued"]:
        summary_parts.append(f"{len(results['discontinued'])} discontinued")
    if results["deleted"]:
        summary_parts.append(f"{len(results['deleted'])} deleted")
    if results["errors"]:
        summary_parts.append(f"{len(results['errors'])} errors")

    results["status"] = "completed" if not results["errors"] else "completed_with_errors"
    results["message"] = f"Medication reconciliation complete: {', '.join(summary_parts)}"

    return results


def extract_observation_value(observation: dict) -> str:
    """Extract value from Observation."""
    if value_quantity := observation.get("valueQuantity"):
        return f"{value_quantity.get('value')} {value_quantity.get('unit', '')}"
    if value_string := observation.get("valueString"):
        return value_string
    if value_codeable := observation.get("valueCodeableConcept"):
        return extract_code_display(value_codeable)
    return "No value"


def parse_dose_value(dosage: str) -> float:
    """Parse numeric value from dosage string."""
    import re
    match = re.search(r"(\d+(?:\.\d+)?)", dosage)
    return float(match.group(1)) if match else 0


def parse_dose_unit(dosage: str) -> str:
    """Parse unit from dosage string."""
    import re
    match = re.search(r"\d+(?:\.\d+)?\s*(\w+)", dosage)
    return match.group(1) if match else "mg"


# =============================================================================
# Phase 8: Comprehensive Clinical Tool Handlers
# =============================================================================


async def handle_create_allergy_intolerance(args: dict) -> dict:
    """Create an allergy/intolerance record for a patient."""
    patient_id = args["patient_id"]
    substance = args["substance"]
    category = args["category"]

    # Build AllergyIntolerance resource
    allergy = {
        "resourceType": "AllergyIntolerance",
        "clinicalStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                "code": "active",
                "display": "Active",
            }]
        },
        "verificationStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                "code": "confirmed",
                "display": "Confirmed",
            }]
        },
        "category": [category],
        "code": {
            "text": substance,
        },
        "patient": {
            "reference": f"Patient/{patient_id}",
        },
    }

    # Add criticality if provided
    if criticality := args.get("criticality"):
        allergy["criticality"] = criticality

    # Add reaction if provided
    if reaction := args.get("reaction"):
        severity = args.get("severity", "moderate")
        allergy["reaction"] = [{
            "manifestation": [{
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "display": reaction,
                }],
                "text": reaction,
            }],
            "severity": severity,
        }]

    result = await fhir_client.create("AllergyIntolerance", allergy)
    fhir_id = result.get("id")

    # Queue for approval
    summary = f"Allergy: {substance} ({category})"
    if reaction := args.get("reaction"):
        summary += f" - {reaction}"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.ALLERGY_INTOLERANCE,
        patient_id=patient_id,
        resource=allergy,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent"},
    )

    return {
        "status": "draft",
        "message": "Allergy documented. Requires clinician approval.",
        "action_id": action.action_id,
        "allergy": {
            "id": fhir_id,
            "substance": substance,
            "category": category,
            "reaction": args.get("reaction"),
            "severity": args.get("severity"),
            "criticality": args.get("criticality"),
        },
    }


async def handle_update_allergy_intolerance(args: dict) -> dict:
    """Update an existing allergy/intolerance record."""
    allergy_id = args["allergy_id"]

    # Fetch current allergy
    try:
        current = await fhir_client.read("AllergyIntolerance", allergy_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Allergy {allergy_id} not found"}
        raise

    substance = extract_code_display(current.get("code"))

    # Update clinical status if provided
    if clinical_status := args.get("clinical_status"):
        current["clinicalStatus"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                "code": clinical_status,
                "display": clinical_status.capitalize(),
            }]
        }

    # Update verification status if provided
    if verification_status := args.get("verification_status"):
        current["verificationStatus"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                "code": verification_status,
                "display": verification_status.capitalize(),
            }]
        }

    # Add new reaction if provided
    if new_reaction := args.get("new_reaction"):
        if "reaction" not in current:
            current["reaction"] = []
        current["reaction"].append({
            "manifestation": [{
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "display": new_reaction,
                }],
                "text": new_reaction,
            }],
        })

    # Update in FHIR server
    await fhir_client.update("AllergyIntolerance", allergy_id, current)

    return {
        "status": "updated",
        "message": f"Allergy '{substance}' updated successfully",
        "allergy": {
            "id": allergy_id,
            "substance": substance,
            "clinical_status": args.get("clinical_status"),
            "verification_status": args.get("verification_status"),
            "new_reaction": args.get("new_reaction"),
        },
    }


async def handle_add_condition(args: dict) -> dict:
    """Add a condition to the patient's problem list."""
    patient_id = args["patient_id"]
    condition_name = args["condition_name"]
    clinical_status = args.get("clinical_status", "active")

    # Build Condition resource
    condition = {
        "resourceType": "Condition",
        "clinicalStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                "code": clinical_status,
            }]
        },
        "verificationStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                "code": "confirmed",
            }]
        },
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                "code": "problem-list-item",
                "display": "Problem List Item",
            }]
        }],
        "code": {
            "text": condition_name,
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
    }

    # Add ICD-10 code if provided
    if icd10_code := args.get("icd10_code"):
        condition["code"]["coding"] = [{
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": icd10_code,
            "display": condition_name,
        }]

    # Add onset date if provided
    if onset_date := args.get("onset_date"):
        condition["onsetDateTime"] = onset_date

    # Add notes if provided
    if notes := args.get("notes"):
        condition["note"] = [{"text": notes}]

    result = await fhir_client.create("Condition", condition)
    fhir_id = result.get("id")

    # Queue for approval
    summary = f"Add condition: {condition_name}"
    if icd10_code := args.get("icd10_code"):
        summary += f" ({icd10_code})"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.CONDITION,
        patient_id=patient_id,
        resource=condition,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent"},
    )

    return {
        "status": "draft",
        "message": "Condition added to problem list. Requires clinician approval.",
        "action_id": action.action_id,
        "condition": {
            "id": fhir_id,
            "name": condition_name,
            "icd10_code": args.get("icd10_code"),
            "clinical_status": clinical_status,
            "onset_date": args.get("onset_date"),
        },
    }


async def handle_update_condition_status(args: dict) -> dict:
    """Update the status of an existing condition."""
    condition_id = args["condition_id"]
    clinical_status = args["clinical_status"]

    # Fetch current condition
    try:
        current = await fhir_client.read("Condition", condition_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Condition {condition_id} not found"}
        raise

    old_status = extract_code_display(current.get("clinicalStatus"))
    condition_name = extract_code_display(current.get("code"))

    # Update clinical status
    current["clinicalStatus"] = {
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "code": clinical_status,
        }]
    }

    # Add abatement date if provided (for resolved conditions)
    if abatement_date := args.get("abatement_date"):
        current["abatementDateTime"] = abatement_date

    # Add note for reason
    if reason := args.get("reason"):
        if "note" not in current:
            current["note"] = []
        current["note"].append({"text": f"Status changed: {reason}"})

    # Update in FHIR server
    await fhir_client.update("Condition", condition_id, current)

    return {
        "status": "updated",
        "message": f"Condition '{condition_name}' status changed from '{old_status}' to '{clinical_status}'",
        "condition": {
            "id": condition_id,
            "name": condition_name,
            "old_status": old_status,
            "new_status": clinical_status,
            "reason": args.get("reason"),
        },
    }


async def handle_create_procedure(args: dict) -> dict:
    """Document a procedure performed on the patient."""
    patient_id = args["patient_id"]
    procedure_name = args["procedure_name"]
    from datetime import datetime

    # Build Procedure resource
    procedure = {
        "resourceType": "Procedure",
        "status": "completed",
        "code": {
            "text": procedure_name,
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "performedDateTime": args.get("performed_date", datetime.now().strftime("%Y-%m-%d")),
    }

    # Add CPT code if provided
    if cpt_code := args.get("cpt_code"):
        procedure["code"]["coding"] = [{
            "system": "http://www.ama-assn.org/go/cpt",
            "code": cpt_code,
            "display": procedure_name,
        }]

    # Add notes if provided
    if notes := args.get("notes"):
        procedure["note"] = [{"text": notes}]

    # Add outcome if provided
    if outcome := args.get("outcome"):
        procedure["outcome"] = {"text": outcome}

    result = await fhir_client.create("Procedure", procedure)
    fhir_id = result.get("id")

    # Queue for approval
    summary = f"Procedure: {procedure_name}"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.PROCEDURE,
        patient_id=patient_id,
        resource=procedure,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent"},
    )

    return {
        "status": "completed",
        "message": "Procedure documented. Requires clinician approval.",
        "action_id": action.action_id,
        "procedure": {
            "id": fhir_id,
            "name": procedure_name,
            "cpt_code": args.get("cpt_code"),
            "performed_date": procedure["performedDateTime"],
            "outcome": args.get("outcome"),
        },
    }


async def handle_search_procedures(args: dict) -> dict:
    """Search for procedures performed on a patient."""
    patient_id = args["patient_id"]

    params = {"patient": patient_id}
    if date_from := args.get("date_from"):
        params["date"] = f"ge{date_from}"

    bundle = await fhir_client.search("Procedure", params)

    procedures = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        procedure = {
            "id": resource.get("id"),
            "name": extract_code_display(resource.get("code")),
            "status": resource.get("status"),
            "performed_date": resource.get("performedDateTime") or resource.get("performedPeriod", {}).get("start"),
            "outcome": resource.get("outcome", {}).get("text") if resource.get("outcome") else None,
        }
        procedures.append(procedure)

    return {
        "total": bundle.get("total", len(procedures)),
        "procedures": procedures,
    }


async def handle_get_lab_results_with_trends(args: dict) -> dict:
    """Get lab results with trend analysis."""
    patient_id = args["patient_id"]
    lab_type = args.get("lab_type")
    months_back = args.get("months_back", 12)

    from datetime import datetime, timedelta
    date_from = (datetime.now() - timedelta(days=months_back * 30)).strftime("%Y-%m-%d")

    params = {
        "patient": patient_id,
        "category": "laboratory",
        "date": f"ge{date_from}",
        "_sort": "-date",
    }

    # Common lab LOINC codes
    lab_codes = {
        "a1c": "4548-4",
        "hemoglobin a1c": "4548-4",
        "hba1c": "4548-4",
        "creatinine": "2160-0",
        "glucose": "2345-7",
        "cholesterol": "2093-3",
        "ldl": "2089-1",
        "hdl": "2085-9",
        "triglycerides": "2571-8",
    }

    if lab_type:
        lab_type_lower = lab_type.lower()
        if lab_type_lower in lab_codes:
            params["code"] = lab_codes[lab_type_lower]

    bundle = await fhir_client.search("Observation", params)

    # Group results by type and analyze trends
    results_by_type = {}
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        code = extract_code_display(resource.get("code"))
        value = extract_observation_value(resource)
        date = resource.get("effectiveDateTime", "")[:10]

        if code not in results_by_type:
            results_by_type[code] = []

        # Extract numeric value for trending
        try:
            numeric_value = float(value.split()[0])
        except (ValueError, IndexError):
            numeric_value = None

        results_by_type[code].append({
            "date": date,
            "value": value,
            "numeric_value": numeric_value,
        })

    # Analyze trends
    trends = []
    for code, values in results_by_type.items():
        if len(values) >= 2:
            # Sort by date
            values.sort(key=lambda x: x["date"])

            # Calculate trend
            numeric_values = [v["numeric_value"] for v in values if v["numeric_value"] is not None]
            if len(numeric_values) >= 2:
                change = numeric_values[-1] - numeric_values[0]
                if abs(change) < 0.05 * numeric_values[0]:
                    trend = "stable"
                elif change > 0:
                    trend = "increasing"
                else:
                    trend = "decreasing"
            else:
                trend = "unknown"

            trends.append({
                "lab_type": code,
                "trend": trend,
                "latest_value": values[-1]["value"],
                "latest_date": values[-1]["date"],
                "oldest_value": values[0]["value"],
                "oldest_date": values[0]["date"],
                "value_count": len(values),
            })

    return {
        "patient_id": patient_id,
        "period": f"Last {months_back} months",
        "trends": trends,
        "summary": f"Found {len(trends)} lab types with trend data",
    }


async def handle_check_renal_function(args: dict) -> dict:
    """Check renal function for medication dosing decisions."""
    patient_id = args["patient_id"]

    # Get patient info for age-based calculations
    try:
        patient = await fhir_client.read("Patient", patient_id)
    except httpx.HTTPStatusError:
        patient = {}

    # Get recent creatinine and eGFR
    from datetime import datetime, timedelta
    date_from = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    # Search for renal-related labs
    params = {
        "patient": patient_id,
        "category": "laboratory",
        "date": f"ge{date_from}",
        "_sort": "-date",
    }

    bundle = await fhir_client.search("Observation", params)

    renal_results = {
        "creatinine": None,
        "egfr": None,
        "bun": None,
    }

    renal_codes = {
        "2160-0": "creatinine",  # Creatinine
        "33914-3": "egfr",  # eGFR
        "48642-3": "egfr",  # eGFR (another code)
        "3094-0": "bun",  # BUN
    }

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        code_obj = resource.get("code", {})
        codings = code_obj.get("coding", [])

        for coding in codings:
            loinc_code = coding.get("code")
            if loinc_code in renal_codes:
                lab_type = renal_codes[loinc_code]
                if renal_results[lab_type] is None:  # Take most recent
                    renal_results[lab_type] = {
                        "value": extract_observation_value(resource),
                        "date": resource.get("effectiveDateTime", "")[:10],
                    }

    # Determine renal function category
    egfr_value = None
    if renal_results["egfr"]:
        try:
            egfr_value = float(renal_results["egfr"]["value"].split()[0])
        except (ValueError, IndexError):
            pass

    if egfr_value:
        if egfr_value >= 90:
            category = "Normal (Stage 1)"
            dosing_note = "Standard dosing appropriate"
        elif egfr_value >= 60:
            category = "Mildly decreased (Stage 2)"
            dosing_note = "Standard dosing usually appropriate"
        elif egfr_value >= 30:
            category = "Moderately decreased (Stage 3)"
            dosing_note = "May need dose adjustment for renally-cleared medications"
        elif egfr_value >= 15:
            category = "Severely decreased (Stage 4)"
            dosing_note = "Dose adjustment likely needed. Consider avoiding nephrotoxic drugs."
        else:
            category = "Kidney failure (Stage 5)"
            dosing_note = "Significant dose adjustments needed. Dialysis dosing may apply."
    else:
        category = "Unknown"
        dosing_note = "Unable to determine renal function. Consider ordering labs."

    return {
        "patient_id": patient_id,
        "renal_function": {
            "creatinine": renal_results["creatinine"],
            "egfr": renal_results["egfr"],
            "bun": renal_results["bun"],
        },
        "category": category,
        "dosing_recommendation": dosing_note,
        "note": "Always verify current renal function before prescribing renally-cleared medications",
    }


async def handle_document_counseling(args: dict) -> dict:
    """Quick documentation of counseling provided."""
    patient_id = args["patient_id"]
    counseling_type = args["counseling_type"]
    duration_minutes = args.get("duration_minutes", 5)
    notes = args.get("notes", "")

    # Map counseling type to display text
    counseling_display = {
        "smoking_cessation": "Smoking Cessation Counseling",
        "diet_nutrition": "Diet and Nutrition Counseling",
        "exercise": "Exercise Counseling",
        "medication_adherence": "Medication Adherence Counseling",
        "disease_education": "Disease Education",
        "other": "General Counseling",
    }

    display_text = counseling_display.get(counseling_type, counseling_type)
    content = f"{display_text}\nDuration: {duration_minutes} minutes\n\n{notes}"

    # Create as DocumentReference
    import base64
    content_b64 = base64.b64encode(content.encode()).decode()

    document = {
        "resourceType": "DocumentReference",
        "status": "current",
        "docStatus": "final",
        "type": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "34117-2",
                "display": "History and physical note",
            }],
            "text": display_text,
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "description": display_text,
        "content": [{
            "attachment": {
                "contentType": "text/plain",
                "data": content_b64,
                "title": display_text,
            }
        }],
    }

    result = await fhir_client.create("DocumentReference", document)
    fhir_id = result.get("id")

    return {
        "status": "documented",
        "message": f"{display_text} documented ({duration_minutes} min)",
        "counseling": {
            "id": fhir_id,
            "type": counseling_type,
            "duration_minutes": duration_minutes,
        },
    }


async def handle_create_work_note(args: dict) -> dict:
    """Generate a work/school excuse note."""
    patient_id = args["patient_id"]
    from_date = args["excuse_from_date"]
    to_date = args["excuse_to_date"]
    reason = args.get("reason", "medical condition")
    restrictions = args.get("restrictions", "")

    # Get patient name
    try:
        patient = await fhir_client.read("Patient", patient_id)
        patient_name = format_name(patient.get("name", []))
    except Exception:
        patient_name = "Patient"

    # Generate note content
    from datetime import datetime
    today = datetime.now().strftime("%B %d, %Y")

    content = f"""WORK/SCHOOL EXCUSE NOTE

Date: {today}

To Whom It May Concern,

This letter confirms that {patient_name} was seen in our office.

Period of absence: {from_date} to {to_date}
Reason: {reason}
"""

    if restrictions:
        content += f"\nWork restrictions: {restrictions}\n"

    content += """
This patient may return to work/school after the above date.

If you have any questions, please contact our office.

Sincerely,
[Provider Signature]
"""

    # Create as DocumentReference
    import base64
    content_b64 = base64.b64encode(content.encode()).decode()

    document = {
        "resourceType": "DocumentReference",
        "status": "current",
        "docStatus": "preliminary",
        "type": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "64288-8",
                "display": "Work excuse note",
            }],
            "text": "Work/School Excuse Note",
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "description": f"Work excuse: {from_date} to {to_date}",
        "content": [{
            "attachment": {
                "contentType": "text/plain",
                "data": content_b64,
                "title": "Work/School Excuse Note",
            }
        }],
    }

    result = await fhir_client.create("DocumentReference", document)
    fhir_id = result.get("id")

    # Queue for approval
    summary = f"Work note: {from_date} to {to_date}"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.DOCUMENT_REFERENCE,
        patient_id=patient_id,
        resource=document,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent"},
    )

    return {
        "status": "draft",
        "message": "Work note created. Requires clinician approval before release.",
        "action_id": action.action_id,
        "work_note": {
            "id": fhir_id,
            "patient": patient_name,
            "from_date": from_date,
            "to_date": to_date,
        },
    }


async def handle_create_phone_encounter(args: dict) -> dict:
    """Document a phone call with patient."""
    patient_id = args["patient_id"]
    call_type = args["call_type"]
    summary = args["summary"]
    duration_minutes = args.get("duration_minutes", 5)
    action_taken = args.get("action_taken", "")

    # Map call type to display
    call_type_display = {
        "refill_request": "Refill Request",
        "test_results": "Test Results Discussion",
        "symptom_followup": "Symptom Follow-up",
        "general_question": "General Question",
        "referral_coordination": "Referral Coordination",
    }

    display_text = call_type_display.get(call_type, call_type)

    from datetime import datetime

    # Create Encounter for phone call
    encounter = {
        "resourceType": "Encounter",
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "VR",
            "display": "virtual",
        },
        "type": [{
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": "185317003",
                "display": "Telephone encounter",
            }],
            "text": f"Phone: {display_text}",
        }],
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "period": {
            "start": datetime.now().isoformat(),
        },
    }

    encounter_result = await fhir_client.create("Encounter", encounter)
    encounter_id = encounter_result.get("id")

    # Create DocumentReference for call notes
    content = f"""PHONE ENCOUNTER

Type: {display_text}
Duration: {duration_minutes} minutes
Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}

Summary:
{summary}
"""

    if action_taken:
        content += f"\nAction Taken:\n{action_taken}\n"

    import base64
    content_b64 = base64.b64encode(content.encode()).decode()

    document = {
        "resourceType": "DocumentReference",
        "status": "current",
        "docStatus": "final",
        "type": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "11506-3",
                "display": "Progress note",
            }],
            "text": f"Phone: {display_text}",
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "context": {
            "encounter": [{"reference": f"Encounter/{encounter_id}"}],
        },
        "description": f"Phone encounter: {display_text}",
        "content": [{
            "attachment": {
                "contentType": "text/plain",
                "data": content_b64,
                "title": f"Phone: {display_text}",
            }
        }],
    }

    doc_result = await fhir_client.create("DocumentReference", document)
    doc_id = doc_result.get("id")

    return {
        "status": "documented",
        "message": f"Phone encounter documented: {display_text}",
        "phone_encounter": {
            "encounter_id": encounter_id,
            "document_id": doc_id,
            "type": call_type,
            "duration_minutes": duration_minutes,
        },
    }


async def handle_create_referral(args: dict) -> dict:
    """Create a referral to a specialist."""
    patient_id = args["patient_id"]
    specialty = args["specialty"]
    reason = args["reason"]
    urgency = args.get("urgency", "routine")
    clinical_summary = args.get("clinical_summary", "")

    # Build ServiceRequest for referral
    service_request = {
        "resourceType": "ServiceRequest",
        "status": "draft",
        "intent": "order",
        "category": [{
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": "3457005",
                "display": "Patient referral",
            }]
        }],
        "priority": urgency,
        "code": {
            "text": f"Referral to {specialty}",
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "reasonCode": [{
            "text": reason,
        }],
    }

    # Add clinical summary as note
    if clinical_summary:
        service_request["note"] = [{"text": clinical_summary}]

    # Add performer type for specialty
    service_request["performerType"] = {
        "text": specialty,
    }

    result = await fhir_client.create("ServiceRequest", service_request)
    fhir_id = result.get("id")

    # Queue for approval
    summary = f"Referral to {specialty}: {reason}"

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.SERVICE_REQUEST,
        patient_id=patient_id,
        resource=service_request,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent", "referral_specialty": specialty},
    )

    return {
        "status": "draft",
        "message": f"Referral to {specialty} created. Requires clinician approval.",
        "action_id": action.action_id,
        "referral": {
            "id": fhir_id,
            "specialty": specialty,
            "reason": reason,
            "urgency": urgency,
        },
    }


async def handle_search_referrals(args: dict) -> dict:
    """Search for referrals for a patient."""
    patient_id = args["patient_id"]

    params = {
        "patient": patient_id,
        "category": "3457005",  # Patient referral SNOMED code
    }

    if status := args.get("status"):
        params["status"] = status

    bundle = await fhir_client.search("ServiceRequest", params)

    referrals = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        # Check if this is a referral
        categories = resource.get("category", [])
        is_referral = False
        for cat in categories:
            for coding in cat.get("coding", []):
                if coding.get("code") == "3457005":
                    is_referral = True
                    break

        if is_referral or "Referral" in extract_code_display(resource.get("code")):
            referral = {
                "id": resource.get("id"),
                "specialty": resource.get("performerType", {}).get("text", extract_code_display(resource.get("code"))),
                "reason": extract_code_display(resource.get("reasonCode", [{}])[0] if resource.get("reasonCode") else {}),
                "status": resource.get("status"),
                "priority": resource.get("priority"),
                "authored_on": resource.get("authoredOn"),
            }
            referrals.append(referral)

    return {
        "total": len(referrals),
        "referrals": referrals,
    }


async def handle_get_immunization_status(args: dict) -> dict:
    """Get patient's vaccination history and identify due/overdue immunizations."""
    patient_id = args["patient_id"]

    # Get patient info for age-based recommendations
    try:
        patient = await fhir_client.read("Patient", patient_id)
        birth_date = patient.get("birthDate")
    except Exception:
        birth_date = None

    # Calculate age
    age = None
    if birth_date:
        from datetime import datetime
        try:
            birth = datetime.strptime(birth_date, "%Y-%m-%d")
            age = (datetime.now() - birth).days // 365
        except ValueError:
            pass

    # Get immunization history
    bundle = await fhir_client.search("Immunization", {"patient": patient_id})

    immunizations = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        immunization = {
            "id": resource.get("id"),
            "vaccine": extract_code_display(resource.get("vaccineCode")),
            "date": resource.get("occurrenceDateTime", "")[:10] if resource.get("occurrenceDateTime") else None,
            "status": resource.get("status"),
        }
        immunizations.append(immunization)

    # Identify vaccines given
    vaccines_received = [i["vaccine"].lower() for i in immunizations if i["status"] == "completed"]

    # Common vaccine recommendations (simplified)
    recommendations = []

    # Flu vaccine - annual
    flu_given_this_year = any("influenza" in v or "flu" in v for v in vaccines_received)
    if not flu_given_this_year:
        recommendations.append({
            "vaccine": "Influenza (Flu)",
            "status": "due",
            "reason": "Annual flu vaccination recommended",
        })

    # COVID-19 - based on latest guidance
    covid_given = any("covid" in v or "sars-cov" in v for v in vaccines_received)
    if not covid_given:
        recommendations.append({
            "vaccine": "COVID-19",
            "status": "due",
            "reason": "COVID-19 vaccination recommended",
        })

    # Tdap - every 10 years for adults
    if age and age >= 19:
        tdap_given = any("tdap" in v or "tetanus" in v for v in vaccines_received)
        if not tdap_given:
            recommendations.append({
                "vaccine": "Tdap",
                "status": "due",
                "reason": "Tdap recommended every 10 years for adults",
            })

    # Pneumococcal - for age >= 65
    if age and age >= 65:
        pneumo_given = any("pneum" in v for v in vaccines_received)
        if not pneumo_given:
            recommendations.append({
                "vaccine": "Pneumococcal (PPSV23/PCV20)",
                "status": "due",
                "reason": "Pneumococcal vaccination recommended for adults 65+",
            })

    # Shingles - for age >= 50
    if age and age >= 50:
        shingles_given = any("zoster" in v or "shingrix" in v for v in vaccines_received)
        if not shingles_given:
            recommendations.append({
                "vaccine": "Shingles (Shingrix)",
                "status": "due",
                "reason": "Shingles vaccination recommended for adults 50+",
            })

    return {
        "patient_id": patient_id,
        "age": age,
        "immunization_history": immunizations,
        "total_vaccines": len(immunizations),
        "recommendations": recommendations,
        "summary": f"{len(immunizations)} vaccines on record, {len(recommendations)} potentially due",
    }
