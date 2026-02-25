#!/usr/bin/env python3
"""
AgentEHR FHIR MCP Server

Exposes FHIR R4 operations as MCP tools for use with Claude and other LLM agents.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    TextContent,
    Tool,
)
from pydantic import BaseModel
from pydantic_settings import BaseSettings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fhir-mcp-server")


class Settings(BaseSettings):
    """Server configuration from environment variables."""

    fhir_server_base_url: str = "http://localhost:8103/fhir/R4"
    fhir_server_access_token: str | None = None
    # Auth credentials (for password flow)
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
        # Get fresh token from auth helper
        auth = await get_auth()
        access_token = await auth.get_access_token()

        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
            )

        # Update headers with current token
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

# Initialize MCP server
server = Server("agentehr-fhir")


# =============================================================================
# MCP TOOLS - Patient Operations
# =============================================================================

@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return list of available FHIR tools."""
    return [
        # Patient tools
        Tool(
            name="search_patient",
            description="Search for patients by name, identifier, birthdate, or other criteria. Returns a list of matching patients with their IDs and basic demographics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Patient name (partial match supported)",
                    },
                    "identifier": {
                        "type": "string",
                        "description": "Medical record number or other identifier",
                    },
                    "birthdate": {
                        "type": "string",
                        "description": "Date of birth (YYYY-MM-DD)",
                    },
                    "gender": {
                        "type": "string",
                        "enum": ["male", "female", "other", "unknown"],
                        "description": "Patient gender",
                    },
                },
            },
        ),
        Tool(
            name="get_patient",
            description="Get detailed information about a specific patient by their ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                },
                "required": ["patient_id"],
            },
        ),
        Tool(
            name="get_patient_summary",
            description="Get a comprehensive summary of a patient including conditions, medications, allergies, and recent encounters. Use this for clinical context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                },
                "required": ["patient_id"],
            },
        ),

        # Medication tools
        Tool(
            name="search_medications",
            description="Search for a patient's current and historical medications.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "completed", "stopped", "on-hold"],
                        "description": "Filter by medication status (default: active)",
                    },
                },
                "required": ["patient_id"],
            },
        ),
        Tool(
            name="create_medication_request",
            description="Create a new medication order for a patient. Returns a draft order for clinician approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "medication_name": {
                        "type": "string",
                        "description": "Name of the medication",
                    },
                    "dosage": {
                        "type": "string",
                        "description": "Dosage amount (e.g., '500 mg')",
                    },
                    "frequency": {
                        "type": "string",
                        "description": "How often to take (e.g., 'twice daily', 'every 8 hours')",
                    },
                    "route": {
                        "type": "string",
                        "enum": ["oral", "intravenous", "subcutaneous", "intramuscular", "topical", "inhaled"],
                        "description": "Route of administration",
                    },
                    "duration": {
                        "type": "string",
                        "description": "Duration of treatment (e.g., '7 days', '30 days')",
                    },
                    "instructions": {
                        "type": "string",
                        "description": "Additional instructions for the patient",
                    },
                },
                "required": ["patient_id", "medication_name", "dosage", "frequency"],
            },
        ),

        # Observation tools
        Tool(
            name="search_observations",
            description="Search for patient observations including vital signs and lab results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["vital-signs", "laboratory", "social-history", "imaging"],
                        "description": "Category of observation",
                    },
                    "code": {
                        "type": "string",
                        "description": "LOINC code for specific observation type",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Start date for observation search (YYYY-MM-DD)",
                    },
                },
                "required": ["patient_id"],
            },
        ),

        # Condition tools
        Tool(
            name="search_conditions",
            description="Search for patient conditions (diagnoses, problems).",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "clinical_status": {
                        "type": "string",
                        "enum": ["active", "resolved", "inactive"],
                        "description": "Clinical status filter",
                    },
                },
                "required": ["patient_id"],
            },
        ),

        # Encounter tools
        Tool(
            name="search_encounters",
            description="Search for patient encounters (visits, admissions).",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["planned", "arrived", "in-progress", "finished", "cancelled"],
                        "description": "Encounter status filter",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Start date for encounter search (YYYY-MM-DD)",
                    },
                },
                "required": ["patient_id"],
            },
        ),

        # Care Plan tools
        Tool(
            name="create_care_plan",
            description="Create a care plan for a patient with goals and activities.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title of the care plan",
                    },
                    "description": {
                        "type": "string",
                        "description": "Description of the care plan",
                    },
                    "goals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of care plan goals",
                    },
                    "activities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of planned activities",
                    },
                },
                "required": ["patient_id", "title"],
            },
        ),

        # Appointment tools
        Tool(
            name="create_appointment",
            description="Create a follow-up appointment for a patient.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for the appointment",
                    },
                    "appointment_type": {
                        "type": "string",
                        "enum": ["routine", "followup", "urgent", "checkup"],
                        "description": "Type of appointment",
                    },
                    "preferred_date": {
                        "type": "string",
                        "description": "Preferred date (YYYY-MM-DD)",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Appointment duration in minutes",
                    },
                },
                "required": ["patient_id", "reason"],
            },
        ),

        Tool(
            name="search_appointments",
            description="Search for existing appointments for a patient. Use to check for conflicts or review upcoming schedule.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["proposed", "booked", "cancelled"],
                        "description": "Filter by appointment status",
                    },
                },
                "required": ["patient_id"],
            },
        ),

        # Approval Queue tools
        Tool(
            name="list_pending_actions",
            description="List all pending clinical actions awaiting approval for a patient. Returns draft medications, orders, care plans, etc. that need clinician review.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID (optional - if omitted, returns all pending actions)",
                    },
                },
            },
        ),
        Tool(
            name="approve_action",
            description="Approve a pending clinical action. This will change the resource status from draft to active and execute it in the EHR.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": "string",
                        "description": "The action ID from list_pending_actions",
                    },
                },
                "required": ["action_id"],
            },
        ),
        Tool(
            name="reject_action",
            description="Reject a pending clinical action. This will delete the draft resource from the EHR.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": "string",
                        "description": "The action ID from list_pending_actions",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for rejection",
                    },
                },
                "required": ["action_id"],
            },
        ),

        # Diagnostic Orders (Lab/Imaging)
        Tool(
            name="create_diagnostic_order",
            description="Create a diagnostic order (lab test or imaging study) for a patient. Order is created as draft and requires clinician approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "order_type": {
                        "type": "string",
                        "enum": ["lab", "imaging"],
                        "description": "Type of diagnostic order",
                    },
                    "test_name": {
                        "type": "string",
                        "description": "Name of the test or study (e.g., 'Complete Blood Count', 'Chest X-Ray')",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Clinical reason for the order",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["routine", "urgent", "asap", "stat"],
                        "description": "Order priority (default: routine)",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Additional clinical notes for the order",
                    },
                },
                "required": ["patient_id", "order_type", "test_name", "reason"],
            },
        ),

        # Clinical Documentation
        Tool(
            name="create_encounter_note",
            description="Create a clinical encounter note or documentation for a patient. Created as draft and requires clinician approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "encounter_id": {
                        "type": "string",
                        "description": "The FHIR Encounter resource ID (optional)",
                    },
                    "note_type": {
                        "type": "string",
                        "enum": ["progress_note", "history_physical", "discharge_summary", "consultation", "procedure_note"],
                        "description": "Type of clinical note",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title of the document",
                    },
                    "content": {
                        "type": "string",
                        "description": "The clinical note content (plain text or markdown)",
                    },
                    "author": {
                        "type": "string",
                        "description": "Name of the author (optional)",
                    },
                },
                "required": ["patient_id", "note_type", "title", "content"],
            },
        ),

        # Communication (Letters)
        Tool(
            name="create_communication",
            description="Create a communication such as a letter to a referring physician or patient notification. Created as draft and requires clinician approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "recipient_type": {
                        "type": "string",
                        "enum": ["referring_physician", "patient", "specialist", "insurance"],
                        "description": "Type of recipient",
                    },
                    "recipient_name": {
                        "type": "string",
                        "description": "Name of the recipient",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Subject of the communication",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content of the communication/letter",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["referral_response", "consultation_note", "lab_results", "follow_up", "general"],
                        "description": "Category of communication",
                    },
                },
                "required": ["patient_id", "recipient_type", "subject", "content"],
            },
        ),

        # Medication Management (Update/Delete)
        Tool(
            name="update_medication_status",
            description="Update the status of an existing medication request. Use this to discontinue, stop, cancel, or reactivate medications.",
            inputSchema={
                "type": "object",
                "properties": {
                    "medication_id": {
                        "type": "string",
                        "description": "The FHIR MedicationRequest resource ID to update",
                    },
                    "new_status": {
                        "type": "string",
                        "enum": ["active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft"],
                        "description": "New status for the medication. Use 'stopped' to discontinue, 'cancelled' to cancel, 'entered-in-error' for duplicates",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for the status change (required for clinical audit)",
                    },
                },
                "required": ["medication_id", "new_status", "reason"],
            },
        ),
        Tool(
            name="delete_medication_request",
            description="Delete a medication request record. Use this to remove duplicate entries or erroneous records. Only draft or entered-in-error records can be deleted.",
            inputSchema={
                "type": "object",
                "properties": {
                    "medication_id": {
                        "type": "string",
                        "description": "The FHIR MedicationRequest resource ID to delete",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for deletion (e.g., 'duplicate entry', 'entered in error')",
                    },
                },
                "required": ["medication_id", "reason"],
            },
        ),
        Tool(
            name="reconcile_medications",
            description="Reconcile a patient's medication list by keeping specified medications active and discontinuing or removing others. Use this for medication reconciliation workflows.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "keep_medication_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of MedicationRequest IDs to keep active",
                    },
                    "discontinue_medication_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of MedicationRequest IDs to discontinue (mark as stopped)",
                    },
                    "delete_medication_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of MedicationRequest IDs to delete (duplicates or errors)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Clinical reason for reconciliation (e.g., 'Medication reconciliation - duplicate entries removed')",
                    },
                },
                "required": ["patient_id", "reason"],
            },
        ),

        # =============================================================================
        # PHASE 8: Comprehensive Clinical Tools
        # =============================================================================

        # Allergy Management
        Tool(
            name="create_allergy_intolerance",
            description="Document a patient allergy or intolerance. Critical for medication safety. Creates as draft for approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "substance": {
                        "type": "string",
                        "description": "Allergen (drug name, food, environmental agent)",
                    },
                    "reaction": {
                        "type": "string",
                        "description": "Reaction type (rash, hives, anaphylaxis, swelling, etc.)",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["mild", "moderate", "severe"],
                        "description": "Reaction severity",
                    },
                    "criticality": {
                        "type": "string",
                        "enum": ["low", "high", "unable-to-assess"],
                        "description": "Risk of future severe reaction",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["food", "medication", "environment", "biologic"],
                        "description": "Allergen category",
                    },
                },
                "required": ["patient_id", "substance", "category"],
            },
        ),
        Tool(
            name="update_allergy_intolerance",
            description="Update an existing allergy record (status, severity, add reactions).",
            inputSchema={
                "type": "object",
                "properties": {
                    "allergy_id": {
                        "type": "string",
                        "description": "The FHIR AllergyIntolerance resource ID",
                    },
                    "clinical_status": {
                        "type": "string",
                        "enum": ["active", "inactive", "resolved"],
                        "description": "New clinical status",
                    },
                    "verification_status": {
                        "type": "string",
                        "enum": ["confirmed", "refuted", "unconfirmed"],
                        "description": "Verification status",
                    },
                    "new_reaction": {
                        "type": "string",
                        "description": "Additional reaction to document",
                    },
                },
                "required": ["allergy_id"],
            },
        ),

        # Problem List Management
        Tool(
            name="add_condition",
            description="Add a diagnosis or problem to the patient's problem list. Creates as draft for approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "condition_name": {
                        "type": "string",
                        "description": "Condition/diagnosis name (e.g., 'Type 2 Diabetes Mellitus')",
                    },
                    "icd10_code": {
                        "type": "string",
                        "description": "ICD-10 code (e.g., 'E11.9')",
                    },
                    "clinical_status": {
                        "type": "string",
                        "enum": ["active", "recurrence", "relapse", "inactive", "remission", "resolved"],
                        "description": "Clinical status (default: active)",
                    },
                    "onset_date": {
                        "type": "string",
                        "description": "Date condition started (YYYY-MM-DD)",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Clinical notes about the condition",
                    },
                },
                "required": ["patient_id", "condition_name"],
            },
        ),
        Tool(
            name="update_condition_status",
            description="Update the status of an existing condition (resolve, inactivate, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "condition_id": {
                        "type": "string",
                        "description": "The FHIR Condition resource ID",
                    },
                    "clinical_status": {
                        "type": "string",
                        "enum": ["active", "inactive", "resolved"],
                        "description": "New clinical status",
                    },
                    "abatement_date": {
                        "type": "string",
                        "description": "Date condition resolved (YYYY-MM-DD)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for status change",
                    },
                },
                "required": ["condition_id", "clinical_status"],
            },
        ),

        # Procedure Documentation
        Tool(
            name="create_procedure",
            description="Document a procedure performed on the patient. Creates as draft for approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "procedure_name": {
                        "type": "string",
                        "description": "Name of procedure performed",
                    },
                    "cpt_code": {
                        "type": "string",
                        "description": "CPT code (optional)",
                    },
                    "performed_date": {
                        "type": "string",
                        "description": "Date performed (YYYY-MM-DD)",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Procedure notes",
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Outcome/findings",
                    },
                },
                "required": ["patient_id", "procedure_name"],
            },
        ),
        Tool(
            name="search_procedures",
            description="Search for procedures performed on a patient.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Start date for search (YYYY-MM-DD)",
                    },
                },
                "required": ["patient_id"],
            },
        ),

        # Lab Results with Decision Support
        Tool(
            name="get_lab_results_with_trends",
            description="Get lab results with trend analysis (improving, stable, worsening). Useful for chronic disease management.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "lab_type": {
                        "type": "string",
                        "description": "Lab type (e.g., 'A1C', 'creatinine', 'cholesterol', 'glucose')",
                    },
                    "months_back": {
                        "type": "integer",
                        "description": "How many months of history (default: 12)",
                    },
                },
                "required": ["patient_id"],
            },
        ),
        Tool(
            name="check_renal_function",
            description="Get renal function (eGFR, creatinine, BUN) for medication dosing decisions. Critical for prescribing renally-cleared medications.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                },
                "required": ["patient_id"],
            },
        ),

        # Quick Documentation Tools
        Tool(
            name="document_counseling",
            description="Quick documentation of counseling provided (smoking cessation, diet, exercise, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "counseling_type": {
                        "type": "string",
                        "enum": ["smoking_cessation", "diet_nutrition", "exercise", "medication_adherence", "disease_education", "other"],
                        "description": "Type of counseling provided",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Time spent counseling in minutes",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Counseling details and patient response",
                    },
                },
                "required": ["patient_id", "counseling_type"],
            },
        ),
        Tool(
            name="create_work_note",
            description="Generate a work/school excuse note for the patient.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "excuse_from_date": {
                        "type": "string",
                        "description": "Start date of absence (YYYY-MM-DD)",
                    },
                    "excuse_to_date": {
                        "type": "string",
                        "description": "End date of absence (YYYY-MM-DD)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "General reason (no PHI - e.g., 'medical condition')",
                    },
                    "restrictions": {
                        "type": "string",
                        "description": "Work restrictions if any (e.g., 'no heavy lifting')",
                    },
                },
                "required": ["patient_id", "excuse_from_date", "excuse_to_date"],
            },
        ),
        Tool(
            name="create_phone_encounter",
            description="Document a phone call with patient (refill request, test result, symptom followup, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "call_type": {
                        "type": "string",
                        "enum": ["refill_request", "test_results", "symptom_followup", "general_question", "referral_coordination"],
                        "description": "Type of phone call",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Call duration in minutes",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of the call",
                    },
                    "action_taken": {
                        "type": "string",
                        "description": "What action was taken (e.g., 'refill sent', 'scheduled appointment')",
                    },
                },
                "required": ["patient_id", "call_type", "summary"],
            },
        ),

        # Referral Management
        Tool(
            name="create_referral",
            description="Create a referral to a specialist. Creates as draft for approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "specialty": {
                        "type": "string",
                        "description": "Specialty (cardiology, dermatology, endocrinology, etc.)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for referral",
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["routine", "urgent", "emergent"],
                        "description": "Urgency level (default: routine)",
                    },
                    "clinical_summary": {
                        "type": "string",
                        "description": "Brief clinical summary for the specialist",
                    },
                },
                "required": ["patient_id", "specialty", "reason"],
            },
        ),
        Tool(
            name="search_referrals",
            description="Search for referrals for a patient.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "active", "completed", "cancelled"],
                        "description": "Filter by referral status",
                    },
                },
                "required": ["patient_id"],
            },
        ),

        # Immunization Status
        Tool(
            name="get_immunization_status",
            description="Get patient's vaccination history and identify due/overdue immunizations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "The FHIR Patient resource ID",
                    },
                },
                "required": ["patient_id"],
            },
        ),

        # =============================================================================
        # Phase 1: Inpatient Encounter Lifecycle
        # =============================================================================
        Tool(
            name="create_inpatient_encounter",
            description="Create an inpatient encounter (admission) for a patient. Creates as draft requiring clinician approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "FHIR Patient ID",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for admission",
                    },
                    "admit_source": {
                        "type": "string",
                        "description": "Admit source code (default: emd)",
                    },
                    "location": {
                        "type": "string",
                        "description": "Initial location/ward (default: General Ward)",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["routine", "urgent", "asap", "stat"],
                        "description": "Admission priority",
                    },
                    "type_code": {
                        "type": "string",
                        "description": "SNOMED encounter type code",
                    },
                    "type_display": {
                        "type": "string",
                        "description": "Encounter type display text",
                    },
                },
                "required": ["patient_id"],
            },
        ),
        Tool(
            name="update_encounter_status",
            description="Update the status of an existing encounter (e.g., planned, arrived, in-progress, finished).",
            inputSchema={
                "type": "object",
                "properties": {
                    "encounter_id": {
                        "type": "string",
                        "description": "FHIR Encounter ID",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["planned", "arrived", "triaged", "in-progress", "onleave", "finished", "cancelled", "entered-in-error"],
                        "description": "New encounter status",
                    },
                },
                "required": ["encounter_id", "status"],
            },
        ),
        Tool(
            name="get_encounter_timeline",
            description="Get a comprehensive encounter timeline including observations, conditions, medications, and flags.",
            inputSchema={
                "type": "object",
                "properties": {
                    "encounter_id": {
                        "type": "string",
                        "description": "FHIR Encounter ID",
                    },
                },
                "required": ["encounter_id"],
            },
        ),
        Tool(
            name="transfer_patient",
            description="Transfer a patient to a new location within the hospital during an encounter.",
            inputSchema={
                "type": "object",
                "properties": {
                    "encounter_id": {
                        "type": "string",
                        "description": "FHIR Encounter ID",
                    },
                    "new_location": {
                        "type": "string",
                        "description": "New location/ward name",
                    },
                    "new_location_status": {
                        "type": "string",
                        "description": "Status of the new location (default: active)",
                    },
                },
                "required": ["encounter_id", "new_location"],
            },
        ),
        Tool(
            name="discharge_patient",
            description="Discharge a patient from an inpatient encounter. Sets status to finished and records disposition.",
            inputSchema={
                "type": "object",
                "properties": {
                    "encounter_id": {
                        "type": "string",
                        "description": "FHIR Encounter ID",
                    },
                    "discharge_disposition": {
                        "type": "string",
                        "description": "Discharge disposition code (default: home)",
                    },
                    "discharge_display": {
                        "type": "string",
                        "description": "Discharge disposition display text (default: Discharge to home)",
                    },
                },
                "required": ["encounter_id"],
            },
        ),

        # =============================================================================
        # Phase 1: Clinical Flags
        # =============================================================================
        Tool(
            name="create_flag",
            description="Create a clinical flag/alert for a patient (e.g., fall risk, drug allergy, isolation). Requires clinician approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "FHIR Patient ID",
                    },
                    "description": {
                        "type": "string",
                        "description": "Flag description text",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["clinical", "safety", "drug", "lab", "contact", "behavioral", "research", "advance-directive"],
                        "description": "Flag category (default: clinical)",
                    },
                    "encounter_id": {
                        "type": "string",
                        "description": "Associated encounter ID (optional)",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["PN", "PL", "PM", "PH"],
                        "description": "Flag priority: PN=none, PL=low, PM=medium, PH=high",
                    },
                    "author": {
                        "type": "string",
                        "description": "Author display name (optional)",
                    },
                },
                "required": ["patient_id", "description"],
            },
        ),
        Tool(
            name="get_active_flags",
            description="Get all active clinical flags for a patient, optionally filtered by encounter.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "string",
                        "description": "FHIR Patient ID",
                    },
                    "encounter_id": {
                        "type": "string",
                        "description": "Filter by encounter ID (optional)",
                    },
                },
                "required": ["patient_id"],
            },
        ),
        Tool(
            name="resolve_flag",
            description="Resolve (inactivate) a clinical flag, setting its end date to now.",
            inputSchema={
                "type": "object",
                "properties": {
                    "flag_id": {
                        "type": "string",
                        "description": "FHIR Flag ID",
                    },
                },
                "required": ["flag_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "search_patient":
            result = await handle_search_patient(arguments)
        elif name == "get_patient":
            result = await handle_get_patient(arguments)
        elif name == "get_patient_summary":
            result = await handle_get_patient_summary(arguments)
        elif name == "search_medications":
            result = await handle_search_medications(arguments)
        elif name == "create_medication_request":
            result = await handle_create_medication_request(arguments)
        elif name == "search_observations":
            result = await handle_search_observations(arguments)
        elif name == "search_conditions":
            result = await handle_search_conditions(arguments)
        elif name == "search_encounters":
            result = await handle_search_encounters(arguments)
        elif name == "create_care_plan":
            result = await handle_create_care_plan(arguments)
        elif name == "create_appointment":
            result = await handle_create_appointment(arguments)
        elif name == "search_appointments":
            result = await handle_search_appointments(arguments)
        elif name == "list_pending_actions":
            result = await handle_list_pending_actions(arguments)
        elif name == "approve_action":
            result = await handle_approve_action(arguments)
        elif name == "reject_action":
            result = await handle_reject_action(arguments)
        elif name == "create_diagnostic_order":
            result = await handle_create_diagnostic_order(arguments)
        elif name == "create_encounter_note":
            result = await handle_create_encounter_note(arguments)
        elif name == "create_communication":
            result = await handle_create_communication(arguments)
        elif name == "update_medication_status":
            result = await handle_update_medication_status(arguments)
        elif name == "delete_medication_request":
            result = await handle_delete_medication_request(arguments)
        elif name == "reconcile_medications":
            result = await handle_reconcile_medications(arguments)
        # Phase 8: Comprehensive Clinical Tools
        elif name == "create_allergy_intolerance":
            result = await handle_create_allergy_intolerance(arguments)
        elif name == "update_allergy_intolerance":
            result = await handle_update_allergy_intolerance(arguments)
        elif name == "add_condition":
            result = await handle_add_condition(arguments)
        elif name == "update_condition_status":
            result = await handle_update_condition_status(arguments)
        elif name == "create_procedure":
            result = await handle_create_procedure(arguments)
        elif name == "search_procedures":
            result = await handle_search_procedures(arguments)
        elif name == "get_lab_results_with_trends":
            result = await handle_get_lab_results_with_trends(arguments)
        elif name == "check_renal_function":
            result = await handle_check_renal_function(arguments)
        elif name == "document_counseling":
            result = await handle_document_counseling(arguments)
        elif name == "create_work_note":
            result = await handle_create_work_note(arguments)
        elif name == "create_phone_encounter":
            result = await handle_create_phone_encounter(arguments)
        elif name == "create_referral":
            result = await handle_create_referral(arguments)
        elif name == "search_referrals":
            result = await handle_search_referrals(arguments)
        elif name == "get_immunization_status":
            result = await handle_get_immunization_status(arguments)
        # Phase 1: Inpatient Encounter Lifecycle
        elif name == "create_inpatient_encounter":
            result = await handle_create_inpatient_encounter(arguments)
        elif name == "update_encounter_status":
            result = await handle_update_encounter_status(arguments)
        elif name == "get_encounter_timeline":
            result = await handle_get_encounter_timeline(arguments)
        elif name == "transfer_patient":
            result = await handle_transfer_patient(arguments)
        elif name == "discharge_patient":
            result = await handle_discharge_patient(arguments)
        # Phase 1: Clinical Flags
        elif name == "create_flag":
            result = await handle_create_flag(arguments)
        elif name == "get_active_flags":
            result = await handle_get_active_flags(arguments)
        elif name == "resolve_flag":
            result = await handle_resolve_flag(arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except httpx.HTTPStatusError as e:
        error_msg = f"FHIR server error: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return [TextContent(type="text", text=json.dumps({"error": error_msg}))]
    except Exception as e:
        error_msg = f"Error executing {name}: {str(e)}"
        logger.exception(error_msg)
        return [TextContent(type="text", text=json.dumps({"error": error_msg}))]


# =============================================================================
# Tool Handlers
# =============================================================================

async def handle_search_patient(args: dict) -> dict:
    """Search for patients."""
    params = {}
    if name := args.get("name"):
        params["name"] = name
    if query := args.get("query"):  # Support 'query' parameter for API compatibility
        normalized_query = query.strip()
        if normalized_query and normalized_query != "*":
            params["name"] = normalized_query
    if identifier := args.get("identifier"):
        params["identifier"] = identifier
    if birthdate := args.get("birthdate"):
        params["birthdate"] = birthdate
    if gender := args.get("gender"):
        params["gender"] = gender
    params["_count"] = str(args.get("count", "200"))
    params["_total"] = "accurate"

    bundle = await fhir_client.search("Patient", params)

    # Format results for readability
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
    """Get comprehensive patient summary."""
    patient_id = args["patient_id"]

    # Fetch patient and related data in parallel
    patient_task = fhir_client.read("Patient", patient_id)
    conditions_task = fhir_client.search("Condition", {"patient": patient_id, "clinical-status": "active"})
    medications_task = fhir_client.search("MedicationRequest", {"patient": patient_id, "status": "active"})
    allergies_task = fhir_client.search("AllergyIntolerance", {"patient": patient_id})

    patient, conditions, medications, allergies = await asyncio.gather(
        patient_task, conditions_task, medications_task, allergies_task,
        return_exceptions=True,
    )

    # Build summary
    summary = {
        "patient": {
            "id": patient.get("id") if isinstance(patient, dict) else patient_id,
            "name": format_name(patient.get("name", [])) if isinstance(patient, dict) else "Unknown",
            "birthDate": patient.get("birthDate") if isinstance(patient, dict) else None,
            "gender": patient.get("gender") if isinstance(patient, dict) else None,
        },
        "activeConditions": [],
        "activeMedications": [],
        "allergies": [],
    }

    # Extract conditions
    if isinstance(conditions, dict):
        for entry in conditions.get("entry", []):
            resource = entry.get("resource", {})
            condition = {
                "code": extract_code_display(resource.get("code")),
                "onsetDate": resource.get("onsetDateTime"),
            }
            summary["activeConditions"].append(condition)

    # Extract medications
    if isinstance(medications, dict):
        for entry in medications.get("entry", []):
            resource = entry.get("resource", {})
            med = {
                "medication": extract_medication_name(resource),
                "dosage": extract_dosage(resource),
            }
            summary["activeMedications"].append(med)

    # Extract allergies
    if isinstance(allergies, dict):
        for entry in allergies.get("entry", []):
            resource = entry.get("resource", {})
            allergy = {
                "substance": extract_code_display(resource.get("code")),
                "reaction": extract_reaction(resource),
            }
            summary["allergies"].append(allergy)

    return summary


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

    # Fetch current medications for drug interaction checking
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

    # Fetch allergies for allergy interaction checking
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

    # Run drug interaction validation
    safety_result = validate_medication_safety(
        medication_name=medication_name,
        current_medications=current_medications,
        allergies=allergies,
    )

    # Convert validation warnings to ValidationWarning objects
    validation_warnings = []
    for warning in safety_result.get("warnings", []):
        validation_warnings.append(ValidationWarning(
            severity=warning["severity"],
            code=warning["code"],
            message=warning["message"],
            details=warning.get("details", {}),
        ))

    # Build MedicationRequest resource
    medication_request = {
        "resourceType": "MedicationRequest",
        "status": "draft",  # Always draft - requires clinician approval
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

    # Add optional fields
    if route := args.get("route"):
        medication_request["dosageInstruction"][0]["route"] = {
            "text": route,
        }

    if instructions := args.get("instructions"):
        medication_request["dosageInstruction"][0]["patientInstruction"] = instructions

    # Create the resource in FHIR server
    result = await fhir_client.create("MedicationRequest", medication_request)
    fhir_id = result.get("id")

    # Build summary for approval queue
    summary = f"Order {medication_name} {args['dosage']} {args['frequency']}"

    # Queue for approval
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

    # Build response with safety information
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

    # Add warnings to response if any exist
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

    # Build summary for approval queue
    summary = f"Care plan: {args['title']}"

    # Queue for approval
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

    # Map order type to FHIR category codes
    category_code = "108252007" if order_type == "lab" else "363679005"  # SNOMED CT
    category_display = "Laboratory procedure" if order_type == "lab" else "Imaging"

    service_request = {
        "resourceType": "ServiceRequest",
        "status": "draft",  # Always draft - requires clinician approval
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

    # Build summary for approval queue
    summary = f"{order_type.capitalize()} order: {test_name}"

    # Queue for approval
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

    # Map note type to LOINC codes
    note_type_codes = {
        "progress_note": ("11506-3", "Progress note"),
        "history_physical": ("34117-2", "History and physical note"),
        "discharge_summary": ("18842-5", "Discharge summary"),
        "consultation": ("11488-4", "Consultation note"),
        "procedure_note": ("28570-0", "Procedure note"),
    }

    loinc_code, loinc_display = note_type_codes.get(note_type, ("11506-3", "Progress note"))

    # Encode content as base64 for attachment
    import base64
    content_b64 = base64.b64encode(content.encode()).decode()

    document_reference = {
        "resourceType": "DocumentReference",
        "status": "current",  # Note: DocumentReference uses current, not draft
        "docStatus": "preliminary",  # Use docStatus for draft state
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

    # Build summary for approval queue
    summary = f"{note_type.replace('_', ' ').title()}: {title}"

    # Queue for approval
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
        "status": "preparation",  # Draft state for Communication
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

    # Add category based on type
    category_map = {
        "referral_response": "referral-response",
        "consultation_note": "consultation",
        "lab_results": "lab-results",
        "follow_up": "follow-up",
        "general": "general",
    }
    if category := args.get("category"):
        communication["category"] = [{"text": category_map.get(category, category)}]

    # Add recipient info
    if recipient_name := args.get("recipient_name"):
        communication["recipient"] = [{"display": recipient_name}]

    # Add note about recipient type in extension or note
    communication["note"] = [{"text": f"Recipient type: {recipient_type}"}]

    result = await fhir_client.create("Communication", communication)
    fhir_id = result.get("id")

    # Build summary for approval queue
    summary = f"Letter to {recipient_type.replace('_', ' ')}: {subject}"

    # Queue for approval
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

    # Approve the action
    queue.approve(action_id)

    # Update the FHIR resource status from draft to active
    try:
        resource_type = action.action_type.value
        fhir_id = action.fhir_id

        if not fhir_id:
            queue.mark_failed(action_id, "No FHIR resource ID")
            return {"error": "Action has no associated FHIR resource"}

        # Get the current resource
        current = await fhir_client.read(resource_type, fhir_id)

        # Update status based on resource type
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
                    duration = current.get("minutesDuration", 30)
                    from datetime import datetime, timedelta
                    try:
                        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                        end_dt = dt + timedelta(minutes=duration)
                        current["end"] = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    except (ValueError, TypeError):
                        current["end"] = start_time
                else:
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

        # Update in FHIR server
        await fhir_client.update(resource_type, fhir_id, current)

        # Mark as executed
        queue.mark_executed(action_id)

        return {
            "status": "approved",
            "message": f"Action approved and executed: {action.summary}",
            "action_id": action_id,
            "fhir_id": fhir_id,
            "resource_type": resource_type,
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

    # Reject the action
    queue.reject(action_id, reason)

    # Delete the draft FHIR resource if it exists
    deleted_fhir = False
    if action.fhir_id:
        try:
            resource_type = action.action_type.value
            await fhir_client.delete(resource_type, action.fhir_id)
            deleted_fhir = True
        except Exception as e:
            logger.warning(f"Failed to delete draft FHIR resource: {e}")

    # Remove from queue
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
    result = await fhir_client.update("MedicationRequest", medication_id, current_med)

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
    # For active medications, recommend using update_medication_status instead
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

    # Keep medications active (ensure they're active status)
    for med_id in keep_ids:
        try:
            current_med = await fhir_client.read("MedicationRequest", med_id)
            medication_name = extract_medication_name(current_med)

            # If not already active, make it active
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

    # Discontinue medications (change status to stopped)
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

    # Delete medications (mark as entered-in-error first, then delete)
    for med_id in delete_ids:
        try:
            current_med = await fhir_client.read("MedicationRequest", med_id)
            medication_name = extract_medication_name(current_med)
            current_status = current_med.get("status", "unknown")

            # If not already deletable, mark as entered-in-error first
            if current_status not in ["draft", "entered-in-error"]:
                current_med["status"] = "entered-in-error"
                current_med["statusReason"] = {
                    "text": f"Marked for deletion: {reason}",
                }
                await fhir_client.update("MedicationRequest", med_id, current_med)

            # Now delete
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

    # Build summary message
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

    summary = f"Inpatient admission: {reason} at {location}"

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
    """Get a comprehensive timeline for an encounter."""
    encounter_id = args["encounter_id"]

    results = await asyncio.gather(
        fhir_client.read("Encounter", encounter_id),
        fhir_client.search("Observation", {"encounter": encounter_id, "_sort": "-date", "_count": "50"}),
        fhir_client.search("Condition", {"encounter": encounter_id}),
        fhir_client.search("MedicationRequest", {"encounter": encounter_id}),
        fhir_client.search("Flag", {"encounter": encounter_id}),
        return_exceptions=True,
    )

    encounter_data, obs_bundle, cond_bundle, med_bundle, flag_bundle = results

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

    for loc in locations:
        if loc.get("status") == "active":
            old_location = loc.get("location", {}).get("display", "Unknown")
            loc["status"] = "completed"
            if "period" not in loc:
                loc["period"] = {}
            loc["period"]["end"] = now_iso

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

    current["status"] = "finished"

    if "period" not in current:
        current["period"] = {}
    current["period"]["end"] = now_iso

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

    summary = f"Flag ({cat_display}): {description}"

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
# Main Entry Point
# =============================================================================

async def main():
    """Run the MCP server."""
    logger.info(f"Starting AgentEHR FHIR MCP Server")
    logger.info(f"FHIR Server: {settings.fhir_server_base_url}")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
