"""eConsent — informed consent version tracking.

Tracks which ICF version each participant signed. When a protocol
amendment introduces a new ICF version, participants on superseded
versions are flagged for re-consent; participants with no consent on
file are flagged as critical findings.
"""

from ..database import find_all, find_one, insert, now_iso


def list_versions(study_id: int) -> list[dict]:
    return find_all("consent_versions", {"study_id": study_id}, sort=[("id", 1)])


def consent_status(study_id: int) -> dict:
    if not find_one("studies", {"id": study_id}):
        raise ValueError("Study not found")
    versions = {v["id"]: v for v in list_versions(study_id)}
    current = next((v for v in versions.values() if v["is_current"]), None)

    participants = find_all("participants", {"study_id": study_id}, sort=[("id", 1)])
    records = find_all("consent_records", {"study_id": study_id}, sort=[("id", 1)])
    latest_by_participant = {}
    for r in records:
        latest_by_participant[r["participant_id"]] = r  # later records overwrite

    rows = []
    for p in participants:
        if p["status"] == "Screen Failure":
            continue
        rec = latest_by_participant.get(p["id"])
        if not rec:
            status = "missing"
            signed = None
        else:
            v = versions.get(rec["consent_version_id"])
            signed = {"version": v["version"], "title": v["title"], "consented_at": rec["consented_at"]} if v else None
            status = "current" if (v and current and v["id"] == current["id"]) else "reconsent_required"
        rows.append({
            "participant_id": p["id"], "subject_code": p["subject_code"],
            "participant_status": p["status"], "consent_status": status, "signed": signed,
        })

    return {
        "study_id": study_id,
        "current_version": current,
        "versions": list(versions.values()),
        "participants": rows,
        "summary": {
            "current": sum(1 for r in rows if r["consent_status"] == "current"),
            "reconsent_required": sum(1 for r in rows if r["consent_status"] == "reconsent_required"),
            "missing": sum(1 for r in rows if r["consent_status"] == "missing"),
        },
    }


def record_consent(participant_id: int, consent_version_id: int) -> dict:
    p = find_one("participants", {"id": participant_id})
    if not p:
        raise ValueError("Participant not found")
    v = find_one("consent_versions", {"id": consent_version_id, "study_id": p["study_id"]})
    if not v:
        raise ValueError("Consent version not found for this participant's study")
    rec = insert("consent_records", {
        "study_id": p["study_id"], "participant_id": participant_id,
        "consent_version_id": consent_version_id, "consented_at": now_iso(),
    })
    rec["subject_code"] = p["subject_code"]
    rec["version"] = v["version"]
    return rec
