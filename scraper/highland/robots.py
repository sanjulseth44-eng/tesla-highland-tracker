"""Minimal RFC 9309 (robots.txt) matcher with wildcard support.

Python's urllib.robotparser does plain prefix matching and treats "*" / "$" literally, which
mis-evaluates rules like "Disallow: /car/*". This implements the Google/RFC semantics:
longest matching rule wins, ties go to Allow, "*" is a wildcard, "$" anchors the end.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RobotsGroup:
    agents: list[str]
    rules: list[tuple[str, str]] = field(default_factory=list)  # (allow|disallow, pattern)
    crawl_delay: Optional[float] = None


@dataclass
class Robots:
    groups: list[RobotsGroup]
    fetched: bool = True   # False => robots.txt was missing/unreadable; everything allowed

    @classmethod
    def parse(cls, text: str) -> "Robots":
        groups: list[RobotsGroup] = []
        cur: Optional[RobotsGroup] = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip()
            if key == "user-agent":
                if cur is None or not last_was_agent:
                    cur = RobotsGroup(agents=[])
                    groups.append(cur)
                cur.agents.append(val.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if cur is None:
                continue
            if key in ("allow", "disallow"):
                cur.rules.append((key, val))
            elif key == "crawl-delay":
                try:
                    cur.crawl_delay = float(val)
                except ValueError:
                    pass
        return cls(groups=groups)

    @classmethod
    def allow_all(cls) -> "Robots":
        return cls(groups=[], fetched=False)

    def _group_for(self, agent: str) -> Optional[RobotsGroup]:
        a = agent.lower()
        for g in self.groups:
            if any(x != "*" and x in a for x in g.agents):
                return g
        for g in self.groups:
            if "*" in g.agents:
                return g
        return None

    def crawl_delay(self, agent: str = "*") -> Optional[float]:
        g = self._group_for(agent)
        return g.crawl_delay if g else None

    def can_fetch(self, path_and_query: str, agent: str = "*") -> bool:
        g = self._group_for(agent)
        if not g:
            return True
        best_len = -1
        best_kind = "allow"
        for kind, pat in g.rules:
            if pat == "":
                continue  # "Disallow:" (empty) = allow everything
            if _match(pat, path_and_query):
                if len(pat) > best_len or (len(pat) == best_len and kind == "allow"):
                    best_len = len(pat)
                    best_kind = kind
        return best_kind == "allow"


def _match(pattern: str, path: str) -> bool:
    if not pattern.startswith("/") and not pattern.startswith("*"):
        pattern = "/" + pattern
    anchored = pattern.endswith("$")
    core = pattern[:-1] if anchored else pattern
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in core)
    rx = "^" + rx + ("$" if anchored else "")
    return re.match(rx, path) is not None
