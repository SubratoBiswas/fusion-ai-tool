"""EDC — Electronic Data Capture.

CRF templates with field-level edit checks applied at entry time
(required fields, numeric ranges, coded values). Out-of-range or
missing values automatically raise data queries, mirroring how a
production EDC fires edit checks on save.
"""

from ..database import find_all, find_one, insert, now_iso


def list_forms() -> list[dict]:
    return find_all("crf_forms")


def list_records(study_id: int) -> list[dict]:
    records = find_all("crf_records", {"study_id": study_id}, sort=[("id", -1)])
    subjects = {p["id"]: p["subject_code"] for p in find_all("participants", {"study_id": study_id})}
    for r in records:
        r["subject_code"] = subjects.get(r["participant_id"], "?")
    return records


def validate_record(template: dict, data: dict) -> list[str]:
    issues = []
    for field in template["fields"]:
        name, label = field["name"], field["label"]
        value = data.get(name)
        if value in (None, ""):
            if field.get("required"):
                issues.append(f"{label} is required but missing.")
            continue
        if field["type"] == "number":
            try:
                num = float(value)
            except (TypeError, ValueError):
                issues.append(f"{label}: '{value}' is not a number.")
                continue
            if "min" in field and num < field["min"]:
                issues.append(f"{label}: {num} is below the expected range (min {field['min']}).")
            if "max" in field and num > field["max"]:
                issues.append(f"{label}: {num} is above the expected range (max {field['max']}).")
        elif field["type"] == "select" and value not in field.get("options", []):
            issues.append(f"{label}: '{value}' is not a permitted value ({', '.join(field['options'])}).")
    return issues


def submit_record(study_id: int, participant_id: int, form_name: str, data: dict) -> dict:
    template = find_one("crf_forms", {"name": form_name})
    if not template:
        raise ValueError(f"Unknown CRF form '{form_name}'")
    participant = find_one("participants", {"id": participant_id, "study_id": study_id})
    if not participant:
        raise ValueError("Participant not found in this study")

    issues = validate_record(template, data)
    record = insert("crf_records", {
        "study_id": study_id,
        "participant_id": participant_id,
        "form_name": form_name,
        "data": data,
        "status": "clean" if not issues else "queried",
        "validation_issues": issues,
        "entered_at": now_iso(),
    })

    # Edit-check failures raise data queries, visible on the CTMS dashboard.
    for issue in issues:
        insert("data_queries", {
            "study_id": study_id,
            "participant_id": participant_id,
            "field": f"edc.{form_name}",
            "issue": issue,
            "severity": "major" if "required" in issue else "minor",
            "status": "open",
            "created_at": now_iso(),
        })

    record["subject_code"] = participant["subject_code"]
    return record
