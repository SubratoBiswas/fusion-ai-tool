# FusionTrials — AI-Powered Clinical Research Platform

FusionTrials is a unified eClinical platform for clinical research teams (sponsors, CROs, and sites). It combines the five core eClinical modules — **CTMS, EDC, RTSM, ePRO, eTMF** — with Claude-powered AI features, backed by **MongoDB** and deployable to **Render** in one click.

## Why this design

The product was shaped by research into the clinical research software landscape:

- **[FuelClinical](https://fuelclinical.com/)** is a clinical trial management partner helping biotech and medical device companies navigate regulatory pathways, manage trial data, and run multisite registries. FusionTrials productizes that workflow.
- **Best-in-class platforms** — Veeva Vault Clinical Suite, Clinion, Curebase, Viedoc, RealTime CTMS — converge on a unified suite (EDC + RTSM + CTMS + eTMF + ePRO) with AI layered on top: AI protocol generation, AI medical coding, intelligent data review, and eligibility/compliance monitoring. FusionTrials implements all of it in one codebase.

## Modules

### Core eClinical suite

| Module | What it does |
|---|---|
| **CTMS Dashboard** | Portfolio KPIs, per-study enrollment vs target, sites, AEs/SAEs, open queries, ePRO alerts. Click a study for participant/AE/query detail. |
| **EDC** | CRF templates (Demographics, Vital Signs, Laboratory) with real-time edit checks — required fields, numeric ranges, coded values. Failures automatically raise data queries. |
| **RTSM** | Subject randomization via minimization (balanced arm allocation) with automatic IP kit dispensing from site inventory, low-stock flags, and pending-randomization worklist. |
| **ePRO** | Patient-reported instruments (symptom diary, quality of life) on a 0–10 scale. Items scored ≥ 8 fire a symptom alert and open a site follow-up query. |
| **eTMF** | Essential documents tracked against a simplified TMF Reference Model: inspection-readiness %, missing-artifact gap analysis, document filing and approval workflow. |

### AI modules (Claude-powered)

| Module | What it does |
|---|---|
| **AI Protocol Designer** | Study concept → structured protocol synopsis (objectives, design, criteria, endpoints, statistics, safety monitoring) via Claude structured outputs. |
| **AI Eligibility Screener** | Unstructured patient profile vs inclusion/exclusion criteria, per-criterion verdicts with rationale and missing-information detection. |
| **AI Medical Coding** | Verbatim AE terms → MedDRA-style Preferred Term + System Organ Class with confidence flags for coder review. |
| **AI Data Quality Review** | Deterministic edit checks across a study + AI-written data review narrative; findings persist as open queries. |
| **Registry Intelligence** | Live ClinicalTrials.gov v2 search with an AI competitive-landscape summary for feasibility planning. |

## Architecture

- **Backend:** Python / FastAPI.
- **Database:** **MongoDB** via `pymongo` (`MONGODB_URI`, e.g. MongoDB Atlas). Without `MONGODB_URI`, an in-memory `mongomock` instance is used — zero-infrastructure local dev and tests.
- **AI:** Anthropic Python SDK, model `claude-opus-4-8`, adaptive thinking, JSON-schema structured outputs.
- **Frontend:** single-page vanilla JS dashboard served from `/`.
- **Graceful degradation:** every AI endpoint has a deterministic rule-based fallback (templates, age-criterion heuristics, an offline PT/SOC dictionary, rule summaries), so the platform is fully demoable without an API key. Responses declare their provenance (`_generated_by: claude | offline-*`).

```
app/
├── main.py            # FastAPI routes (CTMS + EDC/RTSM/ePRO/eTMF + AI)
├── database.py        # MongoDB layer + seed data (mongomock fallback)
├── modules/
│   ├── edc.py         # CRF templates, edit checks, auto data queries
│   ├── rtsm.py        # minimization randomization + kit dispensing
│   ├── epro.py        # PRO instruments, submissions, symptom alerts
│   └── etmf.py        # TMF reference model, completeness, approvals
├── ai/
│   ├── client.py      # Anthropic client wrapper (shared)
│   ├── protocol.py    # protocol synopsis generation
│   ├── eligibility.py
│   ├── coding.py
│   ├── data_quality.py
│   └── registry.py    # ClinicalTrials.gov search + AI summary
└── static/            # SPA frontend
render.yaml            # Render Blueprint (web service)
tests/test_api.py      # offline-mode API tests (23 tests)
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

All AI outputs (protocol drafts, eligibility verdicts, medical codings, data-review narratives) are **decision-support drafts for qualified human review**. They are not a substitute for medical, statistical, or regulatory judgment, and final decisions rest with investigators, medical coders, data managers, and regulatory professionals. This is a demo platform — production use in regulated trials would additionally require audit trails, e-signatures (21 CFR Part 11), access control, and validation.
