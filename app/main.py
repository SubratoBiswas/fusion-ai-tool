"""FusionTrials — AI-powered clinical research platform.

A unified eClinical demo combining a CTMS-style operations dashboard
with Claude-powered modules: protocol design, eligibility screening,
medical coding, data-quality review, and registry intelligence.
"""

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai.client import ai_available
from .ai.coding import code_terms
from .ai.data_quality import review_narrative, run_edit_checks
from .ai.eligibility import screen_patient
from .ai.protocol import generate_protocol
from .ai.registry import search_trials
from .database import get_db, init_db, rows_to_dicts

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="FusionTrials", version="1.0.0", lifespan=lifespan)

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


# ---------- Core CTMS endpoints ----------

@app.get("/api/health")
def health():
    return {"status": "ok", "ai_enabled": ai_available()}


@app.get("/api/dashboard")
def dashboard():
    with get_db() as db:
        studies = rows_to_dicts(db.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM participants p WHERE p.study_id = s.id AND p.status NOT IN ('Screen Failure')) AS enrolled,
                   (SELECT COUNT(*) FROM sites st WHERE st.study_id = s.id) AS site_count,
                   (SELECT COUNT(*) FROM adverse_events ae WHERE ae.study_id = s.id) AS ae_count,
                   (SELECT COUNT(*) FROM adverse_events ae WHERE ae.study_id = s.id AND ae.serious = 1) AS sae_count,
                   (SELECT COUNT(*) FROM data_queries q WHERE q.study_id = s.id AND q.status = 'open') AS open_queries
            FROM studies s ORDER BY s.id
            """
        ).fetchall())
        totals = db.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM studies) AS studies,
                (SELECT COUNT(*) FROM sites) AS sites,
                (SELECT COUNT(*) FROM participants WHERE status NOT IN ('Screen Failure')) AS participants,
                (SELECT COUNT(*) FROM adverse_events WHERE serious = 1) AS saes,
                (SELECT COUNT(*) FROM data_queries WHERE status = 'open') AS open_queries
            """
        ).fetchone()
    return {"totals": dict(totals), "studies": studies, "ai_enabled": ai_available()}


@app.get("/api/studies/{study_id}")
def study_detail(study_id: int):
    with get_db() as db:
        study = db.execute("SELECT * FROM studies WHERE id = ?", (study_id,)).fetchone()
        if not study:
            raise HTTPException(404, "Study not found")
        sites = rows_to_dicts(db.execute("SELECT * FROM sites WHERE study_id = ?", (study_id,)).fetchall())
        participants = rows_to_dicts(db.execute(
            "SELECT p.*, st.name AS site_name FROM participants p JOIN sites st ON st.id = p.site_id WHERE p.study_id = ?",
            (study_id,),
        ).fetchall())
        aes = rows_to_dicts(db.execute(
            "SELECT ae.*, p.subject_code FROM adverse_events ae JOIN participants p ON p.id = ae.participant_id WHERE ae.study_id = ? ORDER BY ae.reported_at DESC",
            (study_id,),
        ).fetchall())
        queries = rows_to_dicts(db.execute(
            "SELECT * FROM data_queries WHERE study_id = ? ORDER BY created_at DESC",
            (study_id,),
        ).fetchall())
    return {"study": dict(study), "sites": sites, "participants": participants, "adverse_events": aes, "queries": queries}


# ---------- AI module endpoints ----------

@app.post("/api/ai/protocol")
def ai_protocol(concept: ProtocolConcept):
    result = generate_protocol(concept.model_dump())
    with get_db() as db:
        db.execute(
            "INSERT INTO protocols (title, indication, phase, content_json, generated_by) VALUES (?,?,?,?,?)",
            (result.get("title", "Untitled"), concept.indication, concept.phase,
             json.dumps(result), result.get("_generated_by", "unknown")),
        )
    return result


@app.get("/api/ai/protocols")
def list_protocols():
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT id, title, indication, phase, generated_by, created_at FROM protocols ORDER BY id DESC LIMIT 20"
        ).fetchall())
    return {"protocols": rows}


@app.post("/api/ai/eligibility")
def ai_eligibility(req: EligibilityRequest):
    return screen_patient(req.patient_profile, req.inclusion_criteria, req.exclusion_criteria)


@app.post("/api/ai/code-events")
def ai_code_events(req: CodingRequest):
    return code_terms(req.verbatim_terms)


@app.post("/api/ai/data-review/{study_id}")
def ai_data_review(study_id: int):
    with get_db() as db:
        study = db.execute("SELECT * FROM studies WHERE id = ?", (study_id,)).fetchone()
        if not study:
            raise HTTPException(404, "Study not found")
        study = dict(study)
        participants = rows_to_dicts(db.execute(
            "SELECT * FROM participants WHERE study_id = ?", (study_id,)
        ).fetchall())
        aes = rows_to_dicts(db.execute(
            "SELECT * FROM adverse_events WHERE study_id = ?", (study_id,)
        ).fetchall())

        findings = run_edit_checks(study, participants, aes)

        # Persist findings as open data queries, skipping duplicates already raised.
        existing = {
            (q["participant_id"], q["field"])
            for q in rows_to_dicts(db.execute(
                "SELECT participant_id, field FROM data_queries WHERE study_id = ?", (study_id,)
            ).fetchall())
        }
        created = 0
        for f in findings:
            key = (f["participant_id"], f["field"])
            if key not in existing:
                db.execute(
                    "INSERT INTO data_queries (study_id, participant_id, field, issue, severity) VALUES (?,?,?,?,?)",
                    (study_id, f["participant_id"], f["field"], f["issue"], f["severity"]),
                )
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
