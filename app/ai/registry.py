"""Trial Registry Intelligence.

Searches the public ClinicalTrials.gov v2 API for competitive/landscape
intelligence and (when AI is enabled) summarizes the landscape — a
lightweight version of the feasibility tooling CROs use during study
startup.
"""

import httpx

from .client import ai_available, text_request

CTGOV_URL = "https://clinicaltrials.gov/api/v2/studies"

SUMMARY_SYSTEM = (
    "You are a clinical trial feasibility analyst. Given a list of registered "
    "trials from ClinicalTrials.gov, summarize the competitive landscape for a "
    "sponsor planning a study in this space: dominant phases, common designs or "
    "endpoints visible from the titles, recruitment status mix, and what that "
    "implies for site competition and enrollment feasibility. Under 200 words."
)


def search_trials(query: str, limit: int = 10) -> dict:
    try:
        resp = httpx.get(
            CTGOV_URL,
            params={"query.term": query, "pageSize": limit},
            timeout=15,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"error": f"ClinicalTrials.gov request failed: {exc}", "trials": [], "summary": None}

    trials = []
    for study in data.get("studies", []):
        ps = study.get("protocolSection", {})
        ident = ps.get("identificationModule", {})
        status = ps.get("statusModule", {})
        design = ps.get("designModule", {})
        sponsor = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
        conditions = ps.get("conditionsModule", {}).get("conditions", [])
        trials.append({
            "nct_id": ident.get("nctId"),
            "title": ident.get("briefTitle"),
            "status": status.get("overallStatus"),
            "phase": ", ".join(design.get("phases", []) or []) or "N/A",
            "conditions": conditions[:3],
            "sponsor": sponsor.get("name"),
        })

    summary = None
    if trials and ai_available():
        listing = "\n".join(
            f"- {t['nct_id']}: {t['title']} | {t['phase']} | {t['status']} | sponsor: {t['sponsor']}"
            for t in trials
        )
        summary = text_request(SUMMARY_SYSTEM, f"Search query: {query}\n\nTrials:\n{listing}")

    return {"query": query, "count": len(trials), "trials": trials, "summary": summary}
