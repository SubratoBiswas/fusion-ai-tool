"""AI Protocol Designer.

Generates a structured clinical study protocol synopsis from a short
study concept — the same capability marketed by leading eClinical
platforms (AI protocol generation). Uses Claude with a JSON schema so
the output is always machine-readable and renderable.
"""

from .client import ai_available, structured_request

PROTOCOL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "background": {"type": "string"},
        "objectives": {
            "type": "object",
            "properties": {
                "primary": {"type": "string"},
                "secondary": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["primary", "secondary"],
            "additionalProperties": False,
        },
        "design": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "duration": {"type": "string"},
                "arms": {"type": "array", "items": {"type": "string"}},
                "randomization": {"type": "string"},
                "blinding": {"type": "string"},
            },
            "required": ["type", "duration", "arms", "randomization", "blinding"],
            "additionalProperties": False,
        },
        "population": {
            "type": "object",
            "properties": {
                "inclusion_criteria": {"type": "array", "items": {"type": "string"}},
                "exclusion_criteria": {"type": "array", "items": {"type": "string"}},
                "sample_size_rationale": {"type": "string"},
            },
            "required": ["inclusion_criteria", "exclusion_criteria", "sample_size_rationale"],
            "additionalProperties": False,
        },
        "endpoints": {
            "type": "object",
            "properties": {
                "primary": {"type": "array", "items": {"type": "string"}},
                "secondary": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["primary", "secondary"],
            "additionalProperties": False,
        },
        "statistical_considerations": {"type": "string"},
        "safety_monitoring": {"type": "string"},
    },
    "required": [
        "title", "background", "objectives", "design",
        "population", "endpoints", "statistical_considerations", "safety_monitoring",
    ],
    "additionalProperties": False,
}

SYSTEM = (
    "You are an expert clinical research protocol writer with deep knowledge of "
    "ICH-GCP, FDA, and EMA guidance. Draft a scientifically rigorous protocol "
    "synopsis for the study concept provided. Be specific and realistic: name "
    "plausible endpoints with timeframes, criteria with measurable thresholds, "
    "and statistical approaches appropriate to the phase. This is a draft for a "
    "medical writer to refine — it must be flagged for expert review downstream."
)


def generate_protocol(concept: dict) -> dict:
    prompt = (
        f"Study concept:\n"
        f"- Working title: {concept.get('title', 'Untitled study')}\n"
        f"- Indication / condition: {concept.get('indication', 'not specified')}\n"
        f"- Phase: {concept.get('phase', 'not specified')}\n"
        f"- Intervention: {concept.get('intervention', 'not specified')}\n"
        f"- Comparator: {concept.get('comparator', 'investigator choice / placebo as appropriate')}\n"
        f"- Additional notes: {concept.get('notes', 'none')}\n\n"
        f"Draft the full protocol synopsis."
    )
    if ai_available():
        result = structured_request(SYSTEM, prompt, PROTOCOL_SCHEMA)
        result["_generated_by"] = "claude"
        return result
    return _offline_protocol(concept)


def _offline_protocol(concept: dict) -> dict:
    """Deterministic template used when no API key is configured."""
    indication = concept.get("indication", "the target condition")
    intervention = concept.get("intervention", "the investigational product")
    phase = concept.get("phase", "Phase II")
    comparator = concept.get("comparator") or "placebo"
    return {
        "title": concept.get("title") or f"A {phase} Study of {intervention} in {indication}",
        "background": (
            f"{indication} represents an area of unmet medical need. {intervention} is being "
            f"developed to address this need. This synopsis is a structural template generated "
            f"in offline mode — configure ANTHROPIC_API_KEY for AI-drafted scientific content."
        ),
        "objectives": {
            "primary": f"To evaluate the efficacy of {intervention} versus {comparator} in participants with {indication}.",
            "secondary": [
                f"To evaluate the safety and tolerability of {intervention}.",
                f"To characterize the pharmacokinetics of {intervention}.",
            ],
        },
        "design": {
            "type": f"Randomized, controlled, parallel-group {phase} study",
            "duration": "24-week treatment period with 4-week safety follow-up",
            "arms": [f"{intervention}", f"{comparator}"],
            "randomization": "1:1 central randomization stratified by site",
            "blinding": "Double-blind",
        },
        "population": {
            "inclusion_criteria": [
                "Adults aged 18 to 75 years, inclusive",
                f"Confirmed diagnosis of {indication}",
                "Able and willing to provide written informed consent",
            ],
            "exclusion_criteria": [
                "Participation in another interventional study within 30 days",
                "Pregnancy or breastfeeding",
                "Any condition that, in the investigator's judgment, would compromise participant safety",
            ],
            "sample_size_rationale": "Sample size to be determined by the study statistician based on the expected effect size, 90% power, and two-sided alpha of 0.05.",
        },
        "endpoints": {
            "primary": [f"Change from baseline in the primary disease activity measure for {indication} at Week 24"],
            "secondary": [
                "Incidence of treatment-emergent adverse events through end of study",
                "Proportion of participants achieving clinically meaningful response at Week 24",
            ],
        },
        "statistical_considerations": (
            "Primary analysis on the intent-to-treat population using a mixed model for repeated "
            "measures (MMRM). Safety analyses descriptive on the safety population."
        ),
        "safety_monitoring": (
            "An independent Data Safety Monitoring Board will review unblinded safety data at "
            "pre-specified intervals. All serious adverse events reported within 24 hours."
        ),
        "_generated_by": "offline-template",
    }
