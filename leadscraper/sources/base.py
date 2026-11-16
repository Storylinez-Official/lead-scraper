"""Source plug-in contract and registry.

A source turns one listing URL into a stream of Leads. Adding a new site is
either a new entry in config/sources.yaml that reuses an existing adapter
(usually `browser_listing` with different selectors), or a new adapter class
decorated with @register("name").
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, Field

from ..schemas import Lead
from ..settings import Settings

_REGISTRY: dict[str, type["Source"]] = {}


def register(adapter: str):
    def deco(cls: type["Source"]) -> type["Source"]:
        if adapter in _REGISTRY:
            raise ValueError(f"adapter {adapter!r} registered twice")
        cls.adapter = adapter
        _REGISTRY[adapter] = cls
        return cls

    return deco


class SourceConfig(BaseModel):
    name: str
    adapter: str
    url: str
    enabled: bool = True
    limit: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class Source(ABC):
    adapter: ClassVar[str]

    def __init__(self, config: SourceConfig, settings: Settings):
        self.config = config
        self.settings = settings
        self.name = config.name
        self.url = config.url
        self.options = config.options

    @abstractmethod
    def iter_leads(self, limit: int) -> Iterator[Lead]:
        """Yield at most `limit` leads, in listing order."""


def load_source_configs(path: Path) -> list[SourceConfig]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    configs = [SourceConfig(**item) for item in data.get("sources", [])]
    names = [c.name for c in configs]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate source names in {path}")
    for c in configs:
        if c.adapter not in _REGISTRY:
            raise ValueError(f"source {c.name!r}: unknown adapter {c.adapter!r}; known: {sorted(_REGISTRY)}")
    return configs


def build_source(config: SourceConfig, settings: Settings) -> Source:
    return _REGISTRY[config.adapter](config, settings)


def adapters() -> list[str]:
    return sorted(_REGISTRY)
