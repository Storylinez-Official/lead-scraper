"""Build the showcase PDF, PPTX and MP4s from the captures in this folder.

    python showcase/capture.py all      # first: screenshots + videos
    python showcase/build.py

One slide list drives both outputs, so the PDF and the deck say the same thing.
The PDF is 16:9, so it can be presented directly; the PPTX embeds the videos.
"""

import html
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).parent
ROOT = HERE.parent
SHOTS = HERE / "screenshots"
VIDEOS = HERE / "videos"
OUTPUT = ROOT / "output"
PDF_OUT = HERE / "LeadScraper-Showcase.pdf"
PPTX_OUT = HERE / "LeadScraper-Showcase.pptx"
HTML_OUT = HERE / "showcase.html"

PAPER, INK, INK2, ACCENT, LINE, CARD = "F2EEE3", "15120E", "5A534A", "E5461A", "D8D1C2", "FAF7EF"

STEPS = [
    ("2.1", "Qualify", "Header scan for doc words + AI: is this a business that needs docs?", "Regex + AI"),
    ("2.2", "Find docs", "Candidate pages scored by regex signals: code blocks, endpoints, curl, doc platforms.", "Regex only"),
    ("3", "Crawl contacts", "Same-site crawl, emails and phones from mailto/tel, text, JSON-LD.", "Regex only"),
    ("4", "Purify", "AI dedupes and drops invalid contacts; a guard blocks anything not crawled.", "AI + guard"),
    ("5", "Audit docs", "AI scores quality, completeness, usability 0-10 with justifications.", "AI, structured"),
    ("6", "Report", "Summary, prioritised improvements, outreach opener. Lead score by fixed rubric.", "AI + rubric"),
]


# ---------------------------------------------------------------- data

def load_runs() -> list[dict]:
    runs = []
    for d in sorted(OUTPUT.glob("run-*")):
        f = d / "leads.jsonl"
        if not f.exists():
            continue
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        if rows:
            runs.append({"id": d.name, "rows": rows, "qualified": sum(r["status"] == "qualified" for r in rows)})
    return runs


def featured_run(runs: list[dict]) -> dict:
    """The newest multi-lead run (normally the one capture.py just recorded)."""
    batch = [r for r in runs if len(r["rows"]) > 1]
    return (batch or runs)[-1]


def frames(prefix: str, n: int, pipeline_only: bool = False) -> list[Path]:
    found = sorted(SHOTS.glob(f"{prefix}-*.png"))
    if pipeline_only:
        # capture.py rotates views [stats, stats, lower]: every third frame shows the table.
        found = [p for p in found if int(p.stem.rsplit("-", 1)[1]) % 3 != 0]
    if len(found) <= n:
        return found
    step = (len(found) - 1) / (n - 1)
    return [found[round(i * step)] for i in range(n)]


def shot(name: str) -> Path | None:
    p = SHOTS / f"{name}.png"
    return p if p.exists() else None


def small(p: Path) -> Path:
    """JPEG copy capped at 1800px wide, so the PDF and deck stay shareable."""
    out = SHOTS / "_web" / (p.stem + ".jpg")
    out.parent.mkdir(exist_ok=True)
    if not out.exists() or out.stat().st_mtime < p.stat().st_mtime:
        im = Image.open(p).convert("RGB")
        if im.width > 1800:
            im = im.resize((1800, round(im.height * 1800 / im.width)), Image.LANCZOS)
        im.save(out, quality=86, optimize=True)
    return out


def panel(name: str) -> Path | None:
    """Crop a desktop dossier screenshot to the drawer (760px of a 1440px viewport, right edge)."""
    src = shot(name)
    if not src:
        return None
    out = SHOTS / "panels" / src.name
    out.parent.mkdir(exist_ok=True)
    im = Image.open(src)
    w, h = im.size
    im.crop((round(w * (1 - 760 / 1440)), 0, w, h)).save(out)
    return out


# ---------------------------------------------------------------- videos

def ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def convert_videos() -> list[Path]:
    exe = ffmpeg()
    if not exe:
        print("ffmpeg not found; keeping .webm only")
        return []
    made = []
    even = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    for webm in sorted(VIDEOS.glob("*.webm")):
        jobs = [(webm.with_suffix(".mp4"), even)]
        if "live-pipeline-run" in webm.stem:
            jobs.append((webm.with_name(webm.stem + "-4x-speed.mp4"), f"setpts=PTS/4,{even}"))
        for out, vf in jobs:
            subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(webm), "-vf", vf, "-an",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(out)],
                           check=True)
            print("  mp4", out.name)
            made.append(out)
    return made


def video_seconds(path: Path) -> float | None:
    exe = ffmpeg()
    if not exe or not path.exists():
        return None
    r = subprocess.run([exe, "-i", str(path)], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return None


def fmt_dur(sec: float | None) -> str:
    if sec is None:
        return ""
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


# ---------------------------------------------------------------- slides

def build_slides(runs: list[dict]) -> list[dict]:
    feat = featured_run(runs)
    rows = feat["rows"]
    q = [r for r in rows if r["status"] == "qualified"]
    total_leads = sum(len(r["rows"]) for r in runs)
    total_q = sum(r["qualified"] for r in runs)
    stops: dict[str, int] = {}
    for r in rows:
        if r["status"] != "qualified":
            stops[r["stage"]] = stops.get(r["stage"], 0) + 1
    labels = {"assess_business": "2.1 Qualify", "find_documentation": "2.2 Find docs", "collect_contacts": "3 Crawl contacts",
              "purify_contacts": "4 Purify", "analyze_documentation": "5 Audit docs", "generate_report": "6 Report"}
    stop_text = ", ".join(f"{n} at {labels.get(k, k)}" for k, n in sorted(stops.items(), key=lambda x: -x[1]))
    scores = [r["lead_score"] for r in q if r["lead_score"] is not None]
    docs = [int(r["doc_overall"]) for r in q if str(r["doc_overall"]).strip() != ""]

    vids = {p.stem: p for p in VIDEOS.glob("*.mp4")}
    slides: list[dict] = []
    add = slides.append

    add({"layout": "cover", "kicker": "Product showcase", "title": "LeadScraper",
         "lede": "Finds products that have documentation, audits how good that documentation is, finds who to talk to, "
                 "and drafts the cold-email opener. Every decision is shown live.",
         "images": [shot("02-hero-and-controls")],
         "facts": [(str(total_leads), "leads processed in recorded runs"), (str(total_q), "qualified with a full report"),
                   ("6", "pipeline steps, LangGraph")]})

    add({"layout": "split", "kicker": "The brief", "title": "From a directory listing to a ready-to-send opener",
         "bullets": [
             "Start from listing sites: GitHub topics (api, developer-tools) and Product Hunt developer tools. Sources live in config, not code.",
             "Keep only products whose business needs documentation, and that actually have it.",
             "Crawl the site for emails and phone numbers; AI cleans the list.",
             "AI audits the docs for quality, completeness and usability.",
             "Write a report: summary, prioritised improvements, outreach opener.",
             "Deterministic flow: every lead either continues or stops with a recorded reason.",
         ],
         "images": [shot("05-pipeline-track")]})

    add({"layout": "pipeline", "kicker": "How it works", "title": "Six steps, each one decides whether a lead continues",
         "note": "LangGraph state machine. After each node a conditional edge continues only while status is running; "
                 "otherwise the lead ends as skipped or error with the step and reason saved. "
                 "All LLM calls use temperature 0 and strict JSON-schema output (gpt-4.1-mini)."})

    add({"layout": "full", "kicker": "The dashboard", "title": "A live control room for running and presenting the pipeline",
         "images": [shot("04-stats-and-pipeline")],
         "caption": "Run totals on top, then the pipeline track: every lead is a chip that moves through the steps. "
                    "Dropped leads stay struck through at the step that rejected them; qualified leads land in the dark tray."})

    live = frames("41-run-live", 4, pipeline_only=True)
    if live:
        add({"layout": "grid", "kicker": "Live run", "title": "Watching a real run as it happens",
             "images": live, "keep": 0.62,  # stats + pipeline track only
             "captions": [f"Frame {i + 1} of {len(live)}" for i in range(len(live))],
             "caption": "Frames captured during a live batch run (3 leads per source, 3 in parallel). Leads go into analysis "
                        "as soon as they are collected, so results arrive within the first minute."})

    add({"layout": "split", "kicker": "Leads", "title": "Every lead, with its progress and where it stopped",
         "bullets": [
             "Six-segment meter per lead: done, running, or the step that stopped it.",
             "Doc score (0-10, AI) and lead score (0-100, rubric) side by side.",
             "Tabs: All, Qualified, In flight, Dropped.",
             "Dropped leads keep their reason, e.g. \"no documentation found (best score 5 < 6)\".",
             "Click any row or chip to open the lead's dossier.",
         ],
         "images": [shot("06-leads-table")]})

    add({"layout": "split", "kicker": "Lead dossier", "title": "Why this lead, in one panel",
         "bullets": [
             "Executive summary and the lead score with its breakdown, so anyone can check the number.",
             "Qualification: business type, worth pursuing, AI confidence and reasoning, the doc links found in the header.",
             "Documentation audit: overall score, three dimensions with justifications, strengths, weaknesses, missing sections.",
         ],
         "images": [panel("10-dossier-top"), panel("11-dossier-documentation-audit")], "row": True})

    add({"layout": "split", "kicker": "Lead dossier", "title": "What to fix, who to tell, and what to say",
         "bullets": [
             "Improvements ranked high / medium / low, each with the issue and the fix.",
             "Contacts the AI kept, with copy buttons. A guard blocks any contact the model returns that was not crawled.",
             "Outreach opener laid out as a letter: To, Subject, body. One click copies the email.",
         ],
         "images": [panel("12-dossier-recommended-improvements"), panel("14-dossier-outreach-opener")], "row": True})

    add({"layout": "split", "kicker": "Evidence", "title": "Every decision is traceable",
         "bullets": [
             "How the docs were found: the regex signals that fired and every candidate URL with its score.",
             "Step timings show where the time goes (usually the crawl and the AI audit).",
             "Dropped leads show the step and the reason, not just a missing row.",
         ],
         "images": [panel("15-dossier-how-the-docs-were-found"), panel("17-dossier-dropped-lead")], "row": True})

    if shot("33-audit-dossier"):
        add({"layout": "split", "kicker": "Single-site audit", "title": "Audit any website in about a minute",
             "bullets": [
                 "Paste a URL and press Audit. The same six steps run on just that site.",
                 "The quickest live demo: the chip walks the track and the dossier fills in step by step.",
                 "Recorded in videos/03-live-single-site-audit.mp4.",
             ],
             "images": [panel("33-audit-dossier"), panel("34-audit-outreach")], "row": True})

    add({"layout": "table", "kicker": "Results", "title": f"Run {feat['id'].removeprefix('run-')}: "
                                                           f"{len(q)} of {len(rows)} leads qualified",
         "rows": rows,
         "caption": (f"Dropped: {stop_text}. " if stop_text else "")
                    + (f"Qualified lead scores {min(scores)}-{max(scores)}" if scores else "")
                    + (f", doc scores {min(docs)}-{max(docs)} out of 10." if docs else "")})

    add({"layout": "rubric", "kicker": "Lead score", "title": "Lead score is calculated in code, not by the AI",
         "note": "In early runs the model gave every lead 70-75; with rules it applied them inconsistently and its "
                 "arithmetic did not match its own explanation. The score now comes from fixed rules and the dossier "
                 "shows the breakdown."})

    add({"layout": "strip", "kicker": "Presenting", "title": "Dark mode for projectors, works down to phone width",
         "images": [shot("19-dark-pipeline"), panel("21-dark-outreach"), shot("24-mobile-pipeline"), shot("26-mobile-dossier")],
         "captions": ["Dark mode: pipeline", "Dark mode: outreach letter", "Phone: pipeline", "Phone: dossier"]})

    for stem, title, poster, note in [
        ("01-dashboard-tour", "Video: dashboard tour", "04-stats-and-pipeline",
         "A saved run: pipeline, leads tabs, a qualified lead's full dossier, a dropped lead, dark mode."),
        ("03-live-single-site-audit", "Video: live single-site audit", "33-audit-dossier",
         "Typing a URL, pressing Audit, and watching it go through all six steps in real time."),
        ("04-live-pipeline-run-4x-speed", "Video: live batch run (4x speed)", "42-run-finished-pipeline",
         "A full run across the three sources. Leads are collected, flow through the steps and land in the tray. "
         "Real-time version: 04-live-pipeline-run.mp4."),
        ("02-mobile", "Video: phone width", "26-mobile-dossier", "The same dashboard at 390px wide."),
    ]:
        if stem in vids and shot(poster):
            add({"layout": "video", "kicker": "Recording", "title": title, "video": vids[stem],
                 "images": [shot(poster)], "caption": f"{note} File: videos/{stem}.mp4 ({fmt_dur(video_seconds(vids[stem]))})."})

    add({"layout": "split", "kicker": "Output", "title": "Every run leaves files a sales team can use",
         "bullets": [
             "leads.csv: one row per lead, status, where it stopped and why, docs URL, contacts, scores, outreach subject.",
             "leads.jsonl: same rows, appended as each lead finishes, so a crash loses nothing.",
             "leads/<domain>.json: full pipeline state with the evidence behind every decision.",
             "reports/<domain>.md: readable report for each qualified lead.",
             "summary.json: counts by status and by the step where leads stopped.",
             "CLI: python -m leadscraper run | lead <url> | collect | graph | serve",
         ],
         "images": [shot("22-dossier-full")], "fit": "top"})

    add({"layout": "split", "kicker": "Status", "title": "What is done and what is next",
         "bullets": [
             "Done: three sources, six-step LangGraph pipeline, live dashboard, run history, CSV/JSON/Markdown output.",
             "Product Hunt sits behind Cloudflare: a visible Chrome window opens on its own to get through. Expected.",
             "Adding a listing site is a config entry for most directories; custom sites get a small adapter class.",
             "Not done: automated tests. Everything shown here was verified by running it.",
             "Next: more sources, named-person contact discovery, sending and tracking outreach.",
         ],
         "images": [shot("18-dark-hero")]})
    return slides


# ---------------------------------------------------------------- PDF (HTML)

CSS = """
@page { size: 1280px 720px; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #%(paper)s; color: #%(ink)s; font-family: 'Hanken Grotesk', system-ui, sans-serif; }
.slide { width: 1280px; height: 720px; padding: 48px 56px 40px; position: relative; overflow: hidden;
  page-break-after: always; display: flex; flex-direction: column; background: #%(paper)s; }
.kicker { font: 600 12px 'JetBrains Mono', monospace; letter-spacing: .14em; text-transform: uppercase; color: #%(accent)s; }
h1 { font: 400 40px/1.08 'Instrument Serif', Georgia, serif; margin: 8px 0 22px; letter-spacing: -.01em; }
h1 em { color: #%(accent)s; }
.foot { position: absolute; left: 56px; right: 56px; bottom: 16px; display: flex; justify-content: space-between;
  font: 500 10px 'JetBrains Mono', monospace; color: #%(ink2)s; letter-spacing: .08em; text-transform: uppercase; }
/* Content sits in a fixed box between the title and the footer, so nothing can run into the footer.
   Every image is sized in Python to fit its box exactly: no object-fit, no clipping, so any PDF
   viewer draws it the same way. */
.content { position: absolute; left: 56px; right: 56px; top: 150px; bottom: 54px; }
.bullets { position: absolute; left: 0; top: 0; width: 400px; list-style: none; display: flex; flex-direction: column; gap: 13px; }
.bullets li { font-size: 16px; line-height: 1.45; color: #%(ink)s; padding-left: 18px; position: relative; }
.bullets li::before { content: ''; position: absolute; left: 0; top: 9px; width: 7px; height: 7px; background: #%(accent)s; border-radius: 2px; }
.area { position: absolute; display: flex; justify-content: center; align-items: flex-start; gap: 20px; }
.shot { display: block; border: 1px solid #%(line)s; border-radius: 8px; }
.caption { position: absolute; left: 0; right: 0; bottom: 0; font-size: 14px; line-height: 1.5; color: #%(ink2)s; }
.grid { position: absolute; left: 0; right: 0; top: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 16px 24px; }
.cell { display: flex; flex-direction: column; align-items: center; }
.cell small { font: 500 11px 'JetBrains Mono', monospace; color: #%(ink2)s; margin-top: 6px; }
.cover { padding: 0; flex-direction: row; }
.cover .left { flex: 0 0 46%%; padding: 64px 48px 48px 64px; display: flex; flex-direction: column; }
.cover h1 { font-size: 88px; margin: 18px 0 18px; }
.cover .lede { font-size: 19px; line-height: 1.5; color: #%(ink2)s; max-width: 470px; }
.cover .facts { margin-top: auto; display: flex; gap: 34px; }
.cover .facts b { display: block; font: 400 52px/1 'Instrument Serif', serif; color: #%(accent)s; }
.cover .facts span { font-size: 12px; color: #%(ink2)s; display: block; max-width: 130px; margin-top: 4px; }
.cover .right { flex: 1; background: #%(ink)s; display: flex; align-items: center; justify-content: center; }
.cover .right .shot { border-color: #3a342c; }
.steps { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; }
.step { background: #%(card)s; border: 1px solid #%(line)s; border-radius: 12px; padding: 16px 14px; min-height: 250px; display: flex; flex-direction: column; }
.step .n { font: 600 12px 'JetBrains Mono', monospace; color: #%(accent)s; letter-spacing: .1em; }
.step h3 { font: 400 26px/1.1 'Instrument Serif', serif; margin: 6px 0 10px; }
.step p { font-size: 13.5px; line-height: 1.45; color: #%(ink2)s; }
.step .t { margin-top: auto; font: 600 10.5px 'JetBrains Mono', monospace; text-transform: uppercase; letter-spacing: .08em;
  background: #%(ink)s; color: #%(paper)s; padding: 5px 8px; border-radius: 5px; align-self: flex-start; }
.gate { font: 500 12px 'JetBrains Mono', monospace; color: #%(ink2)s; margin: 14px 0 0; letter-spacing: .04em; }
.note { font-size: 15px; line-height: 1.55; color: #%(ink2)s; margin-top: 18px; max-width: 1080px; }
table { width: 100%%; border-collapse: collapse; font-size: 12.5px; }
th { text-align: left; font: 600 10.5px 'JetBrains Mono', monospace; letter-spacing: .1em; text-transform: uppercase; color: #%(ink2)s;
  border-bottom: 1.5px solid #%(ink)s; padding: 6px 8px; }
td { padding: 6.5px 8px; border-bottom: 1px solid #%(line)s; vertical-align: top; }
td.num { text-align: right; font-family: 'JetBrains Mono', monospace; }
.pill { font: 600 10px 'JetBrains Mono', monospace; padding: 2px 7px; border-radius: 99px; text-transform: uppercase; letter-spacing: .06em; }
.pill.qualified { background: #d6e6da; color: #1f5a37; } .pill.skipped { background: #efe0c4; color: #7a5212; } .pill.error { background: #f3d2c8; color: #8a2a12; }
.why { color: #%(ink2)s; }
.rubric { display: grid; grid-template-columns: 1fr 1fr; gap: 18px 28px; }
.rule { background: #%(card)s; border: 1px solid #%(line)s; border-radius: 12px; padding: 18px 20px; }
.rule h4 { font: 400 24px 'Instrument Serif', serif; margin-bottom: 8px; }
.rule p { font: 500 13px/1.7 'JetBrains Mono', monospace; color: #%(ink2)s; }
.vwrap { position: relative; }
.play { position: absolute; left: 50%%; top: 50%%; width: 86px; height: 86px; margin: -43px 0 0 -43px; border-radius: 50%%;
  background: #%(accent)s; }
.play::after { content: ''; position: absolute; left: 34px; top: 25px; border-left: 28px solid #fff; border-top: 18px solid transparent; border-bottom: 18px solid transparent; }
""" % {"paper": PAPER, "ink": INK, "ink2": INK2, "accent": ACCENT, "line": LINE, "card": CARD}

RUBRIC = [
    ("Documentation gap", "docs <= 3: +25 | 4-5: +20 | 6: +10\n7: 0 | 8: -15 | 9-10: -30"),
    ("Who we can reach", "named person: +10\nteam inbox or phone: +5\nonly security/legal inboxes: -15"),
    ("Developer product", "API, SDK, platform, CLI, library,\nframework, open source: +10"),
    ("Docs size", "<= 2 pages sampled and <= 3 nav links:\n-10 (very small docs site)"),
]


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


# Content box is 1168 x 516 px (see .content).
CW, CH = 1168, 516


def img_tag(p: Path | None, bw: float, bh: float, top: bool = False, keep: float = 1.0) -> str:
    """An <img> scaled to fit bw x bh exactly. top=True crops a tall image from the top to the box's shape;
    keep < 1 keeps only that top fraction of the image."""
    if not p:
        return ""
    src = small(p)
    im = Image.open(src)
    iw, ih = im.size
    if keep < 1:
        src = src.with_name(f"{src.stem}-keep{round(keep * 100)}.jpg")
        im.crop((0, 0, iw, round(ih * keep))).save(src, quality=86)
        iw, ih = Image.open(src).size
    if top and iw / ih < bw / bh:
        src = src.with_name(src.stem + "-top.jpg")
        im.crop((0, 0, iw, round(iw * bh / bw))).save(src, quality=86)
        iw, ih = Image.open(src).size
    k = min(bw / iw, bh / ih)
    w, h = round(iw * k), round(ih * k)
    return f'<img class="shot" src="{src.relative_to(HERE).as_posix()}" style="width:{w}px;height:{h}px">'


def table_rows(rows: list[dict], limit: int = 13) -> list[dict]:
    order = {"qualified": 0, "skipped": 1, "error": 2}
    return sorted(rows, key=lambda r: (order.get(r["status"], 3), -(r["lead_score"] or 0)))[:limit]


def host(url: str) -> str:
    return url.split("//")[-1].split("/")[0].removeprefix("www.")


def slide_html(s: dict, i: int, n: int) -> str:
    lay = s["layout"]
    foot = f'<div class="foot"><span>LeadScraper / showcase</span><span>{i:02d} / {n:02d}</span></div>'
    head = f'<div class="kicker">{esc(s["kicker"])}</div><h1>{esc(s["title"])}</h1>'
    if lay == "cover":
        facts = "".join(f"<div><b>{esc(a)}</b><span>{esc(b)}</span></div>" for a, b in s["facts"])
        img = img_tag(s["images"][0], 611, 560)
        return (f'<section class="slide cover"><div class="left"><div class="kicker">{esc(s["kicker"])}</div>'
                f'<h1>Lead<em>Scraper</em></h1><p class="lede">{esc(s["lede"])}</p><div class="facts">{facts}</div></div>'
                f'<div class="right">{img}</div></section>')
    if lay == "split":
        bl = "".join(f"<li>{esc(b)}</li>" for b in s["bullets"])
        imgs = [p for p in s["images"] if p]
        aw, gap, n_img = CW - 440, 20, max(len(imgs), 1)
        if s.get("row"):
            tags = "".join(img_tag(p, (aw - gap * (n_img - 1)) / n_img, CH, s.get("fit") == "top") for p in imgs)
            style = f"left:440px;top:0;width:{aw}px;height:{CH}px"
        else:
            tags = "".join(img_tag(p, aw, (CH - gap * (n_img - 1)) / n_img, s.get("fit") == "top") for p in imgs)
            style = f"left:440px;top:0;width:{aw}px;height:{CH}px;flex-direction:column;align-items:center"
        return (f'<section class="slide">{head}<div class="content"><ul class="bullets">{bl}</ul>'
                f'<div class="area" style="{style}">{tags}</div></div>{foot}</section>')
    if lay in ("full", "video"):
        inner = img_tag(s["images"][0], CW, CH - 64)
        if lay == "video":
            inner = f'<div class="vwrap">{inner}<div class="play"></div></div>'
        return (f'<section class="slide">{head}<div class="content"><div class="area" style="left:0;top:0;width:{CW}px;height:{CH - 64}px">'
                f'{inner}</div><p class="caption">{esc(s["caption"])}</p></div>{foot}</section>')
    if lay == "grid":
        caps = s.get("captions") or [""] * len(s["images"])
        reserve = 56 if s.get("caption") else 0
        cell_h = (CH - reserve - 16) / 2
        cells = "".join(f'<div class="cell">{img_tag(p, (CW - 24) / 2, cell_h - 22, keep=s.get("keep", 1.0))}<small>{esc(c)}</small></div>'
                        for p, c in zip(s["images"], caps) if p)
        cap = f'<p class="caption">{esc(s["caption"])}</p>' if s.get("caption") else ""
        return f'<section class="slide">{head}<div class="content"><div class="grid">{cells}</div>{cap}</div>{foot}</section>'
    if lay == "strip":
        # One row, every image the same height, scaled so the row fills the width.
        imgs = [p for p in s["images"] if p]
        gap = 20
        ratios = [Image.open(small(p)).size[0] / Image.open(small(p)).size[1] for p in imgs]
        h = min(CH - 40, (CW - gap * (len(imgs) - 1)) / sum(ratios))
        cells = "".join(f'<div class="cell">{img_tag(p, r * h, h)}<small>{esc(c)}</small></div>'
                        for p, r, c in zip(imgs, ratios, s.get("captions") or [""] * len(imgs)))
        return (f'<section class="slide">{head}<div class="content"><div class="area" style="left:0;top:0;width:{CW}px;height:{CH}px;gap:{gap}px;align-items:center">'
                f'{cells}</div></div>{foot}</section>')
    if lay == "pipeline":
        cards = "".join(f'<div class="step"><span class="n">STEP {esc(a)}</span><h3>{esc(b)}</h3><p>{esc(c)}</p><span class="t">{esc(d)}</span></div>'
                        for a, b, c, d in STEPS)
        return (f'<section class="slide">{head}<div class="steps">{cards}</div>'
                f'<p class="gate">Gate after 2.2: no docs, lead stops. Gate after 3: no email or phone, lead stops.</p>'
                f'<p class="note">{esc(s["note"])}</p>{foot}</section>')
    if lay == "table":
        trs = []
        for r in table_rows(s["rows"]):
            why = "" if r["status"] == "qualified" else r.get("skip_reason", "")
            trs.append(f'<tr><td><b>{esc(r["name"])}</b><br><span class="why">{esc(host(r["website"]))}</span></td>'
                       f'<td>{esc(r["source"])}</td><td><span class="pill {esc(r["status"])}">{esc(r["status"])}</span></td>'
                       f'<td class="why">{esc(why or r.get("business_type", ""))}</td>'
                       f'<td class="num">{esc(r["doc_overall"]) or "-"}</td><td class="num">{esc(r["lead_score"]) if r["lead_score"] is not None else "-"}</td></tr>')
        return (f'<section class="slide">{head}<table><thead><tr><th>Product</th><th>Source</th><th>Status</th>'
                f'<th>Business / why dropped</th><th style="text-align:right">Docs</th><th style="text-align:right">Lead</th></tr></thead>'
                f'<tbody>{"".join(trs)}</tbody></table><p class="note">{esc(s["caption"])}</p>{foot}</section>')
    if lay == "rubric":
        rules = "".join(f'<div class="rule"><h4>{esc(a)}</h4><p>{esc(b).replace(chr(10), "<br>")}</p></div>' for a, b in RUBRIC)
        return (f'<section class="slide">{head}<div class="rubric">{rules}</div>'
                f'<p class="gate">Start at 50, add each rule, clamp to 0-100.</p><p class="note">{esc(s["note"])}</p>{foot}</section>')
    raise ValueError(lay)


def build_pdf(slides: list[dict]) -> None:
    body = "".join(slide_html(s, i + 1, len(slides)) for i, s in enumerate(slides))
    HTML_OUT.write_text(
        '<!doctype html><html><head><meta charset="utf-8"><title>LeadScraper Showcase</title>'
        '<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Hanken+Grotesk:wght@400;500;600;700'
        '&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">'
        f"<style>{CSS}</style></head><body>{body}</body></html>", encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(HTML_OUT.as_uri(), wait_until="networkidle")
        page.evaluate("() => document.fonts.ready")
        page.pdf(path=str(PDF_OUT), width="1280px", height="720px", print_background=True)
        b.close()
    print("  pdf", PDF_OUT.name)


# ---------------------------------------------------------------- PPTX

def rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h)


def text(slide, x, y, w, h, s, size, color=INK, bold=False, font="Hanken Grotesk", align=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(s.split("\n") if isinstance(s, str) else s):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = line
        if align:
            para.alignment = align
        f = para.font
        f.size, f.bold, f.name, f.color.rgb = Pt(size), bold, font, rgb(color)
    return tb


def rect(slide, x, y, w, h, fill, line=None):
    from pptx.enum.shapes import MSO_SHAPE
    r = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    r.adjustments[0] = 0.06
    r.fill.solid()
    r.fill.fore_color.rgb = rgb(fill)
    if line:
        r.line.color.rgb = rgb(line)
    else:
        r.line.fill.background()
    r.shadow.inherit = False
    return r


def picture(slide, p: Path | None, x, y, w, h, top=False, keep=1.0):
    """Fit an image into a box: contain, or fill-and-crop from the top. keep < 1 keeps the top fraction."""
    if not p:
        return None
    p = small(p)
    if keep < 1:
        im = Image.open(p)
        cropped = p.with_name(f"{p.stem}-keep{round(keep * 100)}.jpg")
        im.crop((0, 0, im.width, round(im.height * keep))).save(cropped, quality=86)
        p = cropped
    iw, ih = Image.open(p).size
    box, img = w / h, iw / ih
    if top and img < box:
        pic = slide.shapes.add_picture(str(p), Inches(x), Inches(y), Inches(w), Inches(h))
        pic.crop_bottom = 1 - (iw / box) / ih
        return pic
    if img > box:
        dw, dh = w, w / img
    else:
        dw, dh = h * img, h
    pic = slide.shapes.add_picture(str(p), Inches(x + (w - dw) / 2), Inches(y + (h - dh) / 2), Inches(dw), Inches(dh))
    pic.line.color.rgb = rgb(LINE)
    return pic


def build_pptx(slides: list[dict]) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    n = len(slides)
    for i, s in enumerate(slides, 1):
        sl = prs.slides.add_slide(blank)
        sl.background.fill.solid()
        sl.background.fill.fore_color.rgb = rgb(PAPER)
        lay = s["layout"]
        if lay == "cover":
            rect(sl, 6.1, -0.2, 7.5, 8, INK)
            picture(sl, s["images"][0], 6.5, 1.0, 6.6, 5.5)
            text(sl, 0.7, 0.8, 5.2, 0.4, s["kicker"].upper(), 11, ACCENT, True, "JetBrains Mono")
            text(sl, 0.7, 1.2, 5.2, 1.3, "LeadScraper", 66, INK, font="Instrument Serif")
            text(sl, 0.7, 2.7, 5.0, 2.0, s["lede"], 16, INK2)
            for k, (a, b) in enumerate(s["facts"]):
                text(sl, 0.7 + k * 1.75, 5.4, 1.7, 0.8, a, 40, ACCENT, font="Instrument Serif")
                text(sl, 0.7 + k * 1.75, 6.25, 1.6, 0.8, b, 10, INK2)
            continue
        text(sl, 0.6, 0.45, 12, 0.3, s["kicker"].upper(), 11, ACCENT, True, "JetBrains Mono")
        text(sl, 0.6, 0.72, 12.1, 0.8, s["title"], 32, INK, font="Instrument Serif")
        text(sl, 0.6, 7.05, 6, 0.3, "LEADSCRAPER / SHOWCASE", 8, INK2, font="JetBrains Mono")
        text(sl, 10.7, 7.05, 2.0, 0.3, f"{i:02d} / {n:02d}", 8, INK2, font="JetBrains Mono", align=PP_ALIGN.RIGHT)
        top, bottom = 1.65, 6.9
        if lay == "split":
            tb = text(sl, 0.6, top, 4.3, bottom - top, ["•  " + b for b in s["bullets"]], 14, INK)
            for para in tb.text_frame.paragraphs:
                para.space_after = Pt(9)
            imgs = [p for p in s["images"] if p]
            gap, k_n = 0.15, max(len(imgs), 1)
            if s.get("row"):
                ww = (7.5 - gap * (k_n - 1)) / k_n
                for k, p in enumerate(imgs):
                    picture(sl, p, 5.2 + k * (ww + gap), top, ww, bottom - top, s.get("fit") == "top")
            else:
                hh = (bottom - top - gap * (k_n - 1)) / k_n
                for k, p in enumerate(imgs):
                    picture(sl, p, 5.2, top + k * (hh + gap), 7.5, hh, s.get("fit") == "top")
        elif lay in ("full", "video"):
            if lay == "video" and s.get("video"):
                poster = s["images"][0]
                iw, ih = Image.open(poster).size
                h = 4.6
                w = min(h * iw / ih, 12.1)
                h = w * ih / iw
                sl.shapes.add_movie(str(s["video"]), Inches(0.6 + (12.1 - w) / 2), Inches(top), Inches(w), Inches(h),
                                    poster_frame_image=str(poster), mime_type="video/mp4")
            else:
                picture(sl, s["images"][0], 0.6, top, 12.1, 4.6)
            text(sl, 0.6, 6.35, 12.1, 0.7, s["caption"], 13, INK2)
        elif lay == "grid":
            imgs = [p for p in s["images"] if p]
            caps = s.get("captions") or [""] * len(imgs)
            has_cap = bool(s.get("caption"))
            gh = (bottom - top - (0.6 if has_cap else 0)) / 2
            for k, (p, c) in enumerate(zip(imgs, caps)):
                x = 0.6 + (k % 2) * 6.15
                y = top + (k // 2) * gh
                picture(sl, p, x, y, 5.95, gh - 0.35, keep=s.get("keep", 1.0))
                text(sl, x, y + gh - 0.33, 5.9, 0.3, c, 9, INK2, font="JetBrains Mono")
            if has_cap:
                text(sl, 0.6, bottom - 0.55, 12.1, 0.6, s["caption"], 12, INK2)
        elif lay == "strip":
            imgs = [p for p in s["images"] if p]
            gap = 0.2
            ratios = [Image.open(small(p)).size[0] / Image.open(small(p)).size[1] for p in imgs]
            h = min(bottom - top - 0.4, (12.1 - gap * (len(imgs) - 1)) / sum(ratios))
            x = 0.6 + (12.1 - (sum(ratios) * h + gap * (len(imgs) - 1))) / 2
            for p, r, c in zip(imgs, ratios, s.get("captions") or [""] * len(imgs)):
                picture(sl, p, x, top, r * h, h)
                text(sl, x, top + h + 0.05, max(r * h, 1.5), 0.3, c, 9, INK2, font="JetBrains Mono")
                x += r * h + gap
        elif lay == "pipeline":
            w = (12.1 - 5 * 0.15) / 6
            for k, (a, b, c, d) in enumerate(STEPS):
                x = 0.6 + k * (w + 0.15)
                rect(sl, x, top, w, 3.1, CARD, LINE)
                text(sl, x + 0.1, top + 0.12, w - 0.2, 0.3, f"STEP {a}", 10, ACCENT, True, "JetBrains Mono")
                text(sl, x + 0.1, top + 0.4, w - 0.2, 0.5, b, 20, INK, font="Instrument Serif")
                text(sl, x + 0.1, top + 0.95, w - 0.2, 1.6, c, 11, INK2)
                text(sl, x + 0.1, top + 2.65, w - 0.2, 0.3, d.upper(), 9, INK, True, "JetBrains Mono")
            text(sl, 0.6, top + 3.3, 12.1, 0.4, "Gate after 2.2: no docs, lead stops. Gate after 3: no email or phone, lead stops.", 11, INK2, font="JetBrains Mono")
            text(sl, 0.6, top + 3.8, 12.1, 1.2, s["note"], 13, INK2)
        elif lay == "table":
            rows = table_rows(s["rows"])
            tbl = sl.shapes.add_table(len(rows) + 1, 6, Inches(0.6), Inches(top), Inches(12.1), Inches(0.3 * (len(rows) + 1))).table
            widths = [3.0, 1.9, 1.0, 4.6, 0.8, 0.8]
            for k, wv in enumerate(widths):
                tbl.columns[k].width = Inches(wv)
            for k, hname in enumerate(["Product", "Source", "Status", "Business / why dropped", "Docs", "Lead"]):
                tbl.cell(0, k).text = hname
            for r_i, r in enumerate(rows, 1):
                vals = [f'{r["name"]} ({host(r["website"])})', r["source"], r["status"],
                        r.get("business_type", "") if r["status"] == "qualified" else r.get("skip_reason", ""),
                        str(r["doc_overall"] or "-"), str(r["lead_score"] if r["lead_score"] is not None else "-")]
                for k, v in enumerate(vals):
                    tbl.cell(r_i, k).text = v
            for r_i in range(len(rows) + 1):
                for k in range(6):
                    c = tbl.cell(r_i, k)
                    c.fill.solid()
                    c.fill.fore_color.rgb = rgb(INK if r_i == 0 else (CARD if r_i % 2 else PAPER))
                    c.margin_top = c.margin_bottom = Emu(30000)
                    for para in c.text_frame.paragraphs:
                        para.font.size = Pt(10)
                        para.font.color.rgb = rgb(PAPER if r_i == 0 else INK)
                        para.font.bold = r_i == 0
            text(sl, 0.6, 6.4, 12.1, 0.6, s["caption"], 12, INK2)
        elif lay == "rubric":
            for k, (a, b) in enumerate(RUBRIC):
                x = 0.6 + (k % 2) * 6.15
                y = top + (k // 2) * 1.75
                rect(sl, x, y, 5.95, 1.6, CARD, LINE)
                text(sl, x + 0.2, y + 0.1, 5.5, 0.5, a, 20, INK, font="Instrument Serif")
                text(sl, x + 0.2, y + 0.6, 5.5, 1.0, b, 11, INK2, font="JetBrains Mono")
            text(sl, 0.6, top + 3.6, 12.1, 0.4, "Start at 50, add each rule, clamp to 0-100.", 11, INK2, font="JetBrains Mono")
            text(sl, 0.6, top + 4.05, 12.1, 1.2, s["note"], 13, INK2)
    prs.save(PPTX_OUT)
    print("  pptx", PPTX_OUT.name)


def main() -> None:
    if not any(SHOTS.glob("*.png")):
        raise SystemExit("no screenshots yet; run: python showcase/capture.py all")
    print("videos")
    convert_videos()
    runs = load_runs()
    if not runs:
        raise SystemExit("no runs in output/")
    slides = build_slides(runs)
    print(f"{len(slides)} slides")
    build_pdf(slides)
    build_pptx(slides)


if __name__ == "__main__":
    main()
