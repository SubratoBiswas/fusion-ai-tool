"""ePRO — Electronic Patient-Reported Outcomes.

Patients (or site staff on their behalf) submit instrument responses on
a 0-10 scale. Any item scored >= 8 fires a symptom alert and raises a
data query so the site follows up — the eCOA-vigilance pattern modern
DCT platforms market.
"""

from ..database import find_all, find_one, insert, now_iso

ALERT_THRESHOLD = 8
SCALE_MIN, SCALE_MAX = 0, 10


def list_instruments() -> list[dict]:
    return find_all("epro_instruments")


def list_submissions(study_id: int) -> list[dict]:
    subs = find_all("epro_submissions", {"study_id": study_id}, sort=[("id", -1)])
    subjects = {p["id"]: p["subject_code"] for p in find_all("participants", {"study_id": study_id})}
    instruments = {i["id"]: i["name"] for i in find_all("epro_instruments")}
    for s in subs:
        s["subject_code"] = subjects.get(s["participant_id"], "?")
        s["instrument_name"] = instruments.get(s["instrument_id"], "?")
    return subs


def submit(participant_id: int, instrument_id: int, responses: dict) -> dict:
    p = find_one("participants", {"id": participant_id})
    if not p:
        raise ValueError("Participant not found")
    instrument = find_one("epro_instruments", {"id": instrument_id})
    if not instrument:
        raise ValueError("Instrument not found")

    codes = {q["code"] for q in instrument["questions"]}
    cleaned = {}
    for code in codes:
        if code not in responses or responses[code] in (None, ""):
            raise ValueError(f"Missing response for '{code}'")
        try:
            val = int(responses[code])
        except (TypeError, ValueError):
            raise ValueError(f"Response for '{code}' must be an integer 0-10")
        if not (SCALE_MIN <= val <= SCALE_MAX):
            raise ValueError(f"Response for '{code}' must be between {SCALE_MIN} and {SCALE_MAX}")
        cleaned[code] = val

    alert_items = [c for c, v in cleaned.items() if v >= ALERT_THRESHOLD]
    submission = insert("epro_submissions", {
        "study_id": p["study_id"],
        "participant_id": participant_id,
        "instrument_id": instrument_id,
        "responses": cleaned,
        "score": sum(cleaned.values()),
        "alert": bool(alert_items),
        "submitted_at": now_iso(),
    })

    if alert_items:
        insert("data_queries", {
            "study_id": p["study_id"],
            "participant_id": participant_id,
            "field": f"epro.{instrument['name']}",
            "issue": (
                f"PRO symptom alert for {p['subject_code']}: "
                + ", ".join(f"{c} scored {cleaned[c]}/10" for c in alert_items)
                + " — site follow-up required."
            ),
            "severity": "major",
            "status": "open",
            "created_at": now_iso(),
        })

    submission["subject_code"] = p["subject_code"]
    submission["instrument_name"] = instrument["name"]
    return submission
