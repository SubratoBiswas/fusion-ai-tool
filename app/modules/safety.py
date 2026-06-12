"""AE/SAE Tracking and Safety Database (pharmacovigilance).

AE/SAE Tracking: sites report adverse events with automatic medical
coding (Claude when enabled, offline dictionary otherwise). Serious
events automatically open a case in the Safety Database.

Safety Database: pharmacovigilance case workflow — medical assessment
(causality, expectedness, seriousness criteria), expedited-reporting
determination with regulatory clocks (7-day for fatal/life-threatening
SUSARs, 15-day otherwise), AI-drafted case narratives, and closure.
"""

from datetime import datetime, timedelta, timezone

from ..ai.client import ai_available, text_request
from ..ai.coding import code_terms
from ..database import find_all, find_one, get_db, insert, next_id, now_iso

SEVERITIES = ("Mild", "Moderate", "Severe")
CAUSALITIES = ("not related", "unlikely related", "possibly related", "probably related", "related")
EXPECTEDNESS = ("expected", "unexpected")
SERIOUSNESS_CRITERIA = (
    "death", "life-threatening", "hospitalization",
    "disability", "congenital anomaly", "medically significant",
)

NARRATIVE_SYSTEM = (
    "You are a pharmacovigilance medical writer. Draft a concise ICSR-style case "
    "narrative from the structured case data provided: patient demographics, the "
    "event with onset and outcome, seriousness criteria, causality and "
    "expectedness assessment, and study context. Write in the conventional "
    "third-person PV narrative style, under 200 words, single paragraph. The "
    "narrative is a draft for safety physician review."
)


# ---------- AE/SAE Tracking ----------

def report_ae(study_id: int, participant_id: int, verbatim_term: str, severity: str,
              serious: bool, outcome: str | None = None) -> dict:
    if severity not in SEVERITIES:
        raise ValueError(f"Severity must be one of {SEVERITIES}")
    p = find_one("participants", {"id": participant_id, "study_id": study_id})
    if not p:
        raise ValueError("Participant not found in this study")

    coding = code_terms([verbatim_term])["codings"][0]
    uncoded = coding["preferred_term"] == "UNCODED"
    ae = insert("adverse_events", {
        "study_id": study_id, "participant_id": participant_id,
        "verbatim_term": verbatim_term,
        "preferred_term": None if uncoded else coding["preferred_term"],
        "system_organ_class": None if uncoded else coding["system_organ_class"],
        "severity": severity, "serious": 1 if serious else 0,
        "outcome": outcome, "reported_at": now_iso(),
    })

    case = None
    if serious:
        case = insert("safety_cases", {
            "case_number": f"CASE-{datetime.now(timezone.utc).year}-{next_id('case_number'):04d}",
            "study_id": study_id, "participant_id": participant_id, "ae_id": ae["id"],
            "status": "new", "causality": None, "expectedness": None,
            "seriousness_criteria": [], "expedited": False,
            "narrative": None, "opened_at": now_iso(), "report_due": None,
        })

    ae["subject_code"] = p["subject_code"]
    return {"adverse_event": ae, "coding": coding, "safety_case": case}


def list_aes(study_id: int, serious_only: bool = False) -> list[dict]:
    query = {"study_id": study_id}
    if serious_only:
        query["serious"] = 1
    aes = find_all("adverse_events", query, sort=[("id", -1)])
    subjects = {p["id"]: p["subject_code"] for p in find_all("participants", {"study_id": study_id})}
    for a in aes:
        a["subject_code"] = subjects.get(a["participant_id"], "?")
    return aes


def update_outcome(ae_id: int, outcome: str) -> dict:
    ae = find_one("adverse_events", {"id": ae_id})
    if not ae:
        raise ValueError("Adverse event not found")
    get_db().adverse_events.update_one({"id": ae_id}, {"$set": {"outcome": outcome}})
    ae["outcome"] = outcome
    return ae


# ---------- Safety Database ----------

def list_cases(study_id: int | None = None) -> list[dict]:
    query = {"study_id": study_id} if study_id else {}
    cases = find_all("safety_cases", query, sort=[("id", -1)])
    for c in cases:
        ae = find_one("adverse_events", {"id": c["ae_id"]})
        p = find_one("participants", {"id": c["participant_id"]})
        c["event"] = ae["preferred_term"] or ae["verbatim_term"] if ae else "?"
        c["severity"] = ae["severity"] if ae else "?"
        c["subject_code"] = p["subject_code"] if p else "?"
        c["days_to_due"] = _days_to_due(c)
    return cases


def _days_to_due(case: dict) -> int | None:
    if not case.get("report_due"):
        return None
    due = datetime.strptime(case["report_due"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return (due - datetime.now(timezone.utc)).days


def assess_case(case_id: int, causality: str, expectedness: str,
                seriousness_criteria: list[str]) -> dict:
    case = find_one("safety_cases", {"id": case_id})
    if not case:
        raise ValueError("Safety case not found")
    if case["status"] == "closed":
        raise ValueError("Case is closed — reopen workflow not supported in this demo")
    if causality not in CAUSALITIES:
        raise ValueError(f"Causality must be one of {CAUSALITIES}")
    if expectedness not in EXPECTEDNESS:
        raise ValueError(f"Expectedness must be one of {EXPECTEDNESS}")
    bad = [c for c in seriousness_criteria if c not in SERIOUSNESS_CRITERIA]
    if bad:
        raise ValueError(f"Unknown seriousness criteria: {bad}")

    # SUSAR logic: suspected (any degree of relatedness above 'unlikely') AND unexpected.
    suspected = causality in ("possibly related", "probably related", "related")
    expedited = suspected and expectedness == "unexpected"
    report_due = None
    if expedited:
        days = 7 if ("death" in seriousness_criteria or "life-threatening" in seriousness_criteria) else 15
        opened = datetime.strptime(case["opened_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        report_due = (opened + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    updates = {
        "causality": causality, "expectedness": expectedness,
        "seriousness_criteria": seriousness_criteria,
        "expedited": expedited, "report_due": report_due,
        "status": "under_review",
    }
    get_db().safety_cases.update_one({"id": case_id}, {"$set": updates})
    case.update(updates)
    case["days_to_due"] = _days_to_due(case)
    return case


def generate_narrative(case_id: int) -> dict:
    case = find_one("safety_cases", {"id": case_id})
    if not case:
        raise ValueError("Safety case not found")
    ae = find_one("adverse_events", {"id": case["ae_id"]})
    p = find_one("participants", {"id": case["participant_id"]})
    study = find_one("studies", {"id": case["study_id"]})

    if ai_available():
        prompt = (
            f"Case {case['case_number']} — study {study['protocol_id']} ({study['title']}).\n"
            f"Subject {p['subject_code']}: {p['age'] or 'age unknown'}-year-old {'male' if p['sex'] == 'M' else 'female'}, "
            f"arm: {p.get('arm') or 'not randomized'}.\n"
            f"Event: '{ae['verbatim_term']}' (coded: {ae['preferred_term'] or 'uncoded'}), "
            f"severity {ae['severity']}, outcome {ae['outcome'] or 'unknown'}, reported {ae['reported_at']}.\n"
            f"Seriousness criteria: {', '.join(case['seriousness_criteria']) or 'not yet assessed'}.\n"
            f"Causality: {case['causality'] or 'not yet assessed'}; expectedness: {case['expectedness'] or 'not yet assessed'}.\n"
            f"Expedited reporting required: {'yes' if case['expedited'] else 'no'}."
        )
        narrative = text_request(NARRATIVE_SYSTEM, prompt)
        generated_by = "claude"
    else:
        sex_word = "male" if p["sex"] == "M" else "female"
        coded_part = f" (coded as {ae['preferred_term']})" if ae["preferred_term"] else ""
        narrative = (
            f"This case ({case['case_number']}) concerns a {p['age'] or 'age-unknown'}-year-old {sex_word} "
            f"subject ({p['subject_code']}) enrolled in study {study['protocol_id']} "
            f"({p.get('arm') or 'treatment arm not assigned'}). The subject experienced "
            f"'{ae['verbatim_term']}'{coded_part}, "
            f"assessed as {ae['severity'].lower()} in severity and serious"
            f"{' (' + ', '.join(case['seriousness_criteria']) + ')' if case['seriousness_criteria'] else ''}. "
            f"Causality was assessed as {case['causality'] or 'pending'}; the event is "
            f"{case['expectedness'] or 'of pending expectedness'} per the reference safety information. "
            f"Outcome at the time of reporting: {ae['outcome'] or 'unknown'}. "
            f"{'Expedited regulatory reporting is required.' if case['expedited'] else 'No expedited reporting is required at this time.'} "
            f"This narrative was generated offline — configure ANTHROPIC_API_KEY for an AI-drafted narrative. "
            f"Draft for safety physician review."
        )
        generated_by = "offline-template"

    get_db().safety_cases.update_one({"id": case_id}, {"$set": {"narrative": narrative}})
    return {"case_id": case_id, "narrative": narrative, "_generated_by": generated_by}


def close_case(case_id: int) -> dict:
    case = find_one("safety_cases", {"id": case_id})
    if not case:
        raise ValueError("Safety case not found")
    if not case.get("causality"):
        raise ValueError("Case cannot be closed before medical assessment (causality/expectedness)")
    get_db().safety_cases.update_one({"id": case_id}, {"$set": {"status": "closed"}})
    case["status"] = "closed"
    return case
