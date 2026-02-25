"""Data models and types for the clinical simulation engine.

Defines the core data structures used throughout the simulation system,
including patient profiles, vital signs, lab results, simulation events,
and the overall simulation state container.
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
from typing import Any


class SimulationStatus(Enum):
    """Lifecycle states for a simulation instance."""
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(Enum):
    """Categories of events that can occur during a simulation."""
    VITALS_UPDATE = "vitals_update"
    LAB_RESULT = "lab_result"
    LAB_ORDER = "lab_order"
    MEDICATION_ADMIN = "medication_admin"
    MEDICATION_ORDER = "medication_order"
    CLINICAL_EVENT = "clinical_event"
    TRANSFER = "transfer"
    ADMISSION = "admission"
    DISCHARGE = "discharge"
    INTERVENTION = "intervention"
    ALERT_GENERATED = "alert_generated"
    AGENT_SPAWNED = "agent_spawned"
    AGENT_RETIRED = "agent_retired"


@dataclass
class VitalSigns:
    """A single set of vital sign measurements.

    All values use standard clinical units:
    - heart_rate: beats per minute (bpm)
    - systolic_bp / diastolic_bp: millimeters of mercury (mmHg)
    - respiratory_rate: breaths per minute
    - spo2: peripheral oxygen saturation (percentage)
    - temperature: degrees Fahrenheit
    """
    heart_rate: float
    systolic_bp: float
    diastolic_bp: float
    respiratory_rate: float
    spo2: float
    temperature: float  # Fahrenheit
    supplemental_o2: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def mean_arterial_pressure(self) -> float:
        """Calculate MAP = diastolic + 1/3 * (systolic - diastolic)."""
        return self.diastolic_bp + (self.systolic_bp - self.diastolic_bp) / 3.0

    @property
    def pulse_pressure(self) -> float:
        """Pulse pressure = systolic - diastolic."""
        return self.systolic_bp - self.diastolic_bp

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for event payloads."""
        return {
            "heart_rate": round(self.heart_rate, 1),
            "systolic_bp": round(self.systolic_bp, 1),
            "diastolic_bp": round(self.diastolic_bp, 1),
            "respiratory_rate": round(self.respiratory_rate, 1),
            "spo2": round(self.spo2, 1),
            "temperature": round(self.temperature, 1),
            "supplemental_o2": self.supplemental_o2,
            "mean_arterial_pressure": round(self.mean_arterial_pressure, 1),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class LabResult:
    """A single laboratory result with reference ranges.

    Attributes:
        name: Standard lab abbreviation (e.g., "WBC", "Lactate", "Creatinine").
        value: Numeric result value.
        unit: Unit of measurement (e.g., "mg/dL", "K/uL").
        reference_low: Lower bound of normal range, or None if unbounded.
        reference_high: Upper bound of normal range, or None if unbounded.
        is_critical: Whether this value falls in the critical notification range.
        timestamp: When the result was finalized.
    """
    name: str
    value: float
    unit: str
    reference_low: float | None = None
    reference_high: float | None = None
    is_critical: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_abnormal(self) -> bool:
        """Check whether the value falls outside the reference range."""
        if self.reference_low is not None and self.value < self.reference_low:
            return True
        if self.reference_high is not None and self.value > self.reference_high:
            return True
        return False

    @property
    def flag(self) -> str:
        """Return clinical flag string: 'H', 'L', 'C', or ''."""
        if self.is_critical:
            return "C"
        if self.reference_low is not None and self.value < self.reference_low:
            return "L"
        if self.reference_high is not None and self.value > self.reference_high:
            return "H"
        return ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "value": round(self.value, 2),
            "unit": self.unit,
            "reference_low": self.reference_low,
            "reference_high": self.reference_high,
            "is_critical": self.is_critical,
            "is_abnormal": self.is_abnormal,
            "flag": self.flag,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SimulationEvent:
    """A discrete event scheduled to occur during a simulation.

    Events are processed in chronological order based on time_offset.
    Conditional branching allows scenario trees: if a condition is specified,
    the engine evaluates it against current state and switches to the named
    branch if the condition is met.

    Attributes:
        time_offset: Time since simulation start when this event fires.
        event_type: Category of the event.
        data: Event-specific payload (varies by event_type).
        description: Human-readable description for logging and display.
        condition: Optional expression evaluated against simulation state.
        branch: Branch name to switch to if condition evaluates true.
    """
    time_offset: timedelta
    event_type: EventType
    data: dict[str, Any]
    description: str = ""
    condition: str | None = None
    branch: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "time_offset_seconds": self.time_offset.total_seconds(),
            "event_type": self.event_type.value,
            "data": self.data,
            "description": self.description,
            "condition": self.condition,
            "branch": self.branch,
        }


@dataclass
class PatientProfile:
    """Demographic and clinical profile for a simulated patient.

    This defines the starting state of the patient entering the simulation.
    The baseline_vitals establish the physiological starting point from which
    trends and interventions will deviate.
    """
    id: str
    name: str
    age: int
    sex: str  # "M" or "F"
    weight_kg: float
    height_cm: float
    conditions: list[str]       # Active conditions / diagnoses
    medications: list[str]      # Active medications on admission
    allergies: list[str]        # Known drug / environmental allergies
    baseline_vitals: VitalSigns  # Starting vital signs

    @property
    def bmi(self) -> float:
        """Body mass index in kg/m^2."""
        height_m = self.height_cm / 100.0
        if height_m <= 0:
            return 0.0
        return self.weight_kg / (height_m ** 2)

    @property
    def age_category(self) -> str:
        """Classify patient into age bracket for physiology modeling."""
        if self.age < 40:
            return "young_adult"
        elif self.age < 65:
            return "middle_age"
        else:
            return "elderly"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "age": self.age,
            "sex": self.sex,
            "weight_kg": self.weight_kg,
            "height_cm": self.height_cm,
            "bmi": round(self.bmi, 1),
            "conditions": self.conditions,
            "medications": self.medications,
            "allergies": self.allergies,
            "baseline_vitals": self.baseline_vitals.to_dict(),
        }


@dataclass
class SimulationState:
    """Complete mutable state of a running simulation.

    This is the central state container that the engine updates on every tick.
    It holds the full history of vitals, labs, and events, as well as the
    current time cursor, speed, and branching state.

    Checkpoints allow saving and restoring simulation state at named points,
    enabling scenario replay and "what-if" branching.
    """
    simulation_id: str
    status: SimulationStatus
    patient: PatientProfile
    current_time: timedelta       # Current simulation time offset from start
    speed_multiplier: float       # 1.0 = real-time, 10.0 = 10x speed
    vitals_history: list[VitalSigns] = field(default_factory=list)
    lab_history: list[LabResult] = field(default_factory=list)
    events_processed: list[SimulationEvent] = field(default_factory=list)
    events_pending: list[SimulationEvent] = field(default_factory=list)
    active_interventions: list[dict] = field(default_factory=list)
    alerts_generated: list[dict] = field(default_factory=list)
    agents_active: list[dict] = field(default_factory=list)
    current_branch: str = "main"
    checkpoints: dict[str, Any] = field(default_factory=dict)

    @property
    def latest_vitals(self) -> VitalSigns | None:
        """Most recent set of vital signs, or None if no history yet."""
        return self.vitals_history[-1] if self.vitals_history else None

    @property
    def latest_labs(self) -> dict[str, LabResult]:
        """Most recent result for each lab name."""
        latest: dict[str, LabResult] = {}
        for lab in self.lab_history:
            if lab.name not in latest or lab.timestamp > latest[lab.name].timestamp:
                latest[lab.name] = lab
        return latest

    def to_dict(self) -> dict[str, Any]:
        """Serialize full state snapshot to dictionary."""
        return {
            "simulation_id": self.simulation_id,
            "status": self.status.value,
            "patient": self.patient.to_dict(),
            "current_time_seconds": self.current_time.total_seconds(),
            "speed_multiplier": self.speed_multiplier,
            "vitals_count": len(self.vitals_history),
            "lab_count": len(self.lab_history),
            "events_processed_count": len(self.events_processed),
            "events_pending_count": len(self.events_pending),
            "active_interventions": self.active_interventions,
            "alerts_generated_count": len(self.alerts_generated),
            "agents_active": self.agents_active,
            "current_branch": self.current_branch,
            "checkpoint_names": list(self.checkpoints.keys()),
        }
