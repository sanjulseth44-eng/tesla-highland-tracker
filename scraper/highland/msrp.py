"""Original base MSRP by model year + canonical trim (USD, excludes destination/order fees).

Tesla changes prices several times a year, so a single number per (year, trim) is an
approximation. Values are the base price at the START of that model year's run, with the
notable mid-year moves in NOTES. Keep this table in sync with data/msrp.json (exported).
"""
from __future__ import annotations

from typing import Optional

MSRP: dict[tuple[int, str], int] = {
    # 2024 (Highland launch, US deliveries from Jan 2024)
    (2024, "RWD"): 38_990,
    (2024, "Long Range RWD"): 42_490,   # added June 2024
    (2024, "Long Range AWD"): 47_490,   # $45,990 at launch, +$1,500 April 2024
    (2024, "Performance"): 52_990,      # launched April 2024; $54,990 from late 2024
    # 2025
    (2025, "RWD"): 38_990,              # base LFP RWD was withdrawn from the US lineup during MY2025
    (2025, "Long Range RWD"): 42_490,
    (2025, "Long Range AWD"): 47_490,
    (2025, "Performance"): 54_990,
    # 2026 (Oct 2025 lineup: Standard / Premium RWD / Premium AWD / Performance)
    (2026, "Standard"): 36_990,
    (2026, "Long Range RWD"): 42_490,   # sold as "Model 3 Premium RWD"
    (2026, "Long Range AWD"): 47_490,   # sold as "Model 3 Premium AWD"
    (2026, "Performance"): 54_990,
}

NOTES: dict[str, str] = {
    "basis": "Base MSRP at the start of the model year, before destination ($1,390) and order fees; "
             "options such as paint, wheels, interior and FSD are not included.",
    "2024 Long Range AWD": "$45,990 at the January 2024 launch, raised to $47,490 in April 2024.",
    "2024 Performance": "Launched April 2024 at $52,990; $54,990 by the end of 2024.",
    "2025 RWD": "Only a small number of MY2025 base RWD cars exist; Tesla dropped the trim from the US lineup.",
    "2026 naming": "Tesla renamed Long Range RWD/AWD to Premium RWD/AWD for 2026 and added the cheaper 'Standard'. "
                   "The dashboard maps Premium -> Long Range so year buckets stay comparable.",
}


def msrp_for(year: Optional[int], trim: Optional[str]) -> Optional[int]:
    if not year or not trim:
        return None
    v = MSRP.get((year, trim))
    if v is None and year > max(y for y, _ in MSRP):
        # Newer model year than the table knows: reuse the latest year's price for that trim.
        latest = max(y for y, t in MSRP if t == trim) if any(t == trim for _, t in MSRP) else None
        v = MSRP.get((latest, trim)) if latest else None
    return v


def export_table() -> list[dict]:
    return [{"year": y, "trim": t, "msrp": v} for (y, t), v in sorted(MSRP.items())]
