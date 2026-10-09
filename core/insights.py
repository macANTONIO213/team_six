"""Portfolio-level findings computed live from the REPH data (used by the app and
analysis/argus_evidence.py). Aggregate / team-level only: no individual analyst ranking."""
from __future__ import annotations

import json

import pandas as pd

from core import config, data

CORE_EVIDENCE_ACTIONS = ("Pull transaction history", "Screen against watchlists", "Check device & address links", "Draft narrative")


def meta() -> dict:
    p = data.cache_path("precompute_meta.json")
    return json.loads(p.read_text()) if p.exists() else {}


def baseline() -> dict:
    r = data.q("""SELECT count(*) FILTER (WHERE is_false_positive IS NOT NULL) AS closed,
                         count(*) FILTER (WHERE is_false_positive) AS fp, count(*) AS total
                  FROM risk_alerts""").iloc[0]
    return {"closed": int(r.closed), "fp": int(r.fp), "total": int(r.total), "fp_rate": round(r.fp / r.closed, 4)}


def quarterly_volume() -> pd.DataFrame:
    return data.q("""SELECT strftime(date_trunc('quarter', created_at), '%Y') || '-Q' || quarter(created_at) AS quarter,
                            count(*) AS alerts, avg(CASE WHEN is_false_positive THEN 1.0 ELSE 0.0 END) AS fp_rate
                     FROM risk_alerts GROUP BY 1 ORDER BY 1""")


def rule_stats() -> pd.DataFrame:
    return data.q("""SELECT r.rule_id, r.rule_name, r.rule_type, count(*) AS alerts,
                            count(*) * 1.0 / sum(count(*)) OVER () AS share,
                            avg(CASE WHEN a.is_false_positive THEN 1.0 ELSE 0.0 END) FILTER (WHERE a.is_false_positive IS NOT NULL) AS fp_rate,
                            count(*) FILTER (WHERE a.is_false_positive = false) AS true_hits
                     FROM risk_alerts a JOIN alert_rules r USING (rule_id)
                     GROUP BY ALL ORDER BY alerts DESC""")


def rule_type_fp() -> pd.DataFrame:
    return data.q("""SELECT r.rule_type, count(*) AS alerts,
                            avg(CASE WHEN a.is_false_positive THEN 1.0 ELSE 0.0 END) FILTER (WHERE a.is_false_positive IS NOT NULL) AS fp_rate
                     FROM risk_alerts a JOIN alert_rules r USING (rule_id) GROUP BY 1 ORDER BY 1""")


def score_bands() -> pd.DataFrame:
    return data.q("""SELECT floor(score * 10) / 10 AS band, count(*) AS alerts,
                            avg(CASE WHEN is_false_positive THEN 1.0 ELSE 0.0 END) AS fp_rate
                     FROM risk_alerts WHERE is_false_positive IS NOT NULL GROUP BY 1 ORDER BY 1""")


def lane_stats() -> pd.DataFrame:
    df = data.q("""SELECT lane, count(*) AS alerts, sum(y) AS true_hits, avg(1 - y) AS fp_rate
                   FROM alert_features WHERE y IS NOT NULL GROUP BY 1""")
    df["share_alerts"] = df["alerts"] / df["alerts"].sum()
    df["share_true_hits"] = df["true_hits"] / df["true_hits"].sum()
    order = {"HOT": 0, "PRIORITY": 1, "STANDARD": 2, "NOISE": 3}
    return df.sort_values("lane", key=lambda s: s.map(order)).reset_index(drop=True)


def ring_cluster_ids(min_size: int | None = None) -> list[str]:
    m = min_size or config.RING_MIN_SIZE
    return data.q("SELECT DISTINCT cluster_id FROM identity_clusters WHERE cluster_size >= ? ORDER BY 1", [m])["cluster_id"].tolist()


def ring_summary(cluster_id: str) -> dict:
    members = data.q("""SELECT c.individual_id, i.occupation, i.created_at FROM identity_clusters c
                        JOIN individuals i USING (individual_id) WHERE c.cluster_id = ? ORDER BY 1""", [cluster_id])
    ids = members["individual_id"].tolist()
    if not ids:
        return {}
    accts = data.q("SELECT account_id, risk_rating FROM accounts WHERE individual_id IN (SELECT unnest(?))", [ids])
    acc_ids = accts["account_id"].tolist()
    tx = data.q("""SELECT txn_id, account_id, counterparty_account_id, amount_usd, txn_ts, hour(txn_ts) AS hr
                   FROM transactions WHERE account_id IN (SELECT unnest(?))""", [acc_ids])
    alerts = data.q("""SELECT alert_id, rule_id, analyst_employee_id, is_false_positive, created_at
                       FROM risk_alerts WHERE account_id IN (SELECT unnest(?))""", [acc_ids])
    inv = data.q("""SELECT i.investigation_id, i.outcome, sum(a.duration_min) AS minutes
                    FROM investigations i LEFT JOIN analyst_actions a USING (investigation_id)
                    WHERE i.alert_id IN (SELECT unnest(?)) GROUP BY 1, 2""", [alerts["alert_id"].tolist() or [""]])
    links = data.q("""SELECT link_type, count(DISTINCT link_value) AS n_values, max(n_members) AS max_members
                      FROM identity_links WHERE individual_id IN (SELECT unnest(?)) GROUP BY 1""", [ids])
    wl = data.q("""SELECT individual_id, list_type, min(listed_date) AS listed_date, min(watchlist_entry_id) AS entry
                   FROM watchlists WHERE individual_id IN (SELECT unnest(?)) GROUP BY 1, 2""", [ids])
    total = float(tx["amount_usd"].sum())
    member_flow = float(tx.loc[tx["counterparty_account_id"].isin(acc_ids), "amount_usd"].sum())
    first_alert = pd.to_datetime(alerts["created_at"]).min() if len(alerts) else None
    after = float(tx.loc[pd.to_datetime(tx["txn_ts"]) >= first_alert, "amount_usd"].sum()) if first_alert is not None else 0.0
    return {
        "cluster_id": cluster_id,
        "members": ids,
        "n_members": len(ids),
        "occupations": members["occupation"].value_counts().to_dict(),
        "onboarded_from": str(pd.to_datetime(members["created_at"]).min().date()),
        "onboarded_to": str(pd.to_datetime(members["created_at"]).max().date()),
        "shared_links": {r.link_type: {"values": int(r.n_values), "max_members": int(r.max_members)} for r in links.itertuples()},
        "n_accounts": len(acc_ids),
        "account_risk_ratings": accts["risk_rating"].value_counts().to_dict(),
        "n_txns": int(len(tx)),
        "total_usd": round(total, 2),
        "member_flow_share": round(member_flow / total, 4) if total else 0,
        "near_10k_txns": int(tx["amount_usd"].between(9000, 9999.99).sum()),
        "night_txns": int(tx["hr"].between(0, 5).sum()),
        "watchlist": wl.assign(listed_date=wl["listed_date"].astype(str)).to_dict("records"),
        "n_alerts": int(len(alerts)),
        "n_rules": int(alerts["rule_id"].nunique()),
        "n_analysts": int(alerts["analyst_employee_id"].nunique()),
        "closed_fp": int((alerts["is_false_positive"] == True).sum()),  # noqa: E712
        "n_investigations": int(len(inv)),
        "investigation_hours": round(float(inv["minutes"].fillna(0).sum()) / 60, 1),
        "nfa_investigations": int((inv["outcome"] == "No further action").sum()),
        "first_alert": str(first_alert.date()) if first_alert is not None else None,
        "share_usd_after_first_alert": round(after / total, 4) if total else 0,
    }


def investigation_effort() -> dict:
    per = data.q("""SELECT investigation_id, sum(duration_min) AS minutes, count(*) AS steps, count(DISTINCT tool_used) AS tools
                    FROM analyst_actions GROUP BY 1""")
    by_action = data.q("""SELECT action_type, sum(duration_min) AS minutes, count(*) AS n,
                                 count(*) * 1.0 / count(DISTINCT investigation_id) AS per_case
                          FROM analyst_actions GROUP BY 1 ORDER BY minutes DESC""")
    by_action["time_share"] = by_action["minutes"] / by_action["minutes"].sum()
    core_share = float(by_action.loc[by_action["action_type"].isin(CORE_EVIDENCE_ACTIONS), "time_share"].sum())
    months = data.scalar("SELECT date_diff('month', min(action_ts), max(action_ts)) + 1 FROM analyst_actions")
    total_h = float(per["minutes"].sum()) / 60
    return {
        "n_investigations": int(len(per)),
        "median_minutes": round(float(per["minutes"].median()), 1),
        "median_steps": float(per["steps"].median()),
        "by_action": by_action,
        "core_evidence_actions": list(CORE_EVIDENCE_ACTIONS),
        "core_evidence_time_share": round(core_share, 4),
        "total_hours": round(total_h, 0),
        "months": int(months),
        "hours_per_year": round(total_h / months * 12, 0),
    }


def ai_assistant_audit(cutover: str = "2025-07-01") -> dict:
    share = data.q("""SELECT avg(CASE WHEN tool_used = 'AI Investigation Assistant' THEN 1.0 ELSE 0.0 END) AS ai_share
                      FROM analyst_actions WHERE action_ts >= ?""", [cutover]).iloc[0, 0]
    df = data.q("""SELECT i.investigation_id, i.opened_at >= CAST(? AS TIMESTAMP) AS after, i.time_to_decision_hours AS ttd,
                          sum(a.duration_min) AS minutes, count(DISTINCT a.tool_used) AS tools
                   FROM investigations i JOIN analyst_actions a USING (investigation_id)
                   WHERE i.closed_at IS NOT NULL GROUP BY 1, 2, 3""", [cutover])
    g = df.groupby("after").agg(n=("investigation_id", "count"), ttd_mean=("ttd", "mean"), ttd_median=("ttd", "median"),
                                minutes_median=("minutes", "median"), minutes_mean=("minutes", "mean"), tools_mean=("tools", "mean"))
    return {"cutover": cutover, "ai_action_share_after": round(float(share), 4), "before_after": g.round(1)}


def ownership_summary() -> dict:
    own = data.q("SELECT * FROM ownership_exposure WHERE flag_50 AND NOT is_sanctions_listed_itself")
    acc = data.q("SELECT entity_id, account_id FROM accounts WHERE entity_id IN (SELECT unnest(?))", [own["entity_id"].tolist() or [""]])
    alerts = data.q("SELECT alert_id, is_false_positive FROM risk_alerts WHERE account_id IN (SELECT unnest(?))", [acc["account_id"].tolist() or [""]])
    m = meta().get("ownership", {})
    return {
        "n_entities_ge50": int(len(own)),
        "n_with_accounts": int(acc["entity_id"].nunique()),
        "n_accounts": int(len(acc)),
        "n_alerts": int(len(alerts)),
        "alerts_closed_fp": int((alerts["is_false_positive"] == True).sum()),  # noqa: E712
        "mutual_pairs": m.get("mutual_pairs", []),
        "largest_cyclic_block": m.get("largest_cyclic_block"),
        "n_sanctioned_roots": m.get("n_sanctioned_roots"),
    }


def supplier_summary() -> dict:
    exp = data.q("SELECT * FROM supplier_exposure")
    listed = exp[exp["exposure"] == "Sanctions-listed"]
    m = meta().get("cleaning", {})
    return {
        "n_sanctions_listed": int(len(listed)),
        "n_listed_rated_low": int((listed["risk_tier"] == "Low").sum()),
        "n_owned_ge50": int((exp["exposure"] != "Sanctions-listed").sum()),
        "paid_after_usd": round(float(listed["paid_after_usd"].sum()), 2),
        "pending_after_usd": round(float(listed["pending_after_usd"].sum()), 2),
        "pending_invoices": int(listed["pending_invoices"].sum()),
        "all_exposed_paid_after_usd": round(float(exp["paid_after_usd"].sum()), 2),
        "all_exposed_pending_after_usd": round(float(exp["pending_after_usd"].sum()), 2),
        "cleaning": m,
    }


def model_card() -> dict:
    import joblib

    b = joblib.load(data.cache_path("triage_model.joblib"))
    return {k: v for k, v in b.items() if k not in ("model", "txn_model")}
