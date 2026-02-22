# AgentEHR Architecture

## Overview

AgentEHR is an agent-based Electronic Health Record interface that allows clinicians to interact with EHR systems through natural language (text or voice) rather than traditional GUI navigation.

## Design Philosophy

**"Embed, Don't Replace"** - Following the Wellsheet model, AgentEHR integrates with existing EHR infrastructure via FHIR APIs rather than replacing clinical systems.

**"Approve, Then Execute"** - All clinical actions (orders, care plans, appointments) are created in draft status and require explicit clinician approval before execution.

**"Evidence Grounding"** - All AI recommendations include supporting data from patient records, ensuring transparency and verifiability.

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                     1. USER INTERFACE LAYER                     │
│         Text Chat + Voice (STT/TTS) + Approval Queue           │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                  2. AGENT ORCHESTRATION LAYER                   │
│              Claude API + Subagent Task Delegation              │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      3. MCP SERVER LAYER                        │
│           FHIR Tools exposed via Model Context Protocol         │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      4. FHIR R4 BACKEND                         │
│               Medplum Server + PostgreSQL + Redis               │
└─────────────────────────────────────────────────────────────────┘
```

## Layer Details

### Layer 1: User Interface

**Components:**
- **Text Chat Interface** - Primary interaction mode
- **Voice Interface** - Speech-to-text (Whisper) + text-to-speech (ElevenLabs/browser)
- **Approval Queue** - Displays draft actions awaiting clinician review

**Key Considerations:**
- Session state management
- Real-time voice transcription for encounter documentation
- Mobile-responsive design for bedside use

### Layer 2: Agent Orchestration

**Primary Agent (Claude):**
- Interprets clinical intent from natural language
- Orchestrates multi-step workflows
- Synthesizes clinical context
- Generates action items

**Subagent Patterns:**
1. **Data Retrieval Agent** - Fetches patient context via FHIR queries
2. **Clinical Analysis Agent** - Analyzes data for recommendations
3. **Documentation Agent** - Generates encounter notes and letters
4. **Scheduling Agent** - Handles appointments and follow-ups

**Workflow Example: Medication Ordering**
```
User: "Order metformin 500mg twice daily for John Smith"
     │
     ▼
┌──────────────────────┐
│ Intent Recognition   │ → Medication Order
└──────────────────────┘
     │
     ▼
┌──────────────────────┐
│ Patient Lookup       │ → search_patient(name="John Smith")
└──────────────────────┘
     │
     ▼
┌──────────────────────┐
│ Clinical Context     │ → get_patient_summary(patient_id)
└──────────────────────┘
     │
     ▼
┌──────────────────────┐
│ Interaction Check    │ → search_medications + analyze
└──────────────────────┘
     │
     ▼
┌──────────────────────┐
│ Draft Order          │ → create_medication_request (status=draft)
└──────────────────────┘
     │
     ▼
┌──────────────────────┐
│ Present for Approval │ → "Ready to order... [Approve] [Modify]"
└──────────────────────┘
```

### Layer 3: MCP Server

**Purpose:** Translates FHIR R4 operations into MCP tools consumable by Claude and other LLM agents.

**Tool Categories:**

| Category | Tools | Purpose |
|----------|-------|---------|
| Patient | search_patient, get_patient, get_patient_summary | Patient identification and context |
| Medications | search_medications, create_medication_request | Med management |
| Observations | search_observations | Labs, vitals |
| Conditions | search_conditions | Problem list |
| Encounters | search_encounters | Visit history |
| Care Plans | create_care_plan | Care coordination |
| Appointments | create_appointment | Scheduling |

**Error Handling:**
- HTTP errors mapped to structured responses
- FHIR validation errors surfaced clearly
- Timeout handling for slow queries

### Layer 4: FHIR R4 Backend

**Medplum Server:**
- Full FHIR R4 compliance
- Self-hosted via Docker
- PostgreSQL for persistence
- Redis for caching

**Data Model:**
- Patient, Practitioner (actors)
- Encounter, Observation, Condition (clinical data)
- MedicationRequest, CarePlan, Appointment (orders/plans)
- Communication, DocumentReference (correspondence)

## Data Flow

### Read Operations
```
User Query → Agent → MCP Tool → FHIR GET → JSON Response → Formatted for Agent
```

### Write Operations (with approval)
```
User Request → Agent → MCP Tool → FHIR POST (status=draft)
                                        │
                                        ▼
                                 Approval Queue
                                        │
                          ┌─────────────┼─────────────┐
                          │             │             │
                       Approve       Modify        Cancel
                          │             │             │
                    Update status   Edit & retry  Delete draft
```

## Security Considerations

### Authentication
- **Development:** Disabled for local testing
- **Production:** SMART on FHIR (OAuth 2.0)

### Authorization
- Role-based access control via FHIR Consent resources
- Practitioner-patient relationships validated
- Audit logging of all queries and modifications

### Data Protection
- All PHI stays within FHIR server
- Agent prompts don't store patient data
- Audit trail via FHIR AuditEvent resources

## Scalability

**Current (MVP):**
- Single Medplum instance
- Single MCP server process
- In-memory approval queue

**Future Scaling:**
- Medplum cluster with read replicas
- MCP server horizontal scaling
- Persistent approval queue (Redis/PostgreSQL)
- Voice transcription queue for async processing

## Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| FHIR Server | Medplum | FHIR-native, modern stack, open source |
| MCP Language | Python | Rapid prototyping, WSO2 reference |
| Agent Model | Claude Opus/Sonnet | Clinical reasoning capability |
| Voice STT | Whisper | Local processing, medical vocabulary |
| Voice TTS | ElevenLabs | Natural voice quality |

## Future Enhancements

1. **Drug Interaction Checking** - Integration with drug databases
2. **Clinical Decision Support** - Evidence-based recommendations
3. **Multi-language Support** - I18n for global deployment
4. **EMR Connectors** - Epic, Cerner via existing MCP servers
5. **Mobile App** - Native iOS/Android interfaces
