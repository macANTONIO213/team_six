"""Reproduce every number used in the ARGUS pitch from the REPH synthetic data.

    python -m analysis.argus_evidence          (runs core.precompute first if the cache is missing)

Prototype findings on synthetic data (scale 0.2), not validated REPH results.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import data, insights, precompute  # noqa: E402


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> None:
    if not data.cache_path("alert_features.parquet").exists():
        precompute.run()
    data.refresh_views()

    print("\n=== 1. Baseline ===")
    b = insights.baseline()
    print(f"{b['fp']:,} of {b['closed']:,} closed alerts are false positives ({pct(b['fp_rate'])}); {b['total']:,} alerts in total")

    print("\n=== 2. Volume by quarter ===")
    qv = insights.quarterly_volume()
    print(qv.to_string(index=False, formatters={"fp_rate": pct}))

    print("\n=== 3/4. Rules ===")
    rs = insights.rule_stats()
    noisy = rs[rs["rule_id"].isin(["R017", "R023"])]
    print(noisy[["rule_id", "rule_name", "alerts", "fp_rate", "share"]].to_string(index=False))
    print(f"R017 + R023 share of all alerts: {pct(noisy['share'].sum())}")
    print(insights.rule_type_fp().to_string(index=False, formatters={"fp_rate": pct}))

    print("\n=== 5. Legacy score bands (FP rate per band) ===")
    print(insights.score_bands().to_string(index=False, formatters={"fp_rate": pct}))
    card = insights.model_card()
    m = card["metrics"]
    print(f"AUC on {m['test_rows']:,} alerts {m['test_period']}: ARGUS {m['auc_argus']:.3f} vs legacy score {m['auc_legacy_score']:.3f}"
          f" (transaction-only model without rule context: {m['auc_argus_txn_model']:.3f})")
    qa, ql = m["queue_argus"], m["queue_legacy"]
    print(f"90% recall reached after {pct(qa['queue_share_for_target'])} of the ARGUS-ordered queue "
          f"-> {pct(qa['fp_reviews_avoided_share'])} fewer FP reviews ({qa['fp_reviews_avoided']:,}); "
          f"legacy score: {pct(ql['queue_share_for_target'])} -> {pct(ql['fp_reviews_avoided_share'])}")

    print("\n=== 6/7. Hidden network(s) ===")
    for cid in insights.ring_cluster_ids():
        r = insights.ring_summary(cid)
        for k, v in r.items():
            print(f"  {k}: {v}")

    print("\n=== 8. Investigator effort ===")
    e = insights.investigation_effort()
    print(f"{e['n_investigations']:,} investigations; median {e['median_minutes']} hands-on minutes "
          f"({e['median_minutes'] / 60:.1f} h) and {e['median_steps']:.0f} steps")
    print(e["by_action"].to_string(index=False, formatters={"time_share": pct}))
    print(f"Evidence gathering + narrative ({', '.join(e['core_evidence_actions'])}): {pct(e['core_evidence_time_share'])} of time")
    print(f"Total {e['total_hours']:,.0f} h over {e['months']} months = {e['hours_per_year']:,.0f} h/yr")

    print("\n=== 9. AI Investigation Assistant audit ===")
    a = insights.ai_assistant_audit()
    print(f"AI assistant share of actions since {a['cutover']}: {pct(a['ai_action_share_after'])}")
    print(a["before_after"].to_string())

    print("\n=== 10. Ownership exposure (50% rule) ===")
    o = insights.ownership_summary()
    for k, v in o.items():
        print(f"  {k}: {v}")

    print("\n=== 11. Suppliers (raw finance files, cleaned) ===")
    s = insights.supplier_summary()
    for k, v in s.items():
        print(f"  {k}: {v}")

    print("\n=== Lanes (all closed alerts) ===")
    ls = insights.lane_stats()
    print(ls.to_string(index=False, formatters={"fp_rate": pct, "share_alerts": pct, "share_true_hits": pct}))
    print("\n=== Signal lifts ===")
    for k, v in card["lifts"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
