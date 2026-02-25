#!/usr/bin/env python3
"""
FHIR Tool Handlers for AgentEHR

This module contains the business logic for FHIR operations.
It's separate from server.py so it can be imported without MCP dependencies.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
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
        normalized_query = query.strip()
        # Treat "*" as "list all patients" for UI discoverability.
        if normalized_query and normalized_query != "*":
            params["name"] = normalized_query
    if identifier := args.get("identifier"):
        params["identifier"] = identifier
    if birthdate := args.get("birthdate"):
        params["birthdate"] = birthdate
    if gender := args.get("gender"):
        params["gender"] = gender
    # Return enough results for the UI to browse the full synthetic cohort.
    params["_count"] = str(args.get("count", "200"))
    params["_total"] = "accurate"

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


# =============================================================================
# Inpatient Encounter Lifecycle
# =============================================================================


async def handle_create_inpatient_encounter(args: dict) -> dict:
    """Create an inpatient encounter for a patient."""
    patient_id = args["patient_id"]
    reason = args.get("reason", "Inpatient admission")
    admit_source = args.get("admit_source", "emd")
    location = args.get("location", "General Ward")
    priority = args.get("priority", "routine")
    type_code = args.get("type_code")
    type_display = args.get("type_display")

    now_iso = datetime.now(timezone.utc).isoformat()

    encounter = {
        "resourceType": "Encounter",
        "status": "in-progress",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "IMP",
            "display": "inpatient encounter",
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "period": {
            "start": now_iso,
        },
        "reasonCode": [
            {
                "text": reason,
            }
        ],
        "hospitalization": {
            "admitSource": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/admit-source",
                        "code": admit_source,
                    }
                ]
            },
        },
        "location": [
            {
                "location": {
                    "display": location,
                },
                "status": "active",
                "period": {
                    "start": now_iso,
                },
            }
        ],
        "priority": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
                    "code": priority,
                    "display": priority,
                }
            ]
        },
    }

    if type_code or type_display:
        encounter["type"] = [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": type_code or "unknown",
                        "display": type_display or type_code or "Unknown",
                    }
                ]
            }
        ]

    result = await fhir_client.create("Encounter", encounter)
    fhir_id = result.get("id")

    # Build summary for approval queue
    summary = f"Inpatient admission: {reason} at {location}"

    # Queue for approval
    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.ENCOUNTER,
        patient_id=patient_id,
        resource=encounter,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent", "admit_source": admit_source, "priority": priority},
    )

    return {
        "status": "in-progress",
        "message": "Inpatient encounter created. Requires clinician approval.",
        "action_id": action.action_id,
        "encounter_id": fhir_id,
    }


async def handle_update_encounter_status(args: dict) -> dict:
    """Update the status of an existing encounter."""
    encounter_id = args["encounter_id"]
    new_status = args["status"]

    valid_statuses = [
        "planned", "arrived", "triaged", "in-progress",
        "onleave", "finished", "cancelled", "entered-in-error",
    ]
    if new_status not in valid_statuses:
        return {"error": f"Invalid status '{new_status}'. Must be one of: {', '.join(valid_statuses)}"}

    try:
        current = await fhir_client.read("Encounter", encounter_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Encounter {encounter_id} not found"}
        raise

    old_status = current.get("status", "unknown")
    current["status"] = new_status

    # If finishing, set period.end
    if new_status == "finished":
        if "period" not in current:
            current["period"] = {}
        current["period"]["end"] = datetime.now(timezone.utc).isoformat()

    await fhir_client.update("Encounter", encounter_id, current)

    return {
        "encounter_id": encounter_id,
        "old_status": old_status,
        "new_status": new_status,
        "message": f"Encounter status updated from '{old_status}' to '{new_status}'",
    }


async def handle_get_encounter_timeline(args: dict) -> dict:
    """Get a comprehensive timeline for an encounter including observations, conditions, medications, and flags."""
    encounter_id = args["encounter_id"]

    # Parallel-fetch all related data
    results = await asyncio.gather(
        fhir_client.read("Encounter", encounter_id),
        fhir_client.search("Observation", {"encounter": encounter_id, "_sort": "-date", "_count": "50"}),
        fhir_client.search("Condition", {"encounter": encounter_id}),
        fhir_client.search("MedicationRequest", {"encounter": encounter_id}),
        fhir_client.search("Flag", {"encounter": encounter_id}),
        return_exceptions=True,
    )

    encounter_data, obs_bundle, cond_bundle, med_bundle, flag_bundle = results

    # Process encounter info
    if isinstance(encounter_data, Exception):
        return {"error": f"Failed to read encounter {encounter_id}: {str(encounter_data)}"}

    encounter_info = {
        "id": encounter_data.get("id"),
        "status": encounter_data.get("status"),
        "class": encounter_data.get("class", {}).get("display"),
        "period": encounter_data.get("period"),
        "location": [
            loc.get("location", {}).get("display")
            for loc in encounter_data.get("location", [])
        ],
    }

    # Process observations
    observations = []
    if not isinstance(obs_bundle, Exception):
        for entry in obs_bundle.get("entry", []):
            resource = entry.get("resource", {})
            observations.append({
                "id": resource.get("id"),
                "code": extract_code_display(resource.get("code")),
                "value": extract_observation_value(resource),
                "effective_date": resource.get("effectiveDateTime"),
            })
    else:
        observations = []

    # Process conditions
    conditions = []
    if not isinstance(cond_bundle, Exception):
        for entry in cond_bundle.get("entry", []):
            resource = entry.get("resource", {})
            conditions.append({
                "id": resource.get("id"),
                "code": extract_code_display(resource.get("code")),
                "clinical_status": extract_code_display(resource.get("clinicalStatus")),
                "onset": resource.get("onsetDateTime"),
            })
    else:
        conditions = []

    # Process medications
    medications = []
    if not isinstance(med_bundle, Exception):
        for entry in med_bundle.get("entry", []):
            resource = entry.get("resource", {})
            medications.append({
                "id": resource.get("id"),
                "medication": extract_medication_name(resource),
                "status": resource.get("status"),
                "authored_on": resource.get("authoredOn"),
            })
    else:
        medications = []

    # Process flags
    flags = []
    if not isinstance(flag_bundle, Exception):
        for entry in flag_bundle.get("entry", []):
            resource = entry.get("resource", {})
            category_list = resource.get("category", [])
            category = extract_code_display(category_list[0]) if category_list else "Unknown"
            flags.append({
                "id": resource.get("id"),
                "status": resource.get("status"),
                "code": extract_code_display(resource.get("code")),
                "category": category,
            })
    else:
        flags = []

    # Assemble warnings for any failed sub-fetches
    warnings = []
    section_names = ["observations", "conditions", "medications", "flags"]
    section_results = [obs_bundle, cond_bundle, med_bundle, flag_bundle]
    for name, res in zip(section_names, section_results):
        if isinstance(res, Exception):
            warnings.append(f"Failed to fetch {name}: {str(res)}")

    timeline = {
        "encounter": encounter_info,
        "observations": observations,
        "conditions": conditions,
        "medications": medications,
        "flags": flags,
    }

    if warnings:
        timeline["warnings"] = warnings

    return timeline


async def handle_transfer_patient(args: dict) -> dict:
    """Transfer a patient to a new location within the hospital."""
    encounter_id = args["encounter_id"]
    new_location = args["new_location"]
    new_location_status = args.get("new_location_status", "active")

    try:
        current = await fhir_client.read("Encounter", encounter_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Encounter {encounter_id} not found"}
        raise

    now_iso = datetime.now(timezone.utc).isoformat()

    locations = current.get("location", [])
    old_location = None

    # Mark the current active location as completed
    for loc in locations:
        if loc.get("status") == "active":
            old_location = loc.get("location", {}).get("display", "Unknown")
            loc["status"] = "completed"
            if "period" not in loc:
                loc["period"] = {}
            loc["period"]["end"] = now_iso

    # Add new location
    locations.append({
        "location": {
            "display": new_location,
        },
        "status": new_location_status,
        "period": {
            "start": now_iso,
        },
    })

    current["location"] = locations
    await fhir_client.update("Encounter", encounter_id, current)

    return {
        "encounter_id": encounter_id,
        "old_location": old_location or "Unknown",
        "new_location": new_location,
        "message": f"Patient transferred from '{old_location or 'Unknown'}' to '{new_location}'",
    }


async def handle_discharge_patient(args: dict) -> dict:
    """Discharge a patient from an inpatient encounter."""
    encounter_id = args["encounter_id"]
    discharge_disposition = args.get("discharge_disposition", "home")
    discharge_display = args.get("discharge_display", "Discharge to home")

    try:
        current = await fhir_client.read("Encounter", encounter_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Encounter {encounter_id} not found"}
        raise

    now_iso = datetime.now(timezone.utc).isoformat()

    # Set status to finished
    current["status"] = "finished"

    # Set period.end
    if "period" not in current:
        current["period"] = {}
    current["period"]["end"] = now_iso

    # Set discharge disposition
    if "hospitalization" not in current:
        current["hospitalization"] = {}
    current["hospitalization"]["dischargeDisposition"] = {
        "coding": [
            {
                "system": "http://terminology.hl7.org/CodeSystem/discharge-disposition",
                "code": discharge_disposition,
                "display": discharge_display,
            }
        ],
        "text": discharge_display,
    }

    await fhir_client.update("Encounter", encounter_id, current)

    # Calculate length of stay if possible
    length_of_stay = None
    period = current.get("period", {})
    start_str = period.get("start")
    end_str = period.get("end")
    if start_str and end_str:
        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            delta = end_dt - start_dt
            length_of_stay = f"{delta.days} days, {delta.seconds // 3600} hours"
        except (ValueError, TypeError):
            pass

    return {
        "encounter_id": encounter_id,
        "status": "finished",
        "discharge_disposition": discharge_disposition,
        "length_of_stay": length_of_stay,
        "message": f"Patient discharged. Disposition: {discharge_display}",
    }


# =============================================================================
# Clinical Flags
# =============================================================================


async def handle_create_flag(args: dict) -> dict:
    """Create a clinical flag/alert for a patient."""
    patient_id = args["patient_id"]
    description = args["description"]
    category = args.get("category", "clinical")
    encounter_id = args.get("encounter_id")
    priority = args.get("priority")
    author = args.get("author")

    now_iso = datetime.now(timezone.utc).isoformat()

    # Map category string to coded value
    category_map = {
        "clinical": ("clinical", "Clinical"),
        "safety": ("safety", "Safety"),
        "drug": ("drug", "Drug"),
        "lab": ("lab", "Lab"),
        "contact": ("contact", "Contact"),
        "behavioral": ("behavioral", "Behavioral"),
        "research": ("research", "Research"),
        "advance-directive": ("advance-directive", "Advance Directive"),
    }

    cat_code, cat_display = category_map.get(category, ("clinical", "Clinical"))

    flag_resource = {
        "resourceType": "Flag",
        "status": "active",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/flag-category",
                        "code": cat_code,
                        "display": cat_display,
                    }
                ]
            }
        ],
        "code": {
            "text": description,
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "period": {
            "start": now_iso,
        },
    }

    if encounter_id:
        flag_resource["encounter"] = {
            "reference": f"Encounter/{encounter_id}",
        }

    if priority:
        flag_resource["extension"] = [
            {
                "url": "http://hl7.org/fhir/StructureDefinition/flag-priority",
                "valueCodeableConcept": {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/flag-priority-code",
                            "code": priority,
                        }
                    ]
                },
            }
        ]

    if author:
        flag_resource["author"] = {
            "display": author,
        }

    result = await fhir_client.create("Flag", flag_resource)
    fhir_id = result.get("id")

    # Build summary for approval queue
    summary = f"Flag ({cat_display}): {description}"

    # Queue for approval
    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.FLAG,
        patient_id=patient_id,
        resource=flag_resource,
        fhir_id=fhir_id,
        summary=summary,
        metadata={"requester": "agent", "category": category},
    )

    return {
        "status": "active",
        "message": "Clinical flag created. Requires clinician approval.",
        "action_id": action.action_id,
        "flag": {
            "id": fhir_id,
            "description": description,
            "category": cat_display,
            "status": "active",
        },
    }


async def handle_get_active_flags(args: dict) -> dict:
    """Get active clinical flags for a patient."""
    patient_id = args["patient_id"]
    encounter_id = args.get("encounter_id")

    params = {
        "patient": patient_id,
        "status": "active",
    }
    if encounter_id:
        params["encounter"] = encounter_id

    bundle = await fhir_client.search("Flag", params)

    flags = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        category_list = resource.get("category", [])
        category = extract_code_display(category_list[0]) if category_list else "Unknown"
        flags.append({
            "id": resource.get("id"),
            "status": resource.get("status"),
            "category": category,
            "code": extract_code_display(resource.get("code")),
            "period": resource.get("period"),
        })

    return {
        "total": bundle.get("total", len(flags)),
        "flags": flags,
    }


async def handle_resolve_flag(args: dict) -> dict:
    """Resolve (inactivate) a clinical flag."""
    flag_id = args["flag_id"]

    try:
        current = await fhir_client.read("Flag", flag_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Flag {flag_id} not found"}
        raise

    old_status = current.get("status", "unknown")
    current["status"] = "inactive"

    # Set period.end
    if "period" not in current:
        current["period"] = {}
    current["period"]["end"] = datetime.now(timezone.utc).isoformat()

    await fhir_client.update("Flag", flag_id, current)

    return {
        "flag_id": flag_id,
        "old_status": old_status,
        "new_status": "inactive",
        "message": f"Flag resolved. Status changed from '{old_status}' to 'inactive'",
    }


# =============================================================================
# Clinical Assessment (ClinicalImpression + RiskAssessment)
# =============================================================================


async def handle_create_clinical_impression(args: dict) -> dict:
    """Create a clinical impression (assessment) for a patient."""
    patient_id = args["patient_id"]
    summary_text = args["summary"]
    encounter_id = args.get("encounter_id")
    assessor = args.get("assessor")
    finding_code = args.get("finding_code")
    finding_display = args.get("finding_display")
    notes = args.get("notes", [])
    status = args.get("status", "completed")

    now_iso = datetime.now(timezone.utc).isoformat()

    impression = {
        "resourceType": "ClinicalImpression",
        "status": status,
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "date": now_iso,
        "summary": summary_text,
    }

    if encounter_id:
        impression["encounter"] = {
            "reference": f"Encounter/{encounter_id}",
        }

    if assessor:
        impression["assessor"] = {
            "display": assessor,
        }

    # Build finding array
    if finding_code or finding_display:
        finding_item = {}
        coding = {
            "system": "http://snomed.info/sct",
        }
        if finding_code:
            coding["code"] = finding_code
        if finding_display:
            coding["display"] = finding_display
        finding_item["itemCodeableConcept"] = {
            "coding": [coding],
        }
        if finding_display:
            finding_item["itemCodeableConcept"]["text"] = finding_display
        impression["finding"] = [finding_item]

    # Build note array
    if notes:
        impression["note"] = [{"text": n} for n in notes]

    # Route through approval queue
    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.CLINICAL_IMPRESSION,
        patient_id=patient_id,
        resource=impression,
        fhir_id=None,
        summary=f"Clinical impression: {summary_text[:80]}",
        metadata={"requester": assessor or "agent"},
    )

    return {
        "impression_id": None,
        "status": status,
        "summary": summary_text,
        "action_id": action.action_id,
        "message": "Clinical impression queued for approval.",
    }


async def handle_get_clinical_impressions(args: dict) -> dict:
    """Get clinical impressions for a patient."""
    patient_id = args["patient_id"]
    encounter_id = args.get("encounter_id")
    status_filter = args.get("status")

    params = {"patient": patient_id}
    if encounter_id:
        params["encounter"] = encounter_id
    if status_filter:
        params["status"] = status_filter

    bundle = await fhir_client.search("ClinicalImpression", params)

    impressions = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        # Extract findings
        findings = []
        for finding in resource.get("finding", []):
            item_cc = finding.get("itemCodeableConcept")
            if item_cc:
                findings.append(extract_code_display(item_cc))

        impressions.append({
            "id": resource.get("id"),
            "status": resource.get("status"),
            "date": resource.get("date"),
            "assessor": resource.get("assessor", {}).get("display"),
            "summary": resource.get("summary"),
            "findings": findings,
        })

    return {
        "total": bundle.get("total", len(impressions)),
        "impressions": impressions,
    }


async def handle_create_risk_assessment(args: dict) -> dict:
    """Create a risk assessment for a patient."""
    patient_id = args["patient_id"]
    condition_display = args["condition_display"]
    encounter_id = args.get("encounter_id")
    outcome_text = args.get("outcome_text")
    risk_level = args.get("risk_level")
    basis = args.get("basis", [])
    notes = args.get("notes", [])
    status = args.get("status", "final")

    now_iso = datetime.now(timezone.utc).isoformat()

    assessment = {
        "resourceType": "RiskAssessment",
        "status": status,
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "occurrenceDateTime": now_iso,
        "condition": {
            "display": condition_display,
        },
    }

    if encounter_id:
        assessment["encounter"] = {
            "reference": f"Encounter/{encounter_id}",
        }

    # Build prediction array
    if outcome_text or risk_level:
        prediction = {}
        if outcome_text:
            prediction["outcome"] = {"text": outcome_text}
        if risk_level:
            prediction["qualitativeRisk"] = {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/risk-probability",
                    "code": risk_level,
                    "display": risk_level.capitalize(),
                }],
                "text": risk_level,
            }
        assessment["prediction"] = [prediction]

    # Build basis array (references as display strings)
    if basis:
        assessment["basis"] = [{"display": b} for b in basis]

    # Build note array
    if notes:
        assessment["note"] = [{"text": n} for n in notes]

    # Route through approval queue
    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.RISK_ASSESSMENT,
        patient_id=patient_id,
        resource=assessment,
        fhir_id=None,
        summary=f"Risk assessment: {condition_display}" + (f" ({risk_level})" if risk_level else ""),
        metadata={"requester": "agent"},
    )

    return {
        "assessment_id": None,
        "condition": condition_display,
        "risk_level": risk_level,
        "action_id": action.action_id,
        "message": "Risk assessment queued for approval.",
    }


async def handle_get_risk_assessments(args: dict) -> dict:
    """Get risk assessments for a patient."""
    patient_id = args["patient_id"]
    encounter_id = args.get("encounter_id")

    params = {"patient": patient_id}
    if encounter_id:
        params["encounter"] = encounter_id

    bundle = await fhir_client.search("RiskAssessment", params)

    assessments = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        # Extract predictions
        predictions = []
        for pred in resource.get("prediction", []):
            predictions.append({
                "outcome": pred.get("outcome", {}).get("text"),
                "risk_level": extract_code_display(pred.get("qualitativeRisk")),
            })

        # Extract basis
        basis_list = []
        for b in resource.get("basis", []):
            basis_list.append(b.get("display") or b.get("reference", ""))

        assessments.append({
            "id": resource.get("id"),
            "status": resource.get("status"),
            "date": resource.get("occurrenceDateTime"),
            "condition": resource.get("condition", {}).get("display"),
            "predictions": predictions,
            "basis": basis_list,
        })

    return {
        "total": bundle.get("total", len(assessments)),
        "assessments": assessments,
    }


# =============================================================================
# Task Management
# =============================================================================


async def handle_create_task(args: dict) -> dict:
    """Create a care coordination task for a patient."""
    patient_id = args["patient_id"]
    description = args["description"]
    encounter_id = args.get("encounter_id")
    priority = args.get("priority", "routine")
    requester = args.get("requester", "Supervisor Agent")
    owner = args.get("owner")
    due_date = args.get("due_date")
    notes = args.get("notes", [])
    intent = args.get("intent", "order")

    task = {
        "resourceType": "Task",
        "status": "requested",
        "intent": intent,
        "priority": priority,
        "code": {
            "text": description,
        },
        "for": {
            "reference": f"Patient/{patient_id}",
        },
        "requester": {
            "display": requester,
        },
    }

    if encounter_id:
        task["encounter"] = {
            "reference": f"Encounter/{encounter_id}",
        }

    if owner:
        task["owner"] = {
            "display": owner,
        }

    if due_date:
        task["restriction"] = {
            "period": {
                "end": due_date,
            },
        }

    if notes:
        task["note"] = [{"text": n} for n in notes]

    # Route through approval queue
    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.TASK,
        patient_id=patient_id,
        resource=task,
        fhir_id=None,
        summary=f"Task: {description[:80]} ({priority})",
        metadata={"requester": requester},
    )

    return {
        "task_id": None,
        "status": "requested",
        "priority": priority,
        "description": description,
        "action_id": action.action_id,
        "message": "Task queued for approval.",
    }


async def handle_assign_task(args: dict) -> dict:
    """Assign a task to an owner."""
    task_id = args["task_id"]
    owner = args["owner"]

    try:
        current = await fhir_client.read("Task", task_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Task {task_id} not found"}
        raise

    current["owner"] = {"display": owner}

    # Accept the task if it is currently in requested status
    if current.get("status") == "requested":
        current["status"] = "accepted"

    await fhir_client.update("Task", task_id, current)

    return {
        "task_id": task_id,
        "owner": owner,
        "status": current["status"],
        "message": f"Task assigned to {owner}. Status: {current['status']}",
    }


async def handle_complete_task(args: dict) -> dict:
    """Mark a task as completed."""
    task_id = args["task_id"]
    output_text = args.get("output_text")

    try:
        current = await fhir_client.read("Task", task_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Task {task_id} not found"}
        raise

    now_iso = datetime.now(timezone.utc).isoformat()

    current["status"] = "completed"

    # Set executionPeriod.end
    if "executionPeriod" not in current:
        current["executionPeriod"] = {}
    current["executionPeriod"]["end"] = now_iso

    # Add output note if provided
    if output_text:
        if "output" not in current:
            current["output"] = []
        current["output"].append({
            "type": {"text": "Completion notes"},
            "valueString": output_text,
        })

    await fhir_client.update("Task", task_id, current)

    return {
        "task_id": task_id,
        "status": "completed",
        "completed_at": now_iso,
        "message": "Task marked as completed.",
    }


async def handle_get_pending_tasks(args: dict) -> dict:
    """Get pending (non-completed) tasks for a patient."""
    patient_id = args["patient_id"]
    encounter_id = args.get("encounter_id")
    status = args.get("status", "requested,accepted,in-progress")

    params = {
        "patient": patient_id,
        "status": status,
    }
    if encounter_id:
        params["encounter"] = encounter_id

    bundle = await fhir_client.search("Task", params)

    tasks = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        tasks.append({
            "id": resource.get("id"),
            "status": resource.get("status"),
            "priority": resource.get("priority"),
            "description": resource.get("code", {}).get("text"),
            "owner": resource.get("owner", {}).get("display"),
            "due_date": resource.get("restriction", {}).get("period", {}).get("end"),
            "requester": resource.get("requester", {}).get("display"),
        })

    return {
        "total": bundle.get("total", len(tasks)),
        "tasks": tasks,
    }


async def handle_update_task_status(args: dict) -> dict:
    """Update the status of a task."""
    task_id = args["task_id"]
    new_status = args["status"]

    try:
        current = await fhir_client.read("Task", task_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Task {task_id} not found"}
        raise

    old_status = current.get("status", "unknown")
    now_iso = datetime.now(timezone.utc).isoformat()

    current["status"] = new_status

    # Set executionPeriod timestamps based on status transitions
    if new_status == "in-progress":
        if "executionPeriod" not in current:
            current["executionPeriod"] = {}
        current["executionPeriod"]["start"] = now_iso
    elif new_status in ("completed", "failed"):
        if "executionPeriod" not in current:
            current["executionPeriod"] = {}
        current["executionPeriod"]["end"] = now_iso

    await fhir_client.update("Task", task_id, current)

    return {
        "task_id": task_id,
        "old_status": old_status,
        "new_status": new_status,
        "message": f"Task status changed from '{old_status}' to '{new_status}'",
    }


# =============================================================================
# Care Team
# =============================================================================


async def handle_create_care_team(args: dict) -> dict:
    """Create a care team for a patient."""
    patient_id = args["patient_id"]
    name = args["name"]
    encounter_id = args.get("encounter_id")
    status = args.get("status", "active")
    participants = args.get("participants", [])

    care_team = {
        "resourceType": "CareTeam",
        "status": status,
        "name": name,
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
    }

    if encounter_id:
        care_team["encounter"] = {
            "reference": f"Encounter/{encounter_id}",
        }

    # Build participant array
    participant_array = []
    for p in participants:
        participant_entry = {}
        if p.get("role_code") or p.get("role_display"):
            role_coding = {
                "system": "http://snomed.info/sct",
            }
            if p.get("role_code"):
                role_coding["code"] = p["role_code"]
            if p.get("role_display"):
                role_coding["display"] = p["role_display"]
            participant_entry["role"] = [{
                "coding": [role_coding],
            }]
        if p.get("member_display"):
            participant_entry["member"] = {
                "display": p["member_display"],
            }
        if participant_entry:
            participant_array.append(participant_entry)

    if participant_array:
        care_team["participant"] = participant_array

    # Route through approval queue
    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.CARE_TEAM,
        patient_id=patient_id,
        resource=care_team,
        fhir_id=None,
        summary=f"Care team: {name} ({len(participant_array)} participants)",
        metadata={"requester": "agent"},
    )

    return {
        "care_team_id": None,
        "name": name,
        "participant_count": len(participant_array),
        "action_id": action.action_id,
        "message": "Care team queued for approval.",
    }


async def handle_get_care_team(args: dict) -> dict:
    """Get care teams for a patient."""
    patient_id = args["patient_id"]
    encounter_id = args.get("encounter_id")
    status = args.get("status", "active")

    params = {
        "patient": patient_id,
        "status": status,
    }
    if encounter_id:
        params["encounter"] = encounter_id

    bundle = await fhir_client.search("CareTeam", params)

    care_teams = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        participants = []
        for p in resource.get("participant", []):
            role_list = p.get("role", [])
            role = extract_code_display(role_list[0]) if role_list else "Unknown"
            member = p.get("member", {}).get("display", "Unknown")
            participants.append({
                "role": role,
                "member": member,
            })

        care_teams.append({
            "id": resource.get("id"),
            "name": resource.get("name"),
            "status": resource.get("status"),
            "participants": participants,
        })

    return {
        "total": bundle.get("total", len(care_teams)),
        "care_teams": care_teams,
    }


async def handle_update_care_team_member(args: dict) -> dict:
    """Add or remove a member from a care team."""
    care_team_id = args["care_team_id"]
    action = args["action"]  # "add" or "remove"
    member_display = args["member_display"]
    role_code = args.get("role_code")
    role_display = args.get("role_display")

    try:
        current = await fhir_client.read("CareTeam", care_team_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"CareTeam {care_team_id} not found"}
        raise

    participants = current.get("participant", [])

    if action == "add":
        new_participant = {
            "member": {
                "display": member_display,
            },
        }
        if role_code or role_display:
            role_coding = {
                "system": "http://snomed.info/sct",
            }
            if role_code:
                role_coding["code"] = role_code
            if role_display:
                role_coding["display"] = role_display
            new_participant["role"] = [{
                "coding": [role_coding],
            }]
        participants.append(new_participant)
    elif action == "remove":
        participants = [
            p for p in participants
            if p.get("member", {}).get("display") != member_display
        ]

    current["participant"] = participants
    await fhir_client.update("CareTeam", care_team_id, current)

    return {
        "care_team_id": care_team_id,
        "action": action,
        "member": member_display,
        "participant_count": len(participants),
        "message": f"Member '{member_display}' {'added to' if action == 'add' else 'removed from'} care team.",
    }


# =============================================================================
# Goals
# =============================================================================


async def handle_create_goal(args: dict) -> dict:
    """Create a clinical goal for a patient."""
    patient_id = args["patient_id"]
    description = args["description"]
    encounter_id = args.get("encounter_id")
    lifecycle_status = args.get("lifecycle_status", "active")
    achievement_status = args.get("achievement_status", "in-progress")
    target_measure_code = args.get("target_measure_code")
    target_measure_display = args.get("target_measure_display")
    target_value = args.get("target_value")
    target_unit = args.get("target_unit")
    start_date = args.get("start_date")
    category = args.get("category")

    goal = {
        "resourceType": "Goal",
        "lifecycleStatus": lifecycle_status,
        "achievementStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/goal-achievement",
                "code": achievement_status,
                "display": achievement_status.replace("-", " ").title(),
            }],
        },
        "description": {
            "text": description,
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
    }

    if encounter_id:
        goal["encounter"] = {
            "reference": f"Encounter/{encounter_id}",
        }

    if start_date:
        goal["startDate"] = start_date

    if category:
        goal["category"] = [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/goal-category",
                "code": category,
                "display": category.capitalize(),
            }],
        }]

    # Build target array if measure provided
    if target_measure_code or target_measure_display:
        target = {
            "measure": {
                "coding": [{
                    "system": "http://loinc.org",
                }],
            },
        }
        if target_measure_code:
            target["measure"]["coding"][0]["code"] = target_measure_code
        if target_measure_display:
            target["measure"]["coding"][0]["display"] = target_measure_display

        if target_value is not None and target_unit:
            target["detailQuantity"] = {
                "value": target_value,
                "unit": target_unit,
                "system": "http://unitsofmeasure.org",
            }

        goal["target"] = [target]

    # Route through approval queue
    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.GOAL,
        patient_id=patient_id,
        resource=goal,
        fhir_id=None,
        summary=f"Goal: {description[:80]}",
        metadata={"requester": "agent"},
    )

    return {
        "goal_id": None,
        "description": description,
        "lifecycle_status": lifecycle_status,
        "action_id": action.action_id,
        "message": "Goal queued for approval.",
    }


async def handle_get_patient_goals(args: dict) -> dict:
    """Get goals for a patient."""
    patient_id = args["patient_id"]
    lifecycle_status = args.get("lifecycle_status")
    encounter_id = args.get("encounter_id")

    params = {"patient": patient_id}
    if lifecycle_status:
        params["lifecycle-status"] = lifecycle_status
    if encounter_id:
        params["encounter"] = encounter_id

    bundle = await fhir_client.search("Goal", params)

    goals = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        # Extract targets
        targets = []
        for t in resource.get("target", []):
            measure = extract_code_display(t.get("measure"))
            detail = t.get("detailQuantity", {})
            targets.append({
                "measure": measure,
                "value": detail.get("value"),
                "unit": detail.get("unit"),
            })

        goals.append({
            "id": resource.get("id"),
            "lifecycle_status": resource.get("lifecycleStatus"),
            "achievement_status": extract_code_display(resource.get("achievementStatus")),
            "description": resource.get("description", {}).get("text"),
            "targets": targets,
        })

    return {
        "total": bundle.get("total", len(goals)),
        "goals": goals,
    }


async def handle_update_goal_status(args: dict) -> dict:
    """Update the lifecycle status of a goal."""
    goal_id = args["goal_id"]
    lifecycle_status = args["lifecycle_status"]
    achievement_status = args.get("achievement_status")

    try:
        current = await fhir_client.read("Goal", goal_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Goal {goal_id} not found"}
        raise

    old_lifecycle_status = current.get("lifecycleStatus", "unknown")
    current["lifecycleStatus"] = lifecycle_status

    # If completed and no explicit achievement_status, default to achieved
    if lifecycle_status == "completed" and not achievement_status:
        achievement_status = "achieved"

    if achievement_status:
        current["achievementStatus"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/goal-achievement",
                "code": achievement_status,
                "display": achievement_status.replace("-", " ").title(),
            }],
        }

    await fhir_client.update("Goal", goal_id, current)

    final_achievement = achievement_status or extract_code_display(current.get("achievementStatus"))

    return {
        "goal_id": goal_id,
        "old_lifecycle_status": old_lifecycle_status,
        "new_lifecycle_status": lifecycle_status,
        "achievement_status": final_achievement,
        "message": f"Goal status changed from '{old_lifecycle_status}' to '{lifecycle_status}'",
    }


# =============================================================================
# Device Metrics
# =============================================================================


async def handle_record_device_metric(args: dict) -> dict:
    """Record a device metric."""
    type_code = args["type_code"]
    type_display = args["type_display"]
    source_display = args.get("source_display")
    category = args.get("category", "measurement")
    operational_status = args.get("operational_status", "on")

    device_metric = {
        "resourceType": "DeviceMetric",
        "type": {
            "coding": [{
                "system": "urn:iso:std:iso:11073:10101",
                "code": type_code,
                "display": type_display,
            }],
        },
        "category": category,
        "operationalStatus": operational_status,
    }

    if source_display:
        device_metric["source"] = {
            "display": source_display,
        }

    result = await fhir_client.create("DeviceMetric", device_metric)
    fhir_id = result.get("id")

    # Route through approval queue (device-level, use placeholder patient_id)
    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.DEVICE_METRIC,
        patient_id="device-registry",
        resource=device_metric,
        fhir_id=fhir_id,
        summary=f"Device metric: {type_display} ({category})",
        metadata={"requester": "agent", "source": source_display or "unknown"},
    )

    return {
        "device_metric_id": fhir_id,
        "type": type_display,
        "source": source_display,
        "category": category,
        "message": f"Device metric recorded: {type_display}",
    }


async def handle_get_device_metrics(args: dict) -> dict:
    """Get device metrics with optional filtering."""
    type_code = args.get("type_code")
    category = args.get("category")
    source = args.get("source")

    params = {}
    if type_code:
        params["type"] = type_code
    if category:
        params["category"] = category
    if source:
        params["source"] = source

    bundle = await fhir_client.search("DeviceMetric", params)

    metrics = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        metrics.append({
            "id": resource.get("id"),
            "type": extract_code_display(resource.get("type")),
            "source": resource.get("source", {}).get("display"),
            "category": resource.get("category"),
            "operational_status": resource.get("operationalStatus"),
        })

    return {
        "total": bundle.get("total", len(metrics)),
        "metrics": metrics,
    }


# =============================================================================
# Adverse Events
# =============================================================================


async def handle_report_adverse_event(args: dict) -> dict:
    """Report an adverse event for a patient."""
    patient_id = args["patient_id"]
    event_description = args["event_description"]
    encounter_id = args.get("encounter_id")
    actuality = args.get("actuality", "actual")
    category_code = args.get("category_code")
    seriousness = args.get("seriousness")
    severity = args.get("severity")
    date = args.get("date", datetime.now(timezone.utc).isoformat())

    adverse_event = {
        "resourceType": "AdverseEvent",
        "actuality": actuality,
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "date": date,
        "event": {
            "text": event_description,
        },
    }

    if encounter_id:
        adverse_event["encounter"] = {
            "reference": f"Encounter/{encounter_id}",
        }

    if category_code:
        adverse_event["category"] = [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/adverse-event-category",
                "code": category_code,
                "display": category_code.replace("-", " ").title(),
            }],
        }]

    if seriousness:
        adverse_event["seriousness"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/adverse-event-seriousness",
                "code": seriousness,
                "display": seriousness.capitalize(),
            }],
        }

    if severity:
        adverse_event["severity"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/adverse-event-severity",
                "code": severity,
                "display": severity.capitalize(),
            }],
        }

    # Route through approval queue
    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.ADVERSE_EVENT,
        patient_id=patient_id,
        resource=adverse_event,
        fhir_id=None,
        summary=f"Adverse event ({actuality}): {event_description[:80]}",
        metadata={"requester": "agent", "seriousness": seriousness or "unknown"},
    )

    return {
        "adverse_event_id": None,
        "event_description": event_description,
        "actuality": actuality,
        "seriousness": seriousness,
        "action_id": action.action_id,
        "message": "Adverse event queued for approval.",
    }


async def handle_get_adverse_events(args: dict) -> dict:
    """Get adverse events for a patient."""
    patient_id = args["patient_id"]
    encounter_id = args.get("encounter_id")
    actuality = args.get("actuality")
    seriousness = args.get("seriousness")
    date = args.get("date")

    params = {"subject": patient_id}
    if encounter_id:
        params["encounter"] = encounter_id
    if actuality:
        params["actuality"] = actuality
    if seriousness:
        params["seriousness"] = seriousness
    if date:
        params["date"] = date

    bundle = await fhir_client.search("AdverseEvent", params)

    events = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        category_list = resource.get("category", [])
        category = extract_code_display(category_list[0]) if category_list else None

        events.append({
            "id": resource.get("id"),
            "actuality": resource.get("actuality"),
            "date": resource.get("date"),
            "event": resource.get("event", {}).get("text"),
            "category": category,
            "seriousness": extract_code_display(resource.get("seriousness")),
            "severity": extract_code_display(resource.get("severity")),
        })

    return {
        "total": bundle.get("total", len(events)),
        "adverse_events": events,
    }


# =============================================================================
# Inpatient Communication
# =============================================================================


async def handle_create_inpatient_communication(args: dict) -> dict:
    """Create an inpatient communication (handoff note, consult request, etc.)."""
    patient_id = args["patient_id"]
    content = args["content"]
    encounter_id = args.get("encounter_id")
    category = args.get("category", "handoff")
    sender = args.get("sender")
    recipient = args.get("recipient")
    priority = args.get("priority", "routine")
    topic = args.get("topic")

    now_iso = datetime.now(timezone.utc).isoformat()

    communication = {
        "resourceType": "Communication",
        "status": "completed",
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/communication-category",
                "code": category,
                "display": category.replace("_", " ").title(),
            }],
        }],
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
        "sent": now_iso,
        "payload": [{
            "contentString": content,
        }],
        "priority": priority,
    }

    if encounter_id:
        communication["encounter"] = {
            "reference": f"Encounter/{encounter_id}",
        }

    if sender:
        communication["sender"] = {
            "display": sender,
        }

    if recipient:
        communication["recipient"] = [{
            "display": recipient,
        }]

    if topic:
        communication["topic"] = {
            "text": topic,
        }

    # Route through approval queue
    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.COMMUNICATION,
        patient_id=patient_id,
        resource=communication,
        fhir_id=None,
        summary=f"Communication ({category}): {content[:80]}",
        metadata={"requester": sender or "agent", "priority": priority},
    )

    return {
        "communication_id": None,
        "category": category,
        "content_preview": content[:100],
        "action_id": action.action_id,
        "message": "Communication queued for approval.",
    }


async def handle_get_communications(args: dict) -> dict:
    """Get communications for an encounter."""
    encounter_id = args["encounter_id"]
    category = args.get("category")

    params = {"encounter": encounter_id}
    if category:
        params["category"] = category

    bundle = await fhir_client.search("Communication", params)

    communications = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        # Extract content from payload
        payload_content = None
        for payload in resource.get("payload", []):
            if "contentString" in payload:
                payload_content = payload["contentString"]
                break

        category_list = resource.get("category", [])
        cat = extract_code_display(category_list[0]) if category_list else None

        communications.append({
            "id": resource.get("id"),
            "status": resource.get("status"),
            "category": cat,
            "sent": resource.get("sent"),
            "sender": resource.get("sender", {}).get("display"),
            "content": payload_content,
            "topic": resource.get("topic", {}).get("text"),
        })

    return {
        "total": bundle.get("total", len(communications)),
        "communications": communications,
    }


async def handle_search_communications(args: dict) -> dict:
    """Search communications for a patient."""
    patient_id = args["patient_id"]
    category = args.get("category")
    sender = args.get("sender")
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    encounter_id = args.get("encounter_id")

    params = {"patient": patient_id}
    if category:
        params["category"] = category
    if sender:
        params["sender"] = sender
    if date_from:
        params["sent"] = f"ge{date_from}"
    if date_to:
        if "sent" in params:
            # FHIR allows multiple date params for range filtering
            params["sent"] = [params["sent"], f"le{date_to}"]
        else:
            params["sent"] = f"le{date_to}"
    if encounter_id:
        params["encounter"] = encounter_id

    bundle = await fhir_client.search("Communication", params)

    communications = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        # Extract content from payload
        payload_content = None
        for payload in resource.get("payload", []):
            if "contentString" in payload:
                payload_content = payload["contentString"]
                break

        category_list = resource.get("category", [])
        cat = extract_code_display(category_list[0]) if category_list else None

        communications.append({
            "id": resource.get("id"),
            "status": resource.get("status"),
            "category": cat,
            "sent": resource.get("sent"),
            "sender": resource.get("sender", {}).get("display"),
            "content": payload_content,
            "topic": resource.get("topic", {}).get("text"),
        })

    return {
        "total": bundle.get("total", len(communications)),
        "communications": communications,
    }
