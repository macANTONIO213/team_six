"""Ownership traversal on a synthetic graph: effective %, 4-hop cap, 10% floor, and loop safety."""
import pandas as pd

from core import data, precompute

LINKS = pd.DataFrame(
    [
        ("O1", "S", "A", 90.0, "Direct"),   # S (sanctioned) -> A 90%
        ("O2", "A", "B", 80.0, "Direct"),   # -> B 72%
        ("O3", "B", "C", 90.0, "Nominee"),  # -> C 64.8%
        ("O4", "C", "D", 90.0, "Direct"),   # -> D 58.3% (4 hops)
        ("O5", "D", "E", 99.0, "Direct"),   # 5th hop: beyond the cap
        ("O6", "B", "A", 50.0, "Direct"),   # loop A <-> B
        ("O7", "S", "F", 5.0, "Direct"),    # below the 10% floor
    ],
    columns=["ownership_link_id", "parent_entity_id", "child_entity_id", "ownership_pct", "link_type"],
)
ROOTS = pd.DataFrame([("S", pd.Timestamp("2020-01-01"), "WL000001")], columns=["entity_id", "listed_date", "watchlist_entry_id"])


def fake_q(sql, params=None):
    if "FROM ownership_links" in sql:
        return LINKS.copy()
    if "list_type = 'Sanctions-like'" in sql:
        return ROOTS.copy()
    return pd.DataFrame({"entity_id": ["S"]})


def test_effective_share_hops_and_loops(monkeypatch):
    monkeypatch.setattr(data, "q", fake_q)
    out, stats = precompute.build_ownership_exposure()
    eff = out.set_index("entity_id")["eff_share"].to_dict()
    assert abs(eff["A"] - 0.90) < 1e-9
    assert abs(eff["B"] - 0.72) < 1e-9
    assert abs(eff["D"] - 0.90 * 0.80 * 0.90 * 0.90) < 1e-4
    assert "E" not in eff, "5th hop must not be reached"
    assert "F" not in eff, "paths below 10% are dropped"
    assert "S" not in eff, "the walk never returns to the sanctioned root"
    d = out.set_index("entity_id").loc["D"]
    assert d["hops"] == 4 and d["path"] == "S > A > B > C > D" and bool(d["flag_50"])
    assert stats["n_mutual_pairs"] == 1 and stats["mutual_pairs"] == [["A", "B"]]
