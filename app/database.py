"""MongoDB persistence layer for FusionTrials.

Connects to the cluster named by MONGODB_URI (e.g. MongoDB Atlas when
hosted on Render). When MONGODB_URI is not set, falls back to an
in-memory mongomock instance so local development and tests run with
zero infrastructure.

Documents carry an application-level integer `id` (from a counters
collection) so the REST API and frontend stay ObjectId-free.
"""

import os
from datetime import datetime, timezone

from pymongo import MongoClient, ReturnDocument

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        uri = os.environ.get("MONGODB_URI")
        if uri:
            _client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        else:
            import mongomock
            _client = mongomock.MongoClient()
        _db = _client[os.environ.get("MONGODB_DB", "fusiontrials")]
    return _db


def next_id(seq: str) -> int:
    doc = get_db().counters.find_one_and_update(
        {"_id": seq},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return doc["seq"]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def clean(doc):
    """Strip Mongo's _id so documents are JSON-serializable as-is."""
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def find_all(coll: str, query: dict | None = None, sort: list | None = None) -> list[dict]:
    cursor = get_db()[coll].find(query or {})
    if sort:
        cursor = cursor.sort(sort)
    return [clean(d) for d in cursor]


def find_one(coll: str, query: dict) -> dict | None:
    return clean(get_db()[coll].find_one(query))


def insert(coll: str, doc: dict) -> dict:
    doc = dict(doc)
    doc.setdefault("id", next_id(coll))
    get_db()[coll].insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SEED_STUDIES = [
    {"protocol_id": "FUS-ONC-301", "title": "Phase III Study of Fusarinib vs Standard of Care in Advanced NSCLC",
     "phase": "Phase III", "therapeutic_area": "Oncology", "status": "Enrolling", "target_enrollment": 420,
     "sponsor": "Fusion Therapeutics", "arms": ["Fusarinib", "Standard of Care"]},
    {"protocol_id": "FUS-CVD-201", "title": "Phase II Dose-Ranging Study of FT-204 in Resistant Hypertension",
     "phase": "Phase II", "therapeutic_area": "Cardiology", "status": "Enrolling", "target_enrollment": 180,
     "sponsor": "Fusion Therapeutics", "arms": ["FT-204 10mg", "FT-204 20mg", "Placebo"]},
    {"protocol_id": "FUS-END-102", "title": "Phase I/II Study of FT-310 in Type 2 Diabetes with Renal Impairment",
     "phase": "Phase I/II", "therapeutic_area": "Endocrinology", "status": "Active, not recruiting", "target_enrollment": 60,
     "sponsor": "Fusion Therapeutics", "arms": ["FT-310"]},
    {"protocol_id": "FUS-NEU-110", "title": "Open-Label Extension Study of FT-115 in Relapsing Multiple Sclerosis",
     "phase": "Phase II", "therapeutic_area": "Neurology", "status": "Enrolling", "target_enrollment": 240,
     "sponsor": "Fusion Therapeutics", "arms": ["FT-115"]},
]

SEED_SITES = [
    (1, "Boston Clinical Research Center", "USA", "Dr. Amara Patel"),
    (1, "MD Westmead Oncology Unit", "Australia", "Dr. James Liu"),
    (1, "Charité Forschungszentrum", "Germany", "Dr. Lena Hoffmann"),
    (2, "Cleveland Heart Institute", "USA", "Dr. Robert Kim"),
    (2, "Toronto Cardiovascular Trials", "Canada", "Dr. Sofia Marino"),
    (3, "Dallas Endocrine Associates", "USA", "Dr. Priya Nair"),
    (4, "Stockholm Neuro Center", "Sweden", "Dr. Erik Lindqvist"),
    (4, "Mayo Neurology Research", "USA", "Dr. Hannah Brooks"),
]

SEED_PARTICIPANTS = [
    # (study_id, site_id, code, age, sex, status, arm)
    (1, 1, "301-001", 64, "M", "Enrolled", "Fusarinib"),
    (1, 1, "301-002", 58, "F", "Enrolled", "Standard of Care"),
    (1, 1, "301-003", 71, "M", "Completed", "Fusarinib"),
    (1, 2, "301-004", 66, "F", "Enrolled", "Standard of Care"),
    (1, 2, "301-005", 17, "M", "Enrolled", None),  # under-age -> data quality finding
    (1, 3, "301-006", 62, "F", "Withdrawn", "Fusarinib"),
    (1, 3, "301-007", 59, "M", "Enrolled", None),  # not yet randomized
    (2, 4, "201-001", 55, "F", "Enrolled", "FT-204 10mg"),
    (2, 4, "201-002", 61, "M", "Enrolled", "Placebo"),
    (2, 5, "201-003", 48, "F", "Screen Failure", None),
    (2, 5, "201-004", 67, "M", "Enrolled", "FT-204 20mg"),
    (2, 5, "201-005", None, "F", "Enrolled", None),  # missing age -> data quality finding
    (3, 6, "102-001", 52, "M", "Completed", "FT-310"),
    (3, 6, "102-002", 60, "F", "Completed", "FT-310"),
    (4, 7, "110-001", 34, "F", "Enrolled", "FT-115"),
    (4, 7, "110-002", 41, "M", "Enrolled", "FT-115"),
    (4, 8, "110-003", 29, "F", "Enrolled", "FT-115"),
    (4, 8, "110-004", 37, "F", "Enrolled", None),  # not yet randomized
]

SEED_AES = [
    (1, 1, "bad headache for 2 days", "Headache", "Nervous system disorders", "Moderate", 0, "Recovered"),
    (1, 2, "felt sick to stomach", "Nausea", "Gastrointestinal disorders", "Mild", 0, "Recovered"),
    (1, 4, "neutrophil count dropped", "Neutropenia", "Blood and lymphatic system disorders", "Severe", 1, "Recovering"),
    (1, 7, "rash on both arms", "Rash", "Skin and subcutaneous tissue disorders", "Mild", 0, "Recovered"),
    (2, 8, "dizzy when standing up", "Dizziness postural", "Nervous system disorders", "Mild", 0, "Recovered"),
    (2, 9, "BP spiked to 190/110", "Hypertensive crisis", "Vascular disorders", "Severe", 1, "Recovered"),
    (2, 11, "swollen ankles", "Oedema peripheral", "General disorders", "Moderate", 0, "Ongoing"),
    (3, 13, "low blood sugar episode", "Hypoglycaemia", "Metabolism and nutrition disorders", "Moderate", 0, "Recovered"),
    (4, 15, "tingling in fingers", "Paraesthesia", "Nervous system disorders", "Mild", 0, "Ongoing"),
    (4, 17, "severe fatigue", None, None, "Mild", 1, "Ongoing"),  # uncoded + mild-but-serious -> findings
]

# EDC: CRF templates available to all studies.
CRF_TEMPLATES = [
    {
        "name": "Demographics",
        "fields": [
            {"name": "age", "label": "Age (years)", "type": "number", "required": True, "min": 18, "max": 100},
            {"name": "sex", "label": "Sex", "type": "select", "required": True, "options": ["M", "F"]},
            {"name": "height_cm", "label": "Height (cm)", "type": "number", "required": True, "min": 100, "max": 220},
            {"name": "weight_kg", "label": "Weight (kg)", "type": "number", "required": True, "min": 30, "max": 250},
        ],
    },
    {
        "name": "Vital Signs",
        "fields": [
            {"name": "systolic_bp", "label": "Systolic BP (mmHg)", "type": "number", "required": True, "min": 70, "max": 250},
            {"name": "diastolic_bp", "label": "Diastolic BP (mmHg)", "type": "number", "required": True, "min": 40, "max": 150},
            {"name": "heart_rate", "label": "Heart rate (bpm)", "type": "number", "required": True, "min": 30, "max": 220},
            {"name": "temperature_c", "label": "Temperature (°C)", "type": "number", "required": False, "min": 34, "max": 42},
        ],
    },
    {
        "name": "Laboratory",
        "fields": [
            {"name": "hemoglobin_g_dl", "label": "Hemoglobin (g/dL)", "type": "number", "required": True, "min": 5, "max": 20},
            {"name": "wbc_10e9_l", "label": "WBC (10^9/L)", "type": "number", "required": True, "min": 1, "max": 30},
            {"name": "creatinine_mg_dl", "label": "Creatinine (mg/dL)", "type": "number", "required": True, "min": 0.2, "max": 10},
        ],
    },
]

# RTSM: investigational product kits per (study, site, arm).
SEED_KITS = [
    # (study_id, site_id, arm, count)
    (1, 1, "Fusarinib", 4), (1, 1, "Standard of Care", 4),
    (1, 2, "Fusarinib", 3), (1, 2, "Standard of Care", 3),
    (1, 3, "Fusarinib", 3), (1, 3, "Standard of Care", 3),
    (2, 4, "FT-204 10mg", 3), (2, 4, "FT-204 20mg", 3), (2, 4, "Placebo", 3),
    (2, 5, "FT-204 10mg", 3), (2, 5, "FT-204 20mg", 3), (2, 5, "Placebo", 3),
    (3, 6, "FT-310", 4),
    (4, 7, "FT-115", 5), (4, 8, "FT-115", 5),
]

# ePRO instruments.
SEED_INSTRUMENTS = [
    {
        "name": "Daily Symptom Diary",
        "frequency": "daily",
        "description": "Patient-reported symptom severity, 0 (none) to 10 (worst imaginable).",
        "questions": [
            {"code": "fatigue", "text": "How severe was your fatigue today?"},
            {"code": "pain", "text": "How severe was your pain today?"},
            {"code": "nausea", "text": "How severe was your nausea today?"},
        ],
    },
    {
        "name": "Weekly Quality of Life",
        "frequency": "weekly",
        "description": "Patient-reported quality of life, 0 (no problems) to 10 (extreme problems).",
        "questions": [
            {"code": "mobility", "text": "Problems walking about this week?"},
            {"code": "self_care", "text": "Problems with washing or dressing this week?"},
            {"code": "anxiety", "text": "How anxious or depressed were you this week?"},
        ],
    },
]

SEED_EPRO_SUBMISSIONS = [
    # (study_id, participant_id, instrument_id, responses)
    (1, 1, 1, {"fatigue": 3, "pain": 2, "nausea": 1}),
    (1, 2, 1, {"fatigue": 5, "pain": 4, "nausea": 6}),
    (1, 4, 1, {"fatigue": 9, "pain": 7, "nausea": 3}),  # fatigue >= 8 -> symptom alert
    (4, 15, 2, {"mobility": 2, "self_care": 1, "anxiety": 4}),
]

# eTMF: essential artifacts every study must file (simplified TMF Reference Model).
TMF_ESSENTIAL_ARTIFACTS = [
    ("01 Trial Management", "Protocol"),
    ("01 Trial Management", "Protocol Amendment Log"),
    ("02 Central Trial Documents", "Investigator's Brochure"),
    ("03 Regulatory", "Regulatory Authority Approval"),
    ("04 IRB or IEC", "Ethics Committee Approval"),
    ("05 Site Management", "Clinical Trial Agreement"),
    ("06 IP and Trial Supplies", "IP Shipment Records"),
    ("07 Safety Reporting", "Safety Management Plan"),
    ("08 Data Management", "Data Management Plan"),
    ("09 Statistics", "Statistical Analysis Plan"),
]

SEED_TMF_DOCS = [
    # (study_id, zone, artifact, title, status, version)
    (1, "01 Trial Management", "Protocol", "FUS-ONC-301 Protocol v3.0", "approved", "3.0"),
    (1, "02 Central Trial Documents", "Investigator's Brochure", "Fusarinib IB Edition 5", "approved", "5.0"),
    (1, "03 Regulatory", "Regulatory Authority Approval", "FDA IND Acknowledgement", "approved", "1.0"),
    (1, "04 IRB or IEC", "Ethics Committee Approval", "Central IRB Approval Letter", "approved", "1.0"),
    (1, "08 Data Management", "Data Management Plan", "FUS-ONC-301 DMP", "draft", "0.9"),
    (2, "01 Trial Management", "Protocol", "FUS-CVD-201 Protocol v2.1", "approved", "2.1"),
    (2, "04 IRB or IEC", "Ethics Committee Approval", "Cleveland IRB Approval", "final", "1.0"),
]

# eConsent: informed consent form versions per study.
SEED_CONSENT_VERSIONS = [
    # (study_id, version, title, is_current)
    (1, "1.0", "FUS-ONC-301 Main ICF v1.0", False),
    (1, "2.0", "FUS-ONC-301 Main ICF v2.0 (Amendment 1)", True),
    (2, "1.0", "FUS-CVD-201 Main ICF v1.0", True),
    (3, "1.0", "FUS-END-102 Main ICF v1.0", True),
    (4, "1.0", "FUS-NEU-110 Main ICF v1.0", True),
]

# eConsent records: (participant_id, consent_version_index). Participants of
# study 1 on version 1 (index 1) need re-consent; 301-007 (id 7) has no
# consent on file at all -> critical finding.
SEED_CONSENT_RECORDS = [
    (1, 2), (2, 2), (3, 2), (4, 1), (5, 1), (6, 1),
    (8, 3), (9, 3), (11, 3), (12, 3),
    (13, 4), (14, 4),
    (15, 5), (16, 5), (17, 5), (18, 5),
]

# Safety Database: cases opened for the seeded serious AEs (ae ids 3, 6, 10).
SEED_SAFETY_CASES = [
    # (ae_id, status, causality, expectedness, seriousness_criteria)
    (3, "under_review", "possibly related", "unexpected", ["hospitalization"]),
    (6, "closed", "unlikely related", "expected", ["medically significant"]),
    (10, "new", None, None, []),
]


def init_db(seed: bool = True):
    db = get_db()
    if not seed:
        return
    if db.studies.count_documents({}) > 0:
        return

    for s in SEED_STUDIES:
        insert("studies", {**s, "created_at": now_iso()})
    for study_id, name, country, pi in SEED_SITES:
        insert("sites", {"study_id": study_id, "name": name, "country": country,
                         "pi_name": pi, "status": "Active"})
    for study_id, site_id, code, age, sex, status, arm in SEED_PARTICIPANTS:
        insert("participants", {
            "study_id": study_id, "site_id": site_id, "subject_code": code,
            "age": age, "sex": sex, "status": status, "arm": arm,
            "randomized_at": now_iso() if arm else None, "enrolled_at": now_iso(),
        })
    for study_id, pid, verbatim, pt, soc, sev, serious, outcome in SEED_AES:
        insert("adverse_events", {
            "study_id": study_id, "participant_id": pid, "verbatim_term": verbatim,
            "preferred_term": pt, "system_organ_class": soc, "severity": sev,
            "serious": serious, "outcome": outcome, "reported_at": now_iso(),
        })
    for tpl in CRF_TEMPLATES:
        insert("crf_forms", tpl)
    for study_id, site_id, arm, count in SEED_KITS:
        for _ in range(count):
            kit_id = next_id("kit_number")
            insert("kits", {
                "study_id": study_id, "site_id": site_id, "arm": arm,
                "kit_number": f"KIT-{kit_id:05d}", "status": "available",
                "dispensed_to": None, "dispensed_at": None,
            })
    for inst in SEED_INSTRUMENTS:
        insert("epro_instruments", inst)
    for study_id, pid, inst_id, responses in SEED_EPRO_SUBMISSIONS:
        score = sum(responses.values())
        insert("epro_submissions", {
            "study_id": study_id, "participant_id": pid, "instrument_id": inst_id,
            "responses": responses, "score": score,
            "alert": any(v >= 8 for v in responses.values()),
            "submitted_at": now_iso(),
        })
    for study_id, zone, artifact, title, status, version in SEED_TMF_DOCS:
        insert("tmf_documents", {
            "study_id": study_id, "zone": zone, "artifact": artifact, "title": title,
            "status": status, "version": version, "uploaded_by": "seed",
            "uploaded_at": now_iso(),
        })
    for study_id, version, title, is_current in SEED_CONSENT_VERSIONS:
        insert("consent_versions", {
            "study_id": study_id, "version": version, "title": title,
            "is_current": is_current, "effective_date": now_iso(),
        })
    for participant_id, version_id in SEED_CONSENT_RECORDS:
        p = find_one("participants", {"id": participant_id})
        insert("consent_records", {
            "study_id": p["study_id"], "participant_id": participant_id,
            "consent_version_id": version_id, "consented_at": now_iso(),
        })
    # A site still in activation for study 1 (no participants yet).
    insert("sites", {"study_id": 1, "name": "Singapore Oncology Partners", "country": "Singapore",
                     "pi_name": "Dr. Wei Tan", "status": "Pending Activation"})
    for ae_id, status, causality, expectedness, criteria in SEED_SAFETY_CASES:
        ae = find_one("adverse_events", {"id": ae_id})
        insert("safety_cases", {
            "case_number": f"CASE-2026-{ae_id:04d}",
            "study_id": ae["study_id"], "participant_id": ae["participant_id"],
            "ae_id": ae_id, "status": status,
            "causality": causality, "expectedness": expectedness,
            "seriousness_criteria": criteria,
            "expedited": bool(causality and "related" in causality and causality != "unlikely related"
                              and expectedness == "unexpected"),
            "narrative": None, "opened_at": now_iso(), "report_due": None,
        })
