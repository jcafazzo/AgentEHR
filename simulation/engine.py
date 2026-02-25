"""Core simulation engine for running clinical inpatient journey simulations.

The SimulationEngine manages the lifecycle of one or more concurrent
simulations, each tracking a virtual patient through a timed sequence of
clinical events. The engine is built on asyncio and supports:

- Real-time and accelerated playback (configurable speed multiplier).
- Event-driven architecture with registered callbacks.
- Checkpoint save/restore for "what-if" scenario branching.
- Runtime event injection for interactive use.
- Conditional branching within scenario event sequences.

Usage::

    engine = SimulationEngine()
    sim_id = await engine.create_simulation(patient, events)
    engine.on_event(my_callback)
    await engine.start(sim_id, speed=10.0)
"""

import asyncio
import copy
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from simulation.models import (
    EventType,
    LabResult,
    PatientProfile,
    SimulationEvent,
    SimulationState,
    SimulationStatus,
    VitalSigns,
)
from simulation.physiology import LabEngine, PhysiologyModel

logger = logging.getLogger(__name__)

# Default tick interval in simulation-seconds between vitals generation
DEFAULT_VITALS_INTERVAL_SECONDS = 300  # 5 minutes of simulation time
# How often (in real seconds) the engine checks for events between vitals
ENGINE_TICK_REAL_SECONDS = 0.1


class SimulationError(Exception):
    """Base exception for simulation engine errors."""
    pass


class SimulationNotFoundError(SimulationError):
    """Raised when an operation references a nonexistent simulation."""
    pass


class SimulationStateError(SimulationError):
    """Raised when an operation is invalid for the current simulation state."""
    pass


class SimulationEngine:
    """Core engine for running clinical simulations.

    The engine maintains a registry of simulation states indexed by ID.
    Each running simulation has its own asyncio task executing the main
    loop, which generates vitals, processes timed events, and fires
    callbacks to registered listeners.

    Attributes:
        vitals_interval: Simulation-time interval between vital sign
            generation cycles, in seconds. Default is 300 (5 minutes).
    """

    def __init__(self, vitals_interval: int = DEFAULT_VITALS_INTERVAL_SECONDS) -> None:
        self._simulations: dict[str, SimulationState] = {}
        self._callbacks: list[Callable] = []
        self._physiology_models: dict[str, PhysiologyModel] = {}
        self._lab_engines: dict[str, LabEngine] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._pause_events: dict[str, asyncio.Event] = {}
        self.vitals_interval = vitals_interval

    # ------------------------------------------------------------------
    # Simulation lifecycle
    # ------------------------------------------------------------------

    async def create_simulation(
        self,
        patient: PatientProfile,
        scenario_events: list[SimulationEvent] | None = None,
    ) -> str:
        """Create a new simulation instance.

        Initializes the physiology model, generates baseline labs, records
        the admission event, and stores the simulation in the registry.

        Args:
            patient: The patient profile for this simulation.
            scenario_events: Optional pre-scripted events to schedule.

        Returns:
            The unique simulation_id string.
        """
        simulation_id = str(uuid.uuid4())

        # Sort scenario events by time offset
        pending = sorted(scenario_events or [], key=lambda e: e.time_offset)

        state = SimulationState(
            simulation_id=simulation_id,
            status=SimulationStatus.CREATED,
            patient=patient,
            current_time=timedelta(0),
            speed_multiplier=1.0,
            events_pending=pending,
        )

        # Initialize physiology model from patient baseline
        physiology = PhysiologyModel(patient)
        lab_engine = LabEngine()

        # Generate baseline vitals and labs
        baseline_vitals = physiology.generate_vitals(timedelta(0), noise=False)
        state.vitals_history.append(baseline_vitals)

        baseline_labs = lab_engine.generate_baseline_labs(patient)
        state.lab_history.extend(baseline_labs)

        # Record admission event
        admission_event = SimulationEvent(
            time_offset=timedelta(0),
            event_type=EventType.ADMISSION,
            data={
                "patient_id": patient.id,
                "patient_name": patient.name,
                "conditions": patient.conditions,
                "medications": patient.medications,
                "baseline_vitals": baseline_vitals.to_dict(),
                "baseline_labs": [lab.to_dict() for lab in baseline_labs],
            },
            description=f"Patient {patient.name} admitted with {', '.join(patient.conditions)}",
        )
        state.events_processed.append(admission_event)

        # Store everything
        self._simulations[simulation_id] = state
        self._physiology_models[simulation_id] = physiology
        self._lab_engines[simulation_id] = lab_engine
        self._pause_events[simulation_id] = asyncio.Event()
        self._pause_events[simulation_id].set()  # Not paused initially

        logger.info(
            "Created simulation %s for patient %s (%s)",
            simulation_id, patient.name, patient.id,
        )

        # Fire admission callback
        await self._fire_callbacks(simulation_id, admission_event)

        return simulation_id

    async def start(self, simulation_id: str, speed: float = 1.0) -> None:
        """Start running a simulation.

        Launches the async run loop as a background task. The simulation
        will generate vitals at regular intervals and process scheduled
        events as their time offsets are reached.

        Args:
            simulation_id: ID of the simulation to start.
            speed: Speed multiplier (1.0 = real-time, 10.0 = 10x, etc.).

        Raises:
            SimulationNotFoundError: If the simulation ID does not exist.
            SimulationStateError: If the simulation is not in CREATED state.
        """
        state = self._get_state(simulation_id)

        if state.status not in (SimulationStatus.CREATED, SimulationStatus.PAUSED):
            raise SimulationStateError(
                f"Cannot start simulation in '{state.status.value}' state. "
                f"Must be 'created' or 'paused'."
            )

        state.speed_multiplier = speed
        state.status = SimulationStatus.RUNNING
        self._pause_events[simulation_id].set()

        # Launch run loop if not already running
        if simulation_id not in self._tasks or self._tasks[simulation_id].done():
            task = asyncio.create_task(
                self._run_loop(simulation_id),
                name=f"sim-{simulation_id[:8]}",
            )
            self._tasks[simulation_id] = task
            logger.info("Started simulation %s at %.1fx speed", simulation_id, speed)

    async def pause(self, simulation_id: str) -> None:
        """Pause a running simulation.

        The run loop will block at its next tick until resumed.

        Args:
            simulation_id: ID of the simulation to pause.

        Raises:
            SimulationNotFoundError: If the simulation ID does not exist.
            SimulationStateError: If the simulation is not currently running.
        """
        state = self._get_state(simulation_id)

        if state.status != SimulationStatus.RUNNING:
            raise SimulationStateError(
                f"Cannot pause simulation in '{state.status.value}' state."
            )

        state.status = SimulationStatus.PAUSED
        self._pause_events[simulation_id].clear()
        logger.info("Paused simulation %s at t=%s", simulation_id, state.current_time)

    async def resume(self, simulation_id: str) -> None:
        """Resume a paused simulation.

        Args:
            simulation_id: ID of the simulation to resume.

        Raises:
            SimulationNotFoundError: If the simulation ID does not exist.
            SimulationStateError: If the simulation is not currently paused.
        """
        state = self._get_state(simulation_id)

        if state.status != SimulationStatus.PAUSED:
            raise SimulationStateError(
                f"Cannot resume simulation in '{state.status.value}' state."
            )

        state.status = SimulationStatus.RUNNING
        self._pause_events[simulation_id].set()
        logger.info("Resumed simulation %s at t=%s", simulation_id, state.current_time)

    async def stop(self, simulation_id: str) -> None:
        """Stop and complete a simulation.

        Cancels the run loop task and sets the status to COMPLETED.

        Args:
            simulation_id: ID of the simulation to stop.

        Raises:
            SimulationNotFoundError: If the simulation ID does not exist.
        """
        state = self._get_state(simulation_id)

        state.status = SimulationStatus.COMPLETED

        # Unblock pause if paused, so the task can exit
        self._pause_events[simulation_id].set()

        # Cancel the run loop task
        task = self._tasks.get(simulation_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info("Stopped simulation %s at t=%s", simulation_id, state.current_time)

    async def set_speed(self, simulation_id: str, speed: float) -> None:
        """Change the simulation speed multiplier.

        Args:
            simulation_id: ID of the simulation.
            speed: New speed multiplier. Must be positive.

        Raises:
            SimulationNotFoundError: If the simulation ID does not exist.
            ValueError: If speed is not positive.
        """
        if speed <= 0:
            raise ValueError(f"Speed multiplier must be positive, got {speed}")

        state = self._get_state(simulation_id)
        old_speed = state.speed_multiplier
        state.speed_multiplier = speed
        logger.info(
            "Changed speed for simulation %s: %.1fx -> %.1fx",
            simulation_id, old_speed, speed,
        )

    async def inject_event(self, simulation_id: str, event: SimulationEvent) -> None:
        """Inject an event into a running or paused simulation.

        The event is inserted into the pending queue in chronological order.
        If the event's time_offset is at or before the current simulation
        time, it will be processed on the next tick.

        Args:
            simulation_id: ID of the simulation.
            event: The event to inject.

        Raises:
            SimulationNotFoundError: If the simulation ID does not exist.
        """
        state = self._get_state(simulation_id)

        # Insert in sorted position
        inserted = False
        for i, pending in enumerate(state.events_pending):
            if event.time_offset < pending.time_offset:
                state.events_pending.insert(i, event)
                inserted = True
                break
        if not inserted:
            state.events_pending.append(event)

        logger.info(
            "Injected event '%s' at t=%s into simulation %s",
            event.event_type.value, event.time_offset, simulation_id,
        )

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    async def save_checkpoint(self, simulation_id: str, name: str) -> dict[str, Any]:
        """Save the current simulation state as a named checkpoint.

        The entire state is deep-copied, allowing later restoration without
        affecting the ongoing simulation.

        Args:
            simulation_id: ID of the simulation.
            name: Name for this checkpoint (e.g., "before_antibiotics").

        Returns:
            Dictionary with checkpoint metadata.

        Raises:
            SimulationNotFoundError: If the simulation ID does not exist.
        """
        state = self._get_state(simulation_id)

        checkpoint = {
            "state": copy.deepcopy(state),
            "physiology": copy.deepcopy(self._physiology_models[simulation_id]),
            "lab_engine": copy.deepcopy(self._lab_engines[simulation_id]),
            "saved_at": datetime.now().isoformat(),
            "simulation_time": state.current_time.total_seconds(),
        }
        state.checkpoints[name] = checkpoint

        logger.info(
            "Saved checkpoint '%s' for simulation %s at t=%s",
            name, simulation_id, state.current_time,
        )

        return {
            "name": name,
            "simulation_id": simulation_id,
            "simulation_time_seconds": state.current_time.total_seconds(),
            "saved_at": checkpoint["saved_at"],
        }

    async def load_checkpoint(self, simulation_id: str, name: str) -> None:
        """Restore a simulation to a previously saved checkpoint.

        The simulation must be paused or completed before loading a checkpoint.
        After loading, the simulation status is set to PAUSED.

        Args:
            simulation_id: ID of the simulation.
            name: Name of the checkpoint to restore.

        Raises:
            SimulationNotFoundError: If the simulation ID does not exist.
            SimulationStateError: If the simulation is currently running.
            KeyError: If the checkpoint name does not exist.
        """
        state = self._get_state(simulation_id)

        if state.status == SimulationStatus.RUNNING:
            raise SimulationStateError(
                "Cannot load checkpoint while simulation is running. Pause it first."
            )

        if name not in state.checkpoints:
            available = list(state.checkpoints.keys())
            raise KeyError(
                f"Checkpoint '{name}' not found. Available: {available}"
            )

        checkpoint = state.checkpoints[name]
        restored_state: SimulationState = copy.deepcopy(checkpoint["state"])
        restored_state.status = SimulationStatus.PAUSED

        # Preserve checkpoint registry from current state (so we don't lose checkpoints)
        restored_state.checkpoints = state.checkpoints

        self._simulations[simulation_id] = restored_state
        self._physiology_models[simulation_id] = copy.deepcopy(checkpoint["physiology"])
        self._lab_engines[simulation_id] = copy.deepcopy(checkpoint["lab_engine"])

        logger.info(
            "Loaded checkpoint '%s' for simulation %s (restored to t=%s)",
            name, simulation_id, restored_state.current_time,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def get_status(self, simulation_id: str) -> SimulationState:
        """Get the current simulation state.

        Args:
            simulation_id: ID of the simulation.

        Returns:
            The SimulationState instance (direct reference, not a copy).

        Raises:
            SimulationNotFoundError: If the simulation ID does not exist.
        """
        return self._get_state(simulation_id)

    def list_simulations(self) -> list[dict[str, Any]]:
        """Return summary information for all simulations.

        Returns:
            List of dictionaries with simulation summaries.
        """
        return [
            {
                "simulation_id": sid,
                "patient_name": state.patient.name,
                "status": state.status.value,
                "current_time_seconds": state.current_time.total_seconds(),
                "speed": state.speed_multiplier,
            }
            for sid, state in self._simulations.items()
        ]

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_event(self, callback: Callable) -> None:
        """Register a callback to be invoked when simulation events occur.

        The callback signature should be:
            async def callback(simulation_id: str, event: SimulationEvent) -> None
        or synchronous:
            def callback(simulation_id: str, event: SimulationEvent) -> None

        Args:
            callback: Function to call on each event.
        """
        self._callbacks.append(callback)
        logger.debug("Registered event callback: %s", callback.__name__)

    def remove_callback(self, callback: Callable) -> bool:
        """Remove a previously registered callback.

        Args:
            callback: The callback function to remove.

        Returns:
            True if the callback was found and removed.
        """
        try:
            self._callbacks.remove(callback)
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Main simulation loop
    # ------------------------------------------------------------------

    async def _run_loop(self, simulation_id: str) -> None:
        """Main simulation loop that processes events in time order.

        On each tick the loop:
        1. Waits for the pause event (blocks if paused).
        2. Advances simulation time by one vitals interval.
        3. Generates new vital signs from the physiology model.
        4. Checks for and processes any pending events at or before current time.
        5. Fires callbacks for the vitals update event.
        6. Sleeps based on the speed multiplier.

        The loop runs until the simulation is completed/failed, there are no
        more pending events and a discharge has occurred, or the task is cancelled.
        """
        state = self._simulations[simulation_id]
        physiology = self._physiology_models[simulation_id]

        logger.info("Simulation loop started for %s", simulation_id)

        try:
            while state.status == SimulationStatus.RUNNING:
                # Block if paused
                await self._pause_events[simulation_id].wait()

                # Check if we were stopped while paused
                if state.status != SimulationStatus.RUNNING:
                    break

                # Advance simulation time
                sim_time_step = timedelta(seconds=self.vitals_interval)
                state.current_time += sim_time_step

                # --- 1. Generate vital signs ---
                vitals = physiology.generate_vitals(state.current_time)
                state.vitals_history.append(vitals)

                vitals_event = SimulationEvent(
                    time_offset=state.current_time,
                    event_type=EventType.VITALS_UPDATE,
                    data=vitals.to_dict(),
                    description=f"Vitals: HR {vitals.heart_rate}, BP {vitals.systolic_bp}/{vitals.diastolic_bp}, "
                                f"RR {vitals.respiratory_rate}, SpO2 {vitals.spo2}, T {vitals.temperature}",
                )
                await self._fire_callbacks(simulation_id, vitals_event)

                # --- 2. Check for and process pending events ---
                events_to_process: list[SimulationEvent] = []
                remaining: list[SimulationEvent] = []

                for event in state.events_pending:
                    if event.time_offset <= state.current_time:
                        # Filter by branch: only process events on the current branch
                        # Events with no branch specification run on all branches
                        if event.branch is None or event.branch == state.current_branch:
                            events_to_process.append(event)
                        else:
                            # Event is for a different branch; discard it
                            pass
                    else:
                        remaining.append(event)

                state.events_pending = remaining

                # Process events in chronological order
                events_to_process.sort(key=lambda e: e.time_offset)
                for event in events_to_process:
                    await self._process_event(state, event)
                    state.events_processed.append(event)
                    await self._fire_callbacks(simulation_id, event)

                # --- 3. Check alert conditions ---
                await self._check_alerts(simulation_id, vitals)

                # --- 4. Check for completion ---
                if self._is_complete(state):
                    state.status = SimulationStatus.COMPLETED
                    logger.info(
                        "Simulation %s completed at t=%s",
                        simulation_id, state.current_time,
                    )
                    break

                # --- 5. Sleep based on speed multiplier ---
                # Real-time sleep = sim_time_step / speed_multiplier
                real_sleep = self.vitals_interval / state.speed_multiplier
                # Cap minimum sleep to prevent CPU spinning
                real_sleep = max(real_sleep, ENGINE_TICK_REAL_SECONDS)
                await asyncio.sleep(real_sleep)

        except asyncio.CancelledError:
            logger.info("Simulation loop cancelled for %s", simulation_id)
            raise
        except Exception:
            state.status = SimulationStatus.FAILED
            logger.exception("Simulation %s failed with unexpected error", simulation_id)
            raise

    async def _process_event(self, state: SimulationState, event: SimulationEvent) -> None:
        """Process a single simulation event and apply its effects.

        Handles each event type by updating the simulation state appropriately:
        - INTERVENTION: applies the intervention to the physiology model.
        - LAB_ORDER: schedules a future LAB_RESULT event with turnaround time.
        - LAB_RESULT: records the result in lab history.
        - MEDICATION_ORDER / MEDICATION_ADMIN: tracks in active interventions.
        - CLINICAL_EVENT: logged and may contain trend modifications.
        - TRANSFER: updates location metadata.
        - DISCHARGE: marks simulation for completion.
        - ALERT_GENERATED: stores alert.
        - AGENT_SPAWNED / AGENT_RETIRED: manages agent registry.

        Conditional branching: if the event has a condition, it is evaluated
        against the current state. If true, the current_branch is switched.

        Args:
            state: The current simulation state.
            event: The event to process.
        """
        simulation_id = state.simulation_id
        physiology = self._physiology_models.get(simulation_id)
        lab_engine = self._lab_engines.get(simulation_id)

        logger.info(
            "Processing event [%s] at t=%s: %s",
            event.event_type.value, event.time_offset, event.description,
        )

        # --- Handle conditional branching ---
        if event.condition is not None:
            condition_met = self._evaluate_condition(state, event.condition)
            if condition_met and event.branch is not None:
                old_branch = state.current_branch
                state.current_branch = event.branch
                logger.info(
                    "Branch switch: '%s' -> '%s' (condition: %s)",
                    old_branch, event.branch, event.condition,
                )

        # --- Process by event type ---
        event_type = event.event_type

        if event_type == EventType.INTERVENTION:
            if physiology is not None:
                intervention_type = event.data.get("intervention_type", "")
                params = event.data.get("params", {})
                physiology.apply_intervention(
                    intervention_type, params, start_time=state.current_time,
                )
                state.active_interventions.append({
                    "type": intervention_type,
                    "params": params,
                    "started_at": state.current_time.total_seconds(),
                })

                # Also apply any trend modifiers bundled with the intervention
                trends = event.data.get("trends", [])
                for trend in trends:
                    physiology.add_trend(
                        vital_name=trend["vital_name"],
                        rate_per_hour=trend["rate_per_hour"],
                        duration_hours=trend["duration_hours"],
                        start_time=state.current_time,
                    )

        elif event_type == EventType.LAB_ORDER:
            # Schedule a lab result event with realistic turnaround time
            lab_names = event.data.get("labs", [])
            turnaround_minutes = event.data.get("turnaround_minutes", 45)
            result_time = state.current_time + timedelta(minutes=turnaround_minutes)

            for lab_name in lab_names:
                # Determine value: use trending if available, else current state
                if lab_engine is not None and lab_name in lab_engine._trend_state:
                    value = lab_engine._trend_state[lab_name]
                    # Apply any directional trends from event data
                    direction = event.data.get("direction")
                    rate = event.data.get("rate_per_hour", 0)
                    hours_elapsed = turnaround_minutes / 60.0
                    if direction and rate:
                        value = lab_engine.trend_lab(lab_name, value, direction, rate, hours_elapsed)
                else:
                    value = event.data.get("value", 0)

                lab_result_event = SimulationEvent(
                    time_offset=result_time,
                    event_type=EventType.LAB_RESULT,
                    data={"lab_name": lab_name, "value": value},
                    description=f"Lab result: {lab_name} = {value}",
                )
                # Insert into pending queue
                await self.inject_event(state.simulation_id, lab_result_event)

        elif event_type == EventType.LAB_RESULT:
            if lab_engine is not None:
                lab_name = event.data.get("lab_name", "")
                value = event.data.get("value", 0)
                result = lab_engine.generate_result(lab_name, value)
                state.lab_history.append(result)

                if result.is_critical:
                    alert = {
                        "type": "critical_lab",
                        "lab_name": lab_name,
                        "value": value,
                        "unit": result.unit,
                        "time": state.current_time.total_seconds(),
                        "message": f"CRITICAL: {lab_name} = {value} {result.unit}",
                    }
                    state.alerts_generated.append(alert)
                    logger.warning("Critical lab value: %s = %s %s", lab_name, value, result.unit)

        elif event_type == EventType.MEDICATION_ORDER:
            state.active_interventions.append({
                "type": "medication",
                "medication": event.data.get("medication", ""),
                "dose": event.data.get("dose", ""),
                "route": event.data.get("route", ""),
                "ordered_at": state.current_time.total_seconds(),
            })

        elif event_type == EventType.MEDICATION_ADMIN:
            # If the medication has physiological effects, apply them
            med_name = event.data.get("medication", "").lower()
            if physiology is not None:
                # Map common medications to intervention types
                if any(term in med_name for term in ("norepinephrine", "vasopressin", "phenylephrine", "dopamine")):
                    physiology.apply_intervention(
                        "vasopressor_start",
                        event.data.get("params", {}),
                        start_time=state.current_time,
                    )
                elif any(term in med_name for term in ("acetaminophen", "ibuprofen", "tylenol", "motrin")):
                    physiology.apply_intervention(
                        "antipyretic", {}, start_time=state.current_time,
                    )
                elif "insulin" in med_name:
                    physiology.apply_intervention(
                        "insulin_drip",
                        event.data.get("params", {}),
                        start_time=state.current_time,
                    )

        elif event_type == EventType.CLINICAL_EVENT:
            # Clinical events may carry trend modifications
            if physiology is not None:
                trends = event.data.get("trends", [])
                for trend in trends:
                    physiology.add_trend(
                        vital_name=trend["vital_name"],
                        rate_per_hour=trend["rate_per_hour"],
                        duration_hours=trend["duration_hours"],
                        start_time=state.current_time,
                    )

        elif event_type == EventType.TRANSFER:
            # Record transfer metadata
            logger.info(
                "Patient transferred: %s -> %s",
                event.data.get("from_unit", "unknown"),
                event.data.get("to_unit", "unknown"),
            )

        elif event_type == EventType.DISCHARGE:
            state.status = SimulationStatus.COMPLETED
            logger.info("Patient discharged at t=%s", state.current_time)

        elif event_type == EventType.ALERT_GENERATED:
            state.alerts_generated.append({
                "type": event.data.get("alert_type", "generic"),
                "message": event.data.get("message", ""),
                "severity": event.data.get("severity", "warning"),
                "time": state.current_time.total_seconds(),
            })

        elif event_type == EventType.AGENT_SPAWNED:
            agent_info = {
                "agent_id": event.data.get("agent_id", str(uuid.uuid4())),
                "agent_type": event.data.get("agent_type", "generic"),
                "spawned_at": state.current_time.total_seconds(),
            }
            state.agents_active.append(agent_info)
            logger.info("Agent spawned: %s", agent_info)

        elif event_type == EventType.AGENT_RETIRED:
            agent_id = event.data.get("agent_id", "")
            state.agents_active = [
                a for a in state.agents_active if a.get("agent_id") != agent_id
            ]
            logger.info("Agent retired: %s", agent_id)

        elif event_type == EventType.ADMISSION:
            # Admission is typically processed at creation; log if re-encountered
            logger.debug("Admission event processed at t=%s", state.current_time)

        else:
            logger.warning("Unhandled event type: %s", event_type.value)

    # ------------------------------------------------------------------
    # Alert checking
    # ------------------------------------------------------------------

    async def _check_alerts(self, simulation_id: str, vitals: VitalSigns) -> None:
        """Check current vitals against alert thresholds.

        Generates alerts for clinically concerning vital sign values.
        These thresholds represent typical hospital alert criteria.
        """
        state = self._simulations[simulation_id]
        alerts: list[dict[str, Any]] = []

        # Heart rate alerts
        if vitals.heart_rate > 130:
            alerts.append({
                "type": "vital_alert",
                "vital": "heart_rate",
                "value": vitals.heart_rate,
                "severity": "critical",
                "message": f"Tachycardia: HR {vitals.heart_rate} bpm",
            })
        elif vitals.heart_rate < 50:
            alerts.append({
                "type": "vital_alert",
                "vital": "heart_rate",
                "value": vitals.heart_rate,
                "severity": "critical",
                "message": f"Bradycardia: HR {vitals.heart_rate} bpm",
            })

        # Blood pressure alerts
        map_value = vitals.mean_arterial_pressure
        if map_value < 65:
            alerts.append({
                "type": "vital_alert",
                "vital": "mean_arterial_pressure",
                "value": map_value,
                "severity": "critical",
                "message": f"Hypotension: MAP {map_value:.0f} mmHg",
            })
        elif vitals.systolic_bp > 180:
            alerts.append({
                "type": "vital_alert",
                "vital": "systolic_bp",
                "value": vitals.systolic_bp,
                "severity": "warning",
                "message": f"Hypertensive: SBP {vitals.systolic_bp} mmHg",
            })

        # SpO2 alerts
        if vitals.spo2 < 90:
            alerts.append({
                "type": "vital_alert",
                "vital": "spo2",
                "value": vitals.spo2,
                "severity": "critical",
                "message": f"Hypoxemia: SpO2 {vitals.spo2}%",
            })
        elif vitals.spo2 < 94:
            alerts.append({
                "type": "vital_alert",
                "vital": "spo2",
                "value": vitals.spo2,
                "severity": "warning",
                "message": f"Low SpO2: {vitals.spo2}%",
            })

        # Temperature alerts
        if vitals.temperature > 101.3:
            alerts.append({
                "type": "vital_alert",
                "vital": "temperature",
                "value": vitals.temperature,
                "severity": "warning",
                "message": f"Fever: {vitals.temperature} F",
            })
        elif vitals.temperature < 95.0:
            alerts.append({
                "type": "vital_alert",
                "vital": "temperature",
                "value": vitals.temperature,
                "severity": "critical",
                "message": f"Hypothermia: {vitals.temperature} F",
            })

        # Respiratory rate alerts
        if vitals.respiratory_rate > 30:
            alerts.append({
                "type": "vital_alert",
                "vital": "respiratory_rate",
                "value": vitals.respiratory_rate,
                "severity": "warning",
                "message": f"Tachypnea: RR {vitals.respiratory_rate}",
            })

        # Store alerts and fire callbacks
        for alert in alerts:
            alert["time"] = state.current_time.total_seconds()
            state.alerts_generated.append(alert)
            alert_event = SimulationEvent(
                time_offset=state.current_time,
                event_type=EventType.ALERT_GENERATED,
                data=alert,
                description=alert["message"],
            )
            await self._fire_callbacks(simulation_id, alert_event)

    # ------------------------------------------------------------------
    # Condition evaluation
    # ------------------------------------------------------------------

    def _evaluate_condition(self, state: SimulationState, condition: str) -> bool:
        """Evaluate a condition string against the current simulation state.

        Supports a simple domain-specific condition language:
        - "hr > 120": Check latest HR against threshold.
        - "sbp < 90": Check latest systolic BP.
        - "spo2 < 92": Check latest SpO2.
        - "temp > 101.5": Check latest temperature.
        - "lactate > 4.0": Check latest lactate lab.
        - "map < 65": Check mean arterial pressure.
        - "branch == main": Check current branch name.

        Args:
            state: Current simulation state.
            condition: Condition expression string.

        Returns:
            True if the condition is met, False otherwise.
        """
        try:
            parts = condition.strip().split()
            if len(parts) != 3:
                logger.warning("Malformed condition '%s'; expected 'param op value'", condition)
                return False

            param, operator, threshold_str = parts

            # Resolve the parameter value
            vitals = state.latest_vitals
            labs = state.latest_labs

            value: float | str | None = None

            if param == "branch":
                # String comparison for branch
                if operator == "==":
                    return state.current_branch == threshold_str
                elif operator == "!=":
                    return state.current_branch != threshold_str
                return False

            if vitals is not None:
                vital_map: dict[str, float] = {
                    "hr": vitals.heart_rate,
                    "heart_rate": vitals.heart_rate,
                    "sbp": vitals.systolic_bp,
                    "systolic_bp": vitals.systolic_bp,
                    "dbp": vitals.diastolic_bp,
                    "diastolic_bp": vitals.diastolic_bp,
                    "rr": vitals.respiratory_rate,
                    "respiratory_rate": vitals.respiratory_rate,
                    "spo2": vitals.spo2,
                    "temp": vitals.temperature,
                    "temperature": vitals.temperature,
                    "map": vitals.mean_arterial_pressure,
                }
                if param in vital_map:
                    value = vital_map[param]

            # Check labs if not found in vitals
            if value is None and param in labs:
                value = labs[param].value

            if value is None:
                logger.warning("Cannot resolve parameter '%s' for condition evaluation", param)
                return False

            threshold = float(threshold_str)

            if operator == ">":
                return value > threshold
            elif operator == "<":
                return value < threshold
            elif operator == ">=":
                return value >= threshold
            elif operator == "<=":
                return value <= threshold
            elif operator == "==":
                return abs(value - threshold) < 0.01
            elif operator == "!=":
                return abs(value - threshold) >= 0.01
            else:
                logger.warning("Unknown operator '%s' in condition", operator)
                return False

        except Exception:
            logger.exception("Error evaluating condition '%s'", condition)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_state(self, simulation_id: str) -> SimulationState:
        """Retrieve simulation state, raising if not found."""
        state = self._simulations.get(simulation_id)
        if state is None:
            raise SimulationNotFoundError(
                f"No simulation found with ID '{simulation_id}'"
            )
        return state

    def _is_complete(self, state: SimulationState) -> bool:
        """Check whether a simulation has reached a natural completion point.

        A simulation is considered complete if:
        - Status has been set to COMPLETED (e.g., by a discharge event).
        - All pending events have been processed and the last processed
          event was a DISCHARGE.
        """
        if state.status == SimulationStatus.COMPLETED:
            return True

        if (
            not state.events_pending
            and state.events_processed
            and state.events_processed[-1].event_type == EventType.DISCHARGE
        ):
            return True

        return False

    async def _fire_callbacks(self, simulation_id: str, event: SimulationEvent) -> None:
        """Invoke all registered callbacks with the given event.

        Callbacks may be synchronous or asynchronous. Exceptions in callbacks
        are logged but do not interrupt the simulation.
        """
        for callback in self._callbacks:
            try:
                result = callback(simulation_id, event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "Error in event callback %s for event %s",
                    callback.__name__, event.event_type.value,
                )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Gracefully shut down all running simulations.

        Cancels all run loop tasks and sets remaining running simulations
        to COMPLETED status.
        """
        logger.info("Shutting down simulation engine (%d simulations)", len(self._simulations))

        for simulation_id, task in self._tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            state = self._simulations.get(simulation_id)
            if state and state.status == SimulationStatus.RUNNING:
                state.status = SimulationStatus.COMPLETED

        self._tasks.clear()
        logger.info("Simulation engine shut down complete")


# ---------------------------------------------------------------------------
# Scenario loader utility
# ---------------------------------------------------------------------------

def load_scenario_from_dict(scenario: dict[str, Any]) -> tuple[PatientProfile, list[SimulationEvent]]:
    """Load a simulation scenario from a dictionary (e.g., parsed from YAML).

    Expected dictionary structure::

        {
            "patient": {
                "id": "PT-001",
                "name": "John Doe",
                "age": 68,
                "sex": "M",
                "weight_kg": 82.0,
                "height_cm": 175.0,
                "conditions": ["Sepsis", "Pneumonia"],
                "medications": ["Lisinopril"],
                "allergies": ["Penicillin"],
                "baseline_vitals": {
                    "heart_rate": 92,
                    "systolic_bp": 105,
                    "diastolic_bp": 62,
                    "respiratory_rate": 22,
                    "spo2": 93,
                    "temperature": 101.8,
                    "supplemental_o2": false
                }
            },
            "events": [
                {
                    "time_offset_minutes": 30,
                    "event_type": "lab_order",
                    "data": {"labs": ["Lactate", "WBC"]},
                    "description": "Order repeat lactate and CBC",
                    "condition": null,
                    "branch": null
                },
                ...
            ]
        }

    Args:
        scenario: Dictionary with "patient" and "events" keys.

    Returns:
        Tuple of (PatientProfile, list of SimulationEvents).

    Raises:
        KeyError: If required keys are missing.
        ValueError: If data values are invalid.
    """
    # --- Parse patient ---
    patient_data = scenario["patient"]
    vitals_data = patient_data["baseline_vitals"]

    baseline_vitals = VitalSigns(
        heart_rate=float(vitals_data["heart_rate"]),
        systolic_bp=float(vitals_data["systolic_bp"]),
        diastolic_bp=float(vitals_data["diastolic_bp"]),
        respiratory_rate=float(vitals_data["respiratory_rate"]),
        spo2=float(vitals_data["spo2"]),
        temperature=float(vitals_data["temperature"]),
        supplemental_o2=bool(vitals_data.get("supplemental_o2", False)),
    )

    patient = PatientProfile(
        id=str(patient_data["id"]),
        name=str(patient_data["name"]),
        age=int(patient_data["age"]),
        sex=str(patient_data["sex"]),
        weight_kg=float(patient_data["weight_kg"]),
        height_cm=float(patient_data["height_cm"]),
        conditions=list(patient_data.get("conditions", [])),
        medications=list(patient_data.get("medications", [])),
        allergies=list(patient_data.get("allergies", [])),
        baseline_vitals=baseline_vitals,
    )

    # --- Parse events ---
    events: list[SimulationEvent] = []
    for event_data in scenario.get("events", []):
        # Support both minutes and seconds for time offset
        if "time_offset_minutes" in event_data:
            time_offset = timedelta(minutes=float(event_data["time_offset_minutes"]))
        elif "time_offset_seconds" in event_data:
            time_offset = timedelta(seconds=float(event_data["time_offset_seconds"]))
        else:
            raise ValueError(
                "Each event must have 'time_offset_minutes' or 'time_offset_seconds'"
            )

        # Resolve event type
        event_type_str = event_data["event_type"]
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            # Try uppercase enum name as fallback
            try:
                event_type = EventType[event_type_str.upper()]
            except KeyError:
                raise ValueError(f"Unknown event type: '{event_type_str}'")

        event = SimulationEvent(
            time_offset=time_offset,
            event_type=event_type,
            data=dict(event_data.get("data", {})),
            description=str(event_data.get("description", "")),
            condition=event_data.get("condition"),
            branch=event_data.get("branch"),
        )
        events.append(event)

    # Sort events chronologically
    events.sort(key=lambda e: e.time_offset)

    logger.info(
        "Loaded scenario: patient '%s' with %d events",
        patient.name, len(events),
    )

    return patient, events
