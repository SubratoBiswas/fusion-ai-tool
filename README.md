# FusionTrials — AI-Powered Clinical Research Platform

FusionTrials is a unified eClinical demo platform for clinical research teams (sponsors, CROs, and sites). It combines a CTMS-style operations dashboard with five Claude-powered AI modules that mirror the capabilities of leading platforms in the space.

## Why this design

The product was shaped by research into the clinical research software landscape:

- **[FuelClinical](https://fuelclinical.com/)** is a clinical trial management partner helping biotech and medical device companies navigate regulatory pathways, manage trial data, and run multisite registries. FusionTrials productizes that workflow: study oversight, data ownership, and operational efficiency in one tool.
- **Best-in-class platforms** — Veeva Vault Clinical Suite, Clinion, Curebase, Viedoc, RealTime CTMS — converge on a unified suite (EDC + CTMS + eTMF) with AI features layered on top: AI protocol generation, AI medical coding, intelligent data review, and eligibility/compliance monitoring. FusionTrials implements lightweight versions of each.

## Features

| Module | What it does |
|---|---|
| **Dashboard (CTMS)** | Portfolio KPIs, per-study enrollment vs target, sites, adverse events, SAEs, and open data queries. Click a study for participant/AE/query detail. |
| **AI Protocol Designer** | Turns a study concept (indication, phase, intervention) into a structured protocol synopsis — objectives, design, eligibility criteria, endpoints, statistics, safety monitoring — via Claude structured outputs. Saved for later retrieval. |
| **AI Eligibility Screener** | Assesses an unstructured patient profile against inclusion/exclusion criteria, criterion by criterion, with verdicts, rationale, and a missing-information list. |
| **AI Medical Coding** | Maps verbatim adverse event terms to MedDRA-style Preferred Terms and System Organ Classes with confidence flags for coder review. |
| **AI Data Quality Review** | Deterministic edit checks (missing demographics, eligibility deviations, uncoded AEs, seriousness/severity mismatches) + an AI-written data review narrative. Findings persist as open queries. |
| **Registry Intelligence** | Live ClinicalTrials.gov v2 search with an AI competitive-landscape summary for feasibility planning. |

## Architecture

- **Backend:** Python / FastAPI, SQLite (stdlib `sqlite3`), seeded with realistic demo data.
- **AI:** Anthropic Python SDK, model `claude-opus-4-8`, adaptive thinking, JSON-schema structured outputs for machine-readable results.
- **Frontend:** single-page vanilla JS dashboard served from `/`.
- **Graceful degradation:** every AI endpoint has a deterministic rule-based fallback (templates, age-criterion heuristics, an offline PT/SOC dictionary, rule summaries), so the platform is fully demoable and testable without an API key. Responses always declare their provenance (`_generated_by: claude | offline-*`).

```
app/
├── main.py          # FastAPI routes (CTMS + AI endpoints)
├── database.py      # SQLite schema + seed data
├── ai/
│   ├── client.py    # Anthropic client wrapper (shared)
│   ├── protocol.py  # protocol synopsis generation
│   ├── eligibility.py
│   ├── coding.py
│   ├── data_quality.py
│   └── registry.py  # ClinicalTrials.gov search + AI summary
└── static/          # SPA frontend
tests/test_api.py    # offline-mode API tests
```

## Quick start

```bash
pip install -r requirements.txt

# Optional — enables Claude-powered features (otherwise offline fallbacks run)
export ANTHROPIC_API_KEY=sk-ant-...

python run.py
# open http://localhost:8000
```

## Tests

```bash
pytest tests/ -v
```

Tests run without network or API keys.

## Important disclaimer

All AI outputs (protocol drafts, eligibility verdicts, medical codings, data-review narratives) are **decision-support drafts for qualified human review**. They are not a substitute for medical, statistical, or regulatory judgment, and final decisions rest with investigators, medical coders, data managers, and regulatory professionals.
