"""Record videos and screenshots of the LeadScraper dashboard for the showcase.

Needs the dashboard running (python -m leadscraper serve).

    python showcase/capture.py tour            # saved run: screenshots + tour video
    python showcase/capture.py audit [URL]     # live single-site audit (uses the OpenAI key)
    python showcase/capture.py run             # live batch run (uses the OpenAI key, ~4-8 min)
    python showcase/capture.py all [URL]

Everything lands in showcase/screenshots and showcase/videos.
"""

import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://127.0.0.1:8765"
HERE = Path(__file__).parent
SHOTS = HERE / "screenshots"
VIDEOS = HERE / "videos"
VIEW = {"width": 1440, "height": 900}

# Headless video has no mouse pointer; draw one so viewers can follow clicks.
CURSOR_JS = """
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.id = '__demo_cursor';
  c.style.cssText = 'position:fixed;z-index:2147483647;width:24px;height:24px;margin:-12px 0 0 -12px;'
    + 'border-radius:50%;background:rgba(229,70,26,.28);border:2px solid rgba(229,70,26,.95);'
    + 'pointer-events:none;transition:transform .12s;left:-100px;top:-100px';
  document.body.appendChild(c);
  document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  document.addEventListener('mousedown', () => c.style.transform = 'scale(.6)', true);
  document.addEventListener('mouseup', () => c.style.transform = '', true);
});
"""


def api(path: str):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())


def shot(page: Page, name: str, **kw) -> None:
    page.evaluate("() => { const c = document.getElementById('__demo_cursor'); if (c) c.style.visibility = 'hidden'; }")
    path = SHOTS / f"{name}.png"
    if "selector" in kw:
        # The sticky masthead would otherwise overlap the top of the element.
        page.evaluate("() => document.querySelector('.masthead').style.visibility = 'hidden'")
        page.locator(kw.pop("selector")).first.screenshot(path=path, **kw)
        page.evaluate("() => document.querySelector('.masthead').style.visibility = ''")
    else:
        page.screenshot(path=path, **kw)
    page.evaluate("() => { const c = document.getElementById('__demo_cursor'); if (c) c.style.visibility = ''; }")
    print("  shot", path.name, flush=True)


def glide(page: Page, selector: str, click: bool = True, pause: float = 0.6) -> None:
    """Move the visible cursor to an element, then click it."""
    loc = page.locator(selector).first
    # Centre it: at the top edge the sticky masthead covers it and swallows the click.
    loc.evaluate("e => { const r = e.getBoundingClientRect(); if (r.top < 120 || r.bottom > innerHeight - 40) e.scrollIntoView({block: 'center', behavior: 'smooth'}); }")
    time.sleep(0.7)
    box = loc.bounding_box()
    if not box:
        raise RuntimeError(f"not visible: {selector}")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=25)
    time.sleep(pause)
    if click:
        page.mouse.down()
        page.mouse.up()
        time.sleep(pause)


def scroll_to(page: Page, selector: str, offset: int = 80, wait: float = 1.2) -> None:
    page.evaluate(
        "([s, o]) => { const el = document.querySelector(s); window.scrollTo({top: el.getBoundingClientRect().top + scrollY - o, behavior: 'smooth'}); }",
        [selector, offset],
    )
    time.sleep(wait)


def scroll_drawer(page: Page, to: str | int, wait: float = 1.4) -> None:
    if isinstance(to, int):
        page.evaluate("y => document.getElementById('drawer').scrollTo({top: y, behavior: 'smooth'})", to)
    else:
        page.evaluate(
            """t => { const d = document.getElementById('drawer');
                const h = [...d.querySelectorAll('.dos-sec h4')].find(x => x.textContent.includes(t));
                if (h) d.scrollTo({top: h.closest('.dos-sec').offsetTop - 24, behavior: 'smooth'}); }""",
            to,
        )
    time.sleep(wait)


def new_context(browser, video: bool, name: str = "", **kw):
    opts = {"viewport": VIEW, "device_scale_factor": 2, "color_scheme": "light"}
    opts.update(kw)
    if video:
        opts["record_video_dir"] = str(VIDEOS / "_raw")
        opts["record_video_size"] = opts["viewport"]
    ctx = browser.new_context(**opts)
    ctx.add_init_script(CURSOR_JS)
    ctx._demo_name = name
    return ctx


def close_context(ctx, page: Page | None) -> None:
    video = page.video if page is not None else None
    ctx.close()
    if video and ctx._demo_name:
        dest = VIDEOS / f"{ctx._demo_name}.webm"
        shutil.move(video.path(), dest)
        print("  video", dest.name, flush=True)


def open_dashboard(page: Page) -> None:
    page.goto(BASE + "/", wait_until="load")  # never networkidle: the SSE stream stays open
    page.wait_for_selector(".station")
    page.evaluate("() => { try { localStorage.setItem('ls-theme', 'light'); } catch {} document.documentElement.dataset.theme = 'light'; }")
    page.evaluate("() => document.fonts.ready")
    time.sleep(1.5)


def best_saved_run() -> str:
    runs = api("/api/history")
    if not runs:
        raise SystemExit("no saved runs in output/ - run the pipeline first")
    return max(runs, key=lambda r: (r["qualified"], r["total"], r["id"]))["id"]


def top_qualified_id(page: Page) -> str:
    glide(page, '#tabs button[data-filter="qualified"]')
    return page.locator("#ledger .row").first.get_attribute("data-id")


# ---------------------------------------------------------------- tour

def tour(browser) -> None:
    run_id = best_saved_run()
    print(f"tour of saved run {run_id}", flush=True)

    ctx = new_context(browser, video=True, name="01-dashboard-tour")
    page = ctx.new_page()
    open_dashboard(page)
    shot(page, "01-landing-empty")

    glide(page, "#historySelect", click=False)
    page.select_option("#historySelect", run_id)
    page.wait_for_selector("#ledger .row")
    time.sleep(2.5)
    shot(page, "02-hero-and-controls")
    shot(page, "03-full-page", full_page=True)

    scroll_to(page, ".stats", offset=40)
    shot(page, "04-stats-and-pipeline")
    shot(page, "05-pipeline-track", selector=".track-wrap")
    glide(page, ".station.final .lchip", click=False, pause=1.0)

    scroll_to(page, ".lower", offset=40)
    shot(page, "06-leads-table", selector=".ledger")
    shot(page, "07-sources-and-activity", selector=".side")
    glide(page, '#tabs button[data-filter="dropped"]')
    shot(page, "08-leads-dropped-tab", selector=".ledger")
    lead_id = top_qualified_id(page)
    shot(page, "09-leads-qualified-tab", selector=".ledger")

    glide(page, f'#ledger .row[data-id="{lead_id}"]')
    page.wait_for_selector("#drawer.open")
    time.sleep(2)
    shot(page, "10-dossier-top")
    for i, section in enumerate(["Documentation audit", "Recommended improvements", "Contacts", "Outreach opener", "How the docs were found", "Step timings"]):
        scroll_drawer(page, section)
        shot(page, f"{11 + i:02d}-dossier-{section.lower().replace(' ', '-')}")
    scroll_drawer(page, 0)
    glide(page, "#drawerClose")

    # A dropped lead's dossier explains where and why it stopped.
    glide(page, '#tabs button[data-filter="dropped"]')
    if page.locator("#ledger .row").count():
        glide(page, "#ledger .row")
        page.wait_for_selector("#drawer.open")
        time.sleep(1.5)
        shot(page, "17-dossier-dropped-lead")
        glide(page, "#drawerClose")
    glide(page, '#tabs button[data-filter="all"]')

    # Dark mode for projectors.
    page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
    time.sleep(1)
    glide(page, "#themeBtn")
    time.sleep(1)
    shot(page, "18-dark-hero")
    scroll_to(page, ".stats", offset=40)
    shot(page, "19-dark-pipeline")
    scroll_to(page, ".lower", offset=40)
    glide(page, f'#ledger .row[data-id="{lead_id}"]')
    page.wait_for_selector("#drawer.open")
    time.sleep(1.5)
    shot(page, "20-dark-dossier")
    scroll_drawer(page, "Outreach opener")
    shot(page, "21-dark-outreach")
    glide(page, "#drawerClose")
    page.evaluate("() => { document.documentElement.dataset.theme = 'light'; localStorage.setItem('ls-theme', 'light'); }")
    time.sleep(1)
    close_context(ctx, page)

    # Whole dossier in one tall image (the drawer is 100vh, so make the viewport tall).
    ctx = new_context(browser, video=False)
    page = ctx.new_page()
    open_dashboard(page)
    page.select_option("#historySelect", run_id)
    page.wait_for_selector("#ledger .row")
    page.evaluate(f"() => document.querySelector('#ledger .row[data-id=\"{lead_id}\"]').click()")
    page.wait_for_selector("#drawer.open")
    time.sleep(1.5)
    h = page.evaluate("() => document.getElementById('drawer').scrollHeight")
    page.set_viewport_size({"width": 1440, "height": min(h + 40, 6000)})
    time.sleep(1.5)
    shot(page, "22-dossier-full", selector="#drawer")
    ctx.close()

    # Phone width.
    ctx = new_context(browser, video=True, name="02-mobile", viewport={"width": 390, "height": 844},
                      device_scale_factor=3, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    open_dashboard(page)
    page.select_option("#historySelect", run_id)
    page.wait_for_selector("#ledger .row")
    time.sleep(2)
    shot(page, "23-mobile-hero")
    scroll_to(page, ".stats", offset=10)
    shot(page, "24-mobile-pipeline")
    scroll_to(page, ".lower", offset=10)
    shot(page, "25-mobile-leads")
    page.locator("#ledger .row").first.tap()
    page.wait_for_selector("#drawer.open")
    time.sleep(1.5)
    shot(page, "26-mobile-dossier")
    scroll_drawer(page, "Outreach opener")
    shot(page, "27-mobile-outreach")
    close_context(ctx, page)


# ---------------------------------------------------------------- live

def wait_for_finish(page: Page, prefix: str, timeout: float, every: float, views: list[str]) -> None:
    """Poll until the run finishes, rotating the view and grabbing frames."""
    t0 = time.time()
    n = 0
    while time.time() - t0 < timeout:
        if page.get_attribute("#liveBadge", "data-state") == "finished":
            return
        view = views[n % len(views)]
        scroll_to(page, view, offset=40, wait=1.5)
        shot(page, f"{prefix}-{n + 1:02d}")
        n += 1
        time.sleep(every)
    print(f"  WARNING: run still going after {timeout:.0f}s; stopping the capture", flush=True)


def live_audit(browser, url: str) -> None:
    if api("/api/meta")["running"]:
        raise SystemExit("a run is already in progress")
    print(f"live audit of {url}", flush=True)
    ctx = new_context(browser, video=True, name="03-live-single-site-audit")
    page = ctx.new_page()
    open_dashboard(page)
    glide(page, "#auditUrl")
    page.keyboard.type(url, delay=60)
    time.sleep(0.6)
    shot(page, "30-audit-typed")
    glide(page, "#auditBtn")
    page.wait_for_selector("#liveBadge[data-state=running]")
    wait_for_finish(page, "31-audit-live", timeout=480, every=6, views=[".stats", ".lower"])
    time.sleep(2)
    scroll_to(page, ".stats", offset=40)
    shot(page, "32-audit-finished")
    glide(page, ".station .lchip")
    page.wait_for_selector("#drawer.open")
    time.sleep(2)
    shot(page, "33-audit-dossier")
    for section in ["Documentation audit", "Recommended improvements", "Outreach opener"]:
        scroll_drawer(page, section, wait=2.2)
    shot(page, "34-audit-outreach")
    glide(page, "#drawerClose")
    close_context(ctx, page)


def live_run(browser) -> None:
    if api("/api/meta")["running"]:
        raise SystemExit("a run is already in progress")
    print("live batch run", flush=True)
    ctx = new_context(browser, video=True, name="04-live-pipeline-run")
    page = ctx.new_page()
    open_dashboard(page)
    # 3 leads per source, 3 in parallel; keep the default source selection.
    while page.locator(".stepper[data-name=limit]").get_attribute("data-value") != "3":
        glide(page, '.stepper[data-name=limit] button[data-delta="-1"]', pause=0.4)
    shot(page, "40-run-configured", selector="#runForm")
    glide(page, "#runBtn")
    page.wait_for_selector("#liveBadge[data-state=running]")
    wait_for_finish(page, "41-run-live", timeout=1200, every=10, views=[".stats", ".stats", ".lower"])
    time.sleep(3)
    scroll_to(page, ".stats", offset=40)
    shot(page, "42-run-finished-pipeline")
    scroll_to(page, ".lower", offset=40)
    shot(page, "43-run-finished-leads")
    if page.locator("#ledger .row").count():
        lead_id = top_qualified_id(page)
        glide(page, f'#ledger .row[data-id="{lead_id}"]')
        page.wait_for_selector("#drawer.open")
        time.sleep(2)
        shot(page, "44-run-top-lead-dossier")
        glide(page, "#drawerClose")
    close_context(ctx, page)


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    url = sys.argv[2] if len(sys.argv) > 2 else "https://www.svix.com"
    SHOTS.mkdir(parents=True, exist_ok=True)
    VIDEOS.mkdir(parents=True, exist_ok=True)
    try:
        api("/api/meta")
    except OSError as exc:
        raise SystemExit(f"dashboard not reachable at {BASE} ({exc}); start it with: python -m leadscraper serve")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        if what in ("tour", "all"):
            tour(browser)
        if what in ("audit", "all"):
            live_audit(browser, url)
        if what in ("run", "all"):
            live_run(browser)
        browser.close()
    shutil.rmtree(VIDEOS / "_raw", ignore_errors=True)


if __name__ == "__main__":
    main()
