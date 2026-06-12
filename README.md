# Fusion AI eClinical Suite

**Fusion AI eClinical Suite** is a unified, AI-powered clinical research platform for sponsors, CROs, and sites. It integrates **16 modules** — including Electronic Data Capture (EDC), Data Management (DM), Interactive Web Response System (IWRS), Clinical Trial Management System (CTMS), AE/SAE Tracking, Safety Database, eTMF, and 24/7 project and clinical data reporting — backed by **MongoDB** and deployable to **Render** in one click.

## Why this design

The product was shaped by research into the clinical research software landscape:

- **[FuelClinical](https://fuelclinical.com/)** is a clinical trial management partner helping biotech and medical device companies navigate regulatory pathways, manage trial data, and run multisite registries. Fusion AI eClinical Suite productizes that workflow.
- **Best-in-class platforms** — Veeva Vault Clinical Suite, Clinion, Curebase, Viedoc, RealTime CTMS — converge on a unified suite with AI layered on top: AI protocol generation, AI medical coding, intelligent data review, and eligibility/compliance monitoring. This suite implements all of it in one codebase.

## The 16 modules

### Clinical operations

| # | Module | What it does |
|---|---|---|
| 1 | **CTMS Dashboard** | Portfolio KPIs, per-study enrollment vs target, sites, AEs/SAEs, open queries, ePRO alerts, study drill-down. |
| 2 | **EDC** | CRF templates (Demographics, Vital Signs, Laboratory) with real-time edit checks; failures automatically raise data queries. |
| 3 | **Data Management (DM)** | Central query workbench (respond/close workflow) for queries raised by EDC, ePRO, and the AI data review. |
| 4 | **IWRS** | Subject randomization via minimization with automatic IP kit dispensing, inventory tracking, and low-stock flags. |
| 5 | **ePRO** | Patient-reported instruments (symptom diary, quality of life); items scored ≥ 8 fire symptom alerts and follow-up queries. |
| 6 | **eTMF** | Essential documents vs the TMF Reference Model: inspection-readiness %, missing-artifact gap analysis, approval workflow. |
| 7 | **eConsent** | ICF version tracking; protocol amendments flag re-consent; missing consent is a critical finding. |
| 8 | **Site Management** | Site activation workflow (pending → active → closed) with per-site enrollment, query, and AE metrics. |

### Safety & pharmacovigilance

| # | Module | What it does |
|---|---|---|
| 9 | **AE/SAE Tracking** | Report adverse events with automatic medical coding; serious events automatically open safety cases. |
| 10 | **Safety Database** | PV case workflow: causality/expectedness/seriousness assessment, SUSAR determination with regulatory clocks (7-day fatal/life-threatening, 15-day otherwise), AI-drafted ICSR narratives, case closure. |

### Reporting

| # | Module | What it does |
|---|---|---|
| 11 | **24/7 Reporting** | Always-available study reports aggregating every module — enrollment, data quality, safety, ePRO, supply, consent — plus CSV dataset exports (participants, AEs, queries, CRFs, ePRO, safety cases). |

### AI studio (Claude-powered)

| # | Module | What it does |
|---|---|---|
| 12 | **AI Protocol Designer** | Study concept → structured protocol synopsis (objectives, design, criteria, endpoints, statistics, safety monitoring). |
| 13 | **AI Eligibility Screener** | Patient profile vs inclusion/exclusion criteria with per-criterion verdicts and missing-information detection. |
| 14 | **AI Medical Coding** | Verbatim AE terms → MedDRA-style Preferred Term + System Organ Class with confidence flags. |
| 15 | **AI Data Review** | Deterministic edit checks across a study + AI-written data review narrative; findings persist as queries. |
| 16 | **Registry Intelligence** | Live ClinicalTrials.gov search with an AI competitive-landscape summary for feasibility planning. |

The modules are integrated, not siloed: an EDC edit-check failure opens a DM query; a serious AE opens a Safety Database case with a reporting clock; an ePRO alert opens a site follow-up query; everything rolls up into the CTMS dashboard and the 24/7 report.

## Architecture

- **Backend:** Python / FastAPI.
- **Database:** **MongoDB** via `pymongo` (`MONGODB_URI`, e.g. MongoDB Atlas). Without `MONGODB_URI`, an in-memory `mongomock` instance is used — zero-infrastructure local dev and tests.
- **AI:** Anthropic Python SDK, model `claude-opus-4-8`, adaptive thinking, JSON-schema structured outputs.
- **Frontend:** single-page vanilla JS app served from `/`.
- **Graceful degradation:** every AI endpoint has a deterministic rule-based fallback (templates, heuristics, offline PT/SOC dictionary), so the platform is fully demoable without an API key. Responses declare their provenance (`_generated_by: claude | offline-*`).

```
app/
├── main.py            # FastAPI routes for all 16 modules
├── database.py        # MongoDB layer + seed data (mongomock fallback)
├── modules/
│   ├── edc.py         # CRF templates, edit checks, auto data queries
│   ├── dm.py          # query workbench (respond/close)
│   ├── rtsm.py        # IWRS: minimization randomization + kit dispensing
│   ├── epro.py        # PRO instruments, submissions, symptom alerts
│   ├── etmf.py        # TMF reference model, completeness, approvals
│   ├── safety.py      # AE/SAE tracking + safety database (PV cases)
│   ├── econsent.py    # ICF version tracking, re-consent flags
│   ├── sites.py       # site activation + performance metrics
│   └── reporting.py   # 24/7 study reports + CSV exports
├── ai/
│   ├── client.py      # Anthropic client wrapper (shared)
│   ├── protocol.py    # protocol synopsis generation
│   ├── eligibility.py
│   ├── coding.py
│   ├── data_quality.py
│   └── registry.py    # ClinicalTrials.gov search + AI summary
└── static/            # SPA frontend
render.yaml            # Render Blueprint (web service)
tests/test_api.py      # offline-mode API tests (38 tests)
```

## Quick start (local)

```bash
pip install -r requirements.txt

# Optional — point at a real MongoDB (otherwise in-memory mongomock is used)
export MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net"

# Optional — enables Claude-powered features (otherwise offline fallbacks run)
export ANTHROPIC_API_KEY=sk-ant-...

python run.py
# open http://localhost:8000
```

## Deploy to Render

The repo ships a [Render Blueprint](https://render.com/docs/blueprint-spec) (`render.yaml`).

1. **Create a MongoDB Atlas cluster** (free M0 tier works): [mongodb.com/atlas](https://www.mongodb.com/atlas). Create a database user and allow access from anywhere (`0.0.0.0/0`) or Render's egress IPs. Copy the connection string.
2. **Create the Render service:** in the [Render dashboard](https://dashboard.render.com) choose **New → Blueprint**, connect this repository, and apply. (Or **New → Web Service** with build command `pip install -r requirements.txt` and start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.)
3. **Set environment variables** on the service:
   - `MONGODB_URI` — the Atlas connection string (required for persistence; without it the app runs on in-memory storage that resets on every deploy/restart).
   - `ANTHROPIC_API_KEY` — optional, enables the Claude-powered AI modules.
4. Deploy. Health check is at `/api/health`; the app seeds demo data into MongoDB on first boot.

## Tests

```bash
pytest tests/ -v
```

Tests run without network, MongoDB, or API keys (mongomock + AI fallbacks).

## Important disclaimer

All AI outputs (protocol drafts, eligibility verdicts, medical codings, case narratives, data-review narratives) are **decision-support drafts for qualified human review**. They are not a substitute for medical, statistical, or regulatory judgment, and final decisions rest with investigators, medical coders, safety physicians, data managers, and regulatory professionals. This is a demo platform — production use in regulated trials would additionally require audit trails, e-signatures (21 CFR Part 11), access control, and validation.
