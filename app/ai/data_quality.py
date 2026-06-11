"""AI-assisted Data Quality Review.

Runs deterministic edit checks over a study's EDC data (the kind a data
manager would script in a classic CDMS), then asks Claude to write the
data-review narrative a sponsor would expect in a periodic report.
Findings are persisted as data queries so site staff can resolve them.
"""

from .client import ai_available, text_request

NARRATIVE_SYSTEM = (
    "You are a senior clinical data manager writing a concise data-quality review "
    "for a sponsor. Given structured findings from automated edit checks, write a "
    "short narrative: lead with the overall data health, call out the findings that "
    "most affect subject safety or primary-endpoint integrity, and recommend "
    "concrete next actions for the site and data management team. Keep it under "
    "250 words and use plain prose, not headings."
)


def run_edit_checks(study: dict, participants: list[dict], adverse_events: list[dict]) -> list[dict]:
    """Deterministic edit checks. Each finding: {participant_id, field, issue, severity}."""
    findings = []

    for p in participants:
        if p["age"] is None:
            findings.append({
                "participant_id": p["id"],
                "subject_code": p["subject_code"],
                "field": "demographics.age",
                "issue": "Age is missing — required for eligibility verification and dosing.",
                "severity": "major",
            })
        elif p["age"] < 18:
            findings.append({
                "participant_id": p["id"],
                "subject_code": p["subject_code"],
                "field": "demographics.age",
                "issue": f"Age {p['age']} is below 18 — verify against the protocol's adult inclusion criterion; possible eligibility deviation.",
                "severity": "critical",
            })
        if p["sex"] not in ("M", "F") and p["sex"] is not None:
            findings.append({
                "participant_id": p["id"],
                "subject_code": p["subject_code"],
                "field": "demographics.sex",
                "issue": f"Unexpected sex value '{p['sex']}'.",
                "severity": "minor",
            })

    subject_by_id = {p["id"]: p["subject_code"] for p in participants}
    for ae in adverse_events:
        code = subject_by_id.get(ae["participant_id"], "?")
        if not ae["preferred_term"]:
            findings.append({
                "participant_id": ae["participant_id"],
                "subject_code": code,
                "field": f"ae[{ae['id']}].preferred_term",
                "issue": f"Adverse event '{ae['verbatim_term']}' is not yet medically coded.",
                "severity": "major",
            })
        if ae["serious"] and ae["severity"] == "Mild":
            findings.append({
                "participant_id": ae["participant_id"],
                "subject_code": code,
                "field": f"ae[{ae['id']}].severity",
                "issue": f"AE '{ae['verbatim_term']}' is flagged serious but graded Mild — confirm seriousness criteria vs severity grading.",
                "severity": "major",
            })
        if ae["serious"] and ae["outcome"] in (None, ""):
            findings.append({
                "participant_id": ae["participant_id"],
                "subject_code": code,
                "field": f"ae[{ae['id']}].outcome",
                "issue": f"Serious AE '{ae['verbatim_term']}' has no outcome recorded.",
                "severity": "critical",
            })

    return findings


def review_narrative(study: dict, findings: list[dict], participant_count: int) -> str:
    if not findings:
        return (
            f"All automated edit checks passed for {study['protocol_id']} across "
            f"{participant_count} participants. No open data quality findings."
        )
    if ai_available():
        findings_text = "\n".join(
            f"- [{f['severity'].upper()}] Subject {f['subject_code']}, field {f['field']}: {f['issue']}"
            for f in findings
        )
        prompt = (
            f"Study: {study['protocol_id']} — {study['title']} ({study['phase']}, "
            f"{participant_count} participants enrolled).\n\n"
            f"Automated edit check findings:\n{findings_text}"
        )
        return text_request(NARRATIVE_SYSTEM, prompt)
    by_sev = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    sev_summary = ", ".join(f"{v} {k}" for k, v in sorted(by_sev.items()))
    return (
        f"Automated edit checks for {study['protocol_id']} identified {len(findings)} finding(s) "
        f"({sev_summary}) across {participant_count} participants. Critical and major findings "
        f"should be queried to sites immediately. Configure ANTHROPIC_API_KEY for an AI-written "
        f"data review narrative with prioritized recommendations."
    )
