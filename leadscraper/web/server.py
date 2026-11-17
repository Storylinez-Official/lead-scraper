"""Dashboard HTTP API and run manager.

  GET  /                     dashboard
  GET  /api/meta             model, sources, pipeline steps, current run
  POST /api/runs             start a batch run   {sources, limit, concurrency}
  POST /api/audit            audit one website   {url, name?}
  POST /api/stop             stop submitting new leads (in-flight leads finish)
  GET  /api/events           server-sent events for the current run
  GET  /api/history          past runs in the output directory
  GET  /api/history/{run_id} rows and full lead states of a past run

One run at a time. The run executes on a background thread using the same
runner the CLI uses, and publishes every step to the event bus.
"""

import asyncio
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..graph import STEPS
from ..llm import LLM, ConfigError
from ..output import RunWriter, lead_slug
from ..runner import RunHooks, iter_leads, process_leads
from ..schemas import Lead
from ..settings import Settings
from ..sources import load_source_configs
from ..urls import normalize_url
from .events import BusLogHandler, EventBus

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
_RUN_ID_RE = re.compile(r"^run-\d{8}-\d{6}$")

STEP_INFO = {
    "assess_business": ("2.1", "Qualify", "Header scan + AI: does this product need docs?"),
    "find_documentation": ("2.2", "Find docs", "Regex-score candidate pages"),
    "collect_contacts": ("3", "Crawl contacts", "Same-site crawl, regex emails & phones"),
    "purify_contacts": ("4", "Purify", "AI cleans contacts, guard blocks inventions"),
    "research_company": ("4.5", "Research", "Team pages + changelog: people, intent signals"),
    "analyze_documentation": ("5", "Audit docs", "AI scores quality, completeness, usability"),
    "generate_report": ("6", "Report", "Summary, improvements, outreach opener"),
}


class RunRequest(BaseModel):
    sources: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=100)
    concurrency: int = Field(default=3, ge=1, le=8)


class AuditRequest(BaseModel):
    url: str
    name: str | None = None


def _lead_ref(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead_slug(lead.website),
        "name": lead.name,
        "website": lead.website,
        "source": lead.source,
        "source_url": lead.source_url,
        "description": lead.description,
    }


class RunManager:
    def __init__(self, settings: Settings, bus: EventBus):
        self.settings = settings
        self.bus = bus
        self.current: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, kind: str, leads_or_request: Any) -> dict[str, Any]:
        if self.running:
            raise HTTPException(409, "a run is already in progress")
        LLM(self.settings)  # surface a missing API key as an HTTP error, not a dead thread
        writer = RunWriter(self.settings.output_dir)
        self._stop.clear()
        self.current = {"id": writer.dir.name, "kind": kind, "status": "running", "started": time.time()}
        if kind == "batch":
            req: RunRequest = leads_or_request
            self.current.update(sources=req.sources, limit=req.limit, concurrency=req.concurrency)
        self.bus.clear()
        self.bus.publish("run_started", run=self.current)
        self._thread = threading.Thread(target=self._run, args=(kind, leads_or_request, writer), daemon=True, name="run")
        self._thread.start()
        return self.current

    def stop(self) -> None:
        if self.running:
            self._stop.set()
            self.bus.publish("run_stopping")

    def _hooks(self) -> RunHooks:
        pub = self.bus.publish
        return RunHooks(
            on_source=lambda name, phase, count: pub("source", source=name, phase=phase, count=count),
            on_lead_collected=lambda lead: pub("lead_queued", lead=_lead_ref(lead)),
            on_lead_started=lambda lead: pub("lead_started", id=lead_slug(lead.website)),
            on_node=lambda lead, node, update: pub("lead_node", id=lead_slug(lead.website), node=node, update=update),
            on_done=lambda row, state: pub(
                "lead_done", id=lead_slug(state["lead"]["website"]), row=row, state=state
            ),
            should_stop=self._stop.is_set,
        )

    def _run(self, kind: str, payload: Any, writer: RunWriter) -> None:
        hooks = self._hooks()
        try:
            if kind == "batch":
                leads = iter_leads(self.settings, payload.sources or None, payload.limit, hooks)
                concurrency = payload.concurrency
            else:
                leads, concurrency = [payload], 1
            process_leads(leads, self.settings, writer, concurrency, hooks)
            out = writer.finish()
            summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            self.current.update(status="stopped" if self._stop.is_set() else "finished", summary=summary)
            self.bus.publish("run_finished", run=self.current)
        except Exception as exc:
            log.exception("run failed")
            writer.finish()
            self.current.update(status="failed", error=str(exc))
            self.bus.publish("run_finished", run=self.current)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def create_app(settings: Settings) -> FastAPI:
    bus = EventBus()
    runs = RunManager(settings, bus)

    pkg_logger = logging.getLogger("leadscraper")
    pkg_logger.addHandler(BusLogHandler(bus))
    pkg_logger.setLevel(logging.INFO)

    app = FastAPI(title="LeadScraper", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        sources = [
            {"name": c.name, "adapter": c.adapter, "url": c.url, "enabled": c.enabled}
            for c in load_source_configs(settings.sources_file)
        ]
        steps = [
            {"node": name, "num": STEP_INFO[name][0], "label": STEP_INFO[name][1], "desc": STEP_INFO[name][2]}
            for name in STEPS
        ]
        return {
            "model": settings.openai_model,
            "has_api_key": bool(settings.openai_api_key),
            "sources": sources,
            "steps": steps,
            "run": runs.current,
            "running": runs.running,
        }

    @app.post("/api/runs")
    def start_run(req: RunRequest) -> dict[str, Any]:
        try:
            return runs.start("batch", req)
        except ConfigError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/audit")
    def audit(req: AuditRequest) -> dict[str, Any]:
        website = normalize_url(req.url)
        if not website:
            raise HTTPException(400, f"invalid URL: {req.url}")
        lead = Lead(name=req.name or lead_slug(website), website=website, source="manual")
        try:
            return runs.start("audit", lead)
        except ConfigError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/stop")
    def stop() -> dict[str, bool]:
        runs.stop()
        return {"ok": True}

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        async def stream():
            agen = bus.subscribe()
            next_event = asyncio.ensure_future(agen.__anext__())
            try:
                while True:
                    done, _ = await asyncio.wait({next_event}, timeout=15)
                    if not done:
                        yield ": keepalive\n\n"
                        continue
                    event = next_event.result()
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                    next_event = asyncio.ensure_future(agen.__anext__())
            finally:
                next_event.cancel()
                await agen.aclose()

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    @app.get("/api/history")
    def history() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not settings.output_dir.exists():
            return out
        for d in sorted(settings.output_dir.iterdir(), reverse=True):
            if not (d.is_dir() and _RUN_ID_RE.match(d.name)):
                continue
            rows = _read_jsonl(d / "leads.jsonl")
            if not rows:
                continue
            out.append({
                "id": d.name,
                "total": len(rows),
                "qualified": sum(r["status"] == "qualified" for r in rows),
                "sources": sorted({r["source"] for r in rows}),
            })
        return out[:50]

    @app.get("/api/history/{run_id}")
    def history_run(run_id: str) -> dict[str, Any]:
        if not _RUN_ID_RE.match(run_id) or not (settings.output_dir / run_id).is_dir():
            raise HTTPException(404, "run not found")
        d = settings.output_dir / run_id
        states = {}
        for f in sorted((d / "leads").glob("*.json")):
            states[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        return {"id": run_id, "rows": _read_jsonl(d / "leads.jsonl"), "states": states}

    return app
