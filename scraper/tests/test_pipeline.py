import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from highland.db import Store
from highland.models import RawListing, SourceResult
from highland.pipeline import run_source, export
from highland.sources.base import Source


class Fake(Source):
    key = "fake"
    label = "Fake"
    kind = "local"
    homepage = "https://example.com"

    def __init__(self, listings, ok=True):
        self._l = listings
        self._ok = ok

    def fetch(self):
        return SourceResult(source="fake", listings=self._l, ok=self._ok, error=None if self._ok else "boom")


def L(vin, price, year=2024, mileage=10000, trim="Long Range All-Wheel Drive"):
    return RawListing(source="fake", source_id=vin[-6:], url=f"https://example.com/{vin}", vin=vin, year=year,
                      price=price, mileage=mileage, trim_raw=trim, city="Houston", state="TX", zip="77002")


V1 = "5YJ3E1EB1RF000001"
V2 = "5YJ3E1EB2RF000002"
V3 = "5YJ3E1EA3PF000003"  # 2023 -> rejected


def test_lifecycle(tmp_path):
    store = Store(":memory:")
    s = run_source(store, Fake([L(V1, 40000), L(V2, 41000), L(V3, 30000, year=2023)]), "2026-09-01T00:00:00+00:00")
    assert s["ok"] and s["new"] == 2 and s["rejected"] == 1
    # price drop + removal
    s = run_source(store, Fake([L(V1, 39000)]), "2026-09-02T00:00:00+00:00")
    assert s["price_drop"] == 1 and s["removed"] == 1
    row = store.get_listing("fake", V1)
    assert row["price"] == 39000 and row["status"] == "active"
    assert store.get_listing("fake", V2)["status"] == "removed"
    assert store.price_history(row["id"]) == [
        {"at": "2026-09-01T00:00:00+00:00", "price": 40000},
        {"at": "2026-09-02T00:00:00+00:00", "price": 39000},
    ]
    # returned
    s = run_source(store, Fake([L(V1, 39000), L(V2, 41000)]), "2026-09-03T00:00:00+00:00")
    assert s["returned"] == 1 and s["kept"] == 1
    # failed run must not remove anything
    s = run_source(store, Fake([], ok=False), "2026-09-04T00:00:00+00:00")
    assert not s["ok"] and store.get_listing("fake", V1)["status"] == "active"
    # a third car so the zero-result guard applies (threshold 3)
    V4 = "5YJ3E1EC4RF000004"
    run_source(store, Fake([L(V1, 39000), L(V2, 41000), L(V4, 45000, trim="Performance")]), "2026-09-04T12:00:00+00:00")
    # suspicious zero result must not remove anything...
    s = run_source(store, Fake([]), "2026-09-05T00:00:00+00:00")
    assert not s["ok"] and store.get_listing("fake", V2)["status"] == "active"
    s = run_source(store, Fake([]), "2026-09-06T00:00:00+00:00")
    assert not s["ok"] and store.get_listing("fake", V2)["status"] == "active"
    # ...until it has happened 3 runs in a row, then we believe it
    s = run_source(store, Fake([]), "2026-09-07T00:00:00+00:00")
    assert not s["ok"]
    s = run_source(store, Fake([]), "2026-09-08T00:00:00+00:00")
    assert s["ok"] and s["removed"] == 3 and store.get_listing("fake", V2)["status"] == "removed"
    # bring two back for the export assertions below
    run_source(store, Fake([L(V1, 39000), L(V2, 41000)]), "2026-09-09T00:00:00+00:00")
    out = tmp_path / "latest.json"
    payload = export(store, {"fake": Fake}, str(out), "2026-09-05T00:00:00+00:00")
    assert payload["stats"]["active"] == 2
    l1 = next(l for l in payload["listings"] if l["vin"] == V1)
    assert l1["trim"] == "Long Range AWD" and l1["msrp"] == 47490 and l1["distance_mi"] is not None
    assert l1["effective_price"] == 39000
    kinds = [c["kind"] for c in payload["changes"]]
    assert "price_drop" in kinds and "removed" in kinds and "returned" in kinds and "new" in kinds
