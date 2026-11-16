"""Run output: per-lead JSON, per-qualified-lead Markdown, leads.csv, leads.jsonl.

output/run-YYYYmmdd-HHMMSS/
  leads.jsonl          one line per processed lead, appended as each finishes
  leads.csv            summary table, written at the end
  summary.json         counts by status and by stop stage
  leads/<slug>.json    full state of each lead
  reports/<slug>.md    readable report, qualified leads only
"""

import csv
import json
import re
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .urls import hostname

CSV_FIELDS = [
    "name", "website", "source", "status", "stage", "skip_reason", "business_type",
    "doc_url", "doc_discovery_score", "emails", "phone_numbers", "decision_makers", "intent_signals",
    "doc_overall", "doc_quality", "doc_completeness", "doc_usability",
    "lead_score", "outreach_subject", "report_file",
]


def lead_slug(website: str) -> str:
    """Stable per-lead id: the host without www. Used for file names and by the dashboard."""
    return re.sub(r"[^a-z0-9.-]+", "-", hostname(website).removeprefix("www.")) or "lead"


class RunWriter:
    def __init__(self, base_dir: Path):
        self.dir = base_dir / datetime.now().strftime("run-%Y%m%d-%H%M%S")
        (self.dir / "leads").mkdir(parents=True, exist_ok=True)
        (self.dir / "reports").mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self.rows: list[dict[str, Any]] = []

    def write(self, state: dict) -> dict[str, Any]:
        slug = lead_slug(state["lead"]["website"])
        with self._lock:
            (self.dir / "leads" / f"{slug}.json").write_text(
                json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            report_file = ""
            if state.get("status") == "qualified":
                report_file = f"reports/{slug}.md"
                (self.dir / report_file).write_text(render_markdown(state), encoding="utf-8")
            row = to_row(state, report_file)
            with (self.dir / "leads.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.rows.append(row)
        return row

    def finish(self) -> Path:
        rows = sorted(self.rows, key=lambda r: (r["status"] != "qualified", -(r["lead_score"] or 0), r["name"]))
        with (self.dir / "leads.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            w.writerows(rows)
        summary = {
            "total": len(rows),
            "by_status": dict(Counter(r["status"] for r in rows)),
            "stopped_at": dict(Counter(r["stage"] for r in rows if r["status"] != "qualified")),
        }
        (self.dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return self.dir


def to_row(state: dict, report_file: str = "") -> dict[str, Any]:
    lead = state["lead"]
    docs = state.get("docs") or {}
    contacts = state.get("contacts") or {}
    analysis = state.get("doc_analysis") or {}
    report = state.get("report") or {}
    research = state.get("research") or {}
    return {
        "name": lead["name"],
        "website": lead["website"],
        "source": lead["source"],
        "status": state.get("status"),
        "stage": state.get("stage"),
        "skip_reason": state.get("skip_reason", ""),
        "business_type": (state.get("assessment") or {}).get("business_type", ""),
        "doc_url": docs.get("doc_url") or "",
        "doc_discovery_score": docs.get("score", ""),
        "emails": "; ".join(contacts.get("emails", [])),
        "phone_numbers": "; ".join(contacts.get("phone_numbers", [])),
        "decision_makers": "; ".join(f"{p['name']} ({p['role']})" for p in research.get("people", [])),
        "intent_signals": "; ".join(
            f"{s['date'] or 'undated'} {s['title']} {s['url']}".strip() for s in research.get("signals", [])
        ),
        "doc_overall": analysis.get("overall_score", ""),
        "doc_quality": (analysis.get("quality") or {}).get("score", ""),
        "doc_completeness": (analysis.get("completeness") or {}).get("score", ""),
        "doc_usability": (analysis.get("usability") or {}).get("score", ""),
        "lead_score": report.get("lead_score"),
        "outreach_subject": (report.get("outreach") or {}).get("subject", ""),
        "report_file": report_file,
    }


def render_markdown(state: dict) -> str:
    lead = state["lead"]
    a = state["doc_analysis"]
    r = state["report"]
    c = state["contacts"]
    m = state.get("doc_metrics", {})
    lines = [
        f"# {lead['name']}",
        "",
        f"- Website: {state['homepage_url']}",
        f"- Documentation: {state['docs']['doc_url']}",
        f"- Business type: {state['assessment']['business_type']}",
        f"- Source: {lead['source']}" + (f" ({lead['source_url']})" if lead.get("source_url") else ""),
        f"- Lead score: **{r['lead_score']}/100** - {r['lead_score_reason']}",
        "",
        "## Summary",
        "",
        r["executive_summary"],
        "",
        "## Documentation scores",
        "",
        "| Dimension | Score | Why |",
        "|---|---|---|",
    ]
    def cell(text: str) -> str:
        return " ".join(str(text).split()).replace("|", "\\|")

    for key in ("quality", "completeness", "usability"):
        lines.append(f"| {key.title()} | {a[key]['score']}/10 | {cell(a[key]['justification'])} |")
    lines += [f"| **Overall** | **{a['overall_score']}/10** | {cell(a['doc_type'])} |", ""]

    def bullets(title: str, items: list[str]) -> None:
        if items:
            lines.extend([f"### {title}", "", *[f"- {i}" for i in items], ""])

    bullets("Strengths", a["strengths"])
    bullets("Weaknesses", a["weaknesses"])
    bullets("Missing sections", a["missing_sections"])

    lines += ["## Recommended improvements", ""]
    for i, imp in enumerate(r["improvements"], 1):
        lines.append(f"{i}. **[{imp['priority']}] {imp['area']}**: {imp['issue']} -> {imp['recommendation']}")
    lines += ["", "## Contacts", ""]
    lines += [f"- {e}" for e in c["emails"]] + [f"- {p}" for p in c["phone_numbers"]]

    research = state.get("research") or {}
    who = research.get("recipient")
    lines += ["", "## People", ""]
    if research.get("people"):
        lines += [f"- **{p['name']}**, {p['role']} ({p['source_url']})"
                  + (" - recommended recipient" if who and p["name"] == who["name"] else "")
                  for p in research["people"]]
    else:
        lines.append("- None named on the team/about pages checked.")
    lines += ["", "## Intent signals", ""]
    if research.get("signals"):
        for s in research["signals"]:
            when = f"{s['date']} ({s['days_ago']} days ago)" if s.get("days_ago") is not None else (s["date"] or "undated")
            lines.append(f"- **{s['title']}** - {when} - {s['url']}")
            lines.append(f"  - {s['summary']} {s['why_it_matters']}")
    else:
        lines.append("- No changelog entries found" + (f" ({research['changelog_url']})." if research.get("changelog_url") else "."))
    lines += [
        "",
        "## Outreach opener",
        "",
        *([f"**To:** {who['name']} ({who['role']})", ""] if who else []),
        f"**Subject:** {r['outreach']['subject']}",
        "",
        r["outreach"]["body"],
        "",
        "## Evidence",
        "",
        f"- Doc discovery score {state['docs']['score']}: " + "; ".join(state["docs"]["signals"]),
        f"- Pages sampled: {m.get('pages_sampled')}, code blocks: {m.get('code_blocks_total')}, "
        f"languages: {', '.join(m.get('code_languages', [])) or 'none detected'}, search: {m.get('has_search')}",
        *[f"  - {p['title'] or p['url']}: {p['url']}" for p in state.get("doc_pages", [])],
        "",
    ]
    return "\n".join(lines)
