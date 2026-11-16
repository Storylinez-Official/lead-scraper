"""Audit a list of websites through the dashboard and package each one for sending.

Needs the dashboard running (python -m leadscraper serve). For each URL it records the
live audit (video + screenshots), takes a full-length dossier image, and copies that
run's output files. Everything goes to audits/<domain>/, then audits/<name>.zip.

    python showcase/audit_sites.py https://www.remotion.dev https://apify.com ...
    python showcase/audit_sites.py --base=http://127.0.0.1:8766 https://...   # dashboard on another port
    python showcase/audit_sites.py              # no URLs: re-package the existing folders only
"""

import shutil
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

import capture  # same folder; reuses the dashboard driving code

ROOT = Path(__file__).parent.parent
OUTPUT = ROOT / "output"
AUDITS = ROOT / "audits"


def domain(url: str) -> str:
    return url.split("//")[-1].split("/")[0].removeprefix("www.")


def run_dirs() -> set[str]:
    return {d.name for d in OUTPUT.glob("run-*")}


def full_dossier(browser, run_id: str, dest: Path) -> None:
    ctx = capture.new_context(browser, video=False)
    page = ctx.new_page()
    capture.open_dashboard(page)
    page.select_option("#historySelect", run_id)
    page.wait_for_selector("#ledger .row")
    page.evaluate("() => document.querySelector('#ledger .row').click()")
    page.wait_for_selector("#drawer.open")
    time.sleep(1.5)
    h = page.evaluate("() => document.getElementById('drawer').scrollHeight")
    page.set_viewport_size({"width": 1440, "height": min(h + 40, 8000)})
    time.sleep(1.5)
    page.locator("#drawer").screenshot(path=dest)
    ctx.close()


def audit_one(browser, url: str) -> Path:
    site = AUDITS / domain(url)
    if site.exists():
        shutil.rmtree(site)
    capture.SHOTS = site / "screenshots"
    capture.VIDEOS = site
    capture.SHOTS.mkdir(parents=True)

    before = run_dirs()
    capture.live_audit(browser, url)
    new = sorted(run_dirs() - before)
    if not new:
        raise RuntimeError(f"no run folder appeared for {url}")
    run = OUTPUT / new[-1]

    (site / "03-live-single-site-audit.webm").rename(site / "audit-recording.webm")
    shutil.copytree(run, site / "data")
    for md in (run / "reports").glob("*.md"):
        shutil.copy(md, site / "report.md")
    full_dossier(browser, run.name, site / "dossier-full.png")

    exe = shutil.which("ffmpeg")
    if exe:
        import subprocess
        subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(site / "audit-recording.webm"),
                        "-vf", "scale=1280:-2", "-an", "-c:v", "libx264", "-preset", "slow", "-pix_fmt", "yuv420p",
                        "-crf", "30", "-movflags", "+faststart", str(site / "audit-recording.mp4")], check=True)
        (site / "audit-recording.webm").unlink()
    print(f"  -> {site}", flush=True)
    return site


def slim(site: Path) -> None:
    """Make a site folder small enough to send: 3 live frames, JPEG instead of PNG."""
    from PIL import Image

    frames = sorted((site / "screenshots").glob("31-audit-live-*.png"))
    keep = {frames[0], frames[len(frames) // 2], frames[-1]} if frames else set()
    for f in frames:
        if f not in keep:
            f.unlink()
    for png in list(site.glob("*.png")) + list((site / "screenshots").glob("*.png")):
        Image.open(png).convert("RGB").save(png.with_suffix(".jpg"), quality=85, optimize=True)
        png.unlink()


def summary(sites: list[Path]) -> str:
    import json

    lines = ["LeadScraper audits", "==================", ""]
    for site in sites:
        row = json.loads((site / "data" / "leads.jsonl").read_text(encoding="utf-8").splitlines()[0])
        lines += [f"{site.name}", "-" * len(site.name), f"Status: {row['status']}"]
        if row["status"] == "qualified":
            lines += [
                f"Lead score: {row['lead_score']}/100   Docs score: {row['doc_overall']}/10",
                f"Docs: {row['doc_url']}",
                f"Decision-makers: {row['decision_makers'] or '-'}",
                f"Intent signals: {row['intent_signals'] or '-'}",
                f"Contacts: {row['emails'] or row['phone_numbers'] or '-'}",
                f"Outreach subject: {row['outreach_subject']}",
            ]
        else:
            lines.append(f"Stopped at {row['stage']}: {row['skip_reason']}")
        lines += ["", ""]
    lines += [
        "Each folder: report.md (full report, qualified sites only), dossier-full.jpg (the whole",
        "dossier as one image), audit-recording.mp4 (the live audit), screenshots/, and data/",
        "(leads.csv, per-lead JSON with all evidence).",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    urls = [a for a in sys.argv[1:] if not a.startswith("--base=")]
    for a in sys.argv[1:]:
        if a.startswith("--base="):
            capture.BASE = a.removeprefix("--base=").rstrip("/")
    AUDITS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for url in urls:
            try:
                slim(audit_one(browser, url))
            except Exception as exc:  # keep going; report at the end
                print(f"  FAILED {url}: {exc}", flush=True)
        browser.close()

    # Package every site folder present (so a single re-run still ships the whole set).
    sites = sorted(d for d in AUDITS.iterdir() if (d / "data" / "leads.jsonl").exists())
    for site in sites:
        if list(site.rglob("*.png")):
            slim(site)
    (AUDITS / "SUMMARY.txt").write_text(summary(sites), encoding="utf-8")
    zpath = AUDITS / f"LeadScraper-audits-{date.today().isoformat()}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(AUDITS / "SUMMARY.txt", "SUMMARY.txt")
        for site in sites:
            for f in sorted(site.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(AUDITS))
    print(f"zip: {zpath} ({zpath.stat().st_size / 1e6:.1f} MB, {len(sites)} sites)")


if __name__ == "__main__":
    main()
