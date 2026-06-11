"""API tests for FusionTrials.

These run entirely in offline mode (no ANTHROPIC_API_KEY required) and
exercise the CTMS endpoints, the rule-based AI fallbacks, and the edit
checks against seeded data.
"""

import os
import tempfile

os.environ["FUSION_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("ANTHROPIC_API_KEY", None)

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


def test_dashboard_seeded(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["studies"] == 4
    assert body["totals"]["sites"] == 8
    assert body["totals"]["participants"] > 0
    assert len(body["studies"]) == 4
    first = body["studies"][0]
    assert first["protocol_id"] == "FUS-ONC-301"
    assert first["enrolled"] <= first["target_enrollment"]


def test_study_detail(client):
    r = client.get("/api/studies/1")
    assert r.status_code == 200
    body = r.json()
    assert body["study"]["protocol_id"] == "FUS-ONC-301"
    assert len(body["participants"]) > 0
    assert len(body["adverse_events"]) > 0


def test_study_not_found(client):
    assert client.get("/api/studies/999").status_code == 404


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
    assert p["objectives"]["primary"]
    assert len(p["population"]["inclusion_criteria"]) >= 3
    # protocol is persisted
    listed = client.get("/api/ai/protocols").json()["protocols"]
    assert any(pr["indication"] == "resistant hypertension" for pr in listed)


def test_eligibility_offline_age_check(client):
    r = client.post("/api/ai/eligibility", json={
        "patient_profile": "72-year-old male with stage IV NSCLC, ECOG 1.",
        "inclusion_criteria": ["Age 18 to 75 years", "Confirmed stage IIIB/IV NSCLC"],
        "exclusion_criteria": ["Untreated brain metastases"],
    })
    assert r.status_code == 200
    body = r.json()
    age_assessment = next(a for a in body["assessments"] if "Age 18" in a["criterion"])
    assert age_assessment["verdict"] == "met"
    assert body["overall"] in ("needs_review", "likely_eligible")


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
    assert r.status_code == 200
    codings = r.json()["codings"]
    assert codings[0]["preferred_term"] == "Headache"
    assert codings[0]["system_organ_class"] == "Nervous system disorders"
    assert codings[1]["preferred_term"] == "Nausea"
    assert codings[2]["preferred_term"] == "UNCODED"
    assert codings[2]["confidence"] == "low"


def test_data_review_creates_queries(client):
    r = client.post("/api/ai/data-review/1")
    assert r.status_code == 200
    body = r.json()
    # Seeded study 1 has an under-age participant (301-005, age 17)
    issues = [f["issue"] for f in body["findings"]]
    assert any("below 18" in i for i in issues)
    assert body["queries_created"] >= 1
    assert body["narrative"]

    # Re-running must not duplicate queries
    r2 = client.post("/api/ai/data-review/1")
    assert r2.json()["queries_created"] == 0


def test_data_review_study_2_missing_age(client):
    body = client.post("/api/ai/data-review/2").json()
    assert any("missing" in f["issue"].lower() for f in body["findings"])


def test_trials_search_requires_query(client):
    assert client.get("/api/trials/search?q=%20").status_code == 400


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "FusionTrials" in r.text
