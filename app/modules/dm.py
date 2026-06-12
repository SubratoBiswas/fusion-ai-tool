"""Data Management (DM) — query workbench.

Central worklist for data queries raised by EDC edit checks, ePRO
symptom alerts, and the AI data review. Sites respond; data managers
close. Complements the AI data review narrative in the same module.
"""

from ..database import find_all, find_one, get_db, now_iso

QUERY_STATUSES = ("open", "answered", "closed")


def list_queries(study_id: int, status: str | None = None) -> list[dict]:
    query = {"study_id": study_id}
    if status:
        if status not in QUERY_STATUSES:
            raise ValueError(f"Status must be one of {QUERY_STATUSES}")
        query["status"] = status
    queries = find_all("data_queries", query, sort=[("id", -1)])
    subjects = {p["id"]: p["subject_code"] for p in find_all("participants", {"study_id": study_id})}
    for q in queries:
        q["subject_code"] = subjects.get(q.get("participant_id"), "—")
    return queries


def respond(query_id: int, response: str) -> dict:
    q = find_one("data_queries", {"id": query_id})
    if not q:
        raise ValueError("Query not found")
    if q["status"] == "closed":
        raise ValueError("Query is already closed")
    if not response.strip():
        raise ValueError("Response text is required")
    updates = {"status": "answered", "response": response.strip(), "responded_at": now_iso()}
    get_db().data_queries.update_one({"id": query_id}, {"$set": updates})
    q.update(updates)
    return q


def close(query_id: int) -> dict:
    q = find_one("data_queries", {"id": query_id})
    if not q:
        raise ValueError("Query not found")
    updates = {"status": "closed", "closed_at": now_iso()}
    get_db().data_queries.update_one({"id": query_id}, {"$set": updates})
    q.update(updates)
    return q
