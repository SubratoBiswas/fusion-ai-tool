"""24/7 Project and Clinical Data Reporting.

Always-available study reports aggregating every module — enrollment,
data quality, safety, ePRO compliance, supply, and consent — plus CSV
dataset exports for sponsors and statisticians.
"""

import csv
import io

from ..database import find_all, find_one, get_db, now_iso

EXPORT_DATASETS = {
    "participants": ["id", "subject_code", "site_id", "age", "sex", "status", "arm",
                     "randomized_at", "enrolled_at"],
    "adverse_events": ["id", "participant_id", "verbatim_term", "preferred_term",
                       "system_organ_class", "severity", "serious", "outcome", "reported_at"],
    "data_queries": ["id", "participant_id", "field", "issue", "severity", "status",
                     "response", "created_at"],
    "crf_records": ["id", "participant_id", "form_name", "status", "entered_at"],
    "epro_submissions": ["id", "participant_id", "instrument_id", "score", "alert", "submitted_at"],
    "safety_cases": ["id", "case_number", "participant_id", "ae_id", "status", "causality",
                     "expectedness", "expedited", "report_due", "opened_at"],
}


def study_report(study_id: int) -> dict:
    study = find_one("studies", {"id": study_id})
    if not study:
        raise ValueError("Study not found")
    db = get_db()

    participants = find_all("participants", {"study_id": study_id})
    active = [p for p in participants if p["status"] != "Screen Failure"]
    sites = find_all("sites", {"study_id": study_id})
    aes = find_all("adverse_events", {"study_id": study_id})
    queries = find_all("data_queries", {"study_id": study_id})
    crf_records = find_all("crf_records", {"study_id": study_id})
    epro_subs = find_all("epro_submissions", {"study_id": study_id})
    kits = find_all("kits", {"study_id": study_id})
    cases = find_all("safety_cases", {"study_id": study_id})

    by_status: dict[str, int] = {}
    for p in participants:
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1

    site_rows = []
    for s in sites:
        pids = [p["id"] for p in participants if p["site_id"] == s["id"]]
        site_rows.append({
            "site": s["name"], "country": s["country"], "status": s["status"],
            "enrolled": sum(1 for p in participants if p["site_id"] == s["id"] and p["status"] != "Screen Failure"),
            "open_queries": sum(1 for q in queries if q.get("participant_id") in pids and q["status"] == "open"),
            "aes": sum(1 for a in aes if a["participant_id"] in pids),
        })

    by_soc: dict[str, int] = {}
    for a in aes:
        soc = a["system_organ_class"] or "Uncoded"
        by_soc[soc] = by_soc.get(soc, 0) + 1

    open_queries = [q for q in queries if q["status"] == "open"]
    by_severity: dict[str, int] = {}
    for q in open_queries:
        by_severity[q["severity"]] = by_severity.get(q["severity"], 0) + 1

    consent_records = find_all("consent_records", {"study_id": study_id})
    consented_ids = {r["participant_id"] for r in consent_records}
    missing_consent = sum(1 for p in active if p["id"] not in consented_ids)

    return {
        "generated_at": now_iso(),
        "study": {k: study[k] for k in ("id", "protocol_id", "title", "phase", "status", "target_enrollment")},
        "enrollment": {
            "enrolled": len(active),
            "target": study["target_enrollment"],
            "pct_of_target": round(100 * len(active) / study["target_enrollment"], 1),
            "randomized": sum(1 for p in active if p.get("arm")),
            "by_status": by_status,
            "by_site": site_rows,
        },
        "data_quality": {
            "crf_records": len(crf_records),
            "crf_clean": sum(1 for r in crf_records if r["status"] == "clean"),
            "queries_total": len(queries),
            "queries_open": len(open_queries),
            "open_by_severity": by_severity,
        },
        "safety": {
            "total_aes": len(aes),
            "saes": sum(1 for a in aes if a["serious"]),
            "uncoded": sum(1 for a in aes if not a["preferred_term"]),
            "by_soc": by_soc,
            "open_cases": sum(1 for c in cases if c["status"] != "closed"),
            "expedited_cases": sum(1 for c in cases if c.get("expedited")),
        },
        "epro": {
            "submissions": len(epro_subs),
            "alerts": sum(1 for s in epro_subs if s["alert"]),
            "avg_score": round(sum(s["score"] for s in epro_subs) / len(epro_subs), 1) if epro_subs else None,
        },
        "supply": {
            "kits_available": sum(1 for k in kits if k["status"] == "available"),
            "kits_dispensed": sum(1 for k in kits if k["status"] == "dispensed"),
        },
        "consent": {
            "consented": len(active) - missing_consent,
            "missing": missing_consent,
        },
        "available_exports": sorted(EXPORT_DATASETS),
    }


def export_csv(study_id: int, dataset: str) -> tuple[str, str]:
    """Return (filename, csv_text) for the requested dataset."""
    if dataset not in EXPORT_DATASETS:
        raise ValueError(f"Unknown dataset '{dataset}'. Available: {sorted(EXPORT_DATASETS)}")
    study = find_one("studies", {"id": study_id})
    if not study:
        raise ValueError("Study not found")

    columns = EXPORT_DATASETS[dataset]
    rows = find_all(dataset, {"study_id": study_id}, sort=[("id", 1)])
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for r in rows:
        writer.writerow([_csv_value(r.get(c)) for c in columns])
    filename = f"{study['protocol_id']}_{dataset}.csv"
    return filename, buf.getvalue()


def _csv_value(v):
    if isinstance(v, (list, dict)):
        return ";".join(map(str, v)) if isinstance(v, list) else str(v)
    return v
