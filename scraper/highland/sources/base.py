"""Base class every source implements. See README "Adding a dealer source"."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..http import Http
from ..models import SourceResult


class Source(ABC):
    key: str = ""                 # short id used in the DB and CLI, e.g. "carmax"
    label: str = ""               # display name, e.g. "CarMax"
    kind: str = "local"           # "carmax" (nationwide + shipping) or "local" (100-mile radius)
    homepage: str = ""
    impersonate: str = "chrome"   # curl_cffi browser fingerprint that gets past this site's edge
    min_interval_s: float = 1.0   # politeness gap between requests to this site

    def __init__(self, http: Optional[Http] = None):
        self.http = http or Http(impersonate=self.impersonate, min_interval=self.min_interval_s)

    @abstractmethod
    def fetch(self) -> SourceResult:
        """Return every 2024+ Model 3 listing the source currently shows. Must not raise for
        ordinary failures -- return SourceResult(ok=False, error=...) so the pipeline can log it."""
