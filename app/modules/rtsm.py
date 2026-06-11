"""RTSM — Randomization and Trial Supply Management.

Randomizes participants using minimization (assign the arm with the
fewest current allocations, first-listed wins ties) and dispenses the
next available investigational product kit at the participant's site.
Tracks kit inventory so low supply is visible per site and arm.
"""

from ..database import find_all, find_one, get_db, now_iso


def randomize(participant_id: int) -> dict:
    p = find_one("participants", {"id": participant_id})
    if not p:
        raise ValueError("Participant not found")
    if p.get("arm"):
        raise ValueError(f"Subject {p['subject_code']} is already randomized to '{p['arm']}'")
    if p["status"] in ("Screen Failure", "Withdrawn"):
        raise ValueError(f"Subject {p['subject_code']} has status '{p['status']}' and cannot be randomized")

    study = find_one("studies", {"id": p["study_id"]})
    arms = study.get("arms", [])
    if not arms:
        raise ValueError("Study has no treatment arms configured")

    # Minimization: pick the arm with the fewest allocations so far.
    db = get_db()
    counts = {arm: db.participants.count_documents({"study_id": p["study_id"], "arm": arm}) for arm in arms}
    chosen = min(arms, key=lambda a: counts[a])

    # Dispense the next available kit for that arm at the subject's site.
    kit = find_one("kits", {
        "study_id": p["study_id"], "site_id": p["site_id"],
        "arm": chosen, "status": "available",
    })
    warning = None
    if kit:
        db.kits.update_one({"id": kit["id"]}, {"$set": {
            "status": "dispensed",
            "dispensed_to": p["subject_code"],
            "dispensed_at": now_iso(),
        }})
    else:
        warning = (
            f"No available kit for arm '{chosen}' at this site — randomization recorded, "
            f"but resupply is required before dosing."
        )

    db.participants.update_one({"id": participant_id}, {"$set": {
        "arm": chosen, "randomized_at": now_iso(),
    }})

    return {
        "participant_id": participant_id,
        "subject_code": p["subject_code"],
        "arm": chosen,
        "kit_number": kit["kit_number"] if kit else None,
        "warning": warning,
        "allocation_counts": {**counts, chosen: counts[chosen] + 1},
    }


def supply_overview(study_id: int) -> dict:
    study = find_one("studies", {"id": study_id})
    if not study:
        raise ValueError("Study not found")
    kits = find_all("kits", {"study_id": study_id})
    sites = {s["id"]: s["name"] for s in find_all("sites", {"study_id": study_id})}

    inventory = {}
    for k in kits:
        key = (k["site_id"], k["arm"])
        entry = inventory.setdefault(key, {"site_id": k["site_id"], "site_name": sites.get(k["site_id"], "?"),
                                           "arm": k["arm"], "available": 0, "dispensed": 0})
        entry[k["status"] if k["status"] in ("available", "dispensed") else "available"] += 1
    rows = sorted(inventory.values(), key=lambda r: (r["site_id"], r["arm"]))
    for r in rows:
        r["low_stock"] = r["available"] <= 1

    db_arms = study.get("arms", [])
    allocations = {arm: 0 for arm in db_arms}
    pending = []
    for p in find_all("participants", {"study_id": study_id}):
        if p.get("arm"):
            allocations[p["arm"]] = allocations.get(p["arm"], 0) + 1
        elif p["status"] not in ("Screen Failure", "Withdrawn"):
            pending.append({"id": p["id"], "subject_code": p["subject_code"],
                            "site_name": sites.get(p["site_id"], "?"), "status": p["status"]})

    return {
        "study_id": study_id,
        "arms": db_arms,
        "allocations": allocations,
        "pending_randomization": pending,
        "inventory": rows,
    }
