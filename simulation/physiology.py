"""Physiology engine for generating clinically realistic vital signs and lab results.

This module provides two primary classes:
- PhysiologyModel: generates vital signs over time with trends, interventions, and noise.
- LabEngine: generates baseline lab panels and trending lab values.

All models are grounded in clinical physiology. Values are age- and sex-adjusted,
and interventions produce effects with realistic onset, peak, and decay curves.
"""

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from simulation.models import LabResult, PatientProfile, VitalSigns

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Age-stratified baseline vital sign ranges
# ---------------------------------------------------------------------------
# Format: (hr_lo, hr_hi, sbp_lo, sbp_hi, dbp_lo, dbp_hi,
#           rr_lo, rr_hi, spo2_lo, spo2_hi, temp_lo, temp_hi)
VITAL_RANGES: dict[str, tuple[float, ...]] = {
    "young_adult": (60, 80, 110, 130, 70, 85, 12, 18, 96, 100, 97.5, 98.9),
    "middle_age":  (65, 85, 115, 140, 75, 90, 14, 20, 95,  99, 97.2, 98.8),
    "elderly":     (60, 90, 120, 150, 70, 85, 14, 22, 93,  98, 96.8, 98.6),
}

# ---------------------------------------------------------------------------
# Noise standard deviations for beat-to-beat / measurement variability
# ---------------------------------------------------------------------------
NOISE_SD: dict[str, float] = {
    "heart_rate": 3.0,       # +/- 3 bpm
    "systolic_bp": 5.0,      # +/- 5 mmHg
    "diastolic_bp": 5.0,     # +/- 5 mmHg
    "respiratory_rate": 1.0,  # +/- 1 breath/min
    "spo2": 1.0,             # +/- 1%
    "temperature": 0.1,      # +/- 0.1 F
}

# ---------------------------------------------------------------------------
# Reference ranges for common lab values
# ---------------------------------------------------------------------------
LAB_REFERENCE_RANGES: dict[str, dict[str, Any]] = {
    # CBC
    "WBC":      {"unit": "K/uL",   "low": 4.5,  "high": 11.0, "critical_low": 2.0,  "critical_high": 30.0},
    "Hgb":      {"unit": "g/dL",   "low": 12.0, "high": 17.5, "critical_low": 7.0,  "critical_high": 20.0},
    "Plt":      {"unit": "K/uL",   "low": 150,  "high": 400,  "critical_low": 50,   "critical_high": 1000},
    # BMP
    "Na":       {"unit": "mEq/L",  "low": 136,  "high": 145,  "critical_low": 120,  "critical_high": 160},
    "K":        {"unit": "mEq/L",  "low": 3.5,  "high": 5.0,  "critical_low": 2.5,  "critical_high": 6.5},
    "Cl":       {"unit": "mEq/L",  "low": 98,   "high": 106,  "critical_low": 80,   "critical_high": 120},
    "CO2":      {"unit": "mEq/L",  "low": 23,   "high": 29,   "critical_low": 10,   "critical_high": 40},
    "BUN":      {"unit": "mg/dL",  "low": 7,    "high": 20,   "critical_low": None,  "critical_high": 100},
    "Creatinine": {"unit": "mg/dL", "low": 0.7, "high": 1.3,  "critical_low": None,  "critical_high": 10.0},
    "Glucose":  {"unit": "mg/dL",  "low": 70,   "high": 100,  "critical_low": 40,   "critical_high": 500},
    # Sepsis-relevant
    "Lactate":  {"unit": "mmol/L", "low": 0.5,  "high": 2.0,  "critical_low": None,  "critical_high": 4.0},
    "Procalcitonin": {"unit": "ng/mL", "low": 0.0, "high": 0.1, "critical_low": None, "critical_high": 10.0},
}

# Normal baseline generation ranges (mean, sd) for healthy patients
LAB_NORMAL_RANGES: dict[str, tuple[float, float]] = {
    "WBC":        (7.5, 1.5),
    "Hgb":        (14.0, 1.5),
    "Plt":        (250, 50),
    "Na":         (140, 2),
    "K":          (4.2, 0.3),
    "Cl":         (102, 2),
    "CO2":        (25, 2),
    "BUN":        (14, 4),
    "Creatinine": (1.0, 0.2),
    "Glucose":    (90, 10),
    "Lactate":    (1.0, 0.3),
    "Procalcitonin": (0.04, 0.02),
}


# ---------------------------------------------------------------------------
# Internal helper dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TrendModifier:
    """A gradual change applied to a single vital parameter over time.

    The effect ramps linearly from zero at start_time to
    (rate_per_hour * duration_hours) at the end, then holds steady.
    """
    vital_name: str
    rate_per_hour: float      # Change per hour (positive = increase)
    duration_hours: float     # How long the trend lasts
    start_time: timedelta     # Simulation time when the trend began
    _applied_delta: float = 0.0  # Track cumulative applied delta

    @property
    def end_time(self) -> timedelta:
        return self.start_time + timedelta(hours=self.duration_hours)

    def delta_at(self, elapsed: timedelta) -> float:
        """Return the cumulative delta produced by this trend at a given time."""
        if elapsed < self.start_time:
            return 0.0
        active_seconds = min(
            (elapsed - self.start_time).total_seconds(),
            self.duration_hours * 3600.0,
        )
        active_hours = active_seconds / 3600.0
        return self.rate_per_hour * active_hours

    def is_expired(self, elapsed: timedelta) -> bool:
        return elapsed >= self.end_time


@dataclass
class ActiveIntervention:
    """Tracks the physiological effect of an active clinical intervention.

    Each intervention type has a characteristic onset, peak, and decay profile
    modeled as a piecewise linear envelope.
    """
    intervention_type: str
    params: dict[str, Any]
    start_time: timedelta
    # Effect envelope timing (in minutes)
    onset_minutes: float = 5.0
    peak_minutes: float = 15.0
    decay_minutes: float = 60.0
    # Peak effect magnitudes per vital
    peak_effects: dict[str, float] = field(default_factory=dict)

    @property
    def total_duration(self) -> timedelta:
        return timedelta(minutes=self.onset_minutes + self.peak_minutes + self.decay_minutes)

    def effect_multiplier(self, elapsed: timedelta) -> float:
        """Return 0.0-1.0 envelope multiplier at the given simulation time.

        The envelope is:
          - Linear ramp from 0 to 1 over onset_minutes
          - Holds at 1.0 for peak_minutes
          - Linear decay from 1 to 0 over decay_minutes
        """
        dt_minutes = (elapsed - self.start_time).total_seconds() / 60.0
        if dt_minutes < 0:
            return 0.0

        if dt_minutes <= self.onset_minutes:
            # Ramp up
            return dt_minutes / self.onset_minutes if self.onset_minutes > 0 else 1.0

        dt_minutes -= self.onset_minutes
        if dt_minutes <= self.peak_minutes:
            # At peak
            return 1.0

        dt_minutes -= self.peak_minutes
        if dt_minutes <= self.decay_minutes:
            # Decay
            return 1.0 - (dt_minutes / self.decay_minutes) if self.decay_minutes > 0 else 0.0

        return 0.0

    def is_expired(self, elapsed: timedelta) -> bool:
        return elapsed >= self.start_time + self.total_duration

    def effect_on(self, vital_name: str, elapsed: timedelta) -> float:
        """Return the current effect magnitude on a given vital parameter."""
        if vital_name not in self.peak_effects:
            return 0.0
        return self.peak_effects[vital_name] * self.effect_multiplier(elapsed)


# ---------------------------------------------------------------------------
# Intervention factory: defines characteristic profiles
# ---------------------------------------------------------------------------

def _create_intervention(
    intervention_type: str,
    params: dict[str, Any],
    start_time: timedelta,
) -> ActiveIntervention:
    """Create an ActiveIntervention with clinically appropriate effect profiles.

    Supported intervention types and their physiological effects:
    - fluid_bolus: MAP increase 5-15 mmHg over 15-30 min, slight HR decrease
    - antipyretic: Temperature decrease 1-2 F over 60-90 min
    - vasopressor_start: MAP increase 10-25 mmHg, may increase HR 5-15 bpm
    - supplemental_o2: SpO2 improvement 2-8% depending on baseline
    - insulin_drip: tracked but no direct vital sign effect (glucose not a vital)
    """

    if intervention_type == "fluid_bolus":
        volume_ml = params.get("volume_ml", 1000)
        # Effect scales with bolus volume; 1000 mL is reference
        scale = volume_ml / 1000.0
        map_increase = random.uniform(5, 15) * scale
        hr_decrease = random.uniform(2, 8) * scale
        return ActiveIntervention(
            intervention_type=intervention_type,
            params=params,
            start_time=start_time,
            onset_minutes=random.uniform(5, 10),
            peak_minutes=random.uniform(15, 30),
            decay_minutes=random.uniform(60, 120),
            peak_effects={
                "systolic_bp": map_increase * 1.2,
                "diastolic_bp": map_increase * 0.8,
                "heart_rate": -hr_decrease,
            },
        )

    elif intervention_type == "antipyretic":
        temp_decrease = random.uniform(1.0, 2.0)
        return ActiveIntervention(
            intervention_type=intervention_type,
            params=params,
            start_time=start_time,
            onset_minutes=random.uniform(15, 30),
            peak_minutes=random.uniform(60, 90),
            decay_minutes=random.uniform(120, 240),
            peak_effects={
                "temperature": -temp_decrease,
                # Antipyretics may slightly reduce HR as fever resolves
                "heart_rate": -random.uniform(3, 8),
            },
        )

    elif intervention_type == "vasopressor_start":
        dose_mcg_kg_min = params.get("dose_mcg_kg_min", 0.1)
        # Norepinephrine-like profile: dose-dependent MAP increase
        dose_scale = min(dose_mcg_kg_min / 0.1, 3.0)  # Cap at 3x effect
        map_increase = random.uniform(10, 25) * dose_scale
        hr_change = random.uniform(5, 15) * dose_scale
        return ActiveIntervention(
            intervention_type=intervention_type,
            params=params,
            start_time=start_time,
            onset_minutes=random.uniform(2, 5),
            peak_minutes=random.uniform(10, 20),
            # Vasopressors sustain effect as long as infusing; use long decay
            decay_minutes=random.uniform(180, 360),
            peak_effects={
                "systolic_bp": map_increase * 1.3,
                "diastolic_bp": map_increase * 0.9,
                "heart_rate": hr_change,
            },
        )

    elif intervention_type == "supplemental_o2":
        fio2 = params.get("fio2", 0.4)
        # Higher FiO2 produces larger SpO2 improvement
        spo2_improvement = random.uniform(2, 8) * min(fio2 / 0.4, 2.0)
        return ActiveIntervention(
            intervention_type=intervention_type,
            params=params,
            start_time=start_time,
            onset_minutes=random.uniform(1, 3),
            peak_minutes=random.uniform(5, 15),
            # O2 effect persists as long as supplementation continues
            decay_minutes=random.uniform(240, 480),
            peak_effects={
                "spo2": spo2_improvement,
                # May slightly decrease respiratory drive
                "respiratory_rate": -random.uniform(1, 3),
            },
        )

    elif intervention_type == "insulin_drip":
        # Insulin drip does not directly affect vital signs in this model.
        # We track it for scenario event purposes.
        return ActiveIntervention(
            intervention_type=intervention_type,
            params=params,
            start_time=start_time,
            onset_minutes=10,
            peak_minutes=60,
            decay_minutes=120,
            peak_effects={},
        )

    else:
        logger.warning("Unknown intervention type '%s'; creating no-effect placeholder.", intervention_type)
        return ActiveIntervention(
            intervention_type=intervention_type,
            params=params,
            start_time=start_time,
            peak_effects={},
        )


# ---------------------------------------------------------------------------
# PhysiologyModel
# ---------------------------------------------------------------------------

class PhysiologyModel:
    """Generates realistic vital signs based on patient profile and clinical state.

    The model layers three components:
    1. Baseline values derived from the patient profile (age/sex adjusted).
    2. Trend modifiers that produce gradual changes over time (e.g., rising HR
       in early sepsis).
    3. Intervention effects that alter vitals with onset/peak/decay kinetics.
    4. Gaussian noise for beat-to-beat / measurement variability.

    Vital sign values are clamped to physiologically plausible ranges to prevent
    impossible readings (e.g., SpO2 > 100 or negative heart rate).
    """

    # Absolute physiological bounds
    VITAL_BOUNDS: dict[str, tuple[float, float]] = {
        "heart_rate":       (20.0, 250.0),
        "systolic_bp":      (40.0, 300.0),
        "diastolic_bp":     (20.0, 200.0),
        "respiratory_rate": (4.0, 60.0),
        "spo2":             (50.0, 100.0),
        "temperature":      (90.0, 108.0),
    }

    def __init__(self, patient: PatientProfile) -> None:
        self.patient = patient
        self.current_vitals = VitalSigns(
            heart_rate=patient.baseline_vitals.heart_rate,
            systolic_bp=patient.baseline_vitals.systolic_bp,
            diastolic_bp=patient.baseline_vitals.diastolic_bp,
            respiratory_rate=patient.baseline_vitals.respiratory_rate,
            spo2=patient.baseline_vitals.spo2,
            temperature=patient.baseline_vitals.temperature,
            supplemental_o2=patient.baseline_vitals.supplemental_o2,
        )
        self._interventions: list[ActiveIntervention] = []
        self._trend_modifiers: list[TrendModifier] = []
        self._last_elapsed: timedelta = timedelta(0)

    def generate_vitals(self, elapsed: timedelta, noise: bool = True) -> VitalSigns:
        """Generate the next set of vital signs at the given elapsed time.

        Computation order:
        1. Start from baseline values.
        2. Apply cumulative trend modifier deltas.
        3. Apply active intervention effects.
        4. Optionally add Gaussian noise.
        5. Clamp to physiological bounds.

        Args:
            elapsed: Time since simulation start.
            noise: Whether to add measurement variability.

        Returns:
            A new VitalSigns instance with a current timestamp.
        """
        baseline = self.patient.baseline_vitals

        # Start from baseline
        hr = baseline.heart_rate
        sbp = baseline.systolic_bp
        dbp = baseline.diastolic_bp
        rr = baseline.respiratory_rate
        spo2 = baseline.spo2
        temp = baseline.temperature
        supp_o2 = baseline.supplemental_o2

        # --- Apply trend modifiers ---
        for trend in self._trend_modifiers:
            delta = trend.delta_at(elapsed)
            if trend.vital_name == "heart_rate":
                hr += delta
            elif trend.vital_name == "systolic_bp":
                sbp += delta
            elif trend.vital_name == "diastolic_bp":
                dbp += delta
            elif trend.vital_name == "respiratory_rate":
                rr += delta
            elif trend.vital_name == "spo2":
                spo2 += delta
            elif trend.vital_name == "temperature":
                temp += delta

        # Clean up expired trends
        self._trend_modifiers = [
            t for t in self._trend_modifiers if not t.is_expired(elapsed)
        ]

        # --- Apply intervention effects ---
        for intervention in self._interventions:
            hr += intervention.effect_on("heart_rate", elapsed)
            sbp += intervention.effect_on("systolic_bp", elapsed)
            dbp += intervention.effect_on("diastolic_bp", elapsed)
            rr += intervention.effect_on("respiratory_rate", elapsed)
            spo2 += intervention.effect_on("spo2", elapsed)
            temp += intervention.effect_on("temperature", elapsed)
            # Track supplemental O2
            if intervention.intervention_type == "supplemental_o2" and not intervention.is_expired(elapsed):
                supp_o2 = True

        # Clean up expired interventions
        self._interventions = [
            i for i in self._interventions if not i.is_expired(elapsed)
        ]

        # --- Add noise ---
        if noise:
            hr += random.gauss(0, NOISE_SD["heart_rate"])
            sbp += random.gauss(0, NOISE_SD["systolic_bp"])
            dbp += random.gauss(0, NOISE_SD["diastolic_bp"])
            rr += random.gauss(0, NOISE_SD["respiratory_rate"])
            spo2 += random.gauss(0, NOISE_SD["spo2"])
            temp += random.gauss(0, NOISE_SD["temperature"])

        # --- Ensure diastolic < systolic (maintain minimum pulse pressure) ---
        if dbp >= sbp - 10:
            dbp = sbp - 10

        # --- Clamp to physiological bounds ---
        hr = self._clamp("heart_rate", hr)
        sbp = self._clamp("systolic_bp", sbp)
        dbp = self._clamp("diastolic_bp", dbp)
        rr = self._clamp("respiratory_rate", rr)
        spo2 = self._clamp("spo2", spo2)
        temp = self._clamp("temperature", temp)

        vitals = VitalSigns(
            heart_rate=round(hr, 1),
            systolic_bp=round(sbp, 1),
            diastolic_bp=round(dbp, 1),
            respiratory_rate=round(rr, 1),
            spo2=round(spo2, 1),
            temperature=round(temp, 1),
            supplemental_o2=supp_o2,
            timestamp=datetime.now(),
        )

        self.current_vitals = vitals
        self._last_elapsed = elapsed
        return vitals

    def add_trend(self, vital_name: str, rate_per_hour: float, duration_hours: float,
                  start_time: timedelta | None = None) -> None:
        """Add a gradual trend to a vital parameter.

        Example: add_trend("heart_rate", 5.0, 3.0) will increase HR by
        5 bpm per hour over 3 hours (total +15 bpm at the end).

        Args:
            vital_name: One of "heart_rate", "systolic_bp", "diastolic_bp",
                       "respiratory_rate", "spo2", "temperature".
            rate_per_hour: Rate of change per hour (positive = increase).
            duration_hours: How long the trend lasts.
            start_time: When the trend starts (defaults to last known elapsed time).
        """
        if vital_name not in self.VITAL_BOUNDS:
            raise ValueError(
                f"Unknown vital parameter '{vital_name}'. "
                f"Valid names: {list(self.VITAL_BOUNDS.keys())}"
            )

        trend = TrendModifier(
            vital_name=vital_name,
            rate_per_hour=rate_per_hour,
            duration_hours=duration_hours,
            start_time=start_time if start_time is not None else self._last_elapsed,
        )
        self._trend_modifiers.append(trend)
        logger.info(
            "Added trend: %s %+.1f/hr for %.1fh starting at %s",
            vital_name, rate_per_hour, duration_hours, trend.start_time,
        )

    def apply_intervention(self, intervention_type: str, params: dict[str, Any] | None = None,
                           start_time: timedelta | None = None) -> None:
        """Apply a clinical intervention that affects physiology.

        Supported intervention types:
        - "fluid_bolus": params may include {"volume_ml": 1000}
          Effect: MAP increase 5-15 mmHg over 15-30 min, slight HR decrease.
        - "antipyretic": no required params
          Effect: Temperature decrease 1-2 F over 60-90 min.
        - "vasopressor_start": params may include {"dose_mcg_kg_min": 0.1}
          Effect: MAP increase 10-25 mmHg, HR may increase 5-15 bpm.
        - "supplemental_o2": params may include {"fio2": 0.4}
          Effect: SpO2 improvement 2-8%.
        - "insulin_drip": params may include {"rate_units_hr": 5}
          Effect: Tracked but no direct vital sign changes.

        Args:
            intervention_type: One of the supported intervention type strings.
            params: Intervention-specific parameters.
            start_time: When the intervention starts (defaults to current time).
        """
        if params is None:
            params = {}
        effective_start = start_time if start_time is not None else self._last_elapsed

        intervention = _create_intervention(intervention_type, params, effective_start)
        self._interventions.append(intervention)
        logger.info(
            "Applied intervention '%s' at %s with params %s",
            intervention_type, effective_start, params,
        )

    def _clamp(self, vital_name: str, value: float) -> float:
        """Clamp a value to the physiological bounds for the given vital."""
        lo, hi = self.VITAL_BOUNDS[vital_name]
        return max(lo, min(hi, value))

    @property
    def active_trend_count(self) -> int:
        """Number of currently active trend modifiers."""
        return len(self._trend_modifiers)

    @property
    def active_intervention_count(self) -> int:
        """Number of currently active interventions."""
        return len(self._interventions)


# ---------------------------------------------------------------------------
# LabEngine
# ---------------------------------------------------------------------------

class LabEngine:
    """Generates lab results with realistic baseline values and trending.

    Lab values are generated based on the patient profile. Conditions like
    sepsis, renal failure, or anemia shift baseline values appropriately.
    Trending allows gradual worsening or improvement of individual labs.
    """

    def __init__(self) -> None:
        self._trend_state: dict[str, float] = {}  # lab_name -> current value

    def generate_baseline_labs(self, patient: PatientProfile) -> list[LabResult]:
        """Generate an initial lab panel based on the patient profile.

        Generates:
        - CBC: WBC, Hgb, Plt
        - BMP: Na, K, Cl, CO2, BUN, Creatinine, Glucose
        - If sepsis-related conditions: Lactate, Procalcitonin

        Values are adjusted based on patient conditions:
        - Sepsis: elevated WBC, lactate, procalcitonin; may have low platelets
        - Anemia / blood loss: decreased Hgb
        - Renal failure / CKD: elevated BUN, creatinine
        - Diabetes: elevated glucose
        - Elderly patients: slight shifts toward lower Hgb, higher creatinine

        Args:
            patient: The patient profile to generate labs for.

        Returns:
            List of LabResult instances representing the initial panel.
        """
        now = datetime.now()
        results: list[LabResult] = []
        conditions_lower = [c.lower() for c in patient.conditions]

        # Detect relevant conditions
        has_sepsis = any(
            term in cond for cond in conditions_lower
            for term in ("sepsis", "septic", "infection", "pneumonia", "uti", "cellulitis")
        )
        has_renal = any(
            term in cond for cond in conditions_lower
            for term in ("renal", "kidney", "ckd", "esrd", "aki")
        )
        has_anemia = any(
            term in cond for cond in conditions_lower
            for term in ("anemia", "blood loss", "hemorrhage", "gi bleed")
        )
        has_diabetes = any(
            term in cond for cond in conditions_lower
            for term in ("diabetes", "diabetic", "dm ", "dm2", "dka")
        )

        # --- CBC ---
        wbc_mean, wbc_sd = LAB_NORMAL_RANGES["WBC"]
        if has_sepsis:
            wbc_mean = random.uniform(14.0, 22.0)
            wbc_sd = 3.0
        wbc = max(0.5, random.gauss(wbc_mean, wbc_sd))
        results.append(self._make_result("WBC", wbc, now))

        hgb_mean, hgb_sd = LAB_NORMAL_RANGES["Hgb"]
        if patient.sex == "F":
            hgb_mean -= 1.5  # Female reference range is lower
        if has_anemia:
            hgb_mean = random.uniform(6.5, 9.5)
            hgb_sd = 1.0
        elif patient.age_category == "elderly":
            hgb_mean -= 0.5
        hgb = max(3.0, random.gauss(hgb_mean, hgb_sd))
        results.append(self._make_result("Hgb", hgb, now))

        plt_mean, plt_sd = LAB_NORMAL_RANGES["Plt"]
        if has_sepsis:
            # Sepsis can cause thrombocytopenia
            plt_mean = random.uniform(80, 180)
            plt_sd = 30
        plt = max(10, random.gauss(plt_mean, plt_sd))
        results.append(self._make_result("Plt", plt, now))

        # --- BMP ---
        for lab_name in ("Na", "K", "Cl", "CO2"):
            mean, sd = LAB_NORMAL_RANGES[lab_name]
            value = random.gauss(mean, sd)
            # Renal patients may have high K and low CO2
            if has_renal and lab_name == "K":
                value += random.uniform(0.5, 1.5)
            if has_renal and lab_name == "CO2":
                value -= random.uniform(2, 5)
            results.append(self._make_result(lab_name, value, now))

        bun_mean, bun_sd = LAB_NORMAL_RANGES["BUN"]
        cr_mean, cr_sd = LAB_NORMAL_RANGES["Creatinine"]
        if has_renal:
            bun_mean = random.uniform(40, 80)
            bun_sd = 10
            cr_mean = random.uniform(2.5, 6.0)
            cr_sd = 0.5
        elif patient.age_category == "elderly":
            cr_mean += 0.2
        bun = max(1, random.gauss(bun_mean, bun_sd))
        cr = max(0.2, random.gauss(cr_mean, cr_sd))
        results.append(self._make_result("BUN", bun, now))
        results.append(self._make_result("Creatinine", cr, now))

        glu_mean, glu_sd = LAB_NORMAL_RANGES["Glucose"]
        if has_diabetes:
            glu_mean = random.uniform(150, 300)
            glu_sd = 30
        glucose = max(20, random.gauss(glu_mean, glu_sd))
        results.append(self._make_result("Glucose", glucose, now))

        # --- Sepsis-specific labs ---
        if has_sepsis:
            lactate = max(0.5, random.gauss(random.uniform(2.5, 5.0), 0.5))
            results.append(self._make_result("Lactate", lactate, now))

            procal = max(0.02, random.gauss(random.uniform(2.0, 15.0), 2.0))
            results.append(self._make_result("Procalcitonin", procal, now))

        # Store initial values for trending
        for result in results:
            self._trend_state[result.name] = result.value

        logger.info(
            "Generated baseline labs for patient %s: %d results",
            patient.id, len(results),
        )
        return results

    def trend_lab(self, lab_name: str, current_value: float,
                  direction: str, rate_per_hour: float,
                  elapsed_hours: float = 1.0) -> float:
        """Calculate the next lab value based on directional trending.

        Applies a rate of change over the given elapsed time, with a small
        amount of random variability (biological noise).

        Args:
            lab_name: Name of the lab test.
            current_value: Current numeric value.
            direction: "up" or "down".
            rate_per_hour: Absolute rate of change per hour.
            elapsed_hours: Time interval to project forward.

        Returns:
            New lab value after trending.

        Raises:
            ValueError: If direction is not "up" or "down".
        """
        if direction not in ("up", "down"):
            raise ValueError(f"Direction must be 'up' or 'down', got '{direction}'")

        sign = 1.0 if direction == "up" else -1.0
        delta = sign * rate_per_hour * elapsed_hours

        # Add small biological noise (5% of rate)
        noise = random.gauss(0, rate_per_hour * 0.05 * elapsed_hours)
        new_value = current_value + delta + noise

        # Ensure non-negative lab values
        new_value = max(0.0, new_value)

        # Update tracked state
        self._trend_state[lab_name] = new_value

        logger.debug(
            "Trended %s: %.2f -> %.2f (%s at %.2f/hr over %.1fh)",
            lab_name, current_value, new_value, direction, rate_per_hour, elapsed_hours,
        )
        return round(new_value, 2)

    def generate_result(self, lab_name: str, value: float,
                        timestamp: datetime | None = None) -> LabResult:
        """Create a LabResult from a name and value using stored reference ranges.

        Args:
            lab_name: The lab test name (must exist in LAB_REFERENCE_RANGES).
            value: The numeric result value.
            timestamp: Optional timestamp; defaults to now.

        Returns:
            A fully populated LabResult with reference ranges and critical flags.
        """
        return self._make_result(lab_name, value, timestamp or datetime.now())

    def _make_result(self, lab_name: str, value: float, timestamp: datetime) -> LabResult:
        """Internal helper to construct a LabResult with reference data."""
        ref = LAB_REFERENCE_RANGES.get(lab_name, {})
        ref_low = ref.get("low")
        ref_high = ref.get("high")
        critical_low = ref.get("critical_low")
        critical_high = ref.get("critical_high")
        unit = ref.get("unit", "")

        is_critical = False
        if critical_low is not None and value < critical_low:
            is_critical = True
        if critical_high is not None and value > critical_high:
            is_critical = True

        return LabResult(
            name=lab_name,
            value=round(value, 2),
            unit=unit,
            reference_low=ref_low,
            reference_high=ref_high,
            is_critical=is_critical,
            timestamp=timestamp,
        )


# ---------------------------------------------------------------------------
# Utility: generate age/sex-appropriate baseline vitals
# ---------------------------------------------------------------------------

def generate_baseline_vitals(patient_age: int, patient_sex: str) -> VitalSigns:
    """Generate a set of baseline vital signs appropriate for age and sex.

    Uses the age-stratified ranges defined in VITAL_RANGES, with slight
    sex-based adjustments (females tend toward lower BP and slightly higher HR).

    Args:
        patient_age: Patient age in years.
        patient_sex: "M" or "F".

    Returns:
        A VitalSigns instance with values drawn from clinically appropriate ranges.
    """
    if patient_age < 40:
        category = "young_adult"
    elif patient_age < 65:
        category = "middle_age"
    else:
        category = "elderly"

    ranges = VITAL_RANGES[category]
    hr_lo, hr_hi = ranges[0], ranges[1]
    sbp_lo, sbp_hi = ranges[2], ranges[3]
    dbp_lo, dbp_hi = ranges[4], ranges[5]
    rr_lo, rr_hi = ranges[6], ranges[7]
    spo2_lo, spo2_hi = ranges[8], ranges[9]
    temp_lo, temp_hi = ranges[10], ranges[11]

    # Sex-based adjustments
    if patient_sex == "F":
        hr_lo += 2
        hr_hi += 3
        sbp_lo -= 5
        sbp_hi -= 5
        dbp_lo -= 3
        dbp_hi -= 3

    return VitalSigns(
        heart_rate=round(random.uniform(hr_lo, hr_hi), 1),
        systolic_bp=round(random.uniform(sbp_lo, sbp_hi), 1),
        diastolic_bp=round(random.uniform(dbp_lo, dbp_hi), 1),
        respiratory_rate=round(random.uniform(rr_lo, rr_hi), 1),
        spo2=round(random.uniform(spo2_lo, spo2_hi), 1),
        temperature=round(random.uniform(temp_lo, temp_hi), 1),
    )
