"""Site Management.

Site activation workflow (pending -> active -> closed) plus per-site
performance metrics: enrollment, open queries, and adverse events.
"""

from ..database import find_all, find_one, get_db, insert

SITE_STATUSES = ("Pending Activation", "Active", "Closed")


def site_overview(study_id: int) -> list[dict]:
    if not find_one("studies", {"id": study_id}):
        raise ValueError("Study not found")
    db = get_db()
    sites = find_all("sites", {"study_id": study_id}, sort=[("id", 1)])
    for s in sites:
        sid = s["id"]
        s["enrolled"] = db.participants.count_documents(
            {"site_id": sid, "status": {"$nin": ["Screen Failure"]}})
        s["open_queries"] = db.data_queries.count_documents({
            "study_id": study_id, "status": "open",
            "participant_id": {"$in": [p["id"] for p in find_all("participants", {"site_id": sid})] or [-1]},
        })
        s["ae_count"] = db.adverse_events.count_documents({
            "participant_id": {"$in": [p["id"] for p in find_all("participants", {"site_id": sid})] or [-1]},
        })
    return sites


def add_site(study_id: int, name: str, country: str, pi_name: str) -> dict:
    if not find_one("studies", {"id": study_id}):
        raise ValueError("Study not found")
    if not (name.strip() and country.strip() and pi_name.strip()):
        raise ValueError("Name, country, and PI name are all required")
    return insert("sites", {
        "study_id": study_id, "name": name.strip(), "country": country.strip(),
        "pi_name": pi_name.strip(), "status": "Pending Activation",
    })


def set_status(site_id: int, status: str) -> dict:
    if status not in SITE_STATUSES:
        raise ValueError(f"Status must be one of {SITE_STATUSES}")
    site = find_one("sites", {"id": site_id})
    if not site:
        raise ValueError("Site not found")
    if status == "Closed":
        active = get_db().participants.count_documents(
            {"site_id": site_id, "status": "Enrolled"})
        if active:
            raise ValueError(f"Cannot close site with {active} actively enrolled participant(s)")
    get_db().sites.update_one({"id": site_id}, {"$set": {"status": status}})
    site["status"] = status
    return site
