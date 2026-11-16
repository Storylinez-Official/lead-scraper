"""Command line interface. Run `python -m leadscraper --help`."""

import argparse
import json
import logging
import sys
from pathlib import Path

import uvicorn

from .graph import build_graph, run_lead
from .llm import LLM, ConfigError
from .output import RunWriter, render_markdown
from .runner import RunHooks, collect_leads, iter_leads, process_leads
from .schemas import Lead
from .settings import Settings
from .sources import adapters, load_source_configs
from .urls import normalize_url
from .web.server import create_app


def _print_row(row: dict) -> None:
    mark = {"qualified": "OK  ", "skipped": "SKIP", "error": "ERR "}.get(row["status"], "?   ")
    detail = (
        f"lead {row['lead_score']}/100, docs {row['doc_overall']}/10, {row['emails'] or row['phone_numbers']}"
        if row["status"] == "qualified"
        else f"[{row['stage']}] {row['skip_reason'][:140]}"
    )
    print(f"{mark} {row['name'][:40]:40} {row['website'][:45]:45} {detail}", flush=True)


def cmd_sources(args: argparse.Namespace, settings: Settings) -> int:
    for c in load_source_configs(settings.sources_file):
        state = "" if c.enabled else " (disabled)"
        print(f"{c.name:32} {c.adapter:16} {c.url}{state}")
    print(f"\nadapters: {', '.join(adapters())}")
    return 0


def cmd_collect(args: argparse.Namespace, settings: Settings) -> int:
    leads = collect_leads(settings, args.source, args.limit)
    for lead in leads:
        print(json.dumps(lead.model_dump(), ensure_ascii=False))
    print(f"{len(leads)} leads", file=sys.stderr)
    return 0


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    LLM(settings)  # fail on a missing API key before spending minutes scraping
    writer = RunWriter(settings.output_dir)
    print(f"output -> {writer.dir}", flush=True)
    hooks = RunHooks(on_done=lambda row, state: _print_row(row))
    leads = iter_leads(settings, args.source, args.limit)
    count = process_leads(leads, settings, writer, args.concurrency or settings.concurrency, hooks)
    out = writer.finish()
    if not count:
        print("no leads collected", file=sys.stderr)
        return 1
    print(f"\ndone: {out}")
    print(json.dumps(json.loads((out / "summary.json").read_text()), indent=2))
    return 0


def cmd_lead(args: argparse.Namespace, settings: Settings) -> int:
    website = normalize_url(args.url)
    if not website:
        print(f"invalid URL: {args.url}", file=sys.stderr)
        return 2
    lead = Lead(name=args.name or website, website=website, source="manual", description=args.description or "")
    state = run_lead(build_graph(), lead, settings, LLM(settings))
    writer = RunWriter(settings.output_dir)
    row = writer.write(state)
    writer.finish()
    _print_row(row)
    if state.get("status") == "qualified" and not args.quiet:
        print("\n" + render_markdown(state))
    print(f"\noutput: {writer.dir}")
    return 0 if state.get("status") != "error" else 1


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    print(f"dashboard: http://{args.host}:{args.port}", flush=True)
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_graph(args: argparse.Namespace, settings: Settings) -> int:
    print(build_graph().get_graph().draw_mermaid())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="leadscraper", description="Find products with docs, audit the docs, collect contacts.")
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v info for libraries, -vv debug")
    p.add_argument("--sources-file", type=Path, help="default: config/sources.yaml")
    p.add_argument("--output-dir", type=Path, help="default: output/")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sources", help="list configured sources and adapters")

    for name, help_ in (("collect", "list leads from sources only (no LLM calls)"), ("run", "full pipeline")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--source", action="append", help="source name (repeatable); default: all enabled")
        sp.add_argument("--limit", type=int, default=10, help="max leads per source (default 10)")
        if name == "run":
            sp.add_argument("--concurrency", type=int, help="leads processed in parallel")

    sp = sub.add_parser("lead", help="run the pipeline on a single website")
    sp.add_argument("url")
    sp.add_argument("--name")
    sp.add_argument("--description")
    sp.add_argument("-q", "--quiet", action="store_true", help="do not print the Markdown report")

    sub.add_parser("graph", help="print the pipeline graph as Mermaid")

    sp = sub.add_parser("serve", help="live dashboard")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)

    args = p.parse_args(argv)
    # Windows consoles default to cp1252; product names are often not ASCII.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    level = logging.DEBUG if args.verbose >= 2 else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-5s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if args.verbose < 1:
        for noisy in ("httpx", "httpcore", "openai", "langchain", "langgraph"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    overrides = {k: v for k, v in (("sources_file", args.sources_file), ("output_dir", args.output_dir)) if v}
    settings = Settings(**overrides)
    handlers = {"sources": cmd_sources, "collect": cmd_collect, "run": cmd_run, "lead": cmd_lead, "graph": cmd_graph,
                "serve": cmd_serve}
    try:
        return handlers[args.cmd](args, settings)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
