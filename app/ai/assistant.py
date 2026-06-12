"""Fusion Assistant — conversational AI for the whole suite.

A Claude-powered agent with tools over the platform's MongoDB data:
it answers questions about studies, enrollment, queries, safety, and
supply, generates formatted study reports on request, and searches
ClinicalTrials.gov. Without an API key it falls back to a rule-based
intent engine over the same data, so the chatbot always works.
"""

import json
import re

from ..database import find_all, find_one, get_db
from ..modules import reporting
from .client import MODEL, ai_available, get_client
from .registry import search_trials

MAX_TOOL_ITERATIONS = 8
MAX_HISTORY = 30

SYSTEM = (
    "You are Fusion Assistant, the built-in AI assistant of the Fusion AI eClinical "
    "Suite — a unified clinical research platform with 16 modules (CTMS, EDC, Data "
    "Management, IWRS, ePRO, eTMF, AE/SAE Tracking, Safety Database, eConsent, Site "
    "Management, 24/7 Reporting, and AI modules for protocol design, eligibility, "
    "coding, and registry intelligence).\n\n"
    "You help sponsors, CRAs, data managers, and site staff by:\n"
    "1. Answering questions about the live data in this platform — always use the "
    "tools to fetch real data before answering; never invent study numbers.\n"
    "2. Generating reports on request: call get_study_report and present the result "
    "as a well-structured markdown report with sections and tables. Mention that "
    "CSV exports are available from the report's export links.\n"
    "3. Answering general clinical research questions (GCP, trial phases, "
    "terminology, regulatory concepts) from your own knowledge — clearly, for a "
    "professional audience.\n\n"
    "Studies can be referenced by protocol ID (e.g. FUS-ONC-301) or by title "
    "keywords. If a study reference is ambiguous, list the portfolio and ask.\n"
    "Format answers in markdown. Keep answers focused; use tables for numbers. "
    "Never provide medical advice for an individual patient; platform data answers "
    "are decision support for qualified professionals."
)

TOOLS = [
    {
        "name": "get_portfolio_overview",
        "description": (
            "Get the portfolio-level overview: totals (studies, sites, participants, "
            "SAEs, open queries, ePRO alerts) and the list of all studies with "
            "protocol ID, title, phase, status, enrollment vs target, site count, "
            "AE/SAE counts, and open queries. Call this first when the user asks "
            "about 'the portfolio', 'all studies', or an ambiguous study."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_study_report",
        "description": (
            "Generate the full 24/7 study report for one study: enrollment (total, "
            "by status, by site), data quality (CRFs, queries by severity), safety "
            "(AEs by SOC, SAEs, expedited cases), ePRO compliance, kit supply, and "
            "consent status. Use this whenever the user asks for a report, status "
            "summary, or detailed metrics on a study."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "study": {"type": "string", "description": "Protocol ID (e.g. FUS-ONC-301), numeric study id, or title keyword"},
            },
            "required": ["study"],
        },
    },
    {
        "name": "list_open_queries",
        "description": "List a study's data queries (field, issue, severity, status, subject). Use for questions about data quality issues or outstanding queries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "study": {"type": "string", "description": "Protocol ID, numeric id, or title keyword"},
                "status": {"type": "string", "enum": ["open", "answered", "closed", "all"], "description": "Filter; default open"},
            },
            "required": ["study"],
        },
    },
    {
        "name": "list_safety_cases",
        "description": "List pharmacovigilance safety cases (case number, event, status, causality, expectedness, expedited/SUSAR flag, reporting due date). Optionally filtered to one study.",
        "input_schema": {
            "type": "object",
            "properties": {
                "study": {"type": "string", "description": "Optional protocol ID, numeric id, or title keyword"},
            },
            "required": [],
        },
    },
    {
        "name": "list_adverse_events",
        "description": "List a study's adverse events (subject, verbatim and coded terms, severity, seriousness, outcome).",
        "input_schema": {
            "type": "object",
            "properties": {
                "study": {"type": "string", "description": "Protocol ID, numeric id, or title keyword"},
                "serious_only": {"type": "boolean", "description": "Only SAEs; default false"},
            },
            "required": ["study"],
        },
    },
    {
        "name": "search_clinical_trials_registry",
        "description": "Search the public ClinicalTrials.gov registry for external trials matching a query (for competitive landscape / feasibility questions).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms, e.g. 'KRAS G12C NSCLC'"},
            },
            "required": ["query"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations (shared by the AI loop and the offline engine)
# ---------------------------------------------------------------------------

def _resolve_study(ref: str) -> dict | None:
    ref = (ref or "").strip()
    if not ref:
        return None
    if ref.isdigit():
        return find_one("studies", {"id": int(ref)})
    study = find_one("studies", {"protocol_id": re.compile(f"^{re.escape(ref)}$", re.I)})
    if study:
        return study
    for s in find_all("studies"):
        if ref.lower() in s["title"].lower() or ref.lower() in s["protocol_id"].lower():
            return s
    return None


def _portfolio_overview() -> dict:
    db = get_db()
    studies = []
    for s in find_all("studies", sort=[("id", 1)]):
        sid = s["id"]
        studies.append({
            "id": sid, "protocol_id": s["protocol_id"], "title": s["title"],
            "phase": s["phase"], "status": s["status"],
            "enrolled": db.participants.count_documents({"study_id": sid, "status": {"$ne": "Screen Failure"}}),
            "target_enrollment": s["target_enrollment"],
            "sites": db.sites.count_documents({"study_id": sid}),
            "aes": db.adverse_events.count_documents({"study_id": sid}),
            "saes": db.adverse_events.count_documents({"study_id": sid, "serious": 1}),
            "open_queries": db.data_queries.count_documents({"study_id": sid, "status": "open"}),
        })
    return {
        "totals": {
            "studies": db.studies.count_documents({}),
            "sites": db.sites.count_documents({}),
            "participants": db.participants.count_documents({"status": {"$ne": "Screen Failure"}}),
            "saes": db.adverse_events.count_documents({"serious": 1}),
            "open_queries": db.data_queries.count_documents({"status": "open"}),
            "pro_alerts": db.epro_submissions.count_documents({"alert": True}),
        },
        "studies": studies,
    }


def _study_report_with_links(study: dict) -> dict:
    report = reporting.study_report(study["id"])
    report["csv_export_links"] = [
        f"/api/reports/study/{study['id']}/export?dataset={d}" for d in report["available_exports"]
    ]
    return report


def execute_tool(name: str, tool_input: dict) -> dict:
    if name == "get_portfolio_overview":
        return _portfolio_overview()

    if name == "search_clinical_trials_registry":
        result = search_trials(tool_input.get("query", ""), limit=8)
        result.pop("summary", None)  # the assistant writes its own summary
        return result

    if name == "list_safety_cases":
        from ..modules import safety
        study = _resolve_study(tool_input.get("study", "")) if tool_input.get("study") else None
        cases = safety.list_cases(study["id"] if study else None)
        return {"study": study["protocol_id"] if study else "all", "cases": cases}

    # Remaining tools require a resolvable study.
    study = _resolve_study(tool_input.get("study", ""))
    if not study:
        portfolio = [s["protocol_id"] for s in find_all("studies")]
        return {"error": f"Study '{tool_input.get('study')}' not found. Available: {portfolio}"}

    if name == "get_study_report":
        return _study_report_with_links(study)

    if name == "list_open_queries":
        from ..modules import dm
        status = tool_input.get("status", "open")
        queries = dm.list_queries(study["id"], None if status == "all" else status)
        return {"study": study["protocol_id"], "count": len(queries), "queries": queries}

    if name == "list_adverse_events":
        from ..modules import safety
        aes = safety.list_aes(study["id"], bool(tool_input.get("serious_only")))
        return {"study": study["protocol_id"], "count": len(aes), "adverse_events": aes}

    return {"error": f"Unknown tool '{name}'"}


# ---------------------------------------------------------------------------
# Claude agentic loop
# ---------------------------------------------------------------------------

def chat(history: list[dict]) -> dict:
    """history: [{role: 'user'|'assistant', content: str}, ...] ending with a user turn."""
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-MAX_HISTORY:]
        if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()
    ]
    if not history or history[-1]["role"] != "user":
        raise ValueError("Conversation must end with a user message")

    if not ai_available():
        return _offline_chat(history[-1]["content"])

    client = get_client()
    messages = list(history)
    tools_used = []
    response = None

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            tools=TOOLS,
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                tools_used.append(block.name)
                try:
                    result = execute_tool(block.name, dict(block.input))
                    results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })
                except Exception as exc:
                    results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": f"Tool error: {exc}", "is_error": True,
                    })
        messages.append({"role": "user", "content": results})

    reply = "".join(b.text for b in response.content if b.type == "text") if response else ""
    if not reply:
        reply = "I wasn't able to complete that request — please try rephrasing."
    return {"reply": reply, "tools_used": tools_used, "_generated_by": "claude"}


# ---------------------------------------------------------------------------
# Offline intent engine (no API key)
# ---------------------------------------------------------------------------

OFFLINE_HELP = (
    "**Fusion Assistant (offline mode)** — I can answer from live platform data:\n\n"
    "- `portfolio` or `overview` — all studies at a glance\n"
    "- `report for FUS-ONC-301` — full study report (works with any protocol ID or title keyword)\n"
    "- `open queries for FUS-CVD-201` — data management worklist\n"
    "- `safety cases` / `SAEs for FUS-ONC-301` — pharmacovigilance status\n"
    "- `adverse events for <study>` — AE listing\n\n"
    "Configure `ANTHROPIC_API_KEY` to unlock free-form conversation, general "
    "clinical research Q&A, and registry search summaries."
)


def _md_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(label for _, label in columns) + " |"
    sep = "|" + "|".join("---" for _ in columns) + "|"
    body = "\n".join(
        "| " + " | ".join(str(r.get(key, "—") if r.get(key) is not None else "—") for key, _ in columns) + " |"
        for r in rows
    )
    return f"{head}\n{sep}\n{body}"


def _offline_report(study: dict) -> str:
    r = _study_report_with_links(study)
    e, dq, sa, ep, su, co = (r["enrollment"], r["data_quality"], r["safety"],
                             r["epro"], r["supply"], r["consent"])
    soc_rows = [{"soc": k, "count": v} for k, v in sa["by_soc"].items()]
    site_rows = r["enrollment"]["by_site"]
    links = " · ".join(f"[{d}]({u})" for d, u in zip(r["available_exports"], r["csv_export_links"]))
    return (
        f"## Study report — {r['study']['protocol_id']}\n"
        f"*{r['study']['title']}* ({r['study']['phase']}, {r['study']['status']}) — generated {r['generated_at']} UTC\n\n"
        f"### Enrollment\n"
        f"- **{e['enrolled']} / {e['target']}** enrolled ({e['pct_of_target']}% of target), {e['randomized']} randomized\n\n"
        + _md_table(site_rows, [("site", "Site"), ("country", "Country"), ("status", "Status"),
                                ("enrolled", "Enrolled"), ("open_queries", "Open queries"), ("aes", "AEs")])
        + f"\n\n### Data quality\n"
        f"- CRF records: {dq['crf_records']} ({dq['crf_clean']} clean)\n"
        f"- Queries: {dq['queries_total']} total, **{dq['queries_open']} open** "
        f"({', '.join(f'{v} {k}' for k, v in dq['open_by_severity'].items()) or 'none'})\n\n"
        f"### Safety\n"
        f"- {sa['total_aes']} adverse events, **{sa['saes']} serious**, {sa['uncoded']} uncoded, "
        f"{sa['open_cases']} open safety case(s), {sa['expedited_cases']} expedited (SUSAR)\n\n"
        + (_md_table(soc_rows, [("soc", "System Organ Class"), ("count", "Events")]) if soc_rows else "")
        + f"\n\n### ePRO, supply & consent\n"
        f"- ePRO: {ep['submissions']} submissions, {ep['alerts']} symptom alert(s), avg score {ep['avg_score'] if ep['avg_score'] is not None else 'n/a'}\n"
        f"- Supply: {su['kits_available']} kits available, {su['kits_dispensed']} dispensed\n"
        f"- Consent: {co['consented']} consented, **{co['missing']} missing**\n\n"
        f"### CSV exports\n{links}\n\n"
        f"*Generated by the offline reporting engine — configure ANTHROPIC_API_KEY for conversational analysis.*"
    )


def _offline_chat(message: str) -> dict:
    text = message.lower()
    study = None
    # Try to find a study reference anywhere in the message.
    for s in find_all("studies"):
        if s["protocol_id"].lower() in text:
            study = s
            break
    if not study:
        m = re.search(r"(?:for|of|on)\s+([a-z0-9 -]{3,40})$", text.strip())
        if m:
            study = _resolve_study(m.group(1))

    tools_used = []

    if "report" in text or "summary" in text or "status" in text:
        if study:
            tools_used.append("get_study_report")
            return {"reply": _offline_report(study), "tools_used": tools_used, "_generated_by": "offline-intents"}
        return {"reply": "Which study? Try `report for FUS-ONC-301`.\n\n" + _offline_portfolio(),
                "tools_used": ["get_portfolio_overview"], "_generated_by": "offline-intents"}

    if "quer" in text:
        if study:
            result = execute_tool("list_open_queries", {"study": study["protocol_id"]})
            rows = result["queries"][:15]
            reply = (f"**{result['count']} open quer{'y' if result['count'] == 1 else 'ies'} for {study['protocol_id']}**\n\n"
                     + (_md_table(rows, [("subject_code", "Subject"), ("field", "Field"),
                                         ("severity", "Severity"), ("issue", "Issue")]) if rows else "No open queries."))
            return {"reply": reply, "tools_used": ["list_open_queries"], "_generated_by": "offline-intents"}
        return {"reply": "Which study's queries? Try `open queries for FUS-ONC-301`.",
                "tools_used": [], "_generated_by": "offline-intents"}

    if "safety case" in text or "susar" in text or "pharmacovigilance" in text or "case" in text:
        result = execute_tool("list_safety_cases", {"study": study["protocol_id"]} if study else {})
        rows = [{**c, "expedited": "SUSAR" if c["expedited"] else "—"} for c in result["cases"][:15]]
        reply = (f"**Safety cases ({result['study']})**\n\n"
                 + (_md_table(rows, [("case_number", "Case"), ("subject_code", "Subject"), ("event", "Event"),
                                     ("status", "Status"), ("causality", "Causality"), ("expedited", "Expedited")])
                    if rows else "No safety cases."))
        return {"reply": reply, "tools_used": ["list_safety_cases"], "_generated_by": "offline-intents"}

    if "adverse" in text or "sae" in text or " ae" in f" {text}":
        if study:
            serious = "sae" in text or "serious" in text
            result = execute_tool("list_adverse_events", {"study": study["protocol_id"], "serious_only": serious})
            rows = result["adverse_events"][:15]
            reply = (f"**{result['count']} {'serious ' if serious else ''}adverse event(s) for {study['protocol_id']}**\n\n"
                     + (_md_table(rows, [("subject_code", "Subject"), ("verbatim_term", "Verbatim"),
                                         ("preferred_term", "Coded"), ("severity", "Severity"),
                                         ("outcome", "Outcome")]) if rows else "None reported."))
            return {"reply": reply, "tools_used": ["list_adverse_events"], "_generated_by": "offline-intents"}
        return {"reply": "Which study's adverse events? Try `SAEs for FUS-ONC-301`.",
                "tools_used": [], "_generated_by": "offline-intents"}

    if "portfolio" in text or "overview" in text or "studies" in text or "enroll" in text or "dashboard" in text:
        return {"reply": _offline_portfolio(), "tools_used": ["get_portfolio_overview"],
                "_generated_by": "offline-intents"}

    return {"reply": OFFLINE_HELP, "tools_used": [], "_generated_by": "offline-intents"}


def _offline_portfolio() -> str:
    o = _portfolio_overview()
    t = o["totals"]
    rows = [{**s, "enrollment": f"{s['enrolled']}/{s['target_enrollment']}"} for s in o["studies"]]
    return (
        f"**Portfolio overview** — {t['studies']} studies, {t['sites']} sites, "
        f"{t['participants']} participants, {t['saes']} SAEs, {t['open_queries']} open queries, "
        f"{t['pro_alerts']} ePRO alert(s)\n\n"
        + _md_table(rows, [("protocol_id", "Protocol"), ("phase", "Phase"), ("status", "Status"),
                           ("enrollment", "Enrolled"), ("sites", "Sites"), ("saes", "SAEs"),
                           ("open_queries", "Open queries")])
    )
