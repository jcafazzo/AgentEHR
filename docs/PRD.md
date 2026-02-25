# AgentEHR: Inpatient Care Oversight Platform
## Product Requirements Document (PRD)

> **Version:** 1.0.0 | **Date:** 2026-02-25 | **Status:** Draft

---

## 1. Executive Summary

AgentEHR evolves from an outpatient EHR chat interface into an **AI-powered inpatient care oversight platform**. When a patient is admitted to the hospital, a **supervisor agent** begins continuous monitoring and spawns **specialized sub-agents** (cardiology, infectious disease, medication safety, etc.) based on the patient's clinical needs. These agents access EHR data via FHIR R4 through MCP servers, monitor real-time vital signs, identify care gaps, flag escalations, and proactively recommend interventions — ensuring every patient receives timely, guideline-compliant, state-of-the-art care.

**The core problem:** Clinical inertia in inpatient settings leads to delayed interventions, missed care gaps, and preventable adverse events. Studies show 95% of hospital alerts are non-actionable (alarm fatigue), early warning signs are detected too late, and guideline adherence varies widely (sepsis bundle compliance averages only 48.9% nationally).

**The solution:** An autonomous agent orchestrator that never sleeps, never forgets a guideline, and escalates intelligently — functioning as a tireless clinical safety net.

---

## 2. Problem Statement

### Clinical Inertia in Inpatient Care
- Delayed recognition of clinical deterioration (average 1.7 hours with traditional RRT vs. 30 hours with eCART)
- Missed care gaps: incomplete workups, overdue screenings, unapplied guidelines
- Alert fatigue: 150-400 physiologic alarms per patient per day in ICU; 53% not responded to
- Siloed specialty knowledge: No single clinician holds all relevant guidelines for complex patients
- Time-to-treatment failures: Door-to-needle (stroke) >60 min, sepsis antibiotics >1 hour in many cases
- Failure-to-rescue: Preventable deaths from inadequate monitoring or delayed response

### Market Gap
No existing product combines:
- Comprehensive inpatient clinical surveillance (not just imaging or sepsis)
- Multi-specialist agent reasoning (not single-condition detection)
- Proactive care gap identification with guideline adherence monitoring
- Intelligent escalation orchestration (not just alerts)
- FHIR-native architecture for seamless EHR integration

Current landscape is fragmented: Viz.ai (imaging only), CLEW (ICU prediction only), Qventus (operations only), Epic Sepsis Model (single condition, 14.7% sensitivity in external validation).

---

## 3. Product Vision & Design Principles

1. **"Agent Per Specialty"** — Each clinical domain has a dedicated agent with its own knowledge base of guidelines, protocols, and evidence. Agents are defined and configured by administrators.

2. **"Escalate, Don't Alert"** — Instead of bombarding clinicians with raw alerts, agents reason about clinical significance, filter noise, and escalate only actionable findings with context and recommendations.

3. **"Evidence-Grounded Autonomy"** — Every agent recommendation cites specific guidelines, scoring systems, or patient data. No black-box decisions.

4. **"Earn Autonomy"** — Start with heavily constrained agents that assist. Add autonomy only as reliability is proven. High-risk decisions always require human approval.

5. **"Simple Dashboard, Deep Intelligence"** — The UI is a clean, streamlined command center — not another bloated EHR. Complexity lives in the agents, not the interface.

---

## 4. Target Users

| User | Role | Primary Needs |
|------|------|---------------|
| **ED Physician** | Frontline clinician | Rapid triage support, time-sensitive alerts, workup completeness |
| **Hospitalist** | Inpatient attending | Patient census oversight, care gap identification, discharge planning |
| **ICU Intensivist** | Critical care | Real-time monitoring, organ failure tracking, ventilator management |
| **Charge Nurse** | Nursing lead | Patient status board, escalation notifications, task management |
| **Clinical Administrator** | System config | Agent definition, knowledge base management, alert threshold tuning |
| **Quality Officer** | Compliance | CMS core measure tracking, guideline adherence reporting |

---

## 5. System Architecture

```
                    +-------------------------------------+
                    |     ADMIN INTERFACE (Agent Config)   |
                    |  Define specialties, knowledge bases, |
                    |  escalation rules, alert thresholds  |
                    +--------------+----------------------+
                                   |
+----------------------------------+----------------------------------+
|                    CLINICIAN DASHBOARD (Next.js)                     |
|  Patient census | Alert feed | Escalation queue | Chat | Vitals    |
+------------------------+-------------------------------------------+
                         | HTTP/WebSocket
+------------------------+-------------------------------------------+
|                    API LAYER (FastAPI)                               |
|  Chat | Census | Alerts | Escalations | Agent Admin | Vitals WS    |
+------------------------+-------------------------------------------+
                         |
+------------------------+-------------------------------------------+
|              AGENT ORCHESTRATION LAYER                               |
|                                                                     |
|  +-------------------------------------+                           |
|  |      SUPERVISOR AGENT (per patient) |                           |
|  |  - Monitors patient state           |                           |
|  |  - Spawns/retires specialty agents  |                           |
|  |  - Synthesizes recommendations      |                           |
|  |  - Manages escalation routing       |                           |
|  +----------+--------------------------+                           |
|             | spawns based on patient conditions                    |
|  +----------+----------+----------+----------+----------+          |
|  |          |          |          |          |          |          |
|  v          v          v          v          v          v          |
| +----+  +--------+ +------+ +------+ +--------+ +---------+      |
| |Card|  |Infect  | |Meds  | |Renal | |Pulm    | |Clinical |      |
| |iolo|  |Disease | |Safety| |      | |        | |Trials   |      |
| |gy  |  |        | |      | |      | |        | |Matcher  |      |
| +----+  +--------+ +------+ +------+ +--------+ +---------+      |
|  Each agent has: knowledge base, tools, escalation triggers        |
+------------------------+-------------------------------------------+
                         |
+------------------------+-------------------------------------------+
|                    MCP SERVER LAYER                                  |
|  FHIR Tools | Vital Signs Stream | Lab Monitor | Scoring Tools     |
|  (expanded from current 47 to 80+ tools)                           |
+------------------------+-------------------------------------------+
                         |
+------------------------+-------------------------------------------+
|                    FHIR R4 BACKEND                                   |
|  Medplum | Real-time Subscriptions | Device Integration            |
|  Encounter | Flag | RiskAssessment | ClinicalImpression | Task     |
+--------------------------------------------------------------------+
```

### Key Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent framework | Claude Agent SDK (supervisor -> subagents) | Native hierarchical delegation, isolated contexts, proven pattern |
| Orchestration | Supervisor per patient + specialist subagents | Maps to clinical care team model; 3-5 agents optimal per research |
| Real-time data | FHIR Subscriptions (R4B backport) + WebSocket | Standard-compliant, low-latency |
| Knowledge bases | RAG (vector store) + structured guidelines | Semantic search + precise protocol lookup |
| Alert system | 4-tier (Critical/Urgent/Routine/Info) | Evidence-based; reduces alarm fatigue |
| Admin config | Configuration-based (not code) | Clinical teams can define agents without engineering |
| Scoring | NEWS2 + eCART + condition-specific | NEWS2 best discriminator; eCART adds 30-hour advance warning |

---

## 6. Agent Framework

### 6.1 Supervisor Agent (one per patient)

Responsibilities:
- **Monitor**: Continuously evaluate patient state via FHIR data
- **Spawn**: Create specialist sub-agents based on active conditions
- **Synthesize**: Aggregate findings from sub-agents into unified recommendations
- **Escalate**: Route urgent findings through the escalation framework
- **Retire**: Remove sub-agents when conditions resolve or patient discharges

System prompt includes: patient demographics, allergies, conditions, medications, care team, encounter details, flags, risk assessments, real-time vitals summary, pending tasks, care gaps.

### 6.2 Specialist Sub-Agents

| Agent | Spawn Triggers | Knowledge Base | Escalation Examples |
|-------|---------------|----------------|-------------------|
| **Cardiology** | AFib, CHF, ACS, arrhythmia | ACC/AHA guidelines | New ST changes, troponin rise >20%, HR >150 |
| **Infectious Disease** | Fever, positive cultures, sepsis criteria | Surviving Sepsis Campaign | qSOFA >=2, positive blood cultures, antibiotic delay |
| **Medication Safety** | Any active medications | Drug interaction DB, renal dosing | Contraindicated combo, allergy alert |
| **Renal** | CKD, AKI, electrolyte abnormalities | KDIGO guidelines | Cr rise >0.3 in 48h, K+ >6.0 |
| **Pulmonary** | COPD, PE, respiratory failure | GOLD, PE protocols | SpO2 <90%, RR >30, Wells >=4 |
| **Endocrine** | DKA, diabetes | ADA guidelines | Anion gap >12 + pH <7.3, glucose >500 |
| **Neurology** | Stroke, seizure, AMS | AHA stroke guidelines | NIHSS increase >=2, new focal deficit |
| **Hematology/Onc** | Cancer, coagulopathy | NCCN guidelines | INR >4, febrile neutropenia |
| **Clinical Trials** | Any condition with active trials | ClinicalTrials.gov | Patient matches high-priority trial |
| **Discharge Planning** | Approaching stability | CMS requirements | High readmission risk, incomplete checklist |

### 6.3 Knowledge Base Architecture

```
agent-knowledge/{specialty}/
|-- guidelines/           # Clinical practice guidelines (PDF/markdown)
|-- protocols/            # Institution-specific protocols
|-- scoring/              # Scoring system definitions (JSON)
|-- escalation_rules.json # When to escalate and to whom
+-- agent_config.json     # Parameters, thresholds, tool access
```

Guidelines embedded in vector store (ChromaDB) for RAG retrieval. Scoring systems and escalation rules as structured JSON for deterministic evaluation.

### 6.4 Agent Lifecycle

```
DEFINE (admin) -> SPAWN (supervisor) -> MONITOR -> EVALUATE -> RETIRE
```

- **Define**: Admin creates agent template with specialty, knowledge base, tools, thresholds
- **Spawn**: Supervisor creates agent when patient conditions match triggers
- **Monitor**: Agent continuously reasons about patient data within its domain
- **Evaluate**: Periodic accuracy checks, override rate monitoring
- **Retire**: Agent removed when condition resolves or patient discharges

### 6.5 Administrator Agent Definition Interface

**Agent Template Editor:**
- Select specialty or create custom
- Upload clinical guidelines and protocols
- Configure alert thresholds per condition
- Define tool access permissions (read-only vs. read-write per FHIR resource)
- Set escalation pathways (who gets notified at each tier)
- Enable/disable per care setting (ED, ICU, med-surg)

**Knowledge Base Manager:**
- Upload/version clinical guidelines
- Tag by condition, specialty, evidence level
- Track which agents use which guidelines

**Performance Dashboard:**
- Alert accuracy, false positive rate, escalation appropriateness
- Override tracking, knowledge base coverage gaps

---

## 7. Clinical Intelligence

### 7.1 Automated Scoring Systems

| Score | Parameters | Thresholds | AUC | Use |
|-------|-----------|------------|-----|-----|
| **NEWS2** | RR, SpO2, BP, pulse, consciousness, temp, O2 | >=5 urgent; >=7 critical | 0.833-0.880 | General ward |
| **eCART** | 33 EHR variables | ML-derived threshold | 0.801-0.88 | Hospital-wide, 30hr warning |
| **SOFA** | 6 organ systems | >=2 increase = sepsis | 0.880 | ICU, organ dysfunction |
| **qSOFA** | BP <=100, RR >=22, GCS <15 | >=2 = high risk | 0.847 | Bedside sepsis screen |
| **KDIGO** | Creatinine, urine output | Stage 1-3 criteria | N/A | AKI detection |
| **Glasgow-Blatchford** | BUN, Hgb, BP, pulse, etc. | 0 = outpatient safe | N/A | GI bleed triage |

### 7.2 Sepsis Detection Pathway

```
Suspected infection -> Calculate qSOFA + SOFA -> qSOFA >=2 or SOFA increase >=2?
    YES -> URGENT escalation
        |-- Blood cultures obtained? (track time)
        |-- Antibiotics administered? (target <1 hour)
        |-- Lactate measured? (track level)
        |-- Fluid resuscitation started? (if hypotension/lactate >=4)
        +-- Monitor Hour-1 Bundle compliance (SEP-1)
```

### 7.3 Condition-Specific Time Benchmarks

| Condition | Key Metric | Target Time |
|-----------|-----------|-------------|
| Stroke (ischemic) | Door-to-needle (tPA) | <60 min (optimal <30) |
| STEMI | Door-to-balloon | <90 min |
| Sepsis | Time to antibiotics | <1 hour from recognition |
| PE | CTPA completion | <2 hours from suspicion |
| DKA | Insulin drip initiation | <2 hours from diagnosis |
| AKI | KDIGO staging | <24 hours from Cr rise |

### 7.4 Clinical Trials Matching

Dedicated agent proactively screens admitted patients against ClinicalTrials.gov eligibility criteria using NLP. Evidence shows this reduces manual chart review by 40-57% while maintaining 98-100% sensitivity.

---

## 8. Escalation Framework

### Four-Tier Alert Classification

| Tier | Response | Delivery | Examples |
|------|----------|----------|----------|
| **CRITICAL** | <5 min | Bedside + phone + page | Cardiac arrest criteria, SpO2 <80%, sepsis + no antibiotics by 1h |
| **URGENT** | 15-30 min | Phone notification | NEWS >=7, lactate >4, troponin rise + symptoms |
| **ROUTINE** | 1-2 hours | Dashboard | NEWS 5-6, mild parameter drift |
| **INFORMATIONAL** | 4+ hours | Passive display | Trending alerts, quality metrics |

### Alarm Fatigue Mitigation
1. **Contextual suppression**: Adjust thresholds per patient baseline
2. **Multi-parameter fusion**: Combine vitals into single clinical decision
3. **Smart deduplication**: Don't re-alert for acknowledged conditions
4. **Override analysis**: Weekly review to tune thresholds
5. **Clinician feedback loop**: Rate alert helpfulness

---

## 9. FHIR R4 Data Model (Expanded)

### New Inpatient Resources & Tools

| Resource | New Tools |
|----------|-----------|
| **Encounter** (inpatient) | `create_inpatient_encounter`, `update_encounter_status`, `get_encounter_timeline`, `transfer_patient` |
| **EpisodeOfCare** | `create_episode_of_care`, `get_active_episodes` |
| **Flag** | `create_clinical_flag`, `get_active_flags`, `resolve_flag` |
| **ClinicalImpression** | `create_clinical_impression`, `get_recent_impressions` |
| **RiskAssessment** | `create_risk_assessment`, `get_risk_scores`, `trend_risk_scores` |
| **Task** | `create_task`, `assign_task`, `complete_task`, `get_pending_tasks` |
| **CareTeam** | `get_care_team`, `update_care_team` |
| **Goal** | `create_goal`, `update_goal_progress`, `get_active_goals` |
| **DeviceMetric** | `get_device_metrics`, `get_waveform_data` |
| **AdverseEvent** | `report_adverse_event`, `get_adverse_events` |
| **Communication** | `create_handoff_note`, `get_shift_communications` |

**Total: ~80+ tools** (current 47 + ~35 new)

### Real-Time Subscriptions

| Topic | Trigger | Agent Response |
|-------|---------|----------------|
| `Observation:vital-signs` | New vitals posted | Recalculate NEWS2/eCART |
| `Observation:laboratory` | New lab result | Critical value check, trending |
| `Encounter:status-change` | ADT event | Spawn/retire agents |
| `Flag:created` | New clinical flag | Evaluate urgency |
| `MedicationAdministration` | Med administered | Track timeliness (e.g., sepsis antibiotics) |
| `Condition:new` | New diagnosis | Spawn relevant specialist agent |

### Key New MCP Tool Groups

**Monitoring:** `get_recent_vital_signs`, `calculate_news2`, `calculate_sofa`, `evaluate_sepsis_criteria`
**Encounter:** `get_active_encounter`, `get_encounter_timeline`, `get_care_team`, `get_pending_tasks`
**Assessment:** `create_risk_assessment`, `get_risk_score_trend`, `evaluate_care_gaps`, `match_clinical_trials`
**Communication:** `create_clinical_flag`, `create_handoff_note`, `create_task`, `assign_task`

---

## 10. User Interface

### Clinician Dashboard (Command Center)

```
+----------+----------------------------------+-----------------------+
| PATIENT  |  SELECTED PATIENT VIEW           |  ESCALATION FEED     |
| CENSUS   |                                  |                      |
|          |  Patient Header + Active Agents   |  CRITICAL (red)      |
| * Smith  |  Real-time Vital Signs           |  URGENT (orange)     |
|   NEWS:7 |  Agent Recommendations           |  ROUTINE (yellow)    |
| * Garcia |  Clinical Data Sections          |  INFO (blue)         |
|   NEWS:5 |                                  |                      |
| * etc.   |                                  |  CHAT (context from  |
|          |                                  |  clinical team)      |
| Sort by: |                                  |                      |
| [Acuity] |                                  |                      |
+----------+----------------------------------+-----------------------+
```

- **Left**: Patient census sorted by acuity (NEWS2), color-coded
- **Center**: Active agents, real-time vitals, recommendations, clinical data
- **Right**: Tiered escalation feed + chat for clinician context input

### Administrator Interface

Dedicated section for agent template management, knowledge base uploads, escalation rule configuration, and performance metrics dashboards.

### Patient Portal (Retained)

Existing patient portal mode preserved for patient-facing access.

---

## 11. Safety & Compliance

| Area | Implementation |
|------|---------------|
| **Human-in-the-loop** | All critical/urgent escalations require clinician acknowledgment. High-risk actions need approval. |
| **Evidence citation** | Every recommendation cites guideline, score, or data point |
| **Conflict resolution** | Supervisor presents conflicting agent perspectives with evidence |
| **Scope limitation** | Agents recommend and escalate — never directly modify treatment |
| **Hallucination prevention** | Strict FHIR data context injection; flag missing data rather than infer |
| **Audit trail** | Every action logged: what, why, when, which agent, clinician response |
| **HIPAA** | FHIR-native granular access controls; minimum necessary data to agents |
| **FDA (CDS)** | Recommendations with reasoning to qualified professionals -> CDS exemption likely |
| **CMS Measures** | Automated SEP-1, stroke, MI, VTE prophylaxis compliance tracking |

---

## 12. Simulation & Testing Engine

### 12.1 Overview

A comprehensive simulation environment for end-to-end testing of the agent orchestration system. Enables spawning synthetic patients, generating realistic clinical journeys, visualizing agent behavior in real-time, and validating system performance — all without real patient data.

**Core goals:**
- Simulate complete patient journeys (ED arrival -> admission -> monitoring -> discharge/deterioration)
- Generate synthetic patients with realistic clinical histories and physiological data
- Visualize agent spawning, reasoning, data processing, and alerting in real-time
- Enable developers and clinicians to understand exactly how the system works
- Provide reproducible test scenarios for regression testing and quality assurance

### 12.2 Synthetic Patient Generation

**Primary tool: Synthea** (open-source synthetic patient generator)
- Generates complete FHIR R4 bundles with realistic clinical histories
- 90+ disease modules with evidence-based progression models
- Configurable demographics, geography, and prevalence rates
- Direct FHIR R4 output — loads directly into Medplum

**Custom inpatient modules** (extend Synthea):

| Module | Scenario | Key Data Generated |
|--------|----------|--------------------|
| Sepsis Progression | ED presentation -> SIRS -> sepsis -> septic shock | Vitals trending, lactate rising, cultures, antibiotics timing |
| Acute MI | Chest pain -> troponin rise -> cath lab -> recovery | Serial troponins, ECG findings, interventions, medications |
| DKA | Hyperglycemia -> acidosis -> insulin drip -> resolution | BMP panels, anion gap, insulin dosing, fluid balance |
| CHF Exacerbation | Dyspnea -> admission -> diuresis -> stabilization | BNP trending, daily weights, I/O, oxygen requirements |
| AKI Progression | Baseline Cr -> injury -> KDIGO staging -> recovery/dialysis | Serial creatinine, urine output, electrolytes |
| PE Workup | Pleuritic chest pain -> Wells score -> CTPA -> anticoagulation | D-dimer, imaging, Wells criteria, heparin dosing |
| Stroke (ischemic) | Sudden deficit -> NIHSS -> tPA decision -> monitoring | NIHSS scores, CT findings, door-to-needle timing |
| Post-op Complication | Surgery -> fever -> wound infection -> antibiotics | Temp trending, WBC, cultures, surgical site assessment |

**LLM-generated journeys**: For scenarios beyond predefined modules, use an LLM (via OpenRouter) to generate realistic patient narratives that are then converted to structured FHIR data. The LLM generates the clinical story; deterministic code converts it to FHIR resources with realistic timestamps and values.

### 12.3 Physiological Simulation Engine

**Vital signs generation** based on validated clinical patterns:

```
SimulationEngine
|-- PhysiologyModel          # Generates realistic vital signs
|   |-- BaselineGenerator    # Age/sex/condition-appropriate baselines
|   |-- TrendEngine          # Gradual deterioration or improvement curves
|   |-- VariabilityModel     # Realistic beat-to-beat and breath-to-breath variation
|   +-- InterventionEffects  # How treatments affect physiology (e.g., fluid bolus -> BP rise)
|-- LabEngine                # Generates lab results with realistic turnaround times
|   |-- CriticalValues       # Flags and auto-results for critical labs
|   +-- TrendingEngine       # Realistic lab value progression
+-- EventEngine              # Clinical events (falls, code blues, transfers)
```

**Vital sign patterns** derived from MIMIC-IV/eICU datasets:
- Heart rate: Normal sinus rhythm with age-appropriate variability, tachycardia/bradycardia patterns
- Blood pressure: Circadian variation, response to medications, shock progression
- SpO2: Desaturation curves, response to supplemental O2, COPD patterns
- Respiratory rate: Gradual tachypnea in sepsis, Kussmaul breathing in DKA
- Temperature: Fever spikes with realistic diurnal patterns, response to antipyretics

**Intervention modeling**: When the system (or clinician) initiates treatment, the physiology model responds:
- Fluid bolus -> MAP increase by 5-15 mmHg over 15-30 min
- Antipyretic -> Temperature decrease 1-2 deg F over 60-90 min
- Vasopressor start -> HR and MAP response within minutes
- Insulin drip -> Glucose decrease 50-100 mg/dL/hr

### 12.4 Scenario Authoring

**JSON/YAML scenario format** with conditional branching:

```yaml
scenario:
  name: "Sepsis - Delayed Antibiotics"
  description: "Patient with UTI progressing to sepsis, testing antibiotic timing alerts"
  patient_template: "elderly_female_uti"
  duration: "24h"

  timeline:
    - time: "0h"
      event: "ed_arrival"
      vitals: { hr: 92, bp: "118/72", temp: 100.8, rr: 20, spo2: 96 }
      labs_ordered: ["CBC", "BMP", "UA", "blood_cultures", "lactate"]

    - time: "0.5h"
      event: "lab_results"
      values: { wbc: 14.2, lactate: 2.8, ua: "positive_nitrites" }

    - time: "1h"
      event: "vitals_update"
      vitals: { hr: 105, bp: "102/60", temp: 101.9, rr: 24, spo2: 94 }
      # Agent should flag: qSOFA=2, sepsis suspected, antibiotics needed

    - time: "2h"
      condition: "antibiotics_not_given"
      branch: "deterioration"
      # If agent alert was acknowledged and antibiotics given, branch to "improvement"

  branches:
    deterioration:
      - time: "+0.5h"
        vitals: { hr: 118, bp: "88/52", temp: 103.1, rr: 28, spo2: 91 }
        event: "septic_shock_onset"

    improvement:
      - time: "+1h"
        vitals: { hr: 95, bp: "110/68", temp: 101.2, rr: 20, spo2: 96 }
        event: "clinical_improvement"
```

**Scenario library** with pre-built templates:
- **Time-critical**: Sepsis, STEMI, stroke, PE — tests escalation timing
- **Slow deterioration**: Gradual AKI, CHF decompensation — tests trend detection
- **Multi-system**: Diabetes + CKD + infection — tests multi-agent coordination
- **False alarm**: Patient with benign vital sign variations — tests specificity
- **Discharge readiness**: Improving patient — tests discharge planning agent

### 12.5 Simulation Control Panel

```
+--------------------------------------------------------------------+
|  SIMULATION CONTROL                                                 |
|                                                                     |
|  > Play  || Pause  << Rewind  >> Skip to Event    Speed: [1x v]    |
|                                                                     |
|  Timeline: --*-------------------------------------- 2h / 24h      |
|              ED Arrival    Labs    Vitals^   [Sepsis Alert]         |
|                                                                     |
|  +-------------------------------------------------------------+   |
|  |  ACTIVE SCENARIO: Sepsis - Delayed Antibiotics               |   |
|  |  Patient: Synthetic-F-72  |  Status: Running  |  Alerts: 3   |   |
|  +-------------------------------------------------------------+   |
|                                                                     |
|  [Inject Event v]  [Save Checkpoint]  [Load Checkpoint]            |
|  [New Scenario]    [Compare Runs]     [Export Report]              |
+--------------------------------------------------------------------+
```

**Controls:**
- **Play/Pause/Rewind**: Control simulation timeline
- **Speed**: 1x (real-time), 2x, 5x, 10x, 60x (1 min = 1 hour), skip-to-next-event
- **Inject Event**: Manually inject clinical events mid-simulation (new lab result, vital sign change, clinician order)
- **Checkpoints**: Save/load simulation state for reproducible testing
- **Compare Runs**: A/B comparison of different agent configurations against the same scenario

### 12.6 Agent Visualization Dashboard

**Real-time agent activity view** (integrated into simulation mode):

```
+-----------------------------------------------------------------+
|  AGENT ORCHESTRATION VIEW                                        |
|                                                                  |
|  +--------------+                                                |
|  |  SUPERVISOR   |--spawned--> +------------+                    |
|  |  Patient F-72 |             | ID Agent    | * ACTIVE          |
|  |  * MONITORING |--spawned--> | monitoring  |                    |
|  +------+-------+             +------------+                    |
|         |                                                        |
|         +--spawned--> +------------+                             |
|         |             | Renal Agent | * ACTIVE                   |
|         |             | Cr trending |                             |
|         |             +------------+                             |
|         |                                                        |
|         +--spawned--> +------------+                             |
|                       | Med Safety  | o IDLE                     |
|                       | (no issues) |                             |
|                       +------------+                             |
|                                                                  |
|  AGENT LOG (real-time):                                          |
|  12:03:22 [Supervisor] Received new vitals: HR=105, BP=102/60   |
|  12:03:23 [Supervisor] qSOFA=2, escalating to ID Agent           |
|  12:03:24 [ID Agent] Evaluating sepsis criteria...               |
|  12:03:25 [ID Agent] ALERT: Sepsis suspected, antibiotics        |
|           recommended within 1 hour (Hour-1 Bundle)               |
|  12:03:25 [ID Agent] -> URGENT escalation generated              |
+-----------------------------------------------------------------+
```

**Visualization components:**

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Agent graph | ReactFlow | Interactive node graph showing supervisor->subagent relationships, spawning/retirement |
| Vital signs | Recharts | Real-time streaming vital sign charts with annotation markers for agent alerts |
| Agent log | Custom stream | Timestamped log of every agent reasoning step, tool call, and decision |
| Decision tree | ReactFlow | Visual trace of agent reasoning: data in -> scoring -> threshold check -> action |
| Timeline | Custom | Horizontal timeline with events, alerts, and branch points annotated |

**Agent observability** (powered by LangFuse + OpenTelemetry):
- Every agent turn traced: input data, reasoning, tool calls, output
- Latency metrics per agent and per tool call
- Token usage tracking per agent
- Decision audit trail: what data led to what conclusion
- Exportable traces for post-simulation analysis

### 12.7 Simulation Modes

| Mode | Purpose | Speed | User Interaction |
|------|---------|-------|-----------------|
| **Demo** | Showcase system to stakeholders | 10-60x | Watch only, pre-scripted |
| **Testing** | Validate agent behavior | 5-10x | Inject events, assert outcomes |
| **Debug** | Investigate agent decisions | 1x or step-through | Pause, inspect state, modify |
| **Stress** | Load testing with multiple patients | Max speed | Automated, metrics collection |
| **Comparison** | A/B test agent configurations | Parallel runs | Side-by-side results |

### 12.8 Test Assertions & Reporting

**Automated assertions** per scenario:

```yaml
assertions:
  - type: "alert_generated"
    agent: "infectious_disease"
    severity: "URGENT"
    within: "30min"  # From when sepsis criteria first met

  - type: "scoring_calculated"
    score: "qSOFA"
    expected_value: 2
    at_time: "1h"

  - type: "escalation_timing"
    max_delay: "5min"  # From data availability to alert

  - type: "no_false_alarm"
    during: "0h-0.5h"  # Before sepsis criteria met
```

**Post-simulation report:**
- Alert timeline: when each alert was generated vs. when it should have been
- Agent accuracy: correct alerts / total alerts (precision), detected events / total events (recall)
- Timing metrics: median time from data availability to alert generation
- Agent utilization: which agents were spawned, active time, tool calls made
- Comparison metrics (if A/B): which configuration performed better and why

### 12.9 Implementation

**Key files:**

| File | Purpose |
|------|---------|
| `simulation/engine.py` | Core simulation engine (time management, event dispatch, physiology models) |
| `simulation/scenarios/` | YAML scenario definitions |
| `simulation/physiology.py` | Vital sign and lab value generation models |
| `simulation/synthetic_patients.py` | Synthea integration + LLM-generated patient creation |
| `simulation/assertions.py` | Test assertion framework |
| `simulation/reporting.py` | Post-simulation report generation |
| `frontend/src/app/simulation/page.tsx` | Simulation dashboard UI |
| `frontend/src/components/AgentGraph.tsx` | ReactFlow agent visualization |
| `frontend/src/components/VitalChart.tsx` | Real-time vital signs chart |
| `frontend/src/components/SimulationControls.tsx` | Play/pause/speed controls |
| `api/simulation.py` | Simulation API endpoints (start, pause, inject, checkpoint) |

**API endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/simulation/start` | POST | Start a simulation with scenario config |
| `/api/simulation/{id}/control` | POST | Play/pause/speed/rewind |
| `/api/simulation/{id}/inject` | POST | Inject event mid-simulation |
| `/api/simulation/{id}/checkpoint` | POST/GET | Save/load simulation state |
| `/api/simulation/{id}/status` | GET | Current simulation state + agent activity |
| `/api/simulation/{id}/report` | GET | Post-simulation analysis report |
| `/api/simulation/scenarios` | GET | List available scenarios |
| `/api/simulation/patients/generate` | POST | Generate synthetic patient |
| `/ws/simulation/{id}/stream` | WebSocket | Real-time vitals + agent activity stream |

---

## 13. Implementation Phases

### Phase 1: Foundation (Months 1-2)
- Extend FHIR tool handlers with inpatient resources (~35 new tools)
- Implement supervisor agent with patient state monitoring
- Build NEWS2 and qSOFA automated scoring
- Create clinician dashboard with patient census and vital signs
- Implement 4-tier alert classification
- Build simulation engine core: physiology models, scenario runner, synthetic patient generation
- Create simulation control panel UI (play/pause/speed/inject)

**Key files:** `fhir-mcp-server/src/handlers.py`, `agents/openrouter_orchestrator.py`, `api/main.py`, `frontend/src/app/page.tsx`, `simulation/engine.py`, `simulation/physiology.py`

### Phase 2: Specialist Agents + Simulation (Months 2-3)
- Agent spawning/retirement lifecycle
- 5 initial specialist agents (Cardiology, ID, Med Safety, Renal, Pulmonary)
- Knowledge base storage and RAG retrieval
- Sepsis detection pathway
- Condition-specific monitoring
- Agent visualization dashboard (ReactFlow graph, agent log stream)
- 8 pre-built simulation scenarios (sepsis, MI, DKA, CHF, AKI, PE, stroke, post-op)
- Scenario authoring format (YAML) with conditional branching

### Phase 3: Admin Interface, Trials & Testing (Months 3-4)
- Admin interface for agent template creation/editing
- Knowledge base upload and management
- Clinical trials matching agent
- Agent performance metrics dashboard
- Test assertion framework and automated scenario validation
- Post-simulation reporting (alert timing, agent accuracy, comparison metrics)
- LLM-generated patient journey creation
- A/B comparison mode for agent configurations

### Phase 4: Real-Time & Scale (Months 4-5)
- FHIR Subscription implementation
- WebSocket streaming for vital signs
- eCART ML scoring integration
- Discharge planning agent
- CMS core measure tracking
- Agent observability integration (LangFuse + OpenTelemetry tracing)
- Stress testing mode (multi-patient concurrent simulation)

### Phase 5: Hardening (Months 5-6)
- Comprehensive audit trails
- HIPAA compliance review
- Performance optimization
- Clinical validation with pilot users
- Simulation scenario library expansion and clinical review

---

## 14. Competitive Positioning

| Capability | Viz.ai | CLEW | Qventus | Epic Sepsis | **AgentEHR** |
|-----------|--------|------|---------|-------------|-------------|
| Multi-condition surveillance | No | Limited | No | Sepsis only | **Yes** |
| Multi-specialist reasoning | No | No | No | No | **Yes (agents)** |
| Care gap identification | No | No | No | No | **Yes** |
| Guideline adherence | No | No | No | No | **Yes (all)** |
| Escalation orchestration | Alert only | Alert only | Workflow | Alert | **Tiered + routing** |
| Clinical trials matching | No | No | No | No | **Yes** |
| Admin-configurable agents | No | No | Limited | No | **Yes** |
| FHIR-native | Limited | Limited | Limited | Proprietary | **Native** |
| Simulation & testing | No | No | No | No | **Yes (full engine)** |

---

## 15. Success Metrics

| Metric | Target | Current Baseline |
|--------|--------|-----------------|
| Alert actionability | >80% | 5% (industry) |
| Time to critical escalation | <5 min | N/A (new) |
| Sepsis bundle compliance | >85% | 48.9% (national avg) |
| Care gap identification | >90% | Manual only |
| False positive rate | <20% | ~95% (industry) |
| Clinical trials matched | >5 per 100 admissions | 0 (no system) |
| Simulation scenario coverage | >90% of common inpatient conditions | 0 (no system) |
| Agent behavior reproducibility | 100% deterministic replay | N/A (new) |

---

## 16. Decisions Needing User Input

| Decision | Options | Recommendation |
|----------|---------|---------------|
| Agent framework | Claude Agent SDK vs. LangGraph vs. Custom | Claude Agent SDK |
| Vector store | ChromaDB vs. Pinecone vs. pgvector | ChromaDB (local, free) |
| ML scoring (eCART) | Custom model vs. rule-based | Rule-based initially, ML Phase 4 |

---

## 17. Evidence Base

### Clinical Research (28 papers)
- Ronan et al. (2022) CDSS Impact. J Hosp Med. DOI: 10.1002/jhm.12825
- Linnen et al. (2019) Statistical EWS vs Aggregate-Weighted. DOI: 10.12788/jhm.3151
- Riahi et al. (2025) AI in Sepsis. Crit Care Res Pract. DOI: 10.1155/ccrp/9031137
- Larsen et al. (2024) Cost Savings AI Monitoring. DOI: 10.1111/aas.14525
- Cai et al. (2021) ML Eligibility Screening. DOI: 10.1002/acr2.11289
- [Full bibliography in research agent outputs]

### Simulation & Synthetic Data
- Synthea: Open-source synthetic patient generator (FHIR R4 output, 90+ disease modules)
- MIMIC-IV: 65,000+ ICU stays with high-fidelity vital signs (MIT/PhysioNet)
- eICU: 200,000+ ICU stays across 208 hospitals (Philips/MIT)
- BioGears: Open-source physiology engine with PK/PD drug modeling (DOD-funded)
- OpenICE: Integrated clinical environment for medical device interoperability (MDPnP)
- SynthAgent pattern: Multi-agent synthetic data refinement (2024)
- LangFuse: Open-source LLM observability and tracing platform
- Arize Phoenix: Open-source agent tracing with OpenTelemetry integration

### Market Analysis
- 20+ competitors analyzed (Viz.ai, Aidoc, CLEW, Qventus, Care.ai, Artisight, etc.)
- Agentic AI Healthcare market: $538.5M (2024), 45.56% CAGR
- Microsoft Healthcare Agent Orchestrator (2025): Multi-agent clinical orchestration validated

### Standards
- FHIR R4/R5 Subscriptions, SMART on FHIR, CDS Hooks, US Core/USCDI, Da Vinci ADT
- IEEE 11073 device communication, FHIR vital signs profiles
- FDA CDS guidance (2026 update), HIPAA Security Rule 2025, CMS Core Measures

### Active Clinical Trials
- NCT06694181: Safe AI-Enabled CDS at Penn Medicine (300K patients, 2025-2028)
- NCT06269198: WARD-CSS Continuous Monitoring (504 patients, RCT)
- NCT05480319: EDICARS ED Cardiac Arrest Prediction (2,010 patients)
