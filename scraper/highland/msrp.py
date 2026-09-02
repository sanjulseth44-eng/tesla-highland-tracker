"""Original base MSRP by model year + canonical trim (USD, excludes destination/order fees).

Tesla changes prices several times a year, so a single number per (year, trim) is an
approximation. Values are the base price at the START of that model year's run, with the
notable mid-year moves in NOTES. Keep this table in sync with data/msrp.json (exported).
"""
from __future__ import annotations

from typing import Optional

MSRP: dict[tuple[int, str], int] = {
    # 2024 -- Highland launch; US orders opened 2024-01-10
    (2024, "RWD"): 38_990,             # $38,990 all year (272 mi LFP)
    (2024, "Long Range RWD"): 42_490,  # (re)introduced July 2024 at $42,490, 363 mi
    (2024, "Long Range AWD"): 47_490,  # $45,990 at launch, $47,490 from spring 2024 onward
    (2024, "Performance"): 54_990,     # launched 2024-04-23 at $52,990, $53,990 days later, $54,990 from May 2024
    # 2025 -- same prices; base RWD faded out of the US lineup during MY2025
    (2025, "RWD"): 38_990,
    (2025, "Long Range RWD"): 42_490,
    (2025, "Long Range AWD"): 47_490,
    (2025, "Performance"): 54_990,
    (2025, "Standard"): 36_990,        # in case an early "Model 3 Standard" carries a 2025 VIN
    # 2026 -- lineup renamed 2025-10-07: Standard / Premium RWD / Premium AWD / Performance
    (2026, "Standard"): 36_990,
    (2026, "Long Range RWD"): 42_490,  # sold as "Model 3 Premium RWD"
    (2026, "Long Range AWD"): 47_490,  # sold as "Model 3 Premium AWD"
    (2026, "Performance"): 54_990,
}

NOTES: dict[str, str] = {
    "basis": "Base MSRP before Tesla's destination ($1,390) and order ($250) fees; paint, wheels, interior and "
             "FSD options are not included. Where Tesla changed the price mid-year the prevailing price for that "
             "model year is used.",
    "2024 Long Range AWD": "$45,990 at the January 2024 launch; raised to $47,490 in spring 2024 and held there.",
    "2024 Performance": "Launched 2024-04-23 at $52,990, $53,990 within days, $54,990 from May 2024 "
                        "(Electrek, InsideEVs).",
    "2024 Long Range RWD": "Added to the US lineup in July 2024 at $42,490 with 363 mi EPA range (Electrek).",
    "2025 RWD": "Tesla dropped the $38,990 LFP base RWD from the US lineup in early October 2024 (InsideEVs, "
                "Teslarati), so almost no MY2025 base RWD cars exist; Long Range RWD became the entry trim.",
    "2026 naming": "On 2025-10-07 Tesla renamed Long Range RWD/AWD to Premium RWD/AWD ($42,490 / $47,490) and added "
                   "the cheaper Model 3 Standard at $36,990 (321 mi). The dashboard maps Premium -> Long Range so "
                   "year buckets stay comparable; Standard is its own trim.",
    "sources": "electrek.co/2024/07/12 (LR RWD), electrek.co/2024/04/26 + insideevs.com/news/720137 (Performance), "
               "insideevs.com/news/704076 + greencarreports.com (Jan 2024 launch prices), "
               "edmunds.com 2026 pricing guide + teslamotorsclub 2025-10-07 thread (Standard/Premium).",
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
