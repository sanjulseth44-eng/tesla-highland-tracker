"""VIN validation and trim canonicalization for the Highland Model 3.

Canonical trims (what the dashboard groups on):
  "RWD"             2024-25 base rear-drive (LFP, ~272 mi)
  "Long Range RWD"  2024+ LR rear-drive; Tesla renamed it "Premium RWD" for the 2026 lineup
  "Long Range AWD"  2024+ LR dual-motor; renamed "Premium AWD" for 2026
  "Performance"     2024+ dual-motor Performance
  "Standard"        the decontented 2026 "Model 3 Standard" (LFP) launched Oct 2025

Tesla VIN cheat-sheet (US-built Model 3 starts with 5YJ3):
  pos 8  motor: A = single motor (RWD or LR RWD -- ambiguous), B = dual motor, C = dual motor Performance
  pos 10 model year: P = 2023, R = 2024, S = 2025, T = 2026, V = 2027
"""
from __future__ import annotations

import re
from typing import Optional

from .config import MIN_YEAR

CANONICAL_TRIMS = ["RWD", "Long Range RWD", "Long Range AWD", "Performance", "Standard"]

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_YEAR_CODES = {"P": 2023, "R": 2024, "S": 2025, "T": 2026, "V": 2027, "W": 2028}


def valid_vin(vin: str | None) -> bool:
    return bool(vin) and bool(_VIN_RE.match(vin.strip().upper()))


def is_model3_vin(vin: str) -> bool:
    v = vin.upper()
    # 5YJ3 = Fremont-built Model 3. (LRW3 = Shanghai; not sold in the US.)
    return v.startswith("5YJ3") or v.startswith("LRW3")


def vin_year(vin: str) -> Optional[int]:
    return _YEAR_CODES.get(vin.upper()[9]) if valid_vin(vin) else None


def vin_motor_code(vin: str) -> Optional[str]:
    return vin.upper()[7] if valid_vin(vin) else None


def infer_trim(
    year: int,
    trim_raw: str | None,
    drivetrain: str | None = None,
    horsepower: int | None = None,
    vin: str | None = None,
) -> tuple[str, str]:
    """Return (canonical_trim, confidence) where confidence is "high" | "medium" | "low".

    Precedence: explicit Performance > AWD signals > explicit LR/Premium > explicit Standard-Range/RWD
    > 2026 "Standard" > horsepower hint > year-based default.
    """
    t = (trim_raw or "").strip().lower()
    t = re.sub(r"[_\-/]+", " ", t)
    code = vin_motor_code(vin) if vin else None
    dt = (drivetrain or "").upper()

    perf_txt = "performance" in t or re.search(r"\bperf\b", t) is not None
    if perf_txt or code == "C":
        return "Performance", "high" if (perf_txt or code == "C") else "medium"

    awd_txt = any(k in t for k in ("awd", "all wheel", "all-wheel", "dual motor", "dual-motor"))
    if awd_txt or dt == "AWD" or code == "B":
        # Dual-motor non-Performance is always Long Range / Premium AWD on the Highland.
        return "Long Range AWD", "high" if (awd_txt or code == "B") else "medium"

    # ---- single-motor (RWD) territory ----
    lr_txt = any(k in t for k in ("long range", "longrange", "premium")) or re.search(r"\blr\b", t) is not None
    if lr_txt:
        return "Long Range RWD", "high"

    if "standard range" in t or "standard range plus" in t:
        return "RWD", "high"

    if "standard" in t:
        # Tesla's decontented "Model 3 Standard" arrived with the 2026 lineup. On an older car
        # a dealer writing "Standard" almost always means the base RWD.
        return ("Standard", "medium") if year >= 2026 else ("RWD", "medium")

    if re.search(r"\brwd\b", t) or "rear wheel" in t or "rear-wheel" in t or t in ("base", "model 3", ""):
        # Bare "RWD"/"Model 3" with no range qualifier. Use horsepower when the source exposes it.
        if horsepower:
            if horsepower >= 290:
                return "Long Range RWD", "medium"
            if horsepower <= 280:
                return "RWD", "medium"
        # Year-based default: Tesla dropped the base RWD from the US lineup for MY2025, so an
        # unqualified 2025 single-motor car is far more likely an LR RWD.
        if year >= 2025:
            return "Long Range RWD", "low"
        return "RWD", "low"

    # Unrecognized string: fall back on the same hp / year logic but flag it.
    if horsepower and horsepower >= 290:
        return "Long Range RWD", "low"
    if year >= 2025:
        return "Long Range RWD", "low"
    return "RWD", "low"


def resolve_year(source_year: int | None, vin: str | None) -> tuple[Optional[int], Optional[str]]:
    """Prefer the VIN's model-year code; report a mismatch note when the source disagrees."""
    vy = vin_year(vin) if vin else None
    if vy and source_year and vy != source_year:
        return vy, f"source said {source_year}, VIN decodes to {vy}"
    return (vy or source_year), None


def is_highland(year: int | None, vin: str | None) -> bool:
    """2024+ model year Model 3. Pre-refresh (2017-2023) cars are excluded entirely."""
    if not year or year < MIN_YEAR:
        return False
    if vin and valid_vin(vin) and not is_model3_vin(vin):
        return False
    return True


def normalize_drivetrain(s: str | None) -> Optional[str]:
    if not s:
        return None
    u = s.upper()
    if "AWD" in u or "ALL" in u or "4WD" in u or "DUAL" in u:
        return "AWD"
    if "RWD" in u or "REAR" in u or "2WD" in u:
        return "RWD"
    return None
