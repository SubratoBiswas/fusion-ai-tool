"""API tests for FusionTrials.

These run entirely offline: no ANTHROPIC_API_KEY (AI fallbacks) and no
MONGODB_URI (in-memory mongomock). They exercise the CTMS endpoints,
the EDC/RTSM/ePRO/eTMF modules, and the rule-based AI fallbacks
against seeded data.
"""

import os

os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("MONGODB_URI", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # Context manager triggers the lifespan handler (DB init + seed).
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ai_enabled"] is False
    assert "mongomock" in body["database"]


def test_dashboard_seeded(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["studies"] == 4
    assert body["totals"]["sites"] == 9  # 8 active + 1 pending activation
    assert body["totals"]["participants"] > 0
    assert body["totals"]["pro_alerts"] >= 1  # seeded fatigue=9 submission
    assert len(body["studies"]) == 4
    first = body["studies"][0]
    assert first["protocol_id"] == "FUS-ONC-301"
    assert first["enrolled"] <= first["target_enrollment"]


def test_study_detail(client):
    r = client.get("/api/studies/1")
    assert r.status_code == 200
    body = r.json()
    assert body["study"]["protocol_id"] == "FUS-ONC-301"
    assert body["study"]["arms"] == ["Fusarinib", "Standard of Care"]
    assert len(body["participants"]) > 0
    assert len(body["adverse_events"]) > 0


def test_study_not_found(client):
    assert client.get("/api/studies/999").status_code == 404


# ---------- EDC ----------

def test_edc_forms_listed(client):
    forms = client.get("/api/edc/forms").json()["forms"]
    names = {f["name"] for f in forms}
    assert {"Demographics", "Vital Signs", "Laboratory"} <= names


def test_edc_clean_record(client):
    r = client.post("/api/edc/records", json={
        "study_id": 1, "participant_id": 1, "form_name": "Vital Signs",
        "data": {"systolic_bp": 122, "diastolic_bp": 78, "heart_rate": 70, "temperature_c": 36.8},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "clean"
    assert body["validation_issues"] == []


def test_edc_edit_checks_raise_queries(client):
    before = client.get("/api/dashboard").json()["totals"]["open_queries"]
    r = client.post("/api/edc/records", json={
        "study_id": 1, "participant_id": 2, "form_name": "Vital Signs",
        "data": {"systolic_bp": 400, "diastolic_bp": 80},  # out of range + missing heart_rate
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queried"
    assert any("above the expected range" in i for i in body["validation_issues"])
    assert any("required" in i for i in body["validation_issues"])
    after = client.get("/api/dashboard").json()["totals"]["open_queries"]
    assert after > before


def test_edc_unknown_form(client):
    r = client.post("/api/edc/records", json={
        "study_id": 1, "participant_id": 1, "form_name": "Nope", "data": {},
    })
    assert r.status_code == 400


# ---------- RTSM ----------

def test_rtsm_supply_overview(client):
    r = client.get("/api/rtsm/supply?study_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["arms"] == ["Fusarinib", "Standard of Care"]
    assert any(p["subject_code"] == "301-007" for p in body["pending_randomization"])
    assert len(body["inventory"]) > 0


def test_rtsm_randomize_assigns_arm_and_kit(client):
    pending = client.get("/api/rtsm/supply?study_id=1").json()["pending_randomization"]
    target = next(p for p in pending if p["subject_code"] == "301-007")
    r = client.post("/api/rtsm/randomize", json={"participant_id": target["id"]})
    assert r.status_code == 200
    body = r.json()
    assert body["arm"] in ("Fusarinib", "Standard of Care")
    assert body["kit_number"] is not None and body["kit_number"].startswith("KIT-")
    # Re-randomizing the same subject must fail
    assert client.post("/api/rtsm/randomize", json={"participant_id": target["id"]}).status_code == 400


def test_rtsm_randomize_screen_failure_rejected(client):
    # 201-003 is a Screen Failure (participant id 10 in seed order)
    detail = client.get("/api/studies/2").json()
    sf = next(p for p in detail["participants"] if p["status"] == "Screen Failure")
    assert client.post("/api/rtsm/randomize", json={"participant_id": sf["id"]}).status_code == 400


# ---------- ePRO ----------

def test_epro_instruments(client):
    instruments = client.get("/api/epro/instruments").json()["instruments"]
    assert {i["name"] for i in instruments} == {"Daily Symptom Diary", "Weekly Quality of Life"}


def test_epro_submission_no_alert(client):
    r = client.post("/api/epro/submissions", json={
        "participant_id": 1, "instrument_id": 1,
        "responses": {"fatigue": 2, "pain": 1, "nausea": 0},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["alert"] is False
    assert body["score"] == 3


def test_epro_submission_alert_opens_query(client):
    before = client.get("/api/dashboard").json()["totals"]["open_queries"]
    r = client.post("/api/epro/submissions", json={
        "participant_id": 1, "instrument_id": 1,
        "responses": {"fatigue": 9, "pain": 3, "nausea": 2},
    })
    assert r.status_code == 200
    assert r.json()["alert"] is True
    after = client.get("/api/dashboard").json()["totals"]["open_queries"]
    assert after == before + 1


def test_epro_invalid_response_rejected(client):
    r = client.post("/api/epro/submissions", json={
        "participant_id": 1, "instrument_id": 1,
        "responses": {"fatigue": 11, "pain": 1, "nausea": 0},
    })
    assert r.status_code == 400


# ---------- eTMF ----------

def test_etmf_completeness_and_missing(client):
    r = client.get("/api/etmf/1")
    assert r.status_code == 200
    body = r.json()
    assert 0 < body["completeness_pct"] < 100
    missing = {(m["zone"], m["artifact"]) for m in body["missing_essential"]}
    # Seeded DMP is draft, not approved -> counts as missing
    assert ("08 Data Management", "Data Management Plan") in missing


def test_etmf_file_and_approve_raises_completeness(client):
    before = client.get("/api/etmf/1").json()["completeness_pct"]
    doc = client.post("/api/etmf/documents", json={
        "study_id": 1, "zone": "09 Statistics", "artifact": "Statistical Analysis Plan",
        "title": "FUS-ONC-301 SAP v1.0", "version": "1.0", "status": "final",
    }).json()
    # Not approved yet -> completeness unchanged
    assert client.get("/api/etmf/1").json()["completeness_pct"] == before
    r = client.post(f"/api/etmf/documents/{doc['id']}/approve")
    assert r.status_code == 200
    assert client.get("/api/etmf/1").json()["completeness_pct"] > before


# ---------- AE/SAE Tracking ----------

def test_ae_report_autocodes_and_opens_case(client):
    r = client.post("/api/safety/ae", json={
        "study_id": 1, "participant_id": 1,
        "verbatim_term": "severe vomiting overnight",
        "severity": "Severe", "serious": True, "outcome": "Ongoing",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["adverse_event"]["preferred_term"] == "Vomiting"
    assert body["safety_case"] is not None
    assert body["safety_case"]["case_number"].startswith("CASE-")
    assert body["safety_case"]["status"] == "new"


def test_ae_nonserious_no_case(client):
    r = client.post("/api/safety/ae", json={
        "study_id": 1, "participant_id": 2,
        "verbatim_term": "mild itching on arms", "severity": "Mild", "serious": False,
    })
    assert r.status_code == 200
    assert r.json()["safety_case"] is None


def test_ae_invalid_severity(client):
    r = client.post("/api/safety/ae", json={
        "study_id": 1, "participant_id": 1,
        "verbatim_term": "headache", "severity": "Catastrophic", "serious": False,
    })
    assert r.status_code == 400


# ---------- Safety Database ----------

def test_safety_cases_seeded(client):
    cases = client.get("/api/safety/cases?study_id=1").json()["cases"]
    assert any(c["status"] == "under_review" and c["expedited"] for c in cases)


def test_safety_case_assessment_susar_clock(client):
    cases = client.get("/api/safety/cases?study_id=4").json()["cases"]
    new_case = next(c for c in cases if c["status"] == "new")
    r = client.post(f"/api/safety/cases/{new_case['id']}/assess", json={
        "causality": "possibly related", "expectedness": "unexpected",
        "seriousness_criteria": ["life-threatening"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["expedited"] is True
    assert body["report_due"] is not None
    assert body["days_to_due"] <= 7  # fatal/life-threatening -> 7-day clock


def test_safety_narrative_and_close(client):
    cases = client.get("/api/safety/cases?study_id=4").json()["cases"]
    case = next(c for c in cases if c["status"] == "under_review")
    n = client.post(f"/api/safety/cases/{case['id']}/narrative")
    assert n.status_code == 200
    assert "narrative" in n.json() and len(n.json()["narrative"]) > 50
    c = client.post(f"/api/safety/cases/{case['id']}/close")
    assert c.status_code == 200
    assert c.json()["status"] == "closed"


def test_safety_close_requires_assessment(client):
    # The just-reported vomiting case is unassessed -> cannot close
    cases = client.get("/api/safety/cases?study_id=1").json()["cases"]
    unassessed = next(c for c in cases if c["status"] == "new" and not c["causality"])
    assert client.post(f"/api/safety/cases/{unassessed['id']}/close").status_code == 400


# ---------- Data Management ----------

def test_dm_query_workbench_respond_close(client):
    # Open queries already exist from the EDC edit-check test above
    queries = client.get("/api/dm/queries?study_id=1&status=open").json()["queries"]
    assert len(queries) > 0
    q = queries[0]
    r = client.post(f"/api/dm/queries/{q['id']}/respond", json={"response": "Source verified; value confirmed correct."})
    assert r.status_code == 200
    assert r.json()["status"] == "answered"
    c = client.post(f"/api/dm/queries/{q['id']}/close")
    assert c.json()["status"] == "closed"
    # Closed query cannot be answered again
    assert client.post(f"/api/dm/queries/{q['id']}/respond", json={"response": "late"}).status_code == 400


# ---------- eConsent ----------

def test_econsent_status_flags(client):
    d = client.get("/api/econsent/status?study_id=1").json()
    assert d["current_version"]["version"] == "2.0"
    assert d["summary"]["reconsent_required"] >= 2  # seeded v1.0 signers
    assert d["summary"]["missing"] >= 1             # 301-007 has no consent on file
    missing = next(p for p in d["participants"] if p["consent_status"] == "missing")
    r = client.post("/api/econsent/consent", json={
        "participant_id": missing["participant_id"],
        "consent_version_id": d["current_version"]["id"],
    })
    assert r.status_code == 200
    d2 = client.get("/api/econsent/status?study_id=1").json()
    assert d2["summary"]["missing"] == d["summary"]["missing"] - 1


# ---------- Site Management ----------

def test_sites_overview_and_activation(client):
    sites_ = client.get("/api/sites?study_id=1").json()["sites"]
    pending = next(s for s in sites_ if s["status"] == "Pending Activation")
    r = client.post(f"/api/sites/{pending['id']}/status", json={"status": "Active"})
    assert r.status_code == 200
    assert r.json()["status"] == "Active"


def test_sites_cannot_close_with_enrolled(client):
    sites_ = client.get("/api/sites?study_id=1").json()["sites"]
    busy = next(s for s in sites_ if s["enrolled"] > 0)
    assert client.post(f"/api/sites/{busy['id']}/status", json={"status": "Closed"}).status_code == 400


def test_sites_add(client):
    r = client.post("/api/sites", json={
        "study_id": 2, "name": "Phoenix Cardio Research", "country": "USA", "pi_name": "Dr. Lee",
    })
    assert r.status_code == 200
    assert r.json()["status"] == "Pending Activation"


# ---------- 24/7 Reporting ----------

def test_study_report_sections(client):
    r = client.get("/api/reports/study/1")
    assert r.status_code == 200
    body = r.json()
    for section in ("enrollment", "data_quality", "safety", "epro", "supply", "consent"):
        assert section in body
    assert body["enrollment"]["target"] == 420
    assert body["safety"]["saes"] >= 2
    assert len(body["enrollment"]["by_site"]) >= 3


def test_report_csv_export(client):
    r = client.get("/api/reports/study/1/export?dataset=adverse_events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("id,participant_id,verbatim_term")
    assert len(lines) > 1


def test_report_csv_unknown_dataset(client):
    assert client.get("/api/reports/study/1/export?dataset=nope").status_code == 400


# ---------- AI fallbacks ----------

def test_protocol_offline_generation(client):
    r = client.post("/api/ai/protocol", json={
        "indication": "resistant hypertension",
        "phase": "Phase II",
        "intervention": "FT-204",
        "comparator": "placebo",
    })
    assert r.status_code == 200
    p = r.json()
    assert p["_generated_by"] == "offline-template"
    assert "FT-204" in p["title"]
    assert len(p["population"]["inclusion_criteria"]) >= 3
    listed = client.get("/api/ai/protocols").json()["protocols"]
    assert any(pr["indication"] == "resistant hypertension" for pr in listed)


def test_eligibility_offline_age_fail(client):
    r = client.post("/api/ai/eligibility", json={
        "patient_profile": "16-year-old female.",
        "inclusion_criteria": ["Age 18 to 75 years"],
        "exclusion_criteria": [],
    })
    body = r.json()
    assert body["assessments"][0]["verdict"] == "not_met"
    assert body["overall"] == "likely_ineligible"


def test_coding_offline_dictionary(client):
    r = client.post("/api/ai/code-events", json={
        "verbatim_terms": ["bad headache for 2 days", "felt sick to stomach", "xyzzy unknown thing"],
    })
    codings = r.json()["codings"]
    assert codings[0]["preferred_term"] == "Headache"
    assert codings[1]["preferred_term"] == "Nausea"
    assert codings[2]["preferred_term"] == "UNCODED"


def test_data_review_creates_queries(client):
    r = client.post("/api/ai/data-review/1")
    assert r.status_code == 200
    body = r.json()
    issues = [f["issue"] for f in body["findings"]]
    assert any("below 18" in i for i in issues)  # seeded under-age subject 301-005
    assert body["queries_created"] >= 1
    assert body["narrative"]
    # Re-running must not duplicate queries
    assert client.post("/api/ai/data-review/1").json()["queries_created"] == 0


def test_trials_search_requires_query(client):
    assert client.get("/api/trials/search?q=%20").status_code == 400


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Fusion AI eClinical Suite" in r.text
