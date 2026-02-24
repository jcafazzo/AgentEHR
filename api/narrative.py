"""
Patient Narrative Generation Service

Generates concise clinical narratives from structured patient data
using Gemini 3 Flash via OpenRouter. Includes in-memory caching
with hash-based invalidation.
"""

import hashlib
import json
import logging
import time

from openrouter_client import OpenRouterClient

logger = logging.getLogger("agentehr.narrative")

# In-memory cache: {patient_id: {"narrative": str, "generated_at": float, "summary_hash": str}}
_narrative_cache: dict[str, dict] = {}

NARRATIVE_PROMPT = """You are a clinical documentation specialist. Write a concise clinical narrative summary (2-3 short paragraphs) for the following patient data. Write in third person, present tense, clinical style — like a chart summary a physician would read before an encounter.

Cover:
1. Patient demographics and chief active problems
2. Current treatment regimen and key medications
3. Outstanding care gaps or concerns requiring attention

Be factual and cite specific values. Do not add information not present in the data. Keep it under 200 words."""

PATIENT_NARRATIVE_PROMPT = """You are a health literacy specialist. Write a warm, patient-friendly health summary (2-3 short paragraphs) in plain language. Address the patient directly using "you/your". Avoid medical jargon — if you must use a medical term, explain it briefly in parentheses.

Cover:
1. Your main health conditions and what they mean for you
2. Your current medications and why you take each one
3. Any upcoming care items or things to discuss with your doctor

Be encouraging but honest. Keep it under 200 words."""


def _hash_summary(patient_summary: dict) -> str:
    """Create a hash of the patient summary to detect changes."""
    relevant = {
        "patient": patient_summary.get("patient", {}),
        "conditions": patient_summary.get("conditions", []),
        "medications": patient_summary.get("medications", []),
        "allergies": patient_summary.get("allergies", []),
        "careGaps": patient_summary.get("careGaps", []),
    }
    return hashlib.md5(json.dumps(relevant, sort_keys=True, default=str).encode()).hexdigest()


def _format_summary_for_prompt(patient_summary: dict) -> str:
    """Format structured patient data into a readable prompt input."""
    patient = patient_summary.get("patient", {})
    conditions = patient_summary.get("conditions", [])
    medications = patient_summary.get("medications", [])
    allergies = patient_summary.get("allergies", [])
    labs = patient_summary.get("labs", [])
    vitals = patient_summary.get("vitals", [])
    care_gaps = patient_summary.get("careGaps", [])
    incomplete = patient_summary.get("incompleteData", [])

    parts = [
        f"Patient: {patient.get('name', 'Unknown')}, {patient.get('age', '?')}yo {patient.get('gender', '')}, DOB: {patient.get('birthDate', 'Unknown')}",
        "",
        "Active Conditions:",
        *[f"  - {c.get('code', 'Unknown')}" for c in conditions if c.get("isActive")],
        "",
        "Current Medications:",
        *[f"  - {m.get('medication', 'Unknown')}" + (f" {m.get('dosage', '')}" if m.get('dosage') else "") for m in medications],
        "",
        "Allergies:",
        *([f"  - {a.get('substance', 'Unknown')} ({a.get('criticality', 'unknown')} criticality)" for a in allergies] or ["  - None documented"]),
        "",
    ]

    if labs:
        parts.append("Recent Labs:")
        for lab in labs[:10]:
            parts.append(f"  - {lab.get('code', '?')}: {lab.get('value', '?')} ({lab.get('date', '')})")
        parts.append("")

    if vitals:
        parts.append("Recent Vitals:")
        for v in vitals[:5]:
            parts.append(f"  - {v.get('code', '?')}: {v.get('value', '?')} ({v.get('date', '')})")
        parts.append("")

    if care_gaps:
        parts.append("Care Gaps:")
        for g in care_gaps:
            parts.append(f"  - [{g.get('priority', 'routine')}] {g.get('description', '')}")
        parts.append("")

    if incomplete:
        parts.append("Incomplete Data:")
        for i in incomplete:
            parts.append(f"  - {i.get('message', '')}")

    return "\n".join(parts)


async def generate_narrative(patient_summary: dict, mode: str = "clinician") -> str:
    """Generate a clinical narrative from structured patient data using Gemini 3 Flash."""
    client = OpenRouterClient(model="gemini-3-flash")
    prompt = PATIENT_NARRATIVE_PROMPT if mode == "patient" else NARRATIVE_PROMPT

    try:
        formatted_data = _format_summary_for_prompt(patient_summary)

        response = await client.create_message(
            messages=[{"role": "user", "content": formatted_data}],
            system=prompt,
            max_tokens=1024,
            temperature=0.3,
        )

        return response.content or ""
    finally:
        await client.close()


async def get_or_generate_narrative(patient_id: str, patient_summary: dict, mode: str = "clinician") -> dict:
    """Get cached narrative or generate a new one."""
    summary_hash = _hash_summary(patient_summary)
    cache_key = f"{patient_id}:{mode}"

    # Check cache
    cached = _narrative_cache.get(cache_key)
    if cached and cached["summary_hash"] == summary_hash:
        logger.info(f"Narrative cache hit for patient {patient_id} (mode={mode})")
        return {
            "narrative": cached["narrative"],
            "generated_at": cached["generated_at"],
            "cached": True,
        }

    # Generate new narrative
    logger.info(f"Generating narrative for patient {patient_id} (mode={mode})")
    narrative = await generate_narrative(patient_summary, mode=mode)
    now = time.time()

    _narrative_cache[cache_key] = {
        "narrative": narrative,
        "generated_at": now,
        "summary_hash": summary_hash,
    }

    return {
        "narrative": narrative,
        "generated_at": now,
        "cached": False,
    }


def invalidate_narrative(patient_id: str):
    """Invalidate cached narrative for a patient (both modes)."""
    for key in [f"{patient_id}:clinician", f"{patient_id}:patient", patient_id]:
        if key in _narrative_cache:
            del _narrative_cache[key]
    logger.info(f"Invalidated narrative cache for patient {patient_id}")
