"""Source registry. Add a module under highland/sources/ that defines SOURCE = <Source subclass>
and list its module name here."""
from __future__ import annotations

import importlib
import logging
from typing import Type

from .base import Source

log = logging.getLogger("highland.sources")

SOURCE_MODULES = [
    "carmax",
    "tesla",
    "autonation",
    "echopark",
    "sewell",
    "carvana",
    "autotrader",
    "cargurus",
    "hertz",
    "enterprise",
    "edmunds",
    "truecar",
    "cars_com",
]


def load_sources(keys: list[str] | None = None) -> dict[str, Type[Source]]:
    out: dict[str, Type[Source]] = {}
    for mod in SOURCE_MODULES:
        try:
            m = importlib.import_module(f"{__name__}.{mod}")
        except ModuleNotFoundError as e:
            if e.name and e.name.endswith(mod):
                continue  # module not implemented yet
            if keys and mod in keys:
                raise
            log.warning("source module %s failed to import (%s); skipping", mod, e)
            continue
        except Exception as e:  # a broken module must not take down the other sources
            if keys and mod in keys:
                raise
            log.warning("source module %s failed to import (%s: %s); skipping", mod, type(e).__name__, e)
            continue
        src = getattr(m, "SOURCE", None)
        if src is None:
            continue
        if keys is None or src.key in keys:
            out[src.key] = src
    if keys:
        missing = [k for k in keys if k not in out]
        if missing:
            raise KeyError(f"unknown source(s): {missing}; available: {sorted(out)}")
    return out
