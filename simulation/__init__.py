"""AgentEHR Simulation Engine - Clinical inpatient journey simulation.

This package provides the core simulation framework for modeling inpatient
clinical journeys with realistic physiology, timed clinical events, and
AI agent integration points.

Core components:
- SimulationEngine: Orchestrates simulation lifecycle, event processing,
  and callback dispatch.
- PhysiologyModel: Generates clinically realistic vital signs with trends,
  interventions, and measurement noise.
- LabEngine: Produces lab results with condition-adjusted baselines and
  directional trending.

Data models:
- PatientProfile: Demographics, conditions, medications, baseline vitals.
- VitalSigns: A single set of vital sign measurements.
- LabResult: A single lab result with reference ranges and critical flags.
- SimulationEvent: A discrete timed event within a scenario.
- SimulationState: The complete mutable state of a running simulation.
- SimulationStatus: Lifecycle enum (CREATED, RUNNING, PAUSED, COMPLETED, FAILED).
- EventType: Event category enum.

Utilities:
- load_scenario_from_dict: Parse a scenario dictionary (e.g., from YAML)
  into a PatientProfile and event list.
- generate_baseline_vitals: Create age/sex-appropriate baseline vital signs.

Example usage::

    import asyncio
    from simulation import (
        SimulationEngine,
        load_scenario_from_dict,
    )

    async def main():
        engine = SimulationEngine()

        scenario = {
            "patient": {
                "id": "PT-001",
                "name": "Jane Doe",
                "age": 68,
                "sex": "F",
                "weight_kg": 70.0,
                "height_cm": 165.0,
                "conditions": ["Sepsis", "Pneumonia"],
                "medications": ["Lisinopril"],
                "allergies": ["Penicillin"],
                "baseline_vitals": {
                    "heart_rate": 95,
                    "systolic_bp": 100,
                    "diastolic_bp": 60,
                    "respiratory_rate": 24,
                    "spo2": 93,
                    "temperature": 101.8,
                }
            },
            "events": []
        }

        patient, events = load_scenario_from_dict(scenario)

        def on_event(sim_id, event):
            print(f"[{event.event_type.value}] {event.description}")

        engine.on_event(on_event)
        sim_id = await engine.create_simulation(patient, events)
        await engine.start(sim_id, speed=60.0)

    asyncio.run(main())
"""

# Models - data types
from simulation.models import (
    EventType,
    LabResult,
    PatientProfile,
    SimulationEvent,
    SimulationState,
    SimulationStatus,
    VitalSigns,
)

# Physiology - vital signs and lab generation
from simulation.physiology import (
    LabEngine,
    PhysiologyModel,
    generate_baseline_vitals,
)

# Engine - core simulation orchestration
from simulation.engine import (
    SimulationEngine,
    SimulationError,
    SimulationNotFoundError,
    SimulationStateError,
    load_scenario_from_dict,
)

__all__ = [
    # Engine
    "SimulationEngine",
    "SimulationError",
    "SimulationNotFoundError",
    "SimulationStateError",
    "load_scenario_from_dict",
    # Physiology
    "PhysiologyModel",
    "LabEngine",
    "generate_baseline_vitals",
    # Models
    "EventType",
    "LabResult",
    "PatientProfile",
    "SimulationEvent",
    "SimulationState",
    "SimulationStatus",
    "VitalSigns",
]
