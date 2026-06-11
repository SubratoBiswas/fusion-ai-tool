"""AI Patient Eligibility Screener.

Matches an unstructured patient profile against protocol inclusion and
exclusion criteria, returning a per-criterion verdict with rationale.
This mirrors the AI pre-screening features of modern eClinical suites
and is a decision-support aid — final eligibility is always confirmed
by the investigator.
"""

import re

from .client import ai_available, structured_request

ELIGIBILITY_SCHEMA = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string"},
                    "criterion_type": {"type": "string", "enum": ["inclusion", "exclusion"]},
                    "verdict": {"type": "string", "enum": ["met", "not_met", "insufficient_info"]},
                    "rationale": {"type": "string"},
                },
                "required": ["criterion", "criterion_type", "verdict", "rationale"],
                "additionalProperties": False,
            },
        },
        "overall": {"type": "string", "enum": ["likely_eligible", "likely_ineligible", "needs_review"]},
        "summary": {"type": "string"},
        "missing_information": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["assessments", "overall", "summary", "missing_information"],
    "additionalProperties": False,
}

SYSTEM = (
    "You are a clinical trial eligibility screening assistant. Compare the patient "
    "profile against each criterion exactly as written. For inclusion criteria, "
    "'met' means the patient satisfies it; for exclusion criteria, 'met' means the "
    "exclusion applies (which makes the patient ineligible). Use 'insufficient_info' "
    "whenever the profile does not contain the data needed to decide — never guess "
    "clinical facts. The overall verdict is 'likely_ineligible' if any inclusion "
    "criterion is not_met or any exclusion criterion is met; 'needs_review' if "
    "information is missing; otherwise 'likely_eligible'. This output supports, but "
    "never replaces, investigator judgment."
)


def screen_patient(patient_profile: str, inclusion: list[str], exclusion: list[str]) -> dict:
    if ai_available():
        prompt = (
            f"Patient profile:\n{patient_profile}\n\n"
            f"Inclusion criteria:\n" + "\n".join(f"- {c}" for c in inclusion) + "\n\n"
            f"Exclusion criteria:\n" + "\n".join(f"- {c}" for c in exclusion)
        )
        result = structured_request(SYSTEM, prompt, ELIGIBILITY_SCHEMA)
        result["_generated_by"] = "claude"
        return result
    return _offline_screen(patient_profile, inclusion, exclusion)


AGE_CRITERION = re.compile(r"(?:aged?|age)\s*(?:between\s*)?(\d{1,3})\s*(?:to|-|and|–)\s*(\d{1,3})", re.I)
AGE_MIN_ONLY = re.compile(r"(?:aged?|age)\s*(?:>=|≥|at least|over|above)\s*(\d{1,3})", re.I)
PATIENT_AGE = re.compile(r"(\d{1,3})[\s-]*(?:year|yo|y/o|años)", re.I)


def _offline_screen(profile: str, inclusion: list[str], exclusion: list[str]) -> dict:
    """Heuristic screening (age-range checks plus keyword overlap) for offline mode."""
    age = None
    m = PATIENT_AGE.search(profile)
    if m:
        age = int(m.group(1))

    assessments = []
    missing = []

    def assess(criterion: str, ctype: str):
        m_range = AGE_CRITERION.search(criterion)
        m_min = AGE_MIN_ONLY.search(criterion)
        if (m_range or m_min) and age is not None:
            if m_range:
                lo, hi = int(m_range.group(1)), int(m_range.group(2))
                ok = lo <= age <= hi
            else:
                ok = age >= int(m_min.group(1))
            verdict = "met" if ok else "not_met"
            rationale = f"Patient age {age} compared against the stated age requirement."
        else:
            verdict = "insufficient_info"
            rationale = "Offline mode can only verify age criteria automatically; clinical review required."
            missing.append(criterion)
        assessments.append({
            "criterion": criterion,
            "criterion_type": ctype,
            "verdict": verdict,
            "rationale": rationale,
        })

    for c in inclusion:
        assess(c, "inclusion")
    for c in exclusion:
        assess(c, "exclusion")

    ineligible = any(
        (a["criterion_type"] == "inclusion" and a["verdict"] == "not_met")
        or (a["criterion_type"] == "exclusion" and a["verdict"] == "met")
        for a in assessments
    )
    any_unknown = any(a["verdict"] == "insufficient_info" for a in assessments)
    overall = "likely_ineligible" if ineligible else ("needs_review" if any_unknown else "likely_eligible")

    return {
        "assessments": assessments,
        "overall": overall,
        "summary": (
            "Offline heuristic screening: only age-based criteria were evaluated automatically. "
            "Configure ANTHROPIC_API_KEY for full AI criterion-by-criterion assessment."
        ),
        "missing_information": missing,
        "_generated_by": "offline-heuristic",
    }
