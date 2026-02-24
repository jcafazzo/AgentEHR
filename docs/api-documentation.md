# AgentEHR API Documentation

> **Version:** 0.1.0
> **Base URL:** `http://localhost:8000`
> **Last Updated:** 2026-02-21

AgentEHR is a conversational clinical AI assistant built on FHIR R4. It provides an HTTP API for the frontend and an MCP (Model Context Protocol) server with 33 tools for direct FHIR operations.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Authentication](#authentication)
3. [HTTP API Endpoints](#http-api-endpoints)
   - [Health Check](#health-check)
   - [Chat](#chat)
   - [Patient Search & Summary](#patient-search--summary)
   - [Action Queue](#action-queue)
4. [MCP Tools Reference](#mcp-tools-reference)
   - [Patient Tools](#patient-tools)
   - [Medication Management](#medication-management)
   - [Observation & Lab Tools](#observation--lab-tools)
   - [Condition / Problem List](#condition--problem-list)
   - [Encounter & Appointment](#encounter--appointment)
   - [Orders & Referrals](#orders--referrals)
   - [Allergy Management](#allergy-management)
   - [Procedure & Documentation](#procedure--documentation)
   - [Communication](#communication)
   - [Immunization](#immunization)
   - [Approval Queue](#approval-queue)
5. [Data Models](#data-models)
6. [Approval Workflow](#approval-workflow)
7. [Drug Interaction Validation](#drug-interaction-validation)
8. [Error Handling](#error-handling)
9. [Architecture](#architecture)

---

## Getting Started

### Prerequisites

| Service | Default URL | Purpose |
|---------|-------------|---------|
| Medplum FHIR Server | `http://localhost:8103` | FHIR R4 backend |
| AgentEHR API | `http://localhost:8000` | FastAPI HTTP layer |
| Frontend | `http://localhost:3000` | Next.js UI |

### Quick Start

```bash
# 1. Set environment variables
export OPENROUTER_API_KEY=your_key_here

# 2. Start the API server
cd api && uvicorn main:app --reload --port 8000

# 3. Start the frontend
cd frontend && npm run dev

# 4. Verify the API is running
curl http://localhost:8000/health
```

### First Request

```bash
# Search for a patient
curl "http://localhost:8000/api/patients/search?q=John+Smith"

# Start a conversation
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Find patient John Smith and show me their summary"}'
```

---

## Authentication

### API Server

The HTTP API does not require authentication for local development. CORS is configured for `http://localhost:3000`.

### FHIR Server (Medplum)

The MCP server authenticates to Medplum using OAuth2 password grant. Configuration is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `FHIR_SERVER_BASE_URL` | `http://localhost:8103/fhir/R4` | Medplum FHIR endpoint |
| `FHIR_SERVER_EMAIL` | `admin@agentehr.local` | Medplum admin email |
| `FHIR_SERVER_PASSWORD` | `medplum123` | Medplum admin password |

Token refresh is automatic with a 60-second buffer before expiry.

### LLM Provider

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes (for chat) | OpenRouter API key for LLM access |

If not set, the `/api/chat` endpoint returns `503 Service Unavailable`.

---

## HTTP API Endpoints

### Health Check

#### `GET /health`

Returns server status and configuration state.

**Response (200 OK):**

```json
{
  "status": "healthy",
  "service": "agentehr-api",
  "active_conversations": 3,
  "openrouter_configured": true
}
```

---

### Chat

#### `POST /api/chat`

Send a message to the clinical AI assistant. Creates or continues a conversation.

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `message` | string | Yes | - | The user's message |
| `conversation_id` | string | No | Auto-generated UUID | ID to continue an existing conversation |
| `model` | string | No | `"glm-5"` | LLM model alias (`glm-5`, `claude-sonnet`, `gpt-4o`) |

**Example Request:**

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Order metformin 500mg twice daily for patient John Smith",
    "conversation_id": "conv-abc-123",
    "model": "glm-5"
  }'
```

**Response (200 OK):**

```json
{
  "content": "I've prepared a Metformin 500mg BID order for John Smith. No drug interactions detected. The order is queued for your approval.",
  "conversation_id": "conv-abc-123",
  "tool_calls": [
    {
      "name": "search_patient",
      "arguments": {"name": "John Smith"}
    },
    {
      "name": "create_medication_request",
      "arguments": {
        "patient_id": "pat-123",
        "medication_name": "Metformin",
        "dosage": "500 mg",
        "frequency": "twice daily"
      }
    }
  ],
  "tool_results": [
    {"tool": "search_patient", "result": {"total": 1, "patients": [{"id": "pat-123", "name": "John Smith"}]}},
    {"tool": "create_medication_request", "result": {"status": "queued", "action_id": "act-456"}}
  ],
  "warnings": [],
  "pending_actions": [
    {
      "action_id": "act-456",
      "action_type": "MEDICATION_REQUEST",
      "patient_id": "pat-123",
      "summary": "Metformin 500 mg twice daily",
      "status": "pending"
    }
  ]
}
```

**Error Responses:**

| Status | Condition | Body |
|--------|-----------|------|
| 503 | `OPENROUTER_API_KEY` not set | `{"detail": "OPENROUTER_API_KEY environment variable not set..."}` |
| 500 | Internal error | `{"detail": "error message"}` |

---

#### `DELETE /api/chat/{conversation_id}`

Reset a conversation, clearing its message history.

**Example:**

```bash
curl -X DELETE http://localhost:8000/api/chat/conv-abc-123
```

**Response (200 OK):**

```json
{
  "status": "reset",
  "conversation_id": "conv-abc-123"
}
```

**Error:** `404` if conversation not found.

---

### Patient Search & Summary

#### `GET /api/patients/search`

Search for patients by name or identifier.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | Yes | Search query (name, MRN, or identifier) |

**Example:**

```bash
curl "http://localhost:8000/api/patients/search?q=Smith"
```

**Response (200 OK):**

```json
{
  "total": 2,
  "patients": [
    {
      "id": "pat-123",
      "name": "John Smith",
      "birthDate": "1970-01-15",
      "gender": "male",
      "identifiers": [{"system": "MRN", "value": "MRN-12345"}]
    },
    {
      "id": "pat-456",
      "name": "Jane Smith",
      "birthDate": "1985-06-20",
      "gender": "female",
      "identifiers": [{"system": "MRN", "value": "MRN-67890"}]
    }
  ]
}
```

---

#### `GET /api/patients/{patient_id}`

Get patient demographics by FHIR ID.

**Example:**

```bash
curl http://localhost:8000/api/patients/pat-123
```

**Response (200 OK):**

```json
{
  "id": "pat-123",
  "name": "John Smith",
  "birthDate": "1970-01-15",
  "gender": "male",
  "identifiers": [{"system": "MRN", "value": "MRN-12345"}],
  "address": "123 Main St, Boston, MA 02101",
  "telecom": [
    {"system": "phone", "value": "555-0100"},
    {"system": "email", "value": "john.smith@example.com"}
  ]
}
```

---

#### `GET /api/patients/{patient_id}/summary`

Get a comprehensive patient summary with all clinical data. Fetches 9 FHIR resource types in parallel.

**Example:**

```bash
curl http://localhost:8000/api/patients/pat-123/summary
```

**Response (200 OK):**

```json
{
  "patient": {
    "id": "pat-123",
    "name": "John Smith",
    "birthDate": "1970-01-15",
    "age": 56,
    "gender": "male",
    "mrn": "MRN-12345"
  },
  "conditions": [
    {
      "id": "cond-1",
      "code": "Type 2 Diabetes Mellitus",
      "status": "active",
      "onsetDate": "2018-03-15",
      "isActive": true
    }
  ],
  "medications": [
    {
      "id": "med-1",
      "medication": "Metformin 500 mg",
      "dosage": "500 mg twice daily",
      "status": "active"
    }
  ],
  "allergies": [
    {
      "id": "allg-1",
      "substance": "Penicillin",
      "reaction": "Hives",
      "criticality": "high",
      "category": "medication"
    }
  ],
  "labs": [
    {
      "id": "obs-1",
      "code": "Hemoglobin A1c",
      "value": "7.2 %",
      "date": "2025-11-01",
      "status": "final"
    }
  ],
  "vitals": [
    {
      "id": "obs-2",
      "code": "Blood Pressure",
      "value": "130/85 mmHg",
      "date": "2026-01-10",
      "status": "final"
    }
  ],
  "immunizations": [
    {
      "id": "imm-1",
      "vaccine": "Influenza",
      "date": "2025-10-15",
      "status": "completed"
    }
  ],
  "procedures": [
    {
      "id": "proc-1",
      "name": "Colonoscopy",
      "date": "2024-05-20",
      "status": "completed"
    }
  ],
  "encounters": [
    {
      "id": "enc-1",
      "type": "Office Visit",
      "status": "finished",
      "date": "2026-01-10"
    }
  ],
  "clinicalNotes": [
    {
      "id": "doc-1",
      "type": "Progress Note",
      "description": "Annual diabetes follow-up",
      "date": "2026-01-10",
      "status": "current"
    }
  ],
  "careGaps": [
    {
      "type": "immunization",
      "description": "Flu vaccine overdue",
      "priority": "routine"
    },
    {
      "type": "screening",
      "description": "Diabetic eye exam overdue",
      "priority": "high"
    }
  ],
  "incompleteData": [
    {
      "field": "allergies",
      "message": "No allergies documented - confirm NKDA or document allergies",
      "priority": "high"
    }
  ]
}
```

---

### Action Queue

#### `GET /api/actions`

List pending clinical actions awaiting approval.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | No | Filter by patient |

**Example:**

```bash
# All pending actions
curl http://localhost:8000/api/actions

# Actions for a specific patient
curl "http://localhost:8000/api/actions?patient_id=pat-123"
```

**Response (200 OK):**

```json
{
  "count": 2,
  "actions": [
    {
      "action_id": "act-456",
      "action_type": "MEDICATION_REQUEST",
      "patient_id": "pat-123",
      "summary": "Metformin 500 mg twice daily",
      "status": "pending",
      "warnings": [],
      "created_at": 1708531200
    },
    {
      "action_id": "act-789",
      "action_type": "SERVICE_REQUEST",
      "patient_id": "pat-123",
      "summary": "Ophthalmology referral - diabetic eye exam",
      "status": "pending",
      "warnings": [],
      "created_at": 1708531250
    }
  ],
  "message": "2 pending actions"
}
```

---

#### `POST /api/actions/{action_id}/approve`

Approve and execute a pending clinical action. Changes the FHIR resource from draft to active.

**Example:**

```bash
curl -X POST http://localhost:8000/api/actions/act-456/approve
```

**Response (200 OK):**

```json
{
  "status": "approved",
  "message": "Action approved and executed",
  "action_id": "act-456",
  "fhir_id": "med-req-789"
}
```

**Error:** `400` if action not found or already processed.

---

#### `POST /api/actions/{action_id}/reject`

Reject a pending clinical action. Deletes the draft FHIR resource.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reason` | string | No | Reason for rejection |

**Example:**

```bash
curl -X POST http://localhost:8000/api/actions/act-789/reject \
  -H "Content-Type: application/json" \
  -d '{"reason": "Patient declined referral"}'
```

**Response (200 OK):**

```json
{
  "status": "rejected",
  "message": "Action rejected",
  "action_id": "act-789",
  "fhir_id": null
}
```

---

## MCP Tools Reference

The MCP server exposes 33 tools for FHIR operations, accessible via the Model Context Protocol (stdio transport). All write operations create resources as **drafts** that must be approved through the approval queue.

### Patient Tools

#### `search_patient`

Search patients by name, MRN, birthdate, or gender.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | No | Patient name (partial match) |
| `identifier` | string | No | MRN or other identifier |
| `birthdate` | string | No | Date of birth (YYYY-MM-DD) |
| `gender` | string | No | `male`, `female`, `other`, `unknown` |

#### `get_patient`

Get detailed demographics for a specific patient.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient resource ID |

#### `get_patient_summary`

Comprehensive patient summary with parallel FHIR queries. Returns conditions, medications, allergies, labs, vitals, immunizations, procedures, encounters, clinical notes, care gaps, and incomplete data flags.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient resource ID |

---

### Medication Management

#### `search_medications`

Search current and historical medications.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `status` | string | No | `active`, `completed`, `stopped`, `on-hold` |

#### `create_medication_request`

Create a new medication order (draft). Automatically validates drug interactions and allergy cross-reactivity.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `medication_name` | string | Yes | Medication name |
| `dosage` | string | Yes | Dose (e.g., `"500 mg"`) |
| `frequency` | string | Yes | Frequency (e.g., `"twice daily"`) |
| `route` | string | No | Route of administration |
| `duration` | string | No | Duration of therapy |
| `instructions` | string | No | Additional patient instructions |

**Returns:** Draft `MedicationRequest` + validation warnings (drug interactions, allergy alerts).

#### `update_medication_status`

Change medication status (discontinue, hold, cancel).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `medication_id` | string | Yes | FHIR MedicationRequest ID |
| `new_status` | string | Yes | `active`, `stopped`, `cancelled`, `on-hold` |
| `reason` | string | No | Reason for status change |

#### `delete_medication_request`

Delete a medication record. Only allowed for `draft` or `entered-in-error` status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `medication_id` | string | Yes | FHIR MedicationRequest ID |
| `reason` | string | No | Reason for deletion |

#### `reconcile_medications`

Bulk medication reconciliation. Keep, discontinue, or delete multiple medications at once.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `keep_medication_ids` | string[] | No | IDs to keep active |
| `discontinue_medication_ids` | string[] | No | IDs to discontinue |
| `delete_medication_ids` | string[] | No | IDs to delete |
| `reason` | string | Yes | Reason for reconciliation |

---

### Observation & Lab Tools

#### `search_observations`

Search vitals, labs, social history, or imaging results.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `category` | string | No | `vital-signs`, `laboratory`, `social-history`, `imaging` |
| `code` | string | No | LOINC code |
| `date_from` | string | No | Start date (YYYY-MM-DD) |

#### `get_lab_results_with_trends`

Get lab results with trend analysis (improving, stable, worsening).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `test_name` | string | No | Lab type (e.g., `"A1C"`, `"creatinine"`) |

#### `check_renal_function`

Get eGFR, creatinine, and BUN for medication dosing decisions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |

---

### Condition / Problem List

#### `search_conditions`

Search diagnoses from the problem list.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `status` | string | No | `active`, `inactive`, `resolved` |

#### `add_condition`

Add a diagnosis to the problem list (draft for approval).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `code` | string | No | ICD-10 or SNOMED code |
| `display` | string | No | Human-readable condition name |
| `onset_date` | string | No | Date of onset (YYYY-MM-DD) |
| `body_site` | string | No | Affected body site |

#### `update_condition_status`

Update the status of a condition (resolve, inactivate).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `condition_id` | string | Yes | FHIR Condition ID |
| `new_status` | string | Yes | `active`, `inactive`, `resolved` |
| `reason` | string | No | Reason for status change |

---

### Encounter & Appointment

#### `search_encounters`

Search patient visits and admissions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `type` | string | No | Encounter type filter |
| `date_from` | string | No | Start date (YYYY-MM-DD) |
| `date_to` | string | No | End date (YYYY-MM-DD) |

#### `create_appointment`

Create a follow-up appointment request (draft).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `reason` | string | Yes | Reason for appointment |
| `appointment_type` | string | No | Appointment type |
| `duration_minutes` | integer | No | Duration in minutes |
| `preferred_date` | string | No | Preferred date (YYYY-MM-DD) |

#### `create_encounter_note`

Create clinical encounter documentation (draft).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `note_type` | string | Yes | Note type (progress, consult, etc.) |
| `title` | string | Yes | Note title |
| `content` | string | Yes | Note content |
| `assessment_and_plan` | string | No | Assessment and plan section |

#### `create_phone_encounter`

Document a phone call with a patient (draft).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `note_type` | string | Yes | Call type |
| `content` | string | Yes | Call summary |
| `interaction_type` | string | No | `refill_request`, `test_results`, `symptom_followup`, etc. |

---

### Orders & Referrals

#### `create_diagnostic_order`

Create a lab or imaging order (draft).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `test_name` | string | Yes | Test name |
| `test_type` | string | Yes | `lab` or `imaging` |
| `priority` | string | No | Order priority |
| `urgency` | string | No | Urgency level |
| `indications` | string | No | Clinical indications |

#### `create_care_plan`

Create a care plan with goals and activities (draft).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `title` | string | Yes | Plan title |
| `description` | string | No | Plan description |
| `goals` | string[] | No | Clinical goals |
| `activities` | string[] | No | Planned activities |

#### `create_referral`

Create a specialty referral request (draft).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `specialty` | string | Yes | Target specialty |
| `reason` | string | Yes | Referral reason |
| `urgency` | string | No | `routine`, `urgent`, `emergent` |
| `additional_notes` | string | No | Clinical summary for specialist |

#### `search_referrals`

Search specialty referrals.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `status` | string | No | `draft`, `active`, `completed`, `cancelled` |
| `specialty` | string | No | Specialty filter |

---

### Allergy Management

#### `create_allergy_intolerance`

Document a patient allergy or intolerance (draft). Critical for medication safety.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `substance` | string | Yes | Allergen (drug, food, environmental) |
| `reaction` | string | No | Reaction type (rash, anaphylaxis, etc.) |
| `severity` | string | No | `mild`, `moderate`, `severe` |
| `notes` | string | No | Additional notes |

#### `update_allergy_intolerance`

Update an existing allergy record.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `allergy_id` | string | Yes | FHIR AllergyIntolerance ID |
| `new_status` | string | No | `active`, `inactive`, `resolved` |
| `severity` | string | No | Updated severity |
| `reactions` | string | No | Additional reactions to document |

---

### Procedure & Documentation

#### `create_procedure`

Document a procedure performed on the patient (draft).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `code` | string | No | CPT or SNOMED code |
| `display` | string | No | Procedure name |
| `performed_date` | string | No | Date performed (YYYY-MM-DD) |
| `notes` | string | No | Procedure notes / outcome |

#### `search_procedures`

Search procedures for a patient.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `status` | string | No | Procedure status |
| `date_from` | string | No | Start date (YYYY-MM-DD) |

#### `document_counseling`

Quick documentation of counseling provided (draft).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `topic` | string | Yes | `smoking`, `diet`, `exercise`, `other` |
| `notes` | string | Yes | Counseling details |

#### `create_work_note`

Generate a work/school excuse note (draft).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `start_date` | string | Yes | Absence start date (YYYY-MM-DD) |
| `end_date` | string | No | Absence end date (YYYY-MM-DD) |
| `restrictions` | string | No | Work restrictions |
| `notes` | string | No | Additional notes |

---

### Communication

#### `create_communication`

Create a letter or notification (draft).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |
| `recipient` | string | Yes | Recipient name or role |
| `subject` | string | Yes | Communication subject |
| `message` | string | Yes | Message body |
| `communication_type` | string | No | Communication type |

---

### Immunization

#### `get_immunization_status`

Get vaccination history and identify due/overdue immunizations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | Yes | FHIR Patient ID |

---

### Approval Queue

#### `list_pending_actions`

List all draft actions awaiting clinician approval.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patient_id` | string | No | Filter by patient |

#### `approve_action`

Approve and execute a pending action. Changes the FHIR resource status from `draft` to `active`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action_id` | string | Yes | Approval queue action ID |

#### `reject_action`

Reject a pending action. Deletes the draft FHIR resource.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action_id` | string | Yes | Approval queue action ID |
| `reason` | string | No | Rejection reason |

---

## Data Models

### PendingAction

```json
{
  "action_id": "uuid-string",
  "action_type": "MEDICATION_REQUEST",
  "patient_id": "fhir-patient-id",
  "summary": "Metformin 500 mg twice daily",
  "status": "pending",
  "warnings": [
    {
      "severity": "warning",
      "code": "drug-interaction",
      "message": "Moderate interaction with existing medication",
      "details": {}
    }
  ],
  "created_at": 1708531200,
  "fhir_id": "fhir-resource-id"
}
```

**Action Types:** `MEDICATION_REQUEST`, `CARE_PLAN`, `APPOINTMENT`, `SERVICE_REQUEST`, `DOCUMENT_REFERENCE`, `COMMUNICATION`, `ALLERGY_INTOLERANCE`, `CONDITION`, `PROCEDURE`

**Action Statuses:** `pending` → `approved` → `executed` | `rejected` | `failed`

### ValidationWarning

```json
{
  "severity": "warning",
  "code": "drug-interaction",
  "message": "Warfarin + Aspirin: Increased risk of bleeding",
  "details": {
    "interacting_drug": "Warfarin",
    "recommendation": "Monitor INR closely if co-prescribed"
  }
}
```

**Severity levels:** `info`, `warning`, `error`

---

## Approval Workflow

All write operations (medications, orders, referrals, etc.) follow the approval queue pattern. No clinical action executes without clinician approval.

```
1. AI suggests action     →  Draft FHIR resource created
2. Action queued          →  Appears in approval queue
3. Clinician reviews      →  Sees warnings, patient context
4. Approve or Reject      →
   ├─ Approve → FHIR resource status: draft → active
   └─ Reject  → Draft FHIR resource deleted
```

### Workflow Example

```bash
# 1. AI creates a draft medication order via chat
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Order metformin 500mg BID for patient pat-123"}'
# Response includes pending_actions with action_id

# 2. List pending actions
curl http://localhost:8000/api/actions?patient_id=pat-123

# 3. Approve the action
curl -X POST http://localhost:8000/api/actions/act-456/approve
# MedicationRequest now active in FHIR

# OR reject it
curl -X POST http://localhost:8000/api/actions/act-456/reject \
  -H "Content-Type: application/json" \
  -d '{"reason": "Patient prefers lifestyle changes first"}'
```

---

## Drug Interaction Validation

The `create_medication_request` tool automatically validates:

### Drug-Drug Interactions

15+ built-in rules including:

| Drug A | Drug B | Severity | Risk |
|--------|--------|----------|------|
| Warfarin | NSAIDs | Severe | Increased bleeding risk |
| ACE Inhibitors | Potassium | Moderate | Hyperkalemia |
| Metformin | Contrast agents | Severe | Lactic acidosis |
| Statins | Amiodarone | Contraindicated | Rhabdomyolysis |
| SSRIs | MAOIs | Contraindicated | Serotonin syndrome |

### Allergy Cross-Reactivity

| Allergy | Cross-Reactive With | Reactivity |
|---------|---------------------|------------|
| Penicillin | Cephalosporins | High |
| Sulfa drugs | Thiazide diuretics | Moderate |
| Aspirin | NSAIDs | High |

### Validation Response

```json
{
  "medication": "Aspirin",
  "safe": false,
  "requires_override": false,
  "requires_attention": true,
  "warnings": [
    {
      "severity": "severe",
      "code": "drug-interaction",
      "message": "Warfarin + Aspirin: Increased risk of bleeding",
      "details": {
        "interacting_drug": "Warfarin",
        "recommendation": "Monitor INR closely"
      }
    }
  ],
  "warning_count": 1
}
```

---

## Error Handling

### HTTP Error Responses

All errors follow this format:

```json
{
  "detail": "Human-readable error message"
}
```

| Status | Meaning | Common Causes |
|--------|---------|---------------|
| 400 | Bad Request | Invalid action ID, action already processed |
| 404 | Not Found | Conversation or resource not found |
| 500 | Internal Error | FHIR server connection failure, handler error |
| 503 | Service Unavailable | `OPENROUTER_API_KEY` not configured |

### MCP Tool Errors

Tool errors are returned as JSON within the tool result:

```json
{
  "error": "Patient not found",
  "details": "No patient found with ID: invalid-id"
}
```

---

## Architecture

```
┌─────────────────┐    HTTP     ┌──────────────────┐
│   Next.js UI    │ ──────────► │   FastAPI Server  │
│  localhost:3000  │            │  localhost:8000   │
└─────────────────┘            └────────┬─────────┘
                                        │
                               ┌────────▼─────────┐
                               │   OpenRouter      │
                               │   Orchestrator    │
                               │   (LLM Agent)     │
                               └────────┬─────────┘
                                        │ Tool calls
                               ┌────────▼─────────┐
                               │   MCP Server      │
                               │   (33 FHIR tools) │
                               └────────┬─────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
           ┌────────▼──────┐  ┌────────▼──────┐  ┌────────▼──────┐
           │ Approval Queue│  │ Drug Interact. │  │  FHIR Client  │
           │  (in-memory)  │  │  Validation    │  │  (OAuth2)     │
           └───────────────┘  └───────────────┘  └────────┬──────┘
                                                          │
                                                 ┌────────▼──────┐
                                                 │ Medplum FHIR  │
                                                 │ localhost:8103 │
                                                 └───────────────┘
```

### FHIR Resources Supported

| Resource | Create | Read | Update | Delete | Search |
|----------|--------|------|--------|--------|--------|
| Patient | - | Y | - | - | Y |
| MedicationRequest | Y (draft) | Y | Y | Y | Y |
| Condition | Y (draft) | Y | Y | - | Y |
| Observation | - | Y | - | - | Y |
| Encounter | Y | Y | Y | - | Y |
| Appointment | Y (draft) | Y | Y | - | Y |
| CarePlan | Y (draft) | Y | Y | - | Y |
| ServiceRequest | Y (draft) | Y | Y | - | Y |
| Communication | Y (draft) | Y | Y | - | Y |
| DocumentReference | Y (draft) | Y | Y | - | Y |
| AllergyIntolerance | Y (draft) | Y | Y | - | Y |
| Procedure | Y (draft) | Y | Y | - | Y |
| Immunization | - | Y | - | - | Y |

### Supported LLM Models

| Alias | OpenRouter Model ID | Notes |
|-------|---------------------|-------|
| `glm-5` | `z-ai/glm-5` | Default model |
| `glm-4` | `z-ai/glm-4.5` | Current generation |
| `glm-flash` | `z-ai/glm-4.7-flash` | Fast/cheap option |
| `claude-sonnet` | `anthropic/claude-3.5-sonnet` | Anthropic |
| `claude-opus` | `anthropic/claude-3-opus` | Anthropic (most capable) |
| `gpt-4o` | `openai/gpt-4o` | OpenAI |
| `gemini` | `google/gemini-2.0-flash-001:free` | Free tier |
