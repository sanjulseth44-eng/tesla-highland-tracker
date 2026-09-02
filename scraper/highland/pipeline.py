"""Run sources -> normalize -> upsert into SQLite -> detect changes -> export JSON for the web app."""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .config import CHANGE_WINDOW_DAYS, HOME_LAT, HOME_LNG, HOME_ZIP, LOCAL_RADIUS_MI, MIN_YEAR
from .db import Store, utcnow
from .geo import city_latlng, distance_from_home, zip_latlng
from .models import RawListing
from .msrp import NOTES as MSRP_NOTES, export_table as msrp_table, msrp_for
from .normalize import infer_trim, is_highland, resolve_year, valid_vin
from .sources import load_sources
from .sources.base import Source

log = logging.getLogger("highland.pipeline")

# If a source that previously had >= this many active listings suddenly returns zero, treat the
# run as suspicious: keep the old listings active and flag the source instead of "removing" all.
SUSPICIOUS_ZERO_THRESHOLD = 3
# Same idea for a large drop (e.g. a pagination bug). Fraction of previously-active listings.
SUSPICIOUS_DROP_FRACTION = 0.6
# ...but if the source keeps returning zero for this many consecutive runs, believe it (the
# dealer really did sell out) so the listings get marked removed and the flag clears.
ACCEPT_ZERO_AFTER_RUNS = 3


def normalize(raw: RawListing) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Turn a RawListing into a DB row dict. Returns (row, reject_reason)."""
    vin = (raw.vin or "").strip().upper()
    if not valid_vin(vin):
        return None, f"invalid VIN {raw.vin!r}"
    year, year_note = resolve_year(raw.year, vin)
    if not is_highland(year, vin):
        return None, f"not a 2024+ Model 3 (year={year}, vin={vin})"
    if not raw.url or not raw.url.startswith("http"):
        return None, "missing listing URL"
    if not raw.price or raw.price < 10_000 or raw.price > 120_000:
        return None, f"implausible price {raw.price}"
    if raw.mileage is None or raw.mileage < 0 or raw.mileage > 300_000:
        return None, f"implausible mileage {raw.mileage}"

    trim, conf = infer_trim(year, raw.trim_raw, raw.drivetrain, raw.horsepower, vin)

    lat, lng = raw.lat, raw.lng
    if (lat is None or lng is None) and raw.zip:
        ll = zip_latlng(raw.zip)
        if ll:
            lat, lng = ll
    if (lat is None or lng is None) and raw.city and raw.state:
        ll = city_latlng(raw.city, raw.state)
        if ll:
            lat, lng = ll
    dist = raw.distance_mi
    if dist is None and lat is not None and lng is not None:
        dist = distance_from_home(lat, lng)

    extra = dict(raw.extra or {})
    if year_note:
        extra["year_note"] = year_note
    row = {
        "source": raw.source,
        "vin": vin,
        "source_id": raw.source_id,
        "url": raw.url,
        "year": year,
        "trim": trim,
        "trim_raw": raw.trim_raw,
        "trim_confidence": conf,
        "mileage": int(raw.mileage),
        "price": int(raw.price),
        "msrp": msrp_for(year, trim),
        "dealer": raw.dealer,
        "city": raw.city,
        "state": raw.state,
        "zip": raw.zip,
        "lat": lat,
        "lng": lng,
        "distance_mi": round(dist, 1) if dist is not None else None,
        "shipping_cost": raw.shipping_cost,
        "shipping_note": raw.shipping_note,
        "exterior_color": raw.exterior_color,
        "interior_color": raw.interior_color,
        "extra": extra,
    }
    return row, None


def run_source(store: Store, src: Source, now: str, dry_run: bool = False) -> dict[str, Any]:
    run_id = store.start_run(src.key, now)
    summary: dict[str, Any] = {"source": src.key, "ok": False, "new": 0, "price_drop": 0, "price_up": 0,
                               "removed": 0, "returned": 0, "kept": 0, "rejected": 0, "error": None, "notes": []}
    try:
        result = src.fetch()
    except Exception as e:  # a source bug must not kill the run
        result = None
        summary["error"] = f"{type(e).__name__}: {e}"
        log.error("source %s crashed:\n%s", src.key, traceback.format_exc())
    if result is None or not result.ok:
        err = summary["error"] or (result.error if result else "unknown")
        summary["error"] = err
        summary["notes"] = list(result.notes) if result else []
        log.warning("source %s FAILED: %s", src.key, err)
        store.finish_run(run_id, ok=False, count=None, error=err, notes=summary["notes"])
        return summary

    summary["notes"] = list(result.notes)
    rows: dict[str, dict[str, Any]] = {}
    for raw in result.listings:
        row, why = normalize(raw)
        if row is None:
            summary["rejected"] += 1
            log.debug("reject %s: %s", raw.vin, why)
            continue
        rows[row["vin"]] = row  # last write wins on duplicate VIN within a source

    previously_active = store.active_by_source(src.key)
    prev_n = len(previously_active)
    if prev_n >= SUSPICIOUS_ZERO_THRESHOLD and len(rows) == 0 and store.consecutive_zero_runs(src.key) < ACCEPT_ZERO_AFTER_RUNS:
        msg = f"returned 0 listings but {prev_n} were active last run; not marking removals"
        summary["notes"].append(msg)
        summary["error"] = msg
        log.warning("source %s: %s", src.key, msg)
        store.finish_run(run_id, ok=False, count=0, error=msg, notes=summary["notes"])
        return summary
    suspicious_drop = prev_n >= 10 and len(rows) < prev_n * (1 - SUSPICIOUS_DROP_FRACTION)

    for vin, row in rows.items():
        existing = store.get_listing(src.key, vin)
        if existing is None:
            store.insert_listing(row, now)
            summary["new"] += 1
        else:
            kinds = store.update_listing(existing, row, now)
            for k in kinds:
                summary[k] += 1
            if not kinds:
                summary["kept"] += 1

    if suspicious_drop:
        msg = (f"count fell from {prev_n} to {len(rows)}; treating as partial fetch and not marking removals")
        summary["notes"].append(msg)
        log.warning("source %s: %s", src.key, msg)
    else:
        gone = [r["id"] for r in previously_active if r["vin"] not in rows]
        summary["removed"] = store.mark_removed(gone, now)

    summary["ok"] = True
    summary["count"] = len(rows)
    store.finish_run(run_id, ok=True, count=len(rows), error=None, notes=summary["notes"])
    if dry_run:
        store.conn.rollback()
    else:
        store.commit()
    return summary


def export(store: Store, source_classes: dict[str, type[Source]], out_path: str, now: str) -> dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=CHANGE_WINDOW_DAYS)).replace(microsecond=0).isoformat()
    labels = {k: (c.label, c.kind, c.homepage) for k, c in source_classes.items()}
    listings = []
    for r in store.listings_for_export(since):
        d = dict(r)
        d["extra"] = json.loads(d.get("extra") or "{}")
        d["source_label"] = labels.get(d["source"], (d["source"], "local", ""))[0]
        d["source_kind"] = labels.get(d["source"], (d["source"], "local", ""))[1]
        d["is_local"] = d["source_kind"] != "carmax" or (d["distance_mi"] is not None and d["distance_mi"] <= LOCAL_RADIUS_MI)
        ship = d["shipping_cost"] or 0
        d["effective_price"] = d["price"] + int(round(ship))
        d["msrp_discount_pct"] = round((d["msrp"] - d["price"]) / d["msrp"] * 100, 1) if d.get("msrp") else None
        d["price_history"] = store.price_history(d["id"])
        listings.append(d)

    changes = []
    for c in store.changes_since(since):
        d = dict(c)
        d["source_label"] = labels.get(d["source"], (d["source"],))[0]
        changes.append(d)

    runs = store.last_runs()
    sources = []
    for k, (label, kind, homepage) in labels.items():
        info = runs.get(k, {})
        sources.append({
            "key": k, "label": label, "kind": kind, "homepage": homepage,
            "ok": info.get("ok"), "count": info.get("count"), "last_run_at": info.get("last_run_at"),
            "last_ok_at": info.get("last_ok_at"), "error": info.get("error"), "notes": info.get("notes", []),
        })

    payload = {
        "generated_at": now,
        "home": {"zip": HOME_ZIP, "lat": HOME_LAT, "lng": HOME_LNG, "radius_mi": LOCAL_RADIUS_MI, "min_year": MIN_YEAR},
        "change_window_days": CHANGE_WINDOW_DAYS,
        "sources": sources,
        "msrp": msrp_table(),
        "msrp_notes": MSRP_NOTES,
        "listings": listings,
        "changes": changes,
        "stats": {
            "active": sum(1 for l in listings if l["status"] == "active"),
            "removed_recent": sum(1 for l in listings if l["status"] != "active"),
        },
    }
    with open(out_path, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"), default=str)
    log.info("exported %d listings, %d changes -> %s", len(listings), len(changes), out_path)
    return payload


def run(source_keys: list[str] | None, db_path: str, out_path: Optional[str], dry_run: bool = False) -> list[dict[str, Any]]:
    now = utcnow()
    classes = load_sources(source_keys)
    all_classes = load_sources(None)
    store = Store(":memory:" if dry_run else db_path)
    summaries = []
    for key, cls in classes.items():
        log.info("=== %s ===", key)
        src = cls()
        s = run_source(store, src, now, dry_run=dry_run)
        summaries.append(s)
        log.info("%s: %s", key, {k: v for k, v in s.items() if k != "notes"})
        for n in s["notes"]:
            log.warning("%s note: %s", key, n)
    if out_path and not dry_run:
        export(store, all_classes, out_path, now)
    store.close()
    return summaries
