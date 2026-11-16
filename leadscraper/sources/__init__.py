"""Lead sources. Importing this package registers every built-in adapter."""

from . import browser_listing, github_topic  # noqa: F401  (registration side effect)
from .base import Source, SourceConfig, adapters, build_source, load_source_configs

__all__ = ["Source", "SourceConfig", "adapters", "build_source", "load_source_configs"]
