"""One-command setup and launch for LeadScraper. Uses only the standard library.

    python start.py                  set up if needed, then open the dashboard
    python start.py setup            set up only
    python start.py run --limit 5    set up if needed, then any leadscraper command

Setup creates .venv, installs requirements.txt (again only when it changes),
installs Playwright's Chromium, creates .env from .env.example (asking for the
OpenAI key), and copies the sample runs into an empty output/. Every step is skipped when already done, so this is also the
everyday way to start the app.
"""

import getpass
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQS = ROOT / "requirements.txt"
REQS_MARKER = VENV / ".requirements.sha256"
BROWSER_MARKER = VENV / ".playwright-chromium"
ENV, ENV_EXAMPLE = ROOT / ".env", ROOT / ".env.example"
SAMPLES, OUTPUT = ROOT / "samples", ROOT / "output"
MIN_PYTHON = (3, 10)


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def run(*cmd: str | Path) -> None:
    subprocess.run([str(c) for c in cmd], cwd=ROOT, check=True)


def ensure_venv() -> None:
    if PY.exists():
        return
    step("Creating virtual environment in .venv")
    venv.create(VENV, with_pip=True)


def ensure_requirements() -> None:
    digest = hashlib.sha256(REQS.read_bytes()).hexdigest()
    if REQS_MARKER.exists() and REQS_MARKER.read_text().strip() == digest:
        return
    step("Installing Python packages (first run takes a minute or two)")
    run(PY, "-m", "pip", "install", "--upgrade", "pip", "--quiet")
    run(PY, "-m", "pip", "install", "-r", REQS)
    REQS_MARKER.write_text(digest)


def ensure_browser() -> None:
    if BROWSER_MARKER.exists():
        return
    step("Installing Playwright Chromium (used to render JS-heavy sites)")
    run(PY, "-m", "playwright", "install", "chromium")
    BROWSER_MARKER.write_text("ok")
    if not (shutil.which("chrome") or shutil.which("google-chrome") or _chrome_on_windows()):
        print("    Tip: install Google Chrome too. Product Hunt's Cloudflare check lets it")
        print("    through more often than bundled Chromium. Everything else works without it.")


def _chrome_on_windows() -> bool:
    if os.name != "nt":
        return False
    bases = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    return any((Path(b) / "Google/Chrome/Application/chrome.exe").exists() for b in bases if b)


def _current_key() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def ensure_env() -> None:
    first_run = not ENV.exists()
    if first_run:
        step("Creating .env from .env.example")
        shutil.copyfile(ENV_EXAMPLE, ENV)
    if _current_key() and _current_key() != "sk-...":
        return
    # Ask once, on the run that created .env; after that only remind. getpass reads
    # the console directly on Windows, so it would block a non-interactive launch.
    if not (first_run and sys.stdin.isatty() and sys.stdout.isatty()):
        print("\n    OPENAI_API_KEY is not set in .env. The dashboard opens read-only until you add it.")
        return
    step("OpenAI API key")
    print("    Needed to run audits (https://platform.openai.com/api-keys).")
    print("    Press Enter to skip: you can still browse the sample runs, and add it to .env later.")
    key = getpass.getpass("    OPENAI_API_KEY (input hidden): ").strip()
    if not key:
        return
    lines = ENV.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("OPENAI_API_KEY="):
            lines[i] = f"OPENAI_API_KEY={key}"
            break
    else:
        lines.insert(0, f"OPENAI_API_KEY={key}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("    Saved to .env")


def ensure_samples() -> None:
    """Copy the anonymised sample runs into output/ when there are no runs yet,
    so the dashboard's Run menu has something to open on first start."""
    if not SAMPLES.is_dir() or (OUTPUT.is_dir() and any(OUTPUT.glob("run-*"))):
        return
    step("Adding sample runs to output/ (anonymised, safe to delete)")
    for run in SAMPLES.glob("run-*"):
        shutil.copytree(run, OUTPUT / run.name)


def _arg(args: list[str], name: str, default: str) -> str:
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def open_when_ready(host: str, port: int) -> None:
    """Open the dashboard in the default browser once the server accepts connections."""
    def wait() -> None:
        for _ in range(120):
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    webbrowser.open(f"http://{host}:{port}")
                    return
            except OSError:
                time.sleep(0.5)
    threading.Thread(target=wait, daemon=True).start()


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"LeadScraper needs Python {'.'.join(map(str, MIN_PYTHON))}+ (this is {sys.version.split()[0]}).")
        return 1
    args = sys.argv[1:]
    setup_only = args[:1] == ["setup"]
    try:
        ensure_venv()
        ensure_requirements()
        ensure_browser()
        ensure_env()
        ensure_samples()
    except subprocess.CalledProcessError as exc:
        print(f"\nSetup failed while running: {' '.join(map(str, exc.cmd))}")
        print("Fix the error above and run start again; finished steps are skipped.")
        return 1
    if setup_only:
        print("\nSetup complete. Start the dashboard with:  python start.py")
        return 0

    args = args or ["serve"]
    if args[0] == "serve" and "--no-browser" not in args:
        open_when_ready(_arg(args, "--host", "127.0.0.1"), int(_arg(args, "--port", "8765")))
    args = [a for a in args if a != "--no-browser"]
    if args[0] == "serve":
        print("\nDashboard starting. Press Ctrl+C to stop.", flush=True)
    try:
        return subprocess.run([str(PY), "-m", "leadscraper", *args], cwd=ROOT).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
