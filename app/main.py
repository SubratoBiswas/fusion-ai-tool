"""Fusion AI eClinical Suite.

A unified AI-powered clinical research platform integrating 16 modules:
CTMS, EDC, Data Management (DM), IWRS (randomization & supply), ePRO,
eTMF, AE/SAE Tracking, Safety Database, eConsent, Site Management,
24/7 project & clinical data reporting, plus Claude-powered AI modules
(protocol design, eligibility screening, medical coding, data review,
registry intelligence). Backed by MongoDB.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai.assistant import chat as assistant_chat
from .ai.client import ai_available
from .ai.coding import code_terms
from .ai.data_quality import review_narrative, run_edit_checks
from .ai.eligibility import screen_patient
from .ai.protocol import generate_protocol
from .ai.registry import search_trials
from .database import find_all, find_one, get_db, init_db, insert, now_iso
from .modules import dm, econsent, edc, epro, etmf, reporting, rtsm, safety, sites


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Fusion AI eClinical Suite", version="3.0.0", lifespan=lifespan)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ---------- Request models ----------

class ProtocolConcept(BaseModel):
    title: str = ""
    indication: str
    phase: str = "Phase II"
    intervention: str
    comparator: str = ""
    notes: str = ""


class EligibilityRequest(BaseModel):
    patient_profile: str = Field(min_length=10)
    inclusion_criteria: list[str]
    exclusion_criteria: list[str] = []


class CodingRequest(BaseModel):
    verbatim_terms: list[str] = Field(min_length=1)


class CrfSubmission(BaseModel):
    study_id: int
    participant_id: int
    form_name: str
    data: dict


class RandomizeRequest(BaseModel):
    participant_id: int


class EproSubmission(BaseModel):
    participant_id: int
    instrument_id: int
    responses: dict


class TmfDocument(BaseModel):
    study_id: int
    zone: str
    artifact: str
    title: str
    version: str = "1.0"
    status: str = "draft"


class AeReport(BaseModel):
    study_id: int
    participant_id: int
    verbatim_term: str = Field(min_length=3)
    severity: str
    serious: bool = False
    outcome: str | None = None


class AeOutcome(BaseModel):
    outcome: str = Field(min_length=2)


class CaseAssessment(BaseModel):
    causality: str
    expectedness: str
    seriousness_criteria: list[str] = []


class QueryResponse(BaseModel):
    response: str = Field(min_length=2)


class ConsentRecord(BaseModel):
    participant_id: int
    consent_version_id: int


class NewSite(BaseModel):
    study_id: int
    name: str
    country: str
    pi_name: str


class SiteStatus(BaseModel):
    status: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)


def _bad_request(fn, *args, **kwargs):
    """Run a module function, translating ValueError into HTTP 400."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ---------- Core CTMS endpoints ----------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "ai_enabled": ai_available(),
        "database": "mongodb" if os.environ.get("MONGODB_URI") else "mongomock (in-memory)",
    }


@app.get("/api/dashboard")
def dashboard():
    db = get_db()
    studies = []
    for s in find_all("studies", sort=[("id", 1)]):
        sid = s["id"]
        studies.append({
            **s,
            "enrolled": db.participants.count_documents({"study_id": sid, "status": {"$ne": "Screen Failure"}}),
            "site_count": db.sites.count_documents({"study_id": sid}),
            "ae_count": db.adverse_events.count_documents({"study_id": sid}),
            "sae_count": db.adverse_events.count_documents({"study_id": sid, "serious": 1}),
            "open_queries": db.data_queries.count_documents({"study_id": sid, "status": "open"}),
        })
    totals = {
        "studies": db.studies.count_documents({}),
        "sites": db.sites.count_documents({}),
        "participants": db.participants.count_documents({"status": {"$ne": "Screen Failure"}}),
        "saes": db.adverse_events.count_documents({"serious": 1}),
        "open_queries": db.data_queries.count_documents({"status": "open"}),
        "pro_alerts": db.epro_submissions.count_documents({"alert": True}),
    }
    return {"totals": totals, "studies": studies, "ai_enabled": ai_available()}


@app.get("/api/studies/{study_id}")
def study_detail(study_id: int):
    study = find_one("studies", {"id": study_id})
    if not study:
        raise HTTPException(404, "Study not found")
    sites = find_all("sites", {"study_id": study_id})
    site_names = {s["id"]: s["name"] for s in sites}
    participants = find_all("participants", {"study_id": study_id}, sort=[("id", 1)])
    for p in participants:
        p["site_name"] = site_names.get(p["site_id"], "?")
    subjects = {p["id"]: p["subject_code"] for p in participants}
    aes = find_all("adverse_events", {"study_id": study_id}, sort=[("id", -1)])
    for a in aes:
        a["subject_code"] = subjects.get(a["participant_id"], "?")
    queries = find_all("data_queries", {"study_id": study_id}, sort=[("id", -1)])
    return {"study": study, "sites": sites, "participants": participants,
            "adverse_events": aes, "queries": queries}


# ---------- EDC ----------

@app.get("/api/edc/forms")
def edc_forms():
    return {"forms": edc.list_forms()}


@app.get("/api/edc/records")
def edc_records(study_id: int):
    return {"records": edc.list_records(study_id)}


@app.post("/api/edc/records")
def edc_submit(sub: CrfSubmission):
    return _bad_request(edc.submit_record, sub.study_id, sub.participant_id, sub.form_name, sub.data)


# ---------- RTSM ----------

@app.post("/api/rtsm/randomize")
def rtsm_randomize(req: RandomizeRequest):
    return _bad_request(rtsm.randomize, req.participant_id)


@app.get("/api/rtsm/supply")
def rtsm_supply(study_id: int):
    return _bad_request(rtsm.supply_overview, study_id)


# ---------- ePRO ----------

@app.get("/api/epro/instruments")
def epro_instruments():
    return {"instruments": epro.list_instruments()}


@app.get("/api/epro/submissions")
def epro_submissions(study_id: int):
    return {"submissions": epro.list_submissions(study_id)}


@app.post("/api/epro/submissions")
def epro_submit(sub: EproSubmission):
    return _bad_request(epro.submit, sub.participant_id, sub.instrument_id, sub.responses)


# ---------- eTMF ----------

@app.get("/api/etmf/{study_id}")
def etmf_study(study_id: int):
    return _bad_request(etmf.study_tmf, study_id)


@app.post("/api/etmf/documents")
def etmf_add(doc: TmfDocument):
    return _bad_request(etmf.add_document, doc.study_id, doc.zone, doc.artifact,
                        doc.title, doc.version, doc.status)


@app.post("/api/etmf/documents/{doc_id}/approve")
def etmf_approve(doc_id: int):
    return _bad_request(etmf.approve_document, doc_id)


# ---------- AE/SAE Tracking ----------

@app.post("/api/safety/ae")
def safety_report_ae(req: AeReport):
    return _bad_request(safety.report_ae, req.study_id, req.participant_id,
                        req.verbatim_term, req.severity, req.serious, req.outcome)


@app.get("/api/safety/aes")
def safety_list_aes(study_id: int, serious_only: bool = False):
    return {"adverse_events": safety.list_aes(study_id, serious_only)}


@app.post("/api/safety/aes/{ae_id}/outcome")
def safety_update_outcome(ae_id: int, req: AeOutcome):
    return _bad_request(safety.update_outcome, ae_id, req.outcome)


# ---------- Safety Database ----------

@app.get("/api/safety/cases")
def safety_cases(study_id: int | None = None):
    return {"cases": safety.list_cases(study_id)}


@app.post("/api/safety/cases/{case_id}/assess")
def safety_assess(case_id: int, req: CaseAssessment):
    return _bad_request(safety.assess_case, case_id, req.causality,
                        req.expectedness, req.seriousness_criteria)


@app.post("/api/safety/cases/{case_id}/narrative")
def safety_narrative(case_id: int):
    return _bad_request(safety.generate_narrative, case_id)


@app.post("/api/safety/cases/{case_id}/close")
def safety_close(case_id: int):
    return _bad_request(safety.close_case, case_id)


# ---------- Data Management (DM) ----------

@app.get("/api/dm/queries")
def dm_queries(study_id: int, status: str | None = None):
    return {"queries": _bad_request(dm.list_queries, study_id, status)}


@app.post("/api/dm/queries/{query_id}/respond")
def dm_respond(query_id: int, req: QueryResponse):
    return _bad_request(dm.respond, query_id, req.response)


@app.post("/api/dm/queries/{query_id}/close")
def dm_close(query_id: int):
    return _bad_request(dm.close, query_id)


# ---------- eConsent ----------

@app.get("/api/econsent/status")
def econsent_status(study_id: int):
    return _bad_request(econsent.consent_status, study_id)


@app.post("/api/econsent/consent")
def econsent_record(req: ConsentRecord):
    return _bad_request(econsent.record_consent, req.participant_id, req.consent_version_id)


# ---------- Site Management ----------

@app.get("/api/sites")
def sites_overview(study_id: int):
    return {"sites": _bad_request(sites.site_overview, study_id)}


@app.post("/api/sites")
def sites_add(req: NewSite):
    return _bad_request(sites.add_site, req.study_id, req.name, req.country, req.pi_name)


@app.post("/api/sites/{site_id}/status")
def sites_status(site_id: int, req: SiteStatus):
    return _bad_request(sites.set_status, site_id, req.status)


# ---------- 24/7 Reporting ----------

@app.get("/api/reports/study/{study_id}")
def report_study(study_id: int):
    return _bad_request(reporting.study_report, study_id)


@app.get("/api/reports/study/{study_id}/export")
def report_export(study_id: int, dataset: str):
    filename, csv_text = _bad_request(reporting.export_csv, study_id, dataset)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- Fusion Assistant (chatbot) ----------

@app.post("/api/assistant/chat")
def assistant_endpoint(req: ChatRequest):
    return _bad_request(assistant_chat, [m.model_dump() for m in req.messages])


# ---------- AI module endpoints ----------

@app.post("/api/ai/protocol")
def ai_protocol(concept: ProtocolConcept):
    result = generate_protocol(concept.model_dump())
    insert("protocols", {
        "title": result.get("title", "Untitled"),
        "indication": concept.indication,
        "phase": concept.phase,
        "content": result,
        "generated_by": result.get("_generated_by", "unknown"),
        "created_at": now_iso(),
    })
    return result


@app.get("/api/ai/protocols")
def list_protocols():
    rows = find_all("protocols", sort=[("id", -1)])[:20]
    for r in rows:
        r.pop("content", None)
    return {"protocols": rows}


@app.post("/api/ai/eligibility")
def ai_eligibility(req: EligibilityRequest):
    return screen_patient(req.patient_profile, req.inclusion_criteria, req.exclusion_criteria)


@app.post("/api/ai/code-events")
def ai_code_events(req: CodingRequest):
    return code_terms(req.verbatim_terms)


@app.post("/api/ai/data-review/{study_id}")
def ai_data_review(study_id: int):
    study = find_one("studies", {"id": study_id})
    if not study:
        raise HTTPException(404, "Study not found")
    participants = find_all("participants", {"study_id": study_id})
    aes = find_all("adverse_events", {"study_id": study_id})

    findings = run_edit_checks(study, participants, aes)

    # Persist findings as open data queries, skipping duplicates already raised.
    existing = {
        (q["participant_id"], q["field"])
        for q in find_all("data_queries", {"study_id": study_id})
    }
    created = 0
    for f in findings:
        key = (f["participant_id"], f["field"])
        if key not in existing:
            insert("data_queries", {
                "study_id": study_id,
                "participant_id": f["participant_id"],
                "field": f["field"],
                "issue": f["issue"],
                "severity": f["severity"],
                "status": "open",
                "created_at": now_iso(),
            })
            created += 1

    narrative = review_narrative(study, findings, len(participants))
    return {
        "study_id": study_id,
        "findings": findings,
        "queries_created": created,
        "narrative": narrative,
        "ai_enabled": ai_available(),
    }


@app.get("/api/trials/search")
def trials_search(q: str, limit: int = 10):
    if not q.strip():
        raise HTTPException(400, "Query parameter 'q' is required")
    return search_trials(q.strip(), min(max(limit, 1), 25))


# ---------- Frontend ----------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
