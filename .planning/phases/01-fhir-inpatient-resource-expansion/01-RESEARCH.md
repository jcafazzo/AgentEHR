# Phase 1: FHIR Inpatient Resource Expansion - Research

**Researched:** 2026-02-25
**Domain:** FHIR R4 inpatient resource handlers, MCP tool registration, Python async handlers
**Confidence:** HIGH

## Summary

Phase 1 requires extending the existing FHIR MCP server with approximately 35 new tool handlers covering 10 inpatient-specific FHIR R4 resource types: Encounter (inpatient lifecycle), Flag, ClinicalImpression, RiskAssessment, Task, CareTeam, Goal, DeviceMetric, AdverseEvent, and Communication. The existing codebase already has 36 handlers across `handlers.py` (2,739 lines), with a well-established pattern: each handler is an `async def handle_X(args: dict) -> dict` function that uses the shared `FHIRClient` singleton, and some handlers route through the `approval_queue` for write operations. Tool registration happens in three places: (1) `Tool()` definitions in `server.py`'s `list_tools()`, (2) `elif` dispatch in `server.py`'s `call_tool()`, and (3) `FHIR_TOOLS` list + `self.handlers` dict in `openrouter_orchestrator.py`.

The existing Communication handler (`handle_create_communication`) and Encounter search handler (`handle_search_encounters`) already exist but are outpatient-focused. The inpatient expansion needs significantly richer encounter lifecycle management (admit, transfer, discharge, status transitions), plus entirely new resource types (Flag, ClinicalImpression, RiskAssessment, Task, CareTeam, Goal, DeviceMetric, AdverseEvent) that do not exist yet.

**Primary recommendation:** Follow the existing handler pattern exactly -- `async def handle_X(args: dict) -> dict` using the shared `fhir_client` -- grouped by domain sections in `handlers.py`. Use the approval queue for clinical write operations. Register in all three locations. New `ActionType` enum values needed for new resource types.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FR-01 | Expand MCP server with ~35 new FHIR R4 tool handlers for inpatient-specific resources: Encounter (inpatient lifecycle), Flag, ClinicalImpression, RiskAssessment, Task, CareTeam, Goal, DeviceMetric, AdverseEvent, Communication. All handlers return valid FHIR R4 JSON against Medplum. | Existing handler pattern is clear and well-established. FHIRClient already supports search/read/create/update/delete. Each resource type needs 2-5 handlers (CRUD + domain-specific queries). Medplum supports all 10 resource types in FHIR R4. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | (existing) | Async HTTP client for FHIR server | Already used by FHIRClient; async, connection pooling |
| pydantic-settings | (existing) | Settings from environment | Already in use for FHIR_SERVER_ config |
| mcp | (existing) | MCP server framework | Tool/TextContent types for server.py registration |
| Python 3.12 | 3.12 | Runtime | Already in use, async/await, union types |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json (stdlib) | - | JSON serialization of FHIR responses | Every handler return value |
| asyncio (stdlib) | - | Parallel FHIR fetches | Composite handlers like get_encounter_timeline |
| datetime (stdlib) | - | ISO 8601 date handling for periods/timestamps | Encounter periods, task due dates, vital timestamps |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw dict FHIR construction | fhir.resources (Pydantic FHIR models) | Type safety vs. added dependency; existing codebase uses raw dicts throughout -- adding typed models mid-stream would create inconsistency |
| Manual FHIR validation | FHIR validator | Runtime overhead; Medplum already validates on create/update |
| Separate handler files per resource | Single handlers.py | Modularity vs. consistency; existing pattern is one file -- splitting now would require refactoring imports in server.py and orchestrator |

**Installation:**
No new packages needed. All dependencies are already installed.

## Architecture Patterns

### Registration Triple Pattern (CRITICAL)
Every new handler must be registered in THREE locations:

```
1. handlers.py          -- async def handle_X(args: dict) -> dict
2. server.py            -- Tool() in list_tools() + elif in call_tool()
3. orchestrator.py      -- FHIR_TOOLS entry + handlers dict + import
```

### Recommended Handler Grouping in handlers.py
```python
# =============================================================================
# Inpatient Encounter Lifecycle
# =============================================================================
# handle_create_inpatient_encounter
# handle_update_encounter_status
# handle_get_encounter_timeline
# handle_transfer_patient
# handle_discharge_patient

# =============================================================================
# Clinical Flags
# =============================================================================
# handle_create_flag
# handle_get_active_flags
# handle_resolve_flag

# =============================================================================
# Clinical Assessment (ClinicalImpression + RiskAssessment)
# =============================================================================
# handle_create_clinical_impression
# handle_get_clinical_impressions
# handle_create_risk_assessment
# handle_get_risk_assessments

# =============================================================================
# Task Management
# =============================================================================
# handle_create_task
# handle_assign_task
# handle_complete_task
# handle_get_pending_tasks
# handle_update_task_status

# =============================================================================
# Care Team
# =============================================================================
# handle_create_care_team
# handle_get_care_team
# handle_update_care_team_member

# =============================================================================
# Goals
# =============================================================================
# handle_create_goal
# handle_get_patient_goals
# handle_update_goal_status

# =============================================================================
# Device Metrics
# =============================================================================
# handle_record_device_metric
# handle_get_device_metrics

# =============================================================================
# Adverse Events
# =============================================================================
# handle_report_adverse_event
# handle_get_adverse_events

# =============================================================================
# Inpatient Communication
# =============================================================================
# handle_create_inpatient_communication
# handle_get_communications
# handle_search_communications
```

### Pattern 1: Search Handler (Read-Only)
**What:** Retrieve FHIR resources with optional filters, format response
**When to use:** All search/get/list operations -- no approval queue needed
**Example:**
```python
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
        flags.append({
            "id": resource.get("id"),
            "status": resource.get("status"),
            "category": extract_code_display(
                resource.get("category", [{}])[0] if resource.get("category") else {}
            ),
            "code": extract_code_display(resource.get("code")),
            "period": resource.get("period"),
        })

    return {
        "total": len(flags),
        "flags": flags,
    }
```

### Pattern 2: Create Handler (Write -- With Approval Queue)
**What:** Build FHIR resource, create via FHIRClient, queue for approval
**When to use:** All create operations that modify clinical state
**Example:**
```python
async def handle_create_flag(args: dict) -> dict:
    """Create a clinical flag for a patient."""
    patient_id = args["patient_id"]

    flag = {
        "resourceType": "Flag",
        "status": "active",
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/flag-category",
                "code": args.get("category", "clinical"),
                "display": args.get("category", "Clinical").title(),
            }]
        }],
        "code": {
            "text": args["description"],
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
        },
    }

    if encounter_id := args.get("encounter_id"):
        flag["encounter"] = {"reference": f"Encounter/{encounter_id}"}

    if priority := args.get("priority"):
        flag["code"]["coding"] = [{
            "system": "http://hl7.org/fhir/flag-priority-code",
            "code": priority,
        }]

    result = await fhir_client.create("Flag", flag)
    fhir_id = result.get("id")

    queue = get_approval_queue()
    action = queue.queue_action(
        action_type=ActionType.FLAG,  # Must add to ActionType enum
        patient_id=patient_id,
        resource=flag,
        fhir_id=fhir_id,
        summary=f"Clinical flag: {args['description']}",
        metadata={"requester": "agent"},
    )

    return {
        "status": "active",
        "message": "Clinical flag created. Requires clinician approval.",
        "action_id": action.action_id,
        "flag": {
            "id": fhir_id,
            "description": args["description"],
            "category": args.get("category", "clinical"),
        },
    }
```

### Pattern 3: Update Handler (Read-Modify-Write)
**What:** Fetch current resource, modify specific fields, PUT back
**When to use:** Status transitions, field updates
**Example:**
```python
async def handle_update_encounter_status(args: dict) -> dict:
    """Update encounter status (e.g., in-progress -> finished)."""
    encounter_id = args["encounter_id"]
    new_status = args["status"]

    try:
        current = await fhir_client.read("Encounter", encounter_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Encounter {encounter_id} not found"}
        raise

    old_status = current.get("status")
    current["status"] = new_status

    # Set period.end on discharge
    if new_status == "finished" and not current.get("period", {}).get("end"):
        from datetime import datetime, timezone
        current.setdefault("period", {})["end"] = datetime.now(timezone.utc).isoformat()

    result = await fhir_client.update("Encounter", encounter_id, current)

    return {
        "encounter_id": encounter_id,
        "old_status": old_status,
        "new_status": new_status,
        "message": f"Encounter status updated: {old_status} -> {new_status}",
    }
```

### Pattern 4: Composite/Timeline Handler
**What:** Parallel fetch of multiple resource types, assemble timeline
**When to use:** Rich views like encounter timeline, patient overview
**Example:**
```python
async def handle_get_encounter_timeline(args: dict) -> dict:
    """Get full timeline for an inpatient encounter."""
    encounter_id = args["encounter_id"]

    # Parallel fetch of related resources
    encounter_task = fhir_client.read("Encounter", encounter_id)
    observations_task = fhir_client.search("Observation", {
        "encounter": encounter_id, "_sort": "-date", "_count": "50"
    })
    conditions_task = fhir_client.search("Condition", {
        "encounter": encounter_id
    })
    medications_task = fhir_client.search("MedicationRequest", {
        "encounter": encounter_id
    })

    encounter, observations, conditions, medications = await asyncio.gather(
        encounter_task, observations_task, conditions_task, medications_task,
        return_exceptions=True,
    )

    # Assemble timeline...
    return { ... }
```

### Anti-Patterns to Avoid
- **Separate FHIRClient instances:** Every handler MUST use the module-level `fhir_client` singleton. Creating new clients leaks connections.
- **Blocking I/O in handlers:** All FHIR calls are async via httpx. Never use `requests` or synchronous HTTP.
- **Returning raw FHIR bundles:** Existing pattern extracts and formats results into clean dicts. New handlers must follow this -- agents consume the formatted output, not raw FHIR JSON.
- **Skipping error handling for 404:** Read-modify-write handlers must catch `httpx.HTTPStatusError` and return an error dict for 404s (see existing `handle_update_condition_status` pattern).
- **Adding new resource types to ActionType without updating approval_queue.py:** Every resource that goes through the approval queue needs a corresponding `ActionType` enum value.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| FHIR resource construction | Custom FHIR resource builder class | Raw dicts following FHIR R4 spec | Existing pattern uses dicts; Medplum validates on create/update |
| HTTP client | Custom async HTTP wrapper | Existing `FHIRClient` class | Already handles auth, headers, error states |
| CodeableConcept extraction | Inline parsing per handler | Existing `extract_code_display()` helper | Reuse the 6 existing helper functions in handlers.py |
| Tool registration | Dynamic registration framework | Copy-paste the existing triple registration pattern | 3 files, ~10 lines each per handler -- simple enough to be explicit |
| FHIR terminology systems | Custom code tables | Standard FHIR URIs from hl7.org | Use official system URIs from FHIR R4 spec |

**Key insight:** This phase is pure extension, not invention. The patterns, client, helpers, and registration mechanisms all exist. The work is applying them to 10 new resource types with inpatient-specific semantics.

## Common Pitfalls

### Pitfall 1: Registration Mismatch
**What goes wrong:** Handler exists in handlers.py but is not registered in server.py or orchestrator.py (or vice versa), causing "Unknown tool" errors at runtime.
**Why it happens:** Three registration points with no automated sync. Easy to add to one and forget another.
**How to avoid:** After creating each handler, immediately add to all three locations. Use a checklist per handler.
**Warning signs:** "Unknown tool: X" errors when testing via MCP or orchestrator.

### Pitfall 2: Encounter Class vs. Type Confusion
**What goes wrong:** Using Encounter.type for "inpatient" vs "outpatient" when FHIR R4 uses Encounter.class for this distinction.
**Why it happens:** Encounter.class (coded as `http://terminology.hl7.org/CodeSystem/v3-ActCode` with values like `IMP` for inpatient, `AMB` for ambulatory) is the correct field. Encounter.type is for visit reason.
**How to avoid:** Always use `class` with system `http://terminology.hl7.org/CodeSystem/v3-ActCode` and code `IMP` for inpatient encounters. Search with `class=IMP` to filter inpatient only.
**Warning signs:** Search returns outpatient encounters mixed with inpatient.

### Pitfall 3: Encounter Status State Machine
**What goes wrong:** Allowing invalid status transitions (e.g., "finished" -> "in-progress") that Medplum may reject.
**Why it happens:** FHIR R4 Encounter has a defined status flow: planned -> arrived -> triaged -> in-progress -> onleave -> finished -> cancelled -> entered-in-error.
**How to avoid:** Validate transitions in the handler before attempting the update. At minimum, document the expected flow.
**Warning signs:** 422 Unprocessable Entity from Medplum on status updates.

### Pitfall 4: Large File Growth
**What goes wrong:** handlers.py is already 2,739 lines. Adding ~35 handlers at ~50-80 lines each adds ~2,000-2,800 lines, pushing it to ~5,000+ lines.
**Why it happens:** Existing pattern is one monolithic file.
**How to avoid:** Keep the single-file pattern for now (consistency with existing code), but use clear section headers with `# ====` separators. Future phases can refactor into submodules if needed.
**Warning signs:** IDE performance degradation, merge conflicts.

### Pitfall 5: Missing encounter_id References
**What goes wrong:** Creating inpatient resources (Flag, Task, ClinicalImpression, etc.) without linking them to the specific Encounter via the `encounter` field. Later queries by encounter fail.
**Why it happens:** Many FHIR resources have optional `encounter` references. For inpatient workflows, these should always be populated.
**How to avoid:** All inpatient handler create functions should accept and populate `encounter_id` as a parameter. Make it required (or strongly recommended) for inpatient resource types.
**Warning signs:** Resources created but not findable when searching by encounter.

### Pitfall 6: Medplum Search Parameter Support
**What goes wrong:** Using FHIR R4 search parameters that Medplum does not index or support, getting empty results or errors.
**Why it happens:** Medplum supports most but not all FHIR R4 search parameters. Some composite or chained searches may not work.
**How to avoid:** Test each search query against Medplum during development. Fall back to broader searches with client-side filtering if needed.
**Warning signs:** Searches return empty bundles when data exists.

## Code Examples

### FHIR R4 Inpatient Encounter Resource Structure
```python
# Source: FHIR R4 Encounter resource definition (hl7.org/fhir/R4/encounter.html)
encounter = {
    "resourceType": "Encounter",
    "status": "in-progress",  # planned|arrived|triaged|in-progress|onleave|finished|cancelled|entered-in-error
    "class": {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "code": "IMP",  # IMP=inpatient, EMER=emergency, AMB=ambulatory
        "display": "inpatient encounter",
    },
    "type": [{
        "coding": [{
            "system": "http://snomed.info/sct",
            "code": "183452005",
            "display": "Emergency hospital admission",
        }]
    }],
    "priority": {
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
            "code": "EM",  # EM=emergency, UR=urgent, R=routine
        }]
    },
    "subject": {"reference": "Patient/{patient_id}"},
    "period": {
        "start": "2026-02-25T08:00:00Z",
        # "end" populated on discharge
    },
    "reasonCode": [{
        "text": "Sepsis workup",
    }],
    "hospitalization": {
        "admitSource": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/admit-source",
                "code": "emd",
                "display": "From accident/emergency department",
            }]
        },
        "dischargeDisposition": None,  # Populated on discharge
    },
    "location": [{
        "location": {"display": "ICU Bed 3"},
        "status": "active",
        "period": {"start": "2026-02-25T08:00:00Z"},
    }],
    "serviceProvider": {"display": "AgentEHR Hospital"},
}
```

### FHIR R4 Flag Resource
```python
# Source: hl7.org/fhir/R4/flag.html
flag = {
    "resourceType": "Flag",
    "status": "active",  # active|inactive|entered-in-error
    "category": [{
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/flag-category",
            "code": "clinical",  # clinical|safety|drug|lab|contact|behavioral|research|advance-directive
        }]
    }],
    "code": {"text": "Fall risk - high"},
    "subject": {"reference": "Patient/{patient_id}"},
    "encounter": {"reference": "Encounter/{encounter_id}"},
    "period": {
        "start": "2026-02-25T08:00:00Z",
    },
    "author": {"display": "Dr. Smith"},
}
```

### FHIR R4 Task Resource
```python
# Source: hl7.org/fhir/R4/task.html
task = {
    "resourceType": "Task",
    "status": "requested",  # draft|requested|received|accepted|rejected|ready|cancelled|in-progress|on-hold|failed|completed|entered-in-error
    "intent": "order",
    "priority": "urgent",  # routine|urgent|asap|stat
    "code": {"text": "Check blood cultures at 4h"},
    "for": {"reference": "Patient/{patient_id}"},
    "encounter": {"reference": "Encounter/{encounter_id}"},
    "requester": {"display": "Supervisor Agent"},
    "owner": {"display": "RN Johnson"},
    "restriction": {
        "period": {
            "end": "2026-02-25T12:00:00Z",  # Due by
        }
    },
    "note": [{"text": "Part of sepsis Hour-1 Bundle compliance"}],
}
```

### FHIR R4 CareTeam Resource
```python
# Source: hl7.org/fhir/R4/careteam.html
care_team = {
    "resourceType": "CareTeam",
    "status": "active",  # proposed|active|suspended|inactive|entered-in-error
    "name": "ICU Care Team - Patient Smith",
    "subject": {"reference": "Patient/{patient_id}"},
    "encounter": {"reference": "Encounter/{encounter_id}"},
    "participant": [
        {
            "role": [{
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "309343006",
                    "display": "Physician",
                }]
            }],
            "member": {"display": "Dr. Williams"},
        },
        {
            "role": [{"coding": [{"code": "224535009", "display": "Registered nurse"}]}],
            "member": {"display": "RN Johnson"},
        },
    ],
}
```

### FHIR R4 ClinicalImpression Resource
```python
# Source: hl7.org/fhir/R4/clinicalimpression.html
clinical_impression = {
    "resourceType": "ClinicalImpression",
    "status": "completed",  # in-progress|completed|entered-in-error
    "subject": {"reference": "Patient/{patient_id}"},
    "encounter": {"reference": "Encounter/{encounter_id}"},
    "date": "2026-02-25T10:30:00Z",
    "assessor": {"display": "Infectious Disease Agent"},
    "summary": "Patient meets qSOFA >= 2. Suspected sepsis. Recommend blood cultures and empiric antibiotics.",
    "finding": [{
        "itemCodeableConcept": {
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": "91302008",
                "display": "Sepsis",
            }]
        },
    }],
    "note": [{"text": "qSOFA score: 2 (hypotension, altered mental status)"}],
}
```

### FHIR R4 RiskAssessment Resource
```python
# Source: hl7.org/fhir/R4/riskassessment.html
risk_assessment = {
    "resourceType": "RiskAssessment",
    "status": "final",  # registered|preliminary|final|amended|corrected|cancelled|entered-in-error
    "subject": {"reference": "Patient/{patient_id}"},
    "encounter": {"reference": "Encounter/{encounter_id}"},
    "occurrenceDateTime": "2026-02-25T10:30:00Z",
    "condition": {
        "display": "Septic shock",
    },
    "prediction": [{
        "outcome": {"text": "Deterioration within 6 hours"},
        "qualitativeRisk": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/risk-probability",
                "code": "high",
            }]
        },
    }],
    "basis": [
        {"display": "NEWS2 score: 9"},
        {"display": "qSOFA score: 2"},
    ],
    "note": [{"text": "Based on NEWS2=9 and qSOFA=2, high risk of deterioration"}],
}
```

### FHIR R4 Goal Resource
```python
# Source: hl7.org/fhir/R4/goal.html
goal = {
    "resourceType": "Goal",
    "lifecycleStatus": "active",  # proposed|planned|accepted|active|on-hold|completed|cancelled|entered-in-error|rejected
    "achievementStatus": {
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/goal-achievement",
            "code": "in-progress",
        }]
    },
    "description": {"text": "MAP > 65 mmHg without vasopressors"},
    "subject": {"reference": "Patient/{patient_id}"},
    "target": [{
        "measure": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "8478-0",
                "display": "Mean blood pressure",
            }]
        },
        "detailQuantity": {
            "value": 65,
            "unit": "mmHg",
            "system": "http://unitsofmeasure.org",
            "code": "mm[Hg]",
        },
    }],
}
```

### FHIR R4 AdverseEvent Resource
```python
# Source: hl7.org/fhir/R4/adverseevent.html
adverse_event = {
    "resourceType": "AdverseEvent",
    "actuality": "actual",  # actual|potential
    "category": [{
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/adverse-event-category",
            "code": "medication-mishap",
        }]
    }],
    "subject": {"reference": "Patient/{patient_id}"},
    "encounter": {"reference": "Encounter/{encounter_id}"},
    "date": "2026-02-25T14:00:00Z",
    "event": {"text": "Allergic reaction to Penicillin"},
    "seriousness": {
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/adverse-event-seriousness",
            "code": "serious",
        }]
    },
    "severity": {
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/adverse-event-severity",
            "code": "moderate",
        }]
    },
}
```

### FHIR R4 DeviceMetric Resource
```python
# Source: hl7.org/fhir/R4/devicemetric.html
device_metric = {
    "resourceType": "DeviceMetric",
    "type": {
        "coding": [{
            "system": "urn:iso:std:iso:11073:10101",
            "code": "150456",
            "display": "SpO2",
        }]
    },
    "source": {"display": "Bedside Monitor - ICU Bed 3"},
    "category": "measurement",  # measurement|setting|calculation|unspecified
    "operationalStatus": "on",  # on|off|standby|entered-in-error
}
# Note: DeviceMetric is a device-level resource, not patient-level.
# Actual metric values go into Observation resources referencing the DeviceMetric.
# For inpatient monitoring, the more useful pattern is:
# DeviceMetric defines what the device measures
# Observation records the actual readings with device reference
```

### Tool Registration Example (All Three Locations)
```python
# 1. handlers.py -- the handler function
async def handle_create_flag(args: dict) -> dict:
    """Create a clinical flag for a patient."""
    # ... implementation ...

# 2. server.py -- Tool definition in list_tools()
Tool(
    name="create_flag",
    description="Create a clinical flag (fall risk, isolation, allergy alert, etc.) for an inpatient.",
    inputSchema={
        "type": "object",
        "properties": {
            "patient_id": {"type": "string", "description": "FHIR Patient ID"},
            "description": {"type": "string", "description": "Flag description (e.g., 'Fall risk - high')"},
            "category": {"type": "string", "enum": ["clinical", "safety", "drug", "behavioral"], "description": "Flag category"},
            "encounter_id": {"type": "string", "description": "FHIR Encounter ID (links flag to admission)"},
            "priority": {"type": "string", "enum": ["PN", "PL", "PM", "PH"], "description": "Priority (low/medium/high)"},
        },
        "required": ["patient_id", "description"],
    },
),

# 2b. server.py -- dispatch in call_tool()
elif name == "create_flag":
    result = await handle_create_flag(arguments)

# 3. orchestrator.py -- FHIR_TOOLS entry
{
    "name": "create_flag",
    "description": "Create a clinical flag (fall risk, isolation, allergy alert, etc.) for an inpatient.",
    "input_schema": {
        "type": "object",
        "properties": {
            "patient_id": {"type": "string", "description": "FHIR Patient ID"},
            "description": {"type": "string", "description": "Flag description"},
            "category": {"type": "string", "enum": ["clinical", "safety", "drug", "behavioral"]},
            "encounter_id": {"type": "string", "description": "FHIR Encounter ID"},
        },
        "required": ["patient_id", "description"],
    },
},

# 3b. orchestrator.py -- handlers dict
"create_flag": handle_create_flag,
```

## Complete Handler Inventory (~35 handlers)

### Encounter Inpatient Lifecycle (5 handlers)
| Handler | FHIR Op | Description |
|---------|---------|-------------|
| `create_inpatient_encounter` | Encounter.create | Admit patient -- creates Encounter with class=IMP |
| `update_encounter_status` | Encounter.update | Transition status (arrived->in-progress->finished) |
| `get_encounter_timeline` | Multi-search | Full encounter view: conditions, vitals, meds, tasks |
| `transfer_patient` | Encounter.update | Update location within facility |
| `discharge_patient` | Encounter.update | Set status=finished, populate discharge disposition |

### Flag (3 handlers)
| Handler | FHIR Op | Description |
|---------|---------|-------------|
| `create_flag` | Flag.create | Create clinical flag (fall risk, isolation, etc.) |
| `get_active_flags` | Flag.search | Get active flags for patient/encounter |
| `resolve_flag` | Flag.update | Set flag status to inactive |

### ClinicalImpression (2 handlers)
| Handler | FHIR Op | Description |
|---------|---------|-------------|
| `create_clinical_impression` | ClinicalImpression.create | Record agent clinical assessment |
| `get_clinical_impressions` | ClinicalImpression.search | Get impressions for patient/encounter |

### RiskAssessment (2 handlers)
| Handler | FHIR Op | Description |
|---------|---------|-------------|
| `create_risk_assessment` | RiskAssessment.create | Record risk assessment (NEWS2, qSOFA basis) |
| `get_risk_assessments` | RiskAssessment.search | Get risk assessments for patient/encounter |

### Task (5 handlers)
| Handler | FHIR Op | Description |
|---------|---------|-------------|
| `create_task` | Task.create | Create care coordination task |
| `assign_task` | Task.update | Assign task to team member |
| `complete_task` | Task.update | Mark task completed with output |
| `get_pending_tasks` | Task.search | Get pending/in-progress tasks |
| `update_task_status` | Task.update | Generic status transition |

### CareTeam (3 handlers)
| Handler | FHIR Op | Description |
|---------|---------|-------------|
| `create_care_team` | CareTeam.create | Create care team for encounter |
| `get_care_team` | CareTeam.search | Get care team for patient/encounter |
| `update_care_team_member` | CareTeam.update | Add/remove team members |

### Goal (3 handlers)
| Handler | FHIR Op | Description |
|---------|---------|-------------|
| `create_goal` | Goal.create | Set clinical goal (MAP target, etc.) |
| `get_patient_goals` | Goal.search | Get active goals for patient |
| `update_goal_status` | Goal.update | Update goal lifecycle/achievement status |

### DeviceMetric (2 handlers)
| Handler | FHIR Op | Description |
|---------|---------|-------------|
| `record_device_metric` | DeviceMetric.create | Register device metric source |
| `get_device_metrics` | DeviceMetric.search | Get device metrics |

### AdverseEvent (2 handlers)
| Handler | FHIR Op | Description |
|---------|---------|-------------|
| `report_adverse_event` | AdverseEvent.create | Report adverse event during encounter |
| `get_adverse_events` | AdverseEvent.search | Get adverse events for patient/encounter |

### Inpatient Communication (3 handlers)
| Handler | FHIR Op | Description |
|---------|---------|-------------|
| `create_inpatient_communication` | Communication.create | Inpatient-specific (handoff, consult request) |
| `get_communications` | Communication.search | Get communications for encounter |
| `search_communications` | Communication.search | Search with filters (category, sender, date) |

**Total: ~30 new handlers** (existing `handle_create_communication` and `handle_search_encounters` cover 2 of the original scope; some resource types need fewer handlers than initially estimated)

### ActionType Additions Needed
```python
# In approval_queue.py, add to ActionType enum:
ENCOUNTER = "Encounter"
FLAG = "Flag"
CLINICAL_IMPRESSION = "ClinicalImpression"
RISK_ASSESSMENT = "RiskAssessment"
TASK = "Task"
CARE_TEAM = "CareTeam"
GOAL = "Goal"
DEVICE_METRIC = "DeviceMetric"
ADVERSE_EVENT = "AdverseEvent"
# Note: Communication already exists in ActionType
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| FHIR DSTU2 Encounter.class as string | FHIR R4 Encounter.class as Coding | R4 (2019) | class is now `{system, code, display}` not a simple string |
| Separate admission/discharge resources | Encounter lifecycle with status machine | R4 | All in one resource with status transitions |
| CareTeam as extension | CareTeam as first-class resource | R4 | Native resource with participant array |
| Flag only for allergy alerts | Flag for any clinical/safety/behavioral flag | R4 | Broader use including fall risk, isolation, VIP |

**Deprecated/outdated:**
- FHIR DSTU2/STU3 patterns for Encounter.class (was a string, now Coding) -- ensure all code uses R4 format
- Using `Encounter.indication` -- replaced by `Encounter.reasonCode` / `Encounter.reasonReference` in R4

## Open Questions

1. **DeviceMetric vs. Observation for vital signs monitoring**
   - What we know: DeviceMetric describes the device/metric capability. Actual readings are Observation resources. The existing system already uses Observation for vitals.
   - What's unclear: Whether the supervisor agent will need DeviceMetric resources or just Observation-with-device-reference. DeviceMetric is primarily for device management, not clinical data.
   - Recommendation: Implement DeviceMetric handlers as specified, but expect that the supervisor agent in Phase 3 will primarily use Observation searches. DeviceMetric handlers may see low usage until device integration becomes relevant.

2. **Approval queue for read-only inpatient resources**
   - What we know: Existing write handlers route through approval queue (NFR-03: no direct treatment modification). ClinicalImpression and RiskAssessment are agent-generated assessments, not treatment modifications.
   - What's unclear: Should agent-created assessments (ClinicalImpression, RiskAssessment) go through approval, or are they informational?
   - Recommendation: Route ClinicalImpression and RiskAssessment through the approval queue since they become part of the medical record. Flag creation and Task creation should also route through approval. Read/search handlers never need approval.

3. **Existing Communication handler overlap**
   - What we know: `handle_create_communication` exists but is outpatient-focused (letters to referring physicians).
   - What's unclear: Whether to modify the existing handler or create a separate inpatient-specific handler.
   - Recommendation: Create a new `handle_create_inpatient_communication` with inpatient-specific categories (handoff, consult_request, nursing_note, interdisciplinary_note) and encounter linkage. Keep the existing handler for outpatient use.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `fhir-mcp-server/src/handlers.py` (2,739 lines, 36 existing handlers) -- pattern analysis
- Existing codebase: `fhir-mcp-server/src/server.py` (2,429 lines, 34 Tool registrations) -- registration pattern
- Existing codebase: `agents/openrouter_orchestrator.py` (1,054 lines, FHIR_TOOLS list + handlers dict) -- orchestrator pattern
- Existing codebase: `fhir-mcp-server/src/approval_queue.py` -- ActionType enum, queue pattern
- FHIR R4 specification (hl7.org/fhir/R4) -- resource definitions for all 10 resource types

### Secondary (MEDIUM confidence)
- FHIR R4 Encounter status state machine -- documented in spec but Medplum enforcement of transitions needs runtime verification
- Medplum FHIR R4 search parameter support -- generally comprehensive but specific parameters for newer resources (ClinicalImpression, RiskAssessment) should be tested

### Tertiary (LOW confidence)
- DeviceMetric utility for agent workflows -- unclear how much the supervisor agent will actually use this resource type vs. direct Observation queries

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new dependencies, pure extension of existing patterns
- Architecture: HIGH - existing triple-registration pattern is clear and well-documented in code
- Pitfalls: HIGH - identified from direct code analysis (not web search); encounter class/type confusion is well-known in FHIR community

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable -- FHIR R4 and existing codebase patterns are settled)
