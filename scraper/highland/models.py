"""Data shapes passed between sources and the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RawListing:
    """One vehicle as reported by a single source. Sources fill what they can; the
    pipeline normalizes trim, validates the VIN/year, and computes distance."""

    source: str                 # source key, e.g. "carmax"
    source_id: str              # dealer's own id (stock number / listing id)
    url: str                    # live listing page (must resolve on the dealer site)
    vin: str
    year: int
    price: int                  # asking price in whole dollars (before tax/fees)
    mileage: int
    trim_raw: Optional[str] = None      # trim string exactly as the source shows it
    drivetrain: Optional[str] = None    # "RWD" | "AWD" | None
    horsepower: Optional[int] = None
    dealer: Optional[str] = None        # human-readable dealer / store name
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    distance_mi: Optional[float] = None     # from HOME_ZIP, if the source computes it
    shipping_cost: Optional[float] = None   # $ to ship to HOME_ZIP, if the source exposes it
    shipping_note: Optional[str] = None     # e.g. "free transfer", "not shippable to 77479"
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)  # anything else worth keeping (JSON)


@dataclass
class SourceResult:
    """What a source run returns to the pipeline."""

    source: str
    listings: list[RawListing]
    ok: bool = True
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)   # non-fatal warnings (markup drift etc.)
    pages_fetched: int = 0
