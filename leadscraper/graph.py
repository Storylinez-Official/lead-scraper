"""The per-lead LangGraph pipeline.

    START
      -> assess_business        (2.1) header keyword scan + LLM: is this worth pursuing?
      -?-> find_documentation   (2.2) regex-score candidate pages, pick the docs URL
      -?-> collect_contacts     (3)   crawl the site, regex emails and phones
      -?-> purify_contacts      (4)   LLM cleans the list (structured output), code guards it
      -?-> research_company     (4.5) team pages + changelog: named people, recent intent signals (never drops)
      -?-> analyze_documentation(5)   sample doc pages, LLM scores them
      -?-> generate_report      (6)   LLM summary, improvements, outreach opener
      -> END

Each node decides whether the lead survives and sets `status`. Every
conditional edge (-?->) continues only while `status == "running"`; any other
status ("skipped", "error") routes to END. So the graph's path is fully
determined by the node outputs, and a skipped lead records where and why it
stopped.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from .crawler import crawl_contacts
from .docs import find_documentation, sample_documentation
from .extract import (
    Link,
    clean_email,
    clean_phone,
    doc_nav_links,
    header_links,
    meta_description,
    page_title,
    phone_digits,
    visible_text,
)
from .fetcher import Fetcher
from .llm import LLM
from .research import gather
from .schemas import Lead
from .settings import Settings
from .urls import normalize_url, registrable_domain

log = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    settings: Settings
    llm: LLM
    fetcher: Fetcher


class LeadState(TypedDict, total=False):
    lead: dict
    status: str  # running | qualified | skipped | error
    stage: str  # last node that ran
    skip_reason: str
    timings: dict[str, float]
    homepage_url: str
    header_doc_links: list[dict]
    assessment: dict
    docs: dict
    raw_contacts: dict
    contacts: dict
    contact_guard: dict
    research: dict
    doc_metrics: dict
    doc_pages: list[dict]
    doc_analysis: dict
    report: dict


NodeFn = Callable[[LeadState, PipelineContext], dict[str, Any]]


def _node(name: str, fn: NodeFn):
    """Wrap a node: record timing and stage, turn exceptions into status=error."""

    def run(state: LeadState, runtime: Runtime[PipelineContext]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            update = fn(state, runtime.context)
        except Exception as exc:  # one bad site must not kill the batch
            log.exception("%s failed for %s", name, state["lead"]["website"])
            update = {"status": "error", "skip_reason": f"{name}: {type(exc).__name__}: {exc}"}
        timings = {**state.get("timings", {}), name: round(time.monotonic() - started, 2)}
        return {"stage": name, "timings": timings, **update}

    return run


def _skip(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "skipped", "skip_reason": reason, **extra}


def _fmt_links(links: list[Link], limit: int = 40) -> str:
    return "\n".join(f"- {link.text or '(no text)'} -> {link.url}" for link in links[:limit]) or "(none)"


# --- nodes -------------------------------------------------------------------


def assess_business(state: LeadState, ctx: PipelineContext) -> dict[str, Any]:
    lead = Lead(**state["lead"])
    home = ctx.fetcher.get(lead.website)
    if home is None or not home.ok:
        return _skip(f"homepage unreachable ({home.status if home else 'network error'})")

    nav = header_links(home.soup, home.url)
    doc_links = doc_nav_links(nav)
    assessment = ctx.llm.assess_business(
        name=lead.name,
        url=home.url,
        description=lead.description or "(none)",
        title=page_title(home.soup),
        meta=meta_description(home.soup),
        nav_links=_fmt_links(nav),
        doc_links=_fmt_links(doc_links),
        text=visible_text(home.soup, max_chars=3000),
    )
    assessment.confidence = min(max(assessment.confidence, 0.0), 1.0)
    update = {
        "homepage_url": home.url,
        "header_doc_links": [asdict(link) for link in doc_links],
        "assessment": assessment.model_dump(),
    }
    if not assessment.worth_pursuing:
        return _skip(f"not worth pursuing: {assessment.reasoning}", **update)
    return update


def find_docs(state: LeadState, ctx: PipelineContext) -> dict[str, Any]:
    home = ctx.fetcher.get(state["homepage_url"])
    links = [Link(**link) for link in state.get("header_doc_links", [])]
    discovery = find_documentation(
        ctx.fetcher, home, links, ctx.settings.docs_max_candidates, ctx.settings.docs_score_threshold
    )
    update = {"docs": asdict(discovery)}
    if not discovery.doc_url:
        return _skip(
            f"no documentation found (best score {discovery.score} < {ctx.settings.docs_score_threshold})", **update
        )
    return update


def collect_contacts(state: LeadState, ctx: PipelineContext) -> dict[str, Any]:
    crawl = crawl_contacts(
        ctx.fetcher, state["homepage_url"], ctx.settings.contact_max_pages, extra_urls=[state["docs"]["doc_url"]]
    )
    update = {
        "raw_contacts": {"emails": crawl.emails, "phones": crawl.phones, "pages_visited": crawl.pages_visited}
    }
    if not crawl.found_any:
        return _skip(f"no contact information found ({len(crawl.pages_visited)} pages crawled)", **update)
    return update


def purify_contacts(state: LeadState, ctx: PipelineContext) -> dict[str, Any]:
    raw = state["raw_contacts"]
    url = state["homepage_url"]
    result = ctx.llm.purify_contacts(url, registrable_domain(url), raw["emails"], raw["phones"])

    # Guard: the LLM may only remove or reformat, never add. Anything whose
    # email / digits are not in the crawled input is dropped.
    raw_emails = set(raw["emails"])
    raw_digits = [phone_digits(p) for p in raw["phones"]]
    emails: list[str] = []
    for e in result.emails:
        cleaned = clean_email(e)
        if cleaned and cleaned in raw_emails and cleaned not in emails:
            emails.append(cleaned)
    phones: list[str] = []
    seen_digits: set[str] = set()
    for p in result.phone_numbers:
        cleaned = clean_phone(p)
        if not cleaned:
            continue
        d = phone_digits(cleaned)
        # Allow a country code of up to 3 digits to be prepended.
        if d in seen_digits or not any(d == r or (d.endswith(r) and len(d) - len(r) <= 3) for r in raw_digits):
            continue
        seen_digits.add(d)
        phones.append(cleaned)

    guard = {
        "llm_emails": result.emails,
        "llm_phone_numbers": result.phone_numbers,
        "rejected_by_guard": [x for x in result.emails if clean_email(x) not in emails]
        + [x for x in result.phone_numbers if clean_phone(x) not in phones],
    }
    update = {"contacts": {"emails": emails, "phone_numbers": phones}, "contact_guard": guard}
    if not emails and not phones:
        return _skip("no valid contacts after purification", **update)
    return update


# Who to address, best first: people who own docs, then product, engineering, leadership.
_ROLE_TIERS = [
    re.compile(r"devrel|developer (relations|advocate|experience|marketing)|documentation|\bdocs\b|technical writ", re.I),
    re.compile(r"\bproduct\b|\bCPO\b", re.I),
    re.compile(r"\bCTO\b|chief technology|engineering|technical", re.I),
    re.compile(r"\bCEO\b|founder|chief executive", re.I),
]
RECENT_DAYS = 90  # scores points
STALE_DAYS = 183  # older signals are dropped (the prompt asks for the last 6 months)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def pick_recipient(people: list[dict]) -> dict | None:
    for tier in _ROLE_TIERS:
        for person in people:
            if tier.search(person["role"]):
                return person
    return people[0] if people else None


def research_company(state: LeadState, ctx: PipelineContext) -> dict[str, Any]:
    """Informational step: it never drops a lead, so failures are recorded, not raised."""
    lead = Lead(**state["lead"])
    today = date.today()
    research: dict[str, Any] = {"people": [], "signals": [], "recipient": None, "rejected_by_guard": [], "error": ""}
    try:
        src = gather(ctx.fetcher, state["homepage_url"], state["docs"]["doc_url"])
        research["people_pages"] = [p.url for p in src.people_pages]
        research["changelog_url"] = src.changelog.url if src.changelog else ""
        if not src.people_pages and not src.changelog:
            return {"research": research}
        result = ctx.llm.research(
            name=lead.name,
            url=state["homepage_url"],
            today=today.isoformat(),
            people_pages="\n\n".join(f"### {p.title}\nURL: {p.url}\n{p.text}" for p in src.people_pages) or "(none found)",
            changelog_url=src.changelog.url if src.changelog else "(none found)",
            changelog_text=src.changelog.text if src.changelog else "",
            changelog_links=_fmt_links(src.changelog_links, limit=120),
        )

        # Guard: a person must be named, verbatim, on a page we fetched.
        texts = {p.url: _norm(p.text) for p in src.people_pages}
        for person in result.people:
            name = " ".join(person.name.split())
            where = [u for u, t in texts.items() if name and _norm(name) in t]
            if not where:
                research["rejected_by_guard"].append(name)
            elif not any(_norm(x["name"]) == _norm(name) for x in research["people"]):
                source = person.source_url if person.source_url in where else where[0]
                research["people"].append({"name": name, "role": person.role.strip(), "source_url": source})

        # Guard: a signal must be on the changelog page (its link, or its title in the page text).
        allowed = {link.url for link in src.changelog_links}
        page_text = _norm(src.changelog.text) if src.changelog else ""
        for sig in result.signals[:3]:
            url = normalize_url(sig.url) if sig.url else None
            if not (url in allowed or (sig.title and _norm(sig.title)[:60] in page_text)):
                research["rejected_by_guard"].append(sig.title)
                continue
            try:
                days_ago = (today - date.fromisoformat(sig.date)).days
            except ValueError:
                days_ago = None
            if days_ago is not None and days_ago > STALE_DAYS:
                # Real but old: an opener about a year-old release reads as if we had not looked.
                research.setdefault("stale_signals", []).append(f"{sig.date} {sig.title}")
                continue
            research["signals"].append({
                **sig.model_dump(), "url": url if url in allowed else src.changelog.url, "days_ago": days_ago,
            })
        research["recipient"] = pick_recipient(research["people"])
    except Exception as exc:  # research is a bonus; a failure here must not cost the lead
        log.exception("research failed for %s", lead.website)
        research["error"] = f"{type(exc).__name__}: {exc}"
    return {"research": research}


def analyze_documentation(state: LeadState, ctx: PipelineContext) -> dict[str, Any]:
    lead = Lead(**state["lead"])
    doc_url = state["docs"]["doc_url"]
    sample = sample_documentation(ctx.fetcher, doc_url, ctx.settings.docs_max_pages)
    if not sample.pages:
        return {"status": "error", "skip_reason": f"documentation page unreachable: {doc_url}"}

    metrics = {**sample.metrics, "discovery_score": state["docs"]["score"], "discovery_signals": state["docs"]["signals"]}
    # Found by research_company on the main site; without it the audit reports "no changelog" for docs that link elsewhere.
    if changelog := (state.get("research") or {}).get("changelog_url"):
        metrics["changelog_url"] = changelog
    pages_text = "\n\n".join(f"### {p['title'] or '(untitled)'}\nURL: {p['url']}\n{p['text']}" for p in sample.pages)
    analysis = ctx.llm.analyze_docs(
        name=lead.name,
        url=state["homepage_url"],
        doc_url=doc_url,
        business_type=state["assessment"]["business_type"],
        metrics=_json(metrics),
        pages=pages_text,
    )
    for dim in (analysis.quality, analysis.completeness, analysis.usability):
        dim.score = min(max(dim.score, 0), 10)
    analysis.overall_score = min(max(analysis.overall_score, 0), 10)
    return {
        "doc_metrics": metrics,
        "doc_pages": [{"url": p["url"], "title": p["title"]} for p in sample.pages],
        "doc_analysis": analysis.model_dump(),
    }


_GENERIC_LOCALS = {
    "hello", "hi", "hey", "info", "contact", "team", "sales", "support", "help", "admin", "office",
    "press", "partners", "partnerships", "business", "founders", "general", "mail", "enquiries", "inquiries",
    "customercare", "customer", "customers", "service", "care", "feedback", "marketing", "media", "community",
    "partner", "developers", "dev", "api", "hq", "ops",
}
_UNREACHABLE_LOCALS = re.compile(
    r"^(security|privacy|legal|abuse|no-?reply|do-?not-?reply|dpo|gdpr|compliance|postmaster|dmca|"
    r"billing|accounts?|careers|jobs|hr|whistle-?blowing|ethics|abuse-?report|dmca)\b"
)
_DEV_PRODUCT_RE = re.compile(r"\b(api|sdk|developer|dev ?tool|platform|library|framework|infrastructure|cli|open[- ]source)", re.I)


def score_lead(state: LeadState) -> tuple[int, list[str]]:
    """Deterministic lead score (0-100) with a human-readable breakdown.

    Kept out of the LLM on purpose: given a rubric, the model applied it
    inconsistently and its arithmetic did not match its own explanation.
    """
    parts: list[str] = ["50 base"]
    score = 50

    def add(points: int, why: str) -> None:
        nonlocal score
        score += points
        parts.append(f"{points:+d} {why}")

    doc = state["doc_analysis"]["overall_score"]
    gap = 25 if doc <= 3 else 20 if doc <= 5 else 10 if doc == 6 else 0 if doc == 7 else -15 if doc == 8 else -30
    add(gap, f"docs scored {doc}/10")

    emails = state["contacts"]["emails"]
    locals_ = [e.split("@", 1)[0] for e in emails]
    named = [e for e, loc in zip(emails, locals_) if loc not in _GENERIC_LOCALS and not _UNREACHABLE_LOCALS.match(loc)]
    generic = [e for e, loc in zip(emails, locals_) if loc in _GENERIC_LOCALS]
    if named:
        add(10, f"direct contact ({named[0]})")
    elif generic or state["contacts"]["phone_numbers"]:
        add(5, "team inbox or phone")
    else:
        add(-15, "only security/legal-type addresses")

    if _DEV_PRODUCT_RE.search(state["assessment"]["business_type"]):
        add(10, "developer product, docs drive adoption")

    m = state["doc_metrics"]
    if m.get("pages_sampled", 0) <= 2 and m.get("doc_nav_links", 0) <= 3:
        add(-10, "very small docs site")

    research = state.get("research") or {}
    if who := research.get("recipient"):
        add(5, f"named decision-maker ({who['name']}, {who['role']})")
    recent = [s for s in research.get("signals", []) if s.get("days_ago") is not None and 0 <= s["days_ago"] <= RECENT_DAYS]
    if recent:
        add(10, f"recent docs-relevant change ({recent[0]['title']}, {recent[0]['days_ago']} days ago)")

    return min(max(score, 0), 100), parts


def generate_report(state: LeadState, ctx: PipelineContext) -> dict[str, Any]:
    lead = Lead(**state["lead"])
    contacts = state["contacts"]
    research = state.get("research") or {}
    who = research.get("recipient")
    report = ctx.llm.write_report(
        name=lead.name,
        url=state["homepage_url"],
        doc_url=state["docs"]["doc_url"],
        business_type=state["assessment"]["business_type"],
        contact_summary=f"{len(contacts['emails'])} email(s), {len(contacts['phone_numbers'])} phone number(s)",
        recipient=f"{who['name']} ({who['role']}); greet as 'Hi {who['name'].split()[0]},'"
        if who else "(none identified; write to the team)",
        signals=_json(research.get("signals", [])),
        analysis=_json(state["doc_analysis"]),
        metrics=_json(state["doc_metrics"]),
    )
    score, breakdown = score_lead(state)
    return {
        "report": {**report.model_dump(), "lead_score": score, "lead_score_reason": "; ".join(breakdown)},
        "status": "qualified",
    }


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False)


# --- graph -------------------------------------------------------------------

# Node order as shown on the dashboard; keep in step with build_graph below.
STEPS: list[str] = [
    "assess_business",
    "find_documentation",
    "collect_contacts",
    "purify_contacts",
    "research_company",
    "analyze_documentation",
    "generate_report",
]


def _keep_going(state: LeadState) -> str:
    """Router for every conditional edge: carry on while the lead is still running."""
    return "next" if state.get("status") == "running" else "stop"


# --- node refs ---
# Each step wrapped by _node, which records its timing and stage and turns an
# exception into status="error" so one bad site cannot kill the batch.

# 2.1  Fetch the homepage, LLM decides if the business is worth pursuing.
assess_business_node = _node("assess_business", assess_business)
# 2.2  Score candidate pages and pick the documentation URL.
find_documentation_node = _node("find_documentation", find_docs)
# 3    Crawl the site and regex out emails and phone numbers.
collect_contacts_node = _node("collect_contacts", collect_contacts)
# 4    LLM cleans the contact list; a code guard rejects anything it invented.
purify_contacts_node = _node("purify_contacts", purify_contacts)
# 4.5  Team pages + changelog: named people and recent signals (informational only).
research_company_node = _node("research_company", research_company)
# 5    Sample doc pages and have the LLM score quality, completeness, usability.
analyze_documentation_node = _node("analyze_documentation", analyze_documentation)
# 6    Write the summary and outreach opener, compute the lead score, mark qualified.
generate_report_node = _node("generate_report", generate_report)


# --- edge refs ---
# Path maps for the conditional edges. _keep_going returns "next" while
# status == "running"; any other status ("skipped", "error") takes "stop" to END.

# stop: homepage unreachable, or LLM says not worth pursuing
after_assess_business = {"next": "find_documentation", "stop": END}
# stop: no candidate page scored above the docs threshold
after_find_documentation = {"next": "collect_contacts", "stop": END}
# stop: crawl found no emails or phone numbers
after_collect_contacts = {"next": "purify_contacts", "stop": END}
# stop: nothing survived purification
after_purify_contacts = {"next": "research_company", "stop": END}
# stop: only on an unexpected error; research never skips a lead itself
after_research_company = {"next": "analyze_documentation", "stop": END}
# stop: documentation page unreachable
after_analyze_documentation = {"next": "generate_report", "stop": END}


def build_graph():
    """Wire the pipeline: START -> seven steps in a line -> END, with an exit after each step."""
    g = StateGraph(LeadState, context_schema=PipelineContext)

    # --- nodes ---
    g.add_node("assess_business", assess_business_node)
    g.add_node("find_documentation", find_documentation_node)
    g.add_node("collect_contacts", collect_contacts_node)
    g.add_node("purify_contacts", purify_contacts_node)
    g.add_node("research_company", research_company_node)
    g.add_node("analyze_documentation", analyze_documentation_node)
    g.add_node("generate_report", generate_report_node)

    # --- edges ---
    # Every lead enters at the business assessment.
    g.add_edge(START, "assess_business")
    # Each step either hands off to the next one or ends the run early.
    #
    # add_conditional_edges(source, path, path_map):
    #   source    the node this edge leaves from. The edge is evaluated each
    #             time that node finishes.
    #   path      the router, called with the current state (the source node's
    #             update already merged in). It returns a key, here "next" or
    #             "stop". Without a path_map it would have to return node names.
    #   path_map  maps each key the router can return to a destination node
    #             (END finishes the run). It also tells LangGraph every possible
    #             destination up front, so the drawn graph shows exactly these
    #             two arrows instead of an arrow to every node.
    #
    # Plain add_edge(a, b) is the unconditional version: always go from a to b.
    g.add_conditional_edges("assess_business", _keep_going, after_assess_business)
    g.add_conditional_edges("find_documentation", _keep_going, after_find_documentation)
    g.add_conditional_edges("collect_contacts", _keep_going, after_collect_contacts)
    g.add_conditional_edges("purify_contacts", _keep_going, after_purify_contacts)
    g.add_conditional_edges("research_company", _keep_going, after_research_company)
    g.add_conditional_edges("analyze_documentation", _keep_going, after_analyze_documentation)
    # The report is the last step; the lead is qualified when it gets here.
    g.add_edge("generate_report", END)

    return g.compile()


def run_lead(
    graph,
    lead: Lead,
    settings: Settings,
    llm: LLM,
    on_update: Callable[[str, dict[str, Any]], None] | None = None,
) -> LeadState:
    """Run one lead through the graph, calling `on_update(node, update)` after each node.

    State channels have no reducers, so merging each node's update into a
    dict reproduces exactly what `graph.invoke` would return.
    """
    state: dict[str, Any] = {"lead": lead.model_dump(), "status": "running", "timings": {}}
    with Fetcher(settings) as fetcher:
        ctx = PipelineContext(settings=settings, llm=llm, fetcher=fetcher)
        for chunk in graph.stream(state, context=ctx, stream_mode="updates"):
            for node, update in chunk.items():
                state.update(update)
                if on_update:
                    on_update(node, update)
    return state
