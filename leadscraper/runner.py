"""Batch orchestration: stream leads from sources into the graph.

Sources run one at a time on the calling thread (they may drive a headed
browser); each collected lead is submitted to the worker pool immediately, so
analysis starts while later sources are still being scraped.
"""

import logging
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .graph import build_graph, run_lead
from .llm import LLM
from .output import RunWriter
from .schemas import Lead
from .settings import Settings
from .sources import build_source, load_source_configs
from .urls import registrable_domain

log = logging.getLogger(__name__)


def _never() -> bool:
    return False


@dataclass
class RunHooks:
    """Optional callbacks. Lead and node callbacks fire on worker threads."""

    on_source: Callable[[str, str, int], None] | None = None  # (source, "start"|"done"|"error", count)
    on_lead_collected: Callable[[Lead], None] | None = None
    on_lead_started: Callable[[Lead], None] | None = None
    on_node: Callable[[Lead, str, dict[str, Any]], None] | None = None
    on_done: Callable[[dict, dict], None] | None = None  # (csv row, full state)
    should_stop: Callable[[], bool] = _never


def iter_leads(
    settings: Settings, source_names: list[str] | None, limit: int, hooks: RunHooks | None = None
) -> Iterator[Lead]:
    """Yield leads from each selected source in config order, de-duplicated by site domain."""
    hooks = hooks or RunHooks()
    configs = load_source_configs(settings.sources_file)
    if source_names:
        unknown = set(source_names) - {c.name for c in configs}
        if unknown:
            raise ValueError(f"unknown source(s): {sorted(unknown)}")
        configs = [c for c in configs if c.name in source_names]
    else:
        configs = [c for c in configs if c.enabled]

    seen: set[str] = set()
    for config in configs:
        if hooks.should_stop():
            return
        source = build_source(config, settings)
        per_source = config.limit or limit
        log.info("source %s (%s): up to %d leads", config.name, config.adapter, per_source)
        if hooks.on_source:
            hooks.on_source(config.name, "start", 0)
        count = 0
        try:
            for lead in source.iter_leads(per_source):
                if hooks.should_stop():
                    break
                domain = registrable_domain(lead.website)
                if domain in seen:
                    log.debug("duplicate site %s from %s", domain, config.name)
                    continue
                seen.add(domain)
                count += 1
                yield lead
        except Exception:
            log.exception("source %s failed after %d leads", config.name, count)
            if hooks.on_source:
                hooks.on_source(config.name, "error", count)
            continue
        log.info("source %s: %d leads", config.name, count)
        if hooks.on_source:
            hooks.on_source(config.name, "done", count)


def collect_leads(settings: Settings, source_names: list[str] | None, limit: int) -> list[Lead]:
    return list(iter_leads(settings, source_names, limit))


def process_leads(
    leads: Iterable[Lead],
    settings: Settings,
    writer: RunWriter,
    concurrency: int,
    hooks: RunHooks | None = None,
) -> int:
    """Run every lead through the graph. Returns the number of leads processed."""
    hooks = hooks or RunHooks()
    graph = build_graph()
    llm = LLM(settings)

    def work(lead: Lead) -> dict:
        if hooks.on_lead_started:
            hooks.on_lead_started(lead)
        on_update = (lambda node, update: hooks.on_node(lead, node, update)) if hooks.on_node else None
        return run_lead(graph, lead, settings, llm, on_update=on_update)

    def finish(fut: Future, lead: Lead) -> None:
        try:
            state = fut.result()
        except Exception as exc:  # graph nodes already catch; this is a setup failure
            log.exception("lead %s crashed", lead.website)
            state = {"lead": lead.model_dump(), "status": "error", "stage": "setup", "skip_reason": str(exc)}
        try:
            row = writer.write(state)
            if hooks.on_done:
                hooks.on_done(row, state)
        except Exception:  # done-callback exceptions are otherwise only logged by the executor
            log.exception("writing results for %s failed", lead.website)

    submitted = 0
    # Done-callbacks (not as_completed after the loop) so results are written
    # while sources are still collecting. The pool's exit waits for all work.
    with ThreadPoolExecutor(max_workers=max(1, concurrency), thread_name_prefix="lead") as pool:
        for lead in leads:
            if hooks.should_stop():
                break
            if hooks.on_lead_collected:
                hooks.on_lead_collected(lead)
            pool.submit(work, lead).add_done_callback(lambda fut, lead=lead: finish(fut, lead))
            submitted += 1
    return submitted
