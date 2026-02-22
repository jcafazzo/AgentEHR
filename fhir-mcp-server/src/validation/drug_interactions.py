"""
Drug Interaction Validation

Checks for drug-drug and drug-allergy interactions when creating medication orders.
Uses a simplified rule-based approach for demonstration purposes.

In production, this would integrate with:
- RxNorm API for drug normalization
- FDA drug interaction databases
- Clinical decision support systems
"""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("fhir-mcp-server.validation")


class InteractionSeverity(str, Enum):
    """Severity levels for drug interactions."""
    CONTRAINDICATED = "contraindicated"  # Should not be given together
    SEVERE = "severe"                     # Major interaction, requires monitoring
    MODERATE = "moderate"                 # May need dose adjustment
    MINOR = "minor"                       # Usually safe, be aware
    INFO = "info"                         # Informational only


@dataclass
class DrugInteraction:
    """A drug-drug interaction warning."""
    severity: InteractionSeverity
    drug1: str
    drug2: str
    description: str
    recommendation: str


@dataclass
class AllergyInteraction:
    """A drug-allergy interaction warning."""
    severity: InteractionSeverity
    drug: str
    allergen: str
    reaction_type: str
    recommendation: str


# Common drug-drug interactions (simplified knowledge base)
# In production, this would come from a clinical database
DRUG_INTERACTIONS = [
    # Anticoagulant interactions
    {
        "drugs": ["warfarin", "aspirin"],
        "severity": InteractionSeverity.SEVERE,
        "description": "Increased bleeding risk when combining warfarin with aspirin",
        "recommendation": "Use with caution. Monitor for signs of bleeding. Consider alternative if possible.",
    },
    {
        "drugs": ["warfarin", "ibuprofen"],
        "severity": InteractionSeverity.SEVERE,
        "description": "NSAIDs increase bleeding risk and may reduce warfarin metabolism",
        "recommendation": "Avoid combination if possible. Use acetaminophen for pain relief instead.",
    },
    {
        "drugs": ["warfarin", "naproxen"],
        "severity": InteractionSeverity.SEVERE,
        "description": "NSAIDs increase bleeding risk and may reduce warfarin metabolism",
        "recommendation": "Avoid combination if possible. Use acetaminophen for pain relief instead.",
    },
    # ACE inhibitor + Potassium interactions
    {
        "drugs": ["lisinopril", "potassium"],
        "severity": InteractionSeverity.MODERATE,
        "description": "ACE inhibitors can increase potassium levels; supplementation may cause hyperkalemia",
        "recommendation": "Monitor serum potassium levels regularly.",
    },
    {
        "drugs": ["enalapril", "potassium"],
        "severity": InteractionSeverity.MODERATE,
        "description": "ACE inhibitors can increase potassium levels; supplementation may cause hyperkalemia",
        "recommendation": "Monitor serum potassium levels regularly.",
    },
    # Metformin + Contrast dye
    {
        "drugs": ["metformin", "contrast"],
        "severity": InteractionSeverity.SEVERE,
        "description": "Metformin should be held before and after contrast procedures due to risk of lactic acidosis",
        "recommendation": "Hold metformin 48 hours before and after contrast administration. Check renal function.",
    },
    # Statin interactions
    {
        "drugs": ["simvastatin", "amiodarone"],
        "severity": InteractionSeverity.SEVERE,
        "description": "Amiodarone increases simvastatin levels, raising risk of myopathy",
        "recommendation": "Limit simvastatin dose to 20mg daily or consider alternative statin.",
    },
    {
        "drugs": ["simvastatin", "clarithromycin"],
        "severity": InteractionSeverity.CONTRAINDICATED,
        "description": "Clarithromycin significantly increases statin levels, high myopathy risk",
        "recommendation": "Avoid combination. Use azithromycin as alternative antibiotic.",
    },
    # SSRIs + MAOIs
    {
        "drugs": ["sertraline", "phenelzine"],
        "severity": InteractionSeverity.CONTRAINDICATED,
        "description": "Serotonin syndrome risk - potentially fatal",
        "recommendation": "Never combine SSRIs with MAOIs. Requires washout period.",
    },
    {
        "drugs": ["fluoxetine", "phenelzine"],
        "severity": InteractionSeverity.CONTRAINDICATED,
        "description": "Serotonin syndrome risk - potentially fatal",
        "recommendation": "Never combine SSRIs with MAOIs. Requires washout period.",
    },
    # QT prolongation
    {
        "drugs": ["amiodarone", "haloperidol"],
        "severity": InteractionSeverity.SEVERE,
        "description": "Both drugs prolong QT interval; combination increases arrhythmia risk",
        "recommendation": "Monitor ECG. Consider alternative agents.",
    },
    # Diabetes medications
    {
        "drugs": ["metformin", "alcohol"],
        "severity": InteractionSeverity.MODERATE,
        "description": "Alcohol increases risk of lactic acidosis with metformin",
        "recommendation": "Limit alcohol intake. Monitor for symptoms of lactic acidosis.",
    },
    {
        "drugs": ["insulin", "metformin"],
        "severity": InteractionSeverity.MINOR,
        "description": "Combination may increase hypoglycemia risk",
        "recommendation": "Monitor blood glucose closely when initiating combination therapy.",
    },
]

# Common drug-allergy cross-reactivity patterns
ALLERGY_CROSS_REACTIONS = [
    {
        "allergen": "penicillin",
        "drugs": ["amoxicillin", "ampicillin", "penicillin", "piperacillin"],
        "cross_reactivity": "high",
        "description": "Direct penicillin class allergy",
    },
    {
        "allergen": "penicillin",
        "drugs": ["cephalexin", "ceftriaxone", "cefazolin"],
        "cross_reactivity": "moderate",
        "description": "~2-5% cross-reactivity between penicillins and cephalosporins",
    },
    {
        "allergen": "sulfa",
        "drugs": ["sulfamethoxazole", "trimethoprim-sulfamethoxazole", "bactrim"],
        "cross_reactivity": "high",
        "description": "Sulfonamide antibiotic allergy",
    },
    {
        "allergen": "aspirin",
        "drugs": ["ibuprofen", "naproxen", "ketorolac"],
        "cross_reactivity": "moderate",
        "description": "NSAID cross-sensitivity in aspirin-sensitive patients",
    },
    {
        "allergen": "codeine",
        "drugs": ["morphine", "hydrocodone", "oxycodone"],
        "cross_reactivity": "high",
        "description": "Opioid cross-sensitivity",
    },
]


def normalize_drug_name(name: str) -> str:
    """Normalize drug name for comparison."""
    return name.lower().strip()


def check_drug_interactions(
    new_medication: str,
    current_medications: list[str],
) -> list[DrugInteraction]:
    """
    Check for drug-drug interactions between a new medication and current medications.

    Args:
        new_medication: Name of the medication being ordered
        current_medications: List of patient's current medication names

    Returns:
        List of DrugInteraction warnings
    """
    warnings = []
    new_med_normalized = normalize_drug_name(new_medication)

    for current_med in current_medications:
        current_med_normalized = normalize_drug_name(current_med)

        for interaction in DRUG_INTERACTIONS:
            drugs_normalized = [normalize_drug_name(d) for d in interaction["drugs"]]

            # Check if both drugs in the interaction pair are present
            if (new_med_normalized in drugs_normalized[0] or drugs_normalized[0] in new_med_normalized) and \
               (current_med_normalized in drugs_normalized[1] or drugs_normalized[1] in current_med_normalized):
                warnings.append(DrugInteraction(
                    severity=interaction["severity"],
                    drug1=new_medication,
                    drug2=current_med,
                    description=interaction["description"],
                    recommendation=interaction["recommendation"],
                ))
            elif (new_med_normalized in drugs_normalized[1] or drugs_normalized[1] in new_med_normalized) and \
                 (current_med_normalized in drugs_normalized[0] or drugs_normalized[0] in current_med_normalized):
                warnings.append(DrugInteraction(
                    severity=interaction["severity"],
                    drug1=new_medication,
                    drug2=current_med,
                    description=interaction["description"],
                    recommendation=interaction["recommendation"],
                ))

    return warnings


def check_allergy_interactions(
    new_medication: str,
    allergies: list[str],
) -> list[AllergyInteraction]:
    """
    Check for drug-allergy interactions.

    Args:
        new_medication: Name of the medication being ordered
        allergies: List of patient's known allergies

    Returns:
        List of AllergyInteraction warnings
    """
    warnings = []
    new_med_normalized = normalize_drug_name(new_medication)

    for allergy in allergies:
        allergy_normalized = normalize_drug_name(allergy)

        for pattern in ALLERGY_CROSS_REACTIONS:
            allergen_normalized = normalize_drug_name(pattern["allergen"])

            # Check if patient has this allergy
            if allergen_normalized not in allergy_normalized and allergy_normalized not in allergen_normalized:
                continue

            # Check if new medication is in the cross-reactive drugs
            for drug in pattern["drugs"]:
                drug_normalized = normalize_drug_name(drug)
                if drug_normalized in new_med_normalized or new_med_normalized in drug_normalized:
                    severity = InteractionSeverity.CONTRAINDICATED if pattern["cross_reactivity"] == "high" else InteractionSeverity.SEVERE

                    warnings.append(AllergyInteraction(
                        severity=severity,
                        drug=new_medication,
                        allergen=allergy,
                        reaction_type=pattern["description"],
                        recommendation=f"Patient has documented {allergy} allergy. {pattern['description']}. Consider alternative medication.",
                    ))

    return warnings


def validate_medication_safety(
    medication_name: str,
    current_medications: list[str],
    allergies: list[str],
) -> dict:
    """
    Comprehensive medication safety check.

    Args:
        medication_name: The medication being ordered
        current_medications: Patient's current medication list
        allergies: Patient's known allergies

    Returns:
        Dictionary with validation results and warnings
    """
    drug_interactions = check_drug_interactions(medication_name, current_medications)
    allergy_interactions = check_allergy_interactions(medication_name, allergies)

    # Determine overall safety status
    all_warnings = []

    for interaction in drug_interactions:
        all_warnings.append({
            "type": "drug_interaction",
            "severity": interaction.severity.value,
            "code": "drug-drug-interaction",
            "message": interaction.description,
            "details": {
                "drug1": interaction.drug1,
                "drug2": interaction.drug2,
                "recommendation": interaction.recommendation,
            },
        })

    for interaction in allergy_interactions:
        all_warnings.append({
            "type": "allergy_interaction",
            "severity": interaction.severity.value,
            "code": "drug-allergy-interaction",
            "message": interaction.reaction_type,
            "details": {
                "drug": interaction.drug,
                "allergen": interaction.allergen,
                "recommendation": interaction.recommendation,
            },
        })

    # Determine if any are blockers
    has_contraindication = any(
        w["severity"] == InteractionSeverity.CONTRAINDICATED.value
        for w in all_warnings
    )

    has_severe = any(
        w["severity"] == InteractionSeverity.SEVERE.value
        for w in all_warnings
    )

    return {
        "medication": medication_name,
        "safe": len(all_warnings) == 0,
        "requires_override": has_contraindication,
        "requires_attention": has_severe,
        "warnings": all_warnings,
        "warning_count": len(all_warnings),
    }
