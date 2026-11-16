from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str | None = None
    github_token: str = ""

    sources_file: Path = Path("config/sources.yaml")
    output_dir: Path = Path("output")

    request_timeout: float = 20.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    contact_max_pages: int = 30
    docs_max_candidates: int = 12
    docs_max_pages: int = 8
    docs_score_threshold: int = 6

    render_js: bool = True
    # JS rendering costs ~2-4s per page; SPAs would otherwise make every crawl slow.
    max_renders_per_lead: int = 8
    browser_channel: str | None = "chrome"

    concurrency: int = 3
