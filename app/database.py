"""SQLite persistence layer for FusionTrials.

Uses the stdlib sqlite3 module with a small schema covering the core
CTMS entities: studies, sites, participants, adverse events, and data
queries. The database is seeded with realistic demo data on first run.
"""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("FUSION_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "fusion.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS studies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    phase TEXT NOT NULL,
    therapeutic_area TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Enrolling',
    target_enrollment INTEGER NOT NULL,
    sponsor TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_id INTEGER NOT NULL REFERENCES studies(id),
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    pi_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_id INTEGER NOT NULL REFERENCES studies(id),
    site_id INTEGER NOT NULL REFERENCES sites(id),
    subject_code TEXT NOT NULL,
    age INTEGER,
    sex TEXT,
    status TEXT NOT NULL DEFAULT 'Enrolled',
    enrolled_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS adverse_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_id INTEGER NOT NULL REFERENCES studies(id),
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    verbatim_term TEXT NOT NULL,
    preferred_term TEXT,
    system_organ_class TEXT,
    severity TEXT NOT NULL,
    serious INTEGER NOT NULL DEFAULT 0,
    outcome TEXT,
    reported_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS data_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_id INTEGER NOT NULL REFERENCES studies(id),
    participant_id INTEGER REFERENCES participants(id),
    field TEXT NOT NULL,
    issue TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'minor',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS protocols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    indication TEXT,
    phase TEXT,
    content_json TEXT NOT NULL,
    generated_by TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


SEED_STUDIES = [
    ("FUS-ONC-301", "Phase III Study of Fusarinib vs Standard of Care in Advanced NSCLC", "Phase III", "Oncology", "Enrolling", 420, "Fusion Therapeutics"),
    ("FUS-CVD-201", "Phase II Dose-Ranging Study of FT-204 in Resistant Hypertension", "Phase II", "Cardiology", "Enrolling", 180, "Fusion Therapeutics"),
    ("FUS-END-102", "Phase I/II Study of FT-310 in Type 2 Diabetes with Renal Impairment", "Phase I/II", "Endocrinology", "Active, not recruiting", 60, "Fusion Therapeutics"),
    ("FUS-NEU-110", "Open-Label Extension Study of FT-115 in Relapsing Multiple Sclerosis", "Phase II", "Neurology", "Enrolling", 240, "Fusion Therapeutics"),
]

SEED_SITES = [
    # (study_idx, name, country, pi)
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
    # (study_idx, site_idx, code, age, sex, status)
    (1, 1, "301-001", 64, "M", "Enrolled"), (1, 1, "301-002", 58, "F", "Enrolled"),
    (1, 1, "301-003", 71, "M", "Completed"), (1, 2, "301-004", 66, "F", "Enrolled"),
    (1, 2, "301-005", 17, "M", "Enrolled"),  # age below typical adult inclusion -> data quality finding
    (1, 3, "301-006", 62, "F", "Withdrawn"), (1, 3, "301-007", 59, "M", "Enrolled"),
    (2, 4, "201-001", 55, "F", "Enrolled"), (2, 4, "201-002", 61, "M", "Enrolled"),
    (2, 5, "201-003", 48, "F", "Screen Failure"), (2, 5, "201-004", 67, "M", "Enrolled"),
    (2, 5, "201-005", None, "F", "Enrolled"),  # missing age -> data quality finding
    (3, 6, "102-001", 52, "M", "Completed"), (3, 6, "102-002", 60, "F", "Completed"),
    (4, 7, "110-001", 34, "F", "Enrolled"), (4, 7, "110-002", 41, "M", "Enrolled"),
    (4, 8, "110-003", 29, "F", "Enrolled"), (4, 8, "110-004", 37, "F", "Enrolled"),
]

SEED_AES = [
    # (study_idx, participant_idx, verbatim, pt, soc, severity, serious, outcome)
    (1, 1, "bad headache for 2 days", "Headache", "Nervous system disorders", "Moderate", 0, "Recovered"),
    (1, 2, "felt sick to stomach", "Nausea", "Gastrointestinal disorders", "Mild", 0, "Recovered"),
    (1, 4, "neutrophil count dropped", "Neutropenia", "Blood and lymphatic system disorders", "Severe", 1, "Recovering"),
    (1, 7, "rash on both arms", "Rash", "Skin and subcutaneous tissue disorders", "Mild", 0, "Recovered"),
    (2, 8, "dizzy when standing up", "Dizziness postural", "Nervous system disorders", "Mild", 0, "Recovered"),
    (2, 9, "BP spiked to 190/110", "Hypertensive crisis", "Vascular disorders", "Severe", 1, "Recovered"),
    (2, 11, "swollen ankles", "Oedema peripheral", "General disorders", "Moderate", 0, "Ongoing"),
    (3, 13, "low blood sugar episode", "Hypoglycaemia", "Metabolism and nutrition disorders", "Moderate", 0, "Recovered"),
    (4, 15, "tingling in fingers", "Paraesthesia", "Nervous system disorders", "Mild", 0, "Ongoing"),
    (4, 17, "severe fatigue", None, None, "Mild", 1, "Ongoing"),  # uncoded + mild-but-serious mismatch -> findings
]


def init_db(seed: bool = True):
    with get_db() as db:
        db.executescript(SCHEMA)
        if not seed:
            return
        if db.execute("SELECT COUNT(*) AS c FROM studies").fetchone()["c"] > 0:
            return
        for s in SEED_STUDIES:
            db.execute(
                "INSERT INTO studies (protocol_id, title, phase, therapeutic_area, status, target_enrollment, sponsor) VALUES (?,?,?,?,?,?,?)",
                s,
            )
        for study_idx, name, country, pi in SEED_SITES:
            db.execute(
                "INSERT INTO sites (study_id, name, country, pi_name) VALUES (?,?,?,?)",
                (study_idx, name, country, pi),
            )
        for study_idx, site_idx, code, age, sex, status in SEED_PARTICIPANTS:
            db.execute(
                "INSERT INTO participants (study_id, site_id, subject_code, age, sex, status) VALUES (?,?,?,?,?,?)",
                (study_idx, site_idx, code, age, sex, status),
            )
        for study_idx, pid, verbatim, pt, soc, sev, serious, outcome in SEED_AES:
            db.execute(
                "INSERT INTO adverse_events (study_id, participant_id, verbatim_term, preferred_term, system_organ_class, severity, serious, outcome) VALUES (?,?,?,?,?,?,?,?)",
                (study_idx, pid, verbatim, pt, soc, sev, serious, outcome),
            )
