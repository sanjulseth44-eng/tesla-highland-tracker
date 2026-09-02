"""SQLite persistence. One row per (source, vin); price history and change log alongside.

Tables
  listings       current state of every listing ever seen (status active|removed)
  price_history  every observed price change (first observation included)
  changes        dashboard change log: new / price_drop / price_up / removed / returned
  runs           one row per source per run (for the "sources" health panel)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  vin TEXT NOT NULL,
  source_id TEXT,
  url TEXT NOT NULL,
  year INTEGER NOT NULL,
  trim TEXT NOT NULL,
  trim_raw TEXT,
  trim_confidence TEXT,
  mileage INTEGER,
  price INTEGER NOT NULL,
  msrp INTEGER,
  dealer TEXT, city TEXT, state TEXT, zip TEXT,
  lat REAL, lng REAL,
  distance_mi REAL,
  shipping_cost REAL,
  shipping_note TEXT,
  exterior_color TEXT, interior_color TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  removed_at TEXT,
  extra TEXT,
  UNIQUE(source, vin)
);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE TABLE IF NOT EXISTS price_history (
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  price INTEGER NOT NULL,
  observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ph_listing ON price_history(listing_id);
CREATE TABLE IF NOT EXISTS changes (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  kind TEXT NOT NULL,
  old_price INTEGER,
  new_price INTEGER
);
CREATE INDEX IF NOT EXISTS idx_changes_at ON changes(at);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  ok INTEGER NOT NULL DEFAULT 0,
  count INTEGER,
  error TEXT,
  notes TEXT
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---- listings ----
    def get_listing(self, source: str, vin: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM listings WHERE source=? AND vin=?", (source, vin)
        ).fetchone()

    def active_by_source(self, source: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM listings WHERE source=? AND status='active'", (source,)
        ).fetchall()

    def insert_listing(self, row: dict[str, Any], now: str) -> int:
        cols = dict(row)
        cols["extra"] = json.dumps(cols.get("extra") or {}, sort_keys=True)
        cols["first_seen"] = now
        cols["last_seen"] = now
        cols["status"] = "active"
        keys = list(cols)
        cur = self.conn.execute(
            f"INSERT INTO listings ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
            [cols[k] for k in keys],
        )
        lid = int(cur.lastrowid)
        self.conn.execute(
            "INSERT INTO price_history (listing_id, price, observed_at) VALUES (?,?,?)",
            (lid, cols["price"], now),
        )
        self.conn.execute(
            "INSERT INTO changes (at, listing_id, kind, old_price, new_price) VALUES (?,?,?,?,?)",
            (now, lid, "new", None, cols["price"]),
        )
        return lid

    def update_listing(self, existing: sqlite3.Row, row: dict[str, Any], now: str) -> list[str]:
        """Refresh mutable fields; return list of change kinds recorded."""
        kinds: list[str] = []
        lid = existing["id"]
        old_price = existing["price"]
        new_price = row["price"]
        cols = dict(row)
        cols["extra"] = json.dumps(cols.get("extra") or {}, sort_keys=True)
        cols["last_seen"] = now
        cols["status"] = "active"
        cols["removed_at"] = None
        sets = ", ".join(f"{k}=?" for k in cols)
        self.conn.execute(f"UPDATE listings SET {sets} WHERE id=?", [*cols.values(), lid])
        if existing["status"] == "removed":
            self.conn.execute(
                "INSERT INTO changes (at, listing_id, kind, old_price, new_price) VALUES (?,?,?,?,?)",
                (now, lid, "returned", old_price, new_price),
            )
            kinds.append("returned")
        if new_price != old_price:
            self.conn.execute(
                "INSERT INTO price_history (listing_id, price, observed_at) VALUES (?,?,?)",
                (lid, new_price, now),
            )
            kind = "price_drop" if new_price < old_price else "price_up"
            self.conn.execute(
                "INSERT INTO changes (at, listing_id, kind, old_price, new_price) VALUES (?,?,?,?,?)",
                (now, lid, kind, old_price, new_price),
            )
            kinds.append(kind)
        return kinds

    def mark_removed(self, listing_ids: Iterable[int], now: str) -> int:
        n = 0
        for lid in listing_ids:
            self.conn.execute(
                "UPDATE listings SET status='removed', removed_at=? WHERE id=? AND status='active'", (now, lid)
            )
            price = self.conn.execute("SELECT price FROM listings WHERE id=?", (lid,)).fetchone()[0]
            self.conn.execute(
                "INSERT INTO changes (at, listing_id, kind, old_price, new_price) VALUES (?,?,?,?,?)",
                (now, lid, "removed", price, None),
            )
            n += 1
        return n

    # ---- runs ----
    def start_run(self, source: str, now: str) -> int:
        cur = self.conn.execute("INSERT INTO runs (source, started_at) VALUES (?,?)", (source, now))
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, ok: bool, count: Optional[int], error: Optional[str], notes: list[str]) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, ok=?, count=?, error=?, notes=? WHERE id=?",
            (utcnow(), 1 if ok else 0, count, error, json.dumps(notes), run_id),
        )

    def consecutive_zero_runs(self, source: str) -> int:
        """How many of the most recent runs for this source (before the current one) returned 0."""
        n = 0
        for r in self.conn.execute(
            "SELECT count, finished_at FROM runs WHERE source=? AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 10",
            (source,),
        ):
            if r["count"] == 0:
                n += 1
            else:
                break
        return n

    def last_runs(self) -> dict[str, dict[str, Any]]:
        """Latest run per source plus the latest *successful* run per source."""
        out: dict[str, dict[str, Any]] = {}
        for r in self.conn.execute(
            "SELECT * FROM runs WHERE id IN (SELECT MAX(id) FROM runs GROUP BY source)"
        ):
            out[r["source"]] = {
                "last_run_at": r["started_at"],
                "ok": bool(r["ok"]),
                "count": r["count"],
                "error": r["error"],
                "notes": json.loads(r["notes"] or "[]"),
            }
        for r in self.conn.execute(
            "SELECT * FROM runs WHERE ok=1 AND id IN (SELECT MAX(id) FROM runs WHERE ok=1 GROUP BY source)"
        ):
            out.setdefault(r["source"], {})["last_ok_at"] = r["started_at"]
        return out

    # ---- export helpers ----
    def price_history(self, listing_id: int) -> list[dict[str, Any]]:
        return [
            {"at": r["observed_at"], "price": r["price"]}
            for r in self.conn.execute(
                "SELECT price, observed_at FROM price_history WHERE listing_id=? ORDER BY id", (listing_id,)
            )
        ]

    def listings_for_export(self, since_iso: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM listings WHERE status='active' OR (status='removed' AND removed_at>=?) "
            "ORDER BY year DESC, trim, price",
            (since_iso,),
        ).fetchall()

    def changes_since(self, since_iso: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT c.*, l.vin, l.source, l.year, l.trim, l.mileage, l.dealer, l.city, l.state, l.url, "
            "l.distance_mi, l.shipping_cost, l.price AS current_price "
            "FROM changes c JOIN listings l ON l.id=c.listing_id WHERE c.at>=? ORDER BY c.id DESC",
            (since_iso,),
        ).fetchall()

    def commit(self) -> None:
        self.conn.commit()
