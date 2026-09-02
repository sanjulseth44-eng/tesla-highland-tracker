#!/usr/bin/env python3
"""CLI entry point.

  python scraper/run.py --sources carmax,tesla --db data/listings.db --out data/latest.json
  python scraper/run.py --dry-run --sources carmax     # fetch + normalize, no DB writes
  python scraper/run.py --export-only                   # rebuild latest.json from the DB
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from highland.db import Store, utcnow  # noqa: E402
from highland.pipeline import export, run  # noqa: E402
from highland.sources import load_sources  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=None, help="comma-separated source keys (default: all)")
    ap.add_argument("--db", default="data/listings.db")
    ap.add_argument("--out", default="data/latest.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
    if a.export_only:
        store = Store(a.db)
        export(store, load_sources(None), a.out, utcnow())
        return 0
    keys = [k.strip() for k in a.sources.split(",")] if a.sources else None
    summaries = run(keys, a.db, None if a.dry_run else a.out, dry_run=a.dry_run)
    failed = [s["source"] for s in summaries if not s["ok"]]
    print("\nSUMMARY")
    for s in summaries:
        flag = "OK " if s["ok"] else "ERR"
        print(f"  {flag} {s['source']:<12} count={s.get('count')} new={s['new']} drop={s['price_drop']} "
              f"up={s['price_up']} removed={s['removed']} returned={s['returned']} rejected={s['rejected']}"
              + (f"  error={s['error']}" if s["error"] else ""))
    # Exit non-zero only if EVERY requested source failed (so one flaky dealer doesn't fail the cron).
    return 1 if summaries and len(failed) == len(summaries) else 0


if __name__ == "__main__":
    sys.exit(main())
