"""eTMF — Electronic Trial Master File.

Tracks study documents against a simplified TMF Reference Model
essential-artifact list, computes inspection-readiness (completeness),
and surfaces missing artifacts — the gap analysis a TMF manager runs
before an audit.
"""

from ..database import TMF_ESSENTIAL_ARTIFACTS, find_all, find_one, get_db, insert, now_iso

VALID_STATUSES = ("draft", "final", "approved")


def study_tmf(study_id: int) -> dict:
    study = find_one("studies", {"id": study_id})
    if not study:
        raise ValueError("Study not found")
    docs = find_all("tmf_documents", {"study_id": study_id}, sort=[("zone", 1)])

    filed = {(d["zone"], d["artifact"]) for d in docs if d["status"] == "approved"}
    missing = [
        {"zone": zone, "artifact": artifact}
        for zone, artifact in TMF_ESSENTIAL_ARTIFACTS
        if (zone, artifact) not in filed
    ]
    completeness = round(
        100 * (len(TMF_ESSENTIAL_ARTIFACTS) - len(missing)) / len(TMF_ESSENTIAL_ARTIFACTS)
    )

    return {
        "study_id": study_id,
        "protocol_id": study["protocol_id"],
        "completeness_pct": completeness,
        "documents": docs,
        "missing_essential": missing,
        "essential_artifacts": [
            {"zone": z, "artifact": a} for z, a in TMF_ESSENTIAL_ARTIFACTS
        ],
    }


def add_document(study_id: int, zone: str, artifact: str, title: str, version: str = "1.0",
                 status: str = "draft", uploaded_by: str = "web") -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"Status must be one of {VALID_STATUSES}")
    if not find_one("studies", {"id": study_id}):
        raise ValueError("Study not found")
    return insert("tmf_documents", {
        "study_id": study_id, "zone": zone, "artifact": artifact, "title": title,
        "status": status, "version": version, "uploaded_by": uploaded_by,
        "uploaded_at": now_iso(),
    })


def approve_document(doc_id: int) -> dict:
    doc = find_one("tmf_documents", {"id": doc_id})
    if not doc:
        raise ValueError("Document not found")
    get_db().tmf_documents.update_one({"id": doc_id}, {"$set": {"status": "approved"}})
    doc["status"] = "approved"
    return doc
