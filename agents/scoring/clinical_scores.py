"""
Clinical Scoring Systems for AgentEHR Inpatient Care Oversight

Implements deterministic clinical scoring systems used for patient acuity
assessment, sepsis screening, organ failure tracking, and AKI staging.

All functions are pure Python with no external dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agentehr.scoring")


# =============================================================================
# Return Types
# =============================================================================

@dataclass
class NEWS2Result:
    """NEWS2 scoring result."""
    total_score: int
    scores: dict[str, int]
    risk_level: str  # LOW, LOW_KEY_CONCERN, MEDIUM, HIGH
    clinical_response: str
    parameters_used: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "scoring_system": "NEWS2",
            "total_score": self.total_score,
            "scores": self.scores,
            "risk_level": self.risk_level,
            "clinical_response": self.clinical_response,
        }


@dataclass
class qSOFAResult:
    """qSOFA scoring result."""
    score: int
    criteria_met: list[str]
    sepsis_risk: bool
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "scoring_system": "qSOFA",
            "score": self.score,
            "criteria_met": self.criteria_met,
            "sepsis_risk": self.sepsis_risk,
            "recommendation": self.recommendation,
        }


@dataclass
class SOFAResult:
    """SOFA scoring result."""
    total_score: int
    organ_scores: dict[str, int]
    mortality_estimate: str
    sepsis_indicated: bool  # True if score increase >= 2 from baseline
    baseline_score: int | None

    def to_dict(self) -> dict:
        return {
            "scoring_system": "SOFA",
            "total_score": self.total_score,
            "organ_scores": self.organ_scores,
            "mortality_estimate": self.mortality_estimate,
            "sepsis_indicated": self.sepsis_indicated,
        }


@dataclass
class KDIGOResult:
    """KDIGO AKI staging result."""
    stage: int  # 0-3
    criteria_met: list[str]
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "scoring_system": "KDIGO",
            "stage": self.stage,
            "criteria_met": self.criteria_met,
            "recommendation": self.recommendation,
        }


# =============================================================================
# NEWS2 (National Early Warning Score 2)
# =============================================================================

def calculate_news2(
    respiratory_rate: float,
    spo2: float,
    systolic_bp: float,
    pulse: float,
    consciousness: str,
    temperature: float,
    supplemental_o2: bool = False,
    spo2_scale: int = 1,
) -> NEWS2Result:
    """
    Calculate NEWS2 score from vital signs.

    Args:
        respiratory_rate: Breaths per minute
        spo2: Oxygen saturation percentage (0-100)
        systolic_bp: Systolic blood pressure in mmHg
        pulse: Heart rate in bpm
        consciousness: One of 'A' (alert), 'C' (confusion), 'V' (voice),
                       'P' (pain), 'U' (unresponsive)
        temperature: Temperature in Celsius
        supplemental_o2: Whether patient is on supplemental oxygen
        spo2_scale: 1 (default) or 2 (for hypercapnic respiratory failure/COPD)

    Returns:
        NEWS2Result with total score, individual scores, risk level, and response.
    """
    scores: dict[str, int] = {}

    # Respiratory rate
    if respiratory_rate <= 8:
        scores["respiratory_rate"] = 3
    elif respiratory_rate <= 11:
        scores["respiratory_rate"] = 1
    elif respiratory_rate <= 20:
        scores["respiratory_rate"] = 0
    elif respiratory_rate <= 24:
        scores["respiratory_rate"] = 2
    else:
        scores["respiratory_rate"] = 3

    # SpO2 scoring depends on scale
    if spo2_scale == 1:
        if spo2 <= 91:
            scores["spo2"] = 3
        elif spo2 <= 93:
            scores["spo2"] = 2
        elif spo2 <= 95:
            scores["spo2"] = 1
        else:
            scores["spo2"] = 0
    else:
        # Scale 2 for hypercapnic respiratory failure (e.g., COPD)
        if spo2 <= 83:
            scores["spo2"] = 3
        elif spo2 <= 85:
            scores["spo2"] = 2
        elif spo2 <= 87:
            scores["spo2"] = 1
        elif spo2 <= 92:
            scores["spo2"] = 0
        elif spo2 <= 94:
            if supplemental_o2:
                scores["spo2"] = 1
            else:
                scores["spo2"] = 0
        elif spo2 <= 96:
            if supplemental_o2:
                scores["spo2"] = 2
            else:
                scores["spo2"] = 0
        else:  # >= 97
            if supplemental_o2:
                scores["spo2"] = 3
            else:
                scores["spo2"] = 0

    # Supplemental oxygen
    scores["supplemental_o2"] = 2 if supplemental_o2 else 0

    # Systolic BP
    if systolic_bp <= 90:
        scores["systolic_bp"] = 3
    elif systolic_bp <= 100:
        scores["systolic_bp"] = 2
    elif systolic_bp <= 110:
        scores["systolic_bp"] = 1
    elif systolic_bp <= 219:
        scores["systolic_bp"] = 0
    else:
        scores["systolic_bp"] = 3

    # Pulse
    if pulse <= 40:
        scores["pulse"] = 3
    elif pulse <= 50:
        scores["pulse"] = 1
    elif pulse <= 90:
        scores["pulse"] = 0
    elif pulse <= 110:
        scores["pulse"] = 1
    elif pulse <= 130:
        scores["pulse"] = 2
    else:
        scores["pulse"] = 3

    # Temperature (Celsius)
    if temperature <= 35.0:
        scores["temperature"] = 3
    elif temperature <= 36.0:
        scores["temperature"] = 1
    elif temperature <= 38.0:
        scores["temperature"] = 0
    elif temperature <= 39.0:
        scores["temperature"] = 1
    else:
        scores["temperature"] = 2

    # Consciousness (ACVPU)
    consciousness_upper = consciousness.upper().strip()
    if consciousness_upper == "A":
        scores["consciousness"] = 0
    else:
        scores["consciousness"] = 3

    total = sum(scores.values())

    # Determine risk level
    has_extreme_single = any(v == 3 for v in scores.values())

    if total >= 7:
        risk_level = "HIGH"
        clinical_response = (
            "Emergency response. Continuous monitoring of vital signs. "
            "Urgent assessment by clinical team with critical care competencies. "
            "Consider transfer to ICU/HDU."
        )
    elif total >= 5:
        risk_level = "MEDIUM"
        clinical_response = (
            "Key threshold for urgent response. Urgent assessment by clinician "
            "with competencies in acute illness. Consider escalation of care."
        )
    elif has_extreme_single and total < 5:
        risk_level = "LOW_KEY_CONCERN"
        clinical_response = (
            "Urgent ward-based response. Clinician to assess and decide "
            "whether escalation of care is needed. Score of 3 in a single "
            "parameter warrants urgent review."
        )
    else:
        risk_level = "LOW"
        clinical_response = (
            "Ward-based monitoring. Continue routine NEWS monitoring. "
            "Minimum 12-hourly observations."
        )

    return NEWS2Result(
        total_score=total,
        scores=scores,
        risk_level=risk_level,
        clinical_response=clinical_response,
        parameters_used={
            "respiratory_rate": respiratory_rate,
            "spo2": spo2,
            "systolic_bp": systolic_bp,
            "pulse": pulse,
            "consciousness": consciousness,
            "temperature": temperature,
            "supplemental_o2": supplemental_o2,
            "spo2_scale": spo2_scale,
        },
    )


# =============================================================================
# qSOFA (Quick Sequential Organ Failure Assessment)
# =============================================================================

def calculate_qsofa(
    systolic_bp: float,
    respiratory_rate: float,
    gcs: int,
) -> qSOFAResult:
    """
    Calculate qSOFA score for bedside sepsis screening.

    Args:
        systolic_bp: Systolic blood pressure in mmHg
        respiratory_rate: Breaths per minute
        gcs: Glasgow Coma Scale score (3-15)

    Returns:
        qSOFAResult with score, criteria met, sepsis risk, and recommendation.
    """
    score = 0
    criteria: list[str] = []

    if systolic_bp <= 100:
        score += 1
        criteria.append(f"Hypotension: SBP {systolic_bp} mmHg (<=100)")

    if respiratory_rate >= 22:
        score += 1
        criteria.append(f"Tachypnea: RR {respiratory_rate}/min (>=22)")

    if gcs < 15:
        score += 1
        criteria.append(f"Altered mentation: GCS {gcs} (<15)")

    sepsis_risk = score >= 2

    if score >= 2:
        recommendation = (
            "qSOFA >= 2: High risk of poor outcome in infection. "
            "Assess for organ dysfunction with full SOFA score. "
            "Consider sepsis workup: blood cultures, lactate, broad-spectrum antibiotics."
        )
    elif score == 1:
        recommendation = (
            "qSOFA = 1: Monitor closely. Re-evaluate if clinical status changes. "
            "Consider infection workup if clinical suspicion exists."
        )
    else:
        recommendation = (
            "qSOFA = 0: Low immediate risk. Continue standard monitoring. "
            "Re-evaluate if new symptoms of infection develop."
        )

    return qSOFAResult(
        score=score,
        criteria_met=criteria,
        sepsis_risk=sepsis_risk,
        recommendation=recommendation,
    )


# =============================================================================
# SOFA (Sequential Organ Failure Assessment)
# =============================================================================

def calculate_sofa(
    pao2_fio2_ratio: float | None = None,
    on_ventilator: bool = False,
    platelets: float | None = None,
    bilirubin: float | None = None,
    mean_arterial_pressure: float | None = None,
    vasopressor: str | None = None,
    vasopressor_dose: float | None = None,
    gcs: int | None = None,
    creatinine: float | None = None,
    urine_output_ml_day: float | None = None,
    baseline_score: int | None = None,
) -> SOFAResult:
    """
    Calculate SOFA score for organ dysfunction assessment.

    Args:
        pao2_fio2_ratio: PaO2/FiO2 ratio (e.g., 300)
        on_ventilator: Whether patient is mechanically ventilated
        platelets: Platelet count (x10^3/uL)
        bilirubin: Total bilirubin (mg/dL)
        mean_arterial_pressure: MAP in mmHg
        vasopressor: Name of vasopressor (dopamine/dobutamine/epinephrine/norepinephrine)
        vasopressor_dose: Dose in mcg/kg/min
        gcs: Glasgow Coma Scale (3-15)
        creatinine: Serum creatinine (mg/dL)
        urine_output_ml_day: 24-hour urine output in mL
        baseline_score: Previous SOFA score for comparison

    Returns:
        SOFAResult with total score, organ scores, mortality, and sepsis indication.
    """
    organ_scores: dict[str, int] = {}

    # Respiration: PaO2/FiO2
    if pao2_fio2_ratio is not None:
        if pao2_fio2_ratio >= 400:
            organ_scores["respiration"] = 0
        elif pao2_fio2_ratio >= 300:
            organ_scores["respiration"] = 1
        elif pao2_fio2_ratio >= 200:
            organ_scores["respiration"] = 2
        elif pao2_fio2_ratio >= 100:
            organ_scores["respiration"] = 3 if on_ventilator else 2
        else:
            organ_scores["respiration"] = 4 if on_ventilator else 2

    # Coagulation: Platelets
    if platelets is not None:
        if platelets >= 150:
            organ_scores["coagulation"] = 0
        elif platelets >= 100:
            organ_scores["coagulation"] = 1
        elif platelets >= 50:
            organ_scores["coagulation"] = 2
        elif platelets >= 20:
            organ_scores["coagulation"] = 3
        else:
            organ_scores["coagulation"] = 4

    # Liver: Bilirubin
    if bilirubin is not None:
        if bilirubin < 1.2:
            organ_scores["liver"] = 0
        elif bilirubin < 2.0:
            organ_scores["liver"] = 1
        elif bilirubin < 6.0:
            organ_scores["liver"] = 2
        elif bilirubin < 12.0:
            organ_scores["liver"] = 3
        else:
            organ_scores["liver"] = 4

    # Cardiovascular: MAP and vasopressors
    if mean_arterial_pressure is not None or vasopressor is not None:
        if vasopressor and vasopressor_dose is not None:
            vp = vasopressor.lower()
            dose = vasopressor_dose
            if vp == "dopamine" and dose > 15:
                organ_scores["cardiovascular"] = 4
            elif vp == "epinephrine" and dose > 0.1:
                organ_scores["cardiovascular"] = 4
            elif vp == "norepinephrine" and dose > 0.1:
                organ_scores["cardiovascular"] = 4
            elif vp == "dopamine" and dose > 5:
                organ_scores["cardiovascular"] = 3
            elif vp == "epinephrine" and dose <= 0.1:
                organ_scores["cardiovascular"] = 3
            elif vp == "norepinephrine" and dose <= 0.1:
                organ_scores["cardiovascular"] = 3
            elif vp in ("dopamine", "dobutamine") and dose <= 5:
                organ_scores["cardiovascular"] = 2
            else:
                organ_scores["cardiovascular"] = 2
        elif mean_arterial_pressure is not None:
            if mean_arterial_pressure >= 70:
                organ_scores["cardiovascular"] = 0
            else:
                organ_scores["cardiovascular"] = 1

    # CNS: Glasgow Coma Scale
    if gcs is not None:
        if gcs >= 15:
            organ_scores["cns"] = 0
        elif gcs >= 13:
            organ_scores["cns"] = 1
        elif gcs >= 10:
            organ_scores["cns"] = 2
        elif gcs >= 6:
            organ_scores["cns"] = 3
        else:
            organ_scores["cns"] = 4

    # Renal: Creatinine or urine output
    if creatinine is not None:
        if creatinine < 1.2:
            organ_scores["renal"] = 0
        elif creatinine < 2.0:
            organ_scores["renal"] = 1
        elif creatinine < 3.5:
            organ_scores["renal"] = 2
        elif creatinine < 5.0:
            organ_scores["renal"] = 3
        else:
            organ_scores["renal"] = 4

    # Urine output can override creatinine score upward
    if urine_output_ml_day is not None:
        uo_score = 0
        if urine_output_ml_day < 200:
            uo_score = 4
        elif urine_output_ml_day < 500:
            uo_score = 3
        current_renal = organ_scores.get("renal", 0)
        organ_scores["renal"] = max(current_renal, uo_score)

    total = sum(organ_scores.values())

    # Mortality estimate based on total SOFA
    if total <= 1:
        mortality = "<3.3%"
    elif total <= 3:
        mortality = "~6.7%"
    elif total <= 5:
        mortality = "~12.8%"
    elif total <= 7:
        mortality = "~21.5%"
    elif total <= 9:
        mortality = "~33.3%"
    elif total <= 11:
        mortality = "~50%"
    elif total <= 14:
        mortality = "~73.3%"
    else:
        mortality = ">90%"

    # Sepsis-3: acute increase >= 2 points from baseline indicates sepsis
    sepsis_indicated = False
    if baseline_score is not None:
        sepsis_indicated = (total - baseline_score) >= 2

    return SOFAResult(
        total_score=total,
        organ_scores=organ_scores,
        mortality_estimate=mortality,
        sepsis_indicated=sepsis_indicated,
        baseline_score=baseline_score,
    )


# =============================================================================
# KDIGO AKI Staging
# =============================================================================

def calculate_kdigo(
    baseline_creatinine: float,
    current_creatinine: float,
    creatinine_48h_ago: float | None = None,
    urine_output_ml_per_kg_per_hr: float | None = None,
    hours_of_oliguria: float | None = None,
) -> KDIGOResult:
    """
    Calculate KDIGO AKI staging.

    Args:
        baseline_creatinine: Baseline serum creatinine (mg/dL)
        current_creatinine: Current serum creatinine (mg/dL)
        creatinine_48h_ago: Creatinine from 48 hours ago (mg/dL), optional
        urine_output_ml_per_kg_per_hr: Urine output rate, optional
        hours_of_oliguria: Duration of oliguria in hours, optional

    Returns:
        KDIGOResult with stage 0-3, criteria met, and recommendation.
    """
    stage = 0
    criteria: list[str] = []

    if baseline_creatinine <= 0:
        return KDIGOResult(
            stage=0,
            criteria_met=["Invalid baseline creatinine"],
            recommendation="Unable to calculate KDIGO staging with baseline Cr <= 0.",
        )

    cr_ratio = current_creatinine / baseline_creatinine

    # Stage 3 criteria (check first — highest severity)
    stage3 = False
    if cr_ratio >= 3.0:
        stage3 = True
        criteria.append(
            f"Creatinine >= 3x baseline ({current_creatinine:.1f} / {baseline_creatinine:.1f} = {cr_ratio:.1f}x)"
        )
    if current_creatinine >= 4.0 and (creatinine_48h_ago is not None and
                                       current_creatinine - creatinine_48h_ago >= 0.3):
        stage3 = True
        criteria.append(
            f"Creatinine >= 4.0 mg/dL ({current_creatinine:.1f}) with acute rise >= 0.3"
        )
    if (urine_output_ml_per_kg_per_hr is not None and hours_of_oliguria is not None):
        if urine_output_ml_per_kg_per_hr < 0.3 and hours_of_oliguria >= 24:
            stage3 = True
            criteria.append(
                f"UO < 0.3 mL/kg/hr for >= 24h ({urine_output_ml_per_kg_per_hr:.2f} for {hours_of_oliguria:.0f}h)"
            )
        if urine_output_ml_per_kg_per_hr == 0 and hours_of_oliguria >= 12:
            stage3 = True
            criteria.append(f"Anuria for >= 12h ({hours_of_oliguria:.0f}h)")

    if stage3:
        stage = 3

    # Stage 2 criteria
    if stage < 2:
        stage2 = False
        if 2.0 <= cr_ratio < 3.0:
            stage2 = True
            criteria.append(
                f"Creatinine 2.0-2.9x baseline ({cr_ratio:.1f}x)"
            )
        if (urine_output_ml_per_kg_per_hr is not None and hours_of_oliguria is not None
                and urine_output_ml_per_kg_per_hr < 0.5 and hours_of_oliguria >= 12):
            stage2 = True
            criteria.append(
                f"UO < 0.5 mL/kg/hr for >= 12h ({urine_output_ml_per_kg_per_hr:.2f} for {hours_of_oliguria:.0f}h)"
            )
        if stage2:
            stage = 2

    # Stage 1 criteria
    if stage < 1:
        stage1 = False
        if creatinine_48h_ago is not None:
            cr_rise_48h = current_creatinine - creatinine_48h_ago
            if cr_rise_48h >= 0.3:
                stage1 = True
                criteria.append(
                    f"Creatinine rise >= 0.3 mg/dL in 48h ({cr_rise_48h:.1f})"
                )
        if 1.5 <= cr_ratio < 2.0:
            stage1 = True
            criteria.append(
                f"Creatinine 1.5-1.9x baseline ({cr_ratio:.1f}x)"
            )
        if (urine_output_ml_per_kg_per_hr is not None and hours_of_oliguria is not None
                and urine_output_ml_per_kg_per_hr < 0.5
                and 6 <= hours_of_oliguria < 12):
            stage1 = True
            criteria.append(
                f"UO < 0.5 mL/kg/hr for 6-12h ({urine_output_ml_per_kg_per_hr:.2f} for {hours_of_oliguria:.0f}h)"
            )
        if stage1:
            stage = 1

    # Generate recommendation
    recommendations = {
        0: "No AKI. Continue routine renal monitoring.",
        1: (
            "KDIGO Stage 1 AKI. Optimize hemodynamics and volume status. "
            "Avoid nephrotoxins. Monitor creatinine and urine output q6-12h. "
            "Review medication dosing for renal function."
        ),
        2: (
            "KDIGO Stage 2 AKI. Urgent nephrology consult recommended. "
            "Consider renal replacement therapy if worsening. "
            "Strict I&O monitoring. Avoid contrast and nephrotoxins. "
            "Monitor electrolytes q6h."
        ),
        3: (
            "KDIGO Stage 3 AKI. Emergent nephrology consult. "
            "Evaluate for renal replacement therapy (RRT/dialysis). "
            "Monitor for hyperkalemia, acidosis, and volume overload. "
            "ICU-level monitoring recommended."
        ),
    }

    return KDIGOResult(
        stage=stage,
        criteria_met=criteria if criteria else ["No AKI criteria met"],
        recommendation=recommendations[stage],
    )


# =============================================================================
# Aggregate Scoring
# =============================================================================

def calculate_all_available_scores(
    vitals: dict[str, Any],
    labs: dict[str, Any] | None = None,
) -> dict[str, dict]:
    """
    Calculate all applicable clinical scores from available data.

    Args:
        vitals: Dict with keys like 'heart_rate', 'systolic_bp', 'diastolic_bp',
                'respiratory_rate', 'spo2', 'temperature_c', 'supplemental_o2',
                'consciousness', 'gcs'
        labs: Optional dict with keys like 'creatinine', 'baseline_creatinine',
              'platelets', 'bilirubin', 'lactate', 'pao2_fio2_ratio', 'wbc'

    Returns:
        Dict mapping score name to result dict. Only includes scores
        that had sufficient data to calculate.
    """
    results: dict[str, dict] = {}
    labs = labs or {}

    # NEWS2 — requires core vitals
    news2_fields = ["respiratory_rate", "spo2", "systolic_bp", "temperature_c"]
    pulse_key = "pulse" if "pulse" in vitals else "heart_rate"
    has_pulse = pulse_key in vitals

    if all(k in vitals for k in news2_fields) and has_pulse:
        try:
            result = calculate_news2(
                respiratory_rate=vitals["respiratory_rate"],
                spo2=vitals["spo2"],
                systolic_bp=vitals["systolic_bp"],
                pulse=vitals[pulse_key],
                consciousness=vitals.get("consciousness", "A"),
                temperature=vitals["temperature_c"],
                supplemental_o2=vitals.get("supplemental_o2", False),
                spo2_scale=vitals.get("spo2_scale", 1),
            )
            results["NEWS2"] = result.to_dict()
        except Exception as e:
            logger.warning(f"NEWS2 calculation failed: {e}")

    # qSOFA — requires SBP, RR, GCS
    if "systolic_bp" in vitals and "respiratory_rate" in vitals:
        gcs = vitals.get("gcs", labs.get("gcs"))
        if gcs is not None:
            try:
                result = calculate_qsofa(
                    systolic_bp=vitals["systolic_bp"],
                    respiratory_rate=vitals["respiratory_rate"],
                    gcs=gcs,
                )
                results["qSOFA"] = result.to_dict()
            except Exception as e:
                logger.warning(f"qSOFA calculation failed: {e}")

    # SOFA — partial calculation with available data
    sofa_has_data = any(
        k in labs for k in [
            "pao2_fio2_ratio", "platelets", "bilirubin", "creatinine",
        ]
    ) or "gcs" in vitals or "mean_arterial_pressure" in vitals

    if sofa_has_data:
        try:
            map_val = vitals.get("mean_arterial_pressure")
            if map_val is None and "systolic_bp" in vitals and "diastolic_bp" in vitals:
                map_val = (vitals["systolic_bp"] + 2 * vitals["diastolic_bp"]) / 3

            result = calculate_sofa(
                pao2_fio2_ratio=labs.get("pao2_fio2_ratio"),
                on_ventilator=vitals.get("on_ventilator", False),
                platelets=labs.get("platelets"),
                bilirubin=labs.get("bilirubin"),
                mean_arterial_pressure=map_val,
                vasopressor=vitals.get("vasopressor"),
                vasopressor_dose=vitals.get("vasopressor_dose"),
                gcs=vitals.get("gcs"),
                creatinine=labs.get("creatinine"),
                urine_output_ml_day=labs.get("urine_output_ml_day"),
                baseline_score=labs.get("sofa_baseline"),
            )
            results["SOFA"] = result.to_dict()
        except Exception as e:
            logger.warning(f"SOFA calculation failed: {e}")

    # KDIGO — requires creatinine values
    if "creatinine" in labs and "baseline_creatinine" in labs:
        try:
            result = calculate_kdigo(
                baseline_creatinine=labs["baseline_creatinine"],
                current_creatinine=labs["creatinine"],
                creatinine_48h_ago=labs.get("creatinine_48h_ago"),
                urine_output_ml_per_kg_per_hr=labs.get("urine_output_ml_per_kg_per_hr"),
                hours_of_oliguria=labs.get("hours_of_oliguria"),
            )
            results["KDIGO"] = result.to_dict()
        except Exception as e:
            logger.warning(f"KDIGO calculation failed: {e}")

    return results
