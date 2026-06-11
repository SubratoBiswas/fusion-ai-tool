"""AI Medical Coding.

Maps verbatim adverse event terms (as reported by sites) to a MedDRA-style
Preferred Term and System Organ Class — the same workflow Clinion and
Veeva market as "AI medical coding". Output always carries a confidence
score so coders can prioritize manual review.
"""

from .client import ai_available, structured_request

CODING_SCHEMA = {
    "type": "object",
    "properties": {
        "codings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "verbatim": {"type": "string"},
                    "preferred_term": {"type": "string"},
                    "system_organ_class": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "notes": {"type": "string"},
                },
                "required": ["verbatim", "preferred_term", "system_organ_class", "confidence", "notes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["codings"],
    "additionalProperties": False,
}

SYSTEM = (
    "You are a medical coding assistant trained on MedDRA conventions. For each "
    "verbatim adverse event term reported by a clinical site, propose the most "
    "appropriate MedDRA Preferred Term (PT) and its primary System Organ Class "
    "(SOC). Use standard MedDRA spelling (e.g. 'Oedema peripheral', "
    "'Hypoglycaemia'). Mark confidence 'low' when the verbatim is ambiguous, "
    "compound (multiple events in one term), or lacks clinical specificity, and "
    "explain in notes. All codings are suggestions pending human coder approval."
)

# Compact PT/SOC dictionary for offline mode — common AE verbatim patterns.
OFFLINE_DICTIONARY = [
    (("headache", "head ache", "migraine"), "Headache", "Nervous system disorders"),
    (("nausea", "sick to stomach", "queasy"), "Nausea", "Gastrointestinal disorders"),
    (("vomit",), "Vomiting", "Gastrointestinal disorders"),
    (("diarrhea", "diarrhoea", "loose stool"), "Diarrhoea", "Gastrointestinal disorders"),
    (("dizzy", "dizziness", "lighthead"), "Dizziness", "Nervous system disorders"),
    (("fatigue", "tired", "exhaust"), "Fatigue", "General disorders and administration site conditions"),
    (("rash", "hives", "urticaria"), "Rash", "Skin and subcutaneous tissue disorders"),
    (("itch", "pruritus"), "Pruritus", "Skin and subcutaneous tissue disorders"),
    (("fever", "pyrexia", "high temperature"), "Pyrexia", "General disorders and administration site conditions"),
    (("cough",), "Cough", "Respiratory, thoracic and mediastinal disorders"),
    (("short of breath", "dyspnea", "dyspnoea", "breathless"), "Dyspnoea", "Respiratory, thoracic and mediastinal disorders"),
    (("insomnia", "can't sleep", "cannot sleep", "sleepless"), "Insomnia", "Psychiatric disorders"),
    (("anxiety", "anxious"), "Anxiety", "Psychiatric disorders"),
    (("low blood sugar", "hypoglycemia", "hypoglycaemia"), "Hypoglycaemia", "Metabolism and nutrition disorders"),
    (("high blood pressure", "bp spiked", "hypertensi"), "Hypertension", "Vascular disorders"),
    (("swollen ankle", "swelling in legs", "peripheral edema", "oedema"), "Oedema peripheral", "General disorders and administration site conditions"),
    (("neutropenia", "neutrophil"), "Neutropenia", "Blood and lymphatic system disorders"),
    (("anemia", "anaemia", "low hemoglobin"), "Anaemia", "Blood and lymphatic system disorders"),
    (("joint pain", "arthralgia"), "Arthralgia", "Musculoskeletal and connective tissue disorders"),
    (("muscle pain", "myalgia"), "Myalgia", "Musculoskeletal and connective tissue disorders"),
    (("tingling", "paresthesia", "paraesthesia", "pins and needles"), "Paraesthesia", "Nervous system disorders"),
    (("injection site",), "Injection site reaction", "General disorders and administration site conditions"),
    (("constipat",), "Constipation", "Gastrointestinal disorders"),
    (("abdominal pain", "stomach pain", "belly pain"), "Abdominal pain", "Gastrointestinal disorders"),
]


def code_terms(verbatim_terms: list[str]) -> dict:
    if ai_available():
        prompt = "Code these verbatim adverse event terms:\n" + "\n".join(
            f"{i + 1}. {t}" for i, t in enumerate(verbatim_terms)
        )
        result = structured_request(SYSTEM, prompt, CODING_SCHEMA)
        result["_generated_by"] = "claude"
        return result
    return _offline_code(verbatim_terms)


def _offline_code(verbatim_terms: list[str]) -> dict:
    codings = []
    for term in verbatim_terms:
        lowered = term.lower()
        match = None
        for keywords, pt, soc in OFFLINE_DICTIONARY:
            if any(k in lowered for k in keywords):
                match = (pt, soc)
                break
        if match:
            codings.append({
                "verbatim": term,
                "preferred_term": match[0],
                "system_organ_class": match[1],
                "confidence": "medium",
                "notes": "Matched against the built-in offline dictionary; confirm against the current MedDRA release.",
            })
        else:
            codings.append({
                "verbatim": term,
                "preferred_term": "UNCODED",
                "system_organ_class": "UNCODED",
                "confidence": "low",
                "notes": "No offline dictionary match — requires manual coding (or configure ANTHROPIC_API_KEY for AI coding).",
            })
    return {"codings": codings, "_generated_by": "offline-dictionary"}
