"""Triage scoring. Alerts use the ML model trained on 2024-25 analyst decisions
(scores are precomputed; 2026 scores are out-of-time). New transactions have no
rule context, where the ML has no lift (AUC 0.50), so ARGUS scores them with
transparent network-signal likelihood ratios learned from the same decisions."""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pandas as pd

from core import config, data, precompute

CHANNELS = ["Mobile wallet", "Online transfer", "Card", "Wire", "ATM", "Branch"]
MERCHANTS = ["(none)", "Crypto exchange", "Dining", "Electronics", "Fuel", "Gaming", "Groceries", "Online marketplace", "Travel"]
CURRENCIES = ["USD", "PHP", "EUR", "GBP", "JPY"]


@lru_cache(maxsize=1)
def bundle() -> dict:
    import joblib

    return joblib.load(data.cache_path("triage_model.joblib"))


@lru_cache(maxsize=1)
def likelihood_ratios() -> dict:
    """LR = P(signal | real hit) / P(signal | false positive), Laplace-smoothed, from closed alerts."""
    df = data.q("SELECT y, " + ", ".join(f"sig_{k}" for k in precompute.SIGNALS) + " FROM alert_features WHERE y IS NOT NULL")
    pos, neg = df[df["y"] == 1], df[df["y"] == 0]
    out = {}
    for k in precompute.SIGNALS:
        c = f"sig_{k}"
        p1 = (pos[c].sum() + 0.5) / (len(pos) + 1)
        p0 = (neg[c].sum() + 0.5) / (len(neg) + 1)
        out[k] = round(float(p1 / p0), 3)
    out["_prior"] = float(df["y"].mean())
    return out


@lru_cache(maxsize=1)
def fx_rates() -> dict:
    df = data.q("SELECT currency, median(amount_usd / amount) AS usd_per_unit FROM transactions WHERE amount > 0 GROUP BY 1")
    return dict(zip(df["currency"], df["usd_per_unit"].astype(float)))


def alert_row(alert_id: str) -> dict | None:
    df = data.q("SELECT * FROM alert_features WHERE alert_id = ?", [alert_id])
    return None if df.empty else df.iloc[0].to_dict()


def txn_features(t: dict) -> tuple[pd.DataFrame, list[str]]:
    """Feature row for a new transaction, computed as of its timestamp from live data."""
    notes: list[str] = []
    ts = pd.Timestamp(t.get("timestamp") or config.AS_OF)
    amount = float(t["amount"])
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    cur = (t.get("currency") or "USD").upper()
    rate = fx_rates().get(cur)
    if rate is None:
        raise ValueError(f"Unsupported currency {cur}. Use one of {', '.join(sorted(fx_rates()))}.")
    amount_usd = amount * rate
    acc = data.q("SELECT * FROM accounts WHERE account_id = ?", [str(t["account_id"]).strip().upper()])
    if acc.empty:
        notes.append("Account not found: treated as a brand-new account with no history.")
        acc_row = {"account_id": t["account_id"], "holder_type": None, "individual_id": None, "entity_id": None,
                   "account_type": None, "risk_rating": None, "opened_at": ts}
    else:
        acc_row = acc.iloc[0].to_dict()
    ind, ent = acc_row.get("individual_id"), acc_row.get("entity_id")
    cp_id = (t.get("counterparty_account_id") or "").strip().upper() or None
    cp = data.q("SELECT individual_id, entity_id FROM accounts WHERE account_id = ?", [cp_id]) if cp_id else pd.DataFrame()
    if cp_id and cp.empty:
        notes.append(f"Counterparty {cp_id} not found: no network history.")
    cp_ind = cp.iloc[0]["individual_id"] if len(cp) else None
    cp_ent = cp.iloc[0]["entity_id"] if len(cp) else None
    fp = (t.get("device_fingerprint") or "").strip().lower() or None

    holder_fp = data.scalar("""SELECT count(DISTINCT d2.individual_id) FROM devices d1
                               JOIN devices d2 ON d2.device_fingerprint = d1.device_fingerprint AND d2.first_seen_at <= ?
                               WHERE d1.individual_id = ? AND d1.first_seen_at <= ?""", [ts, ind, ts]) if ind else 0
    txn_fp = data.scalar("SELECT count(DISTINCT individual_id) FROM devices WHERE device_fingerprint = ? AND first_seen_at <= ?", [fp, ts]) if fp else 0
    if fp and not txn_fp:
        notes.append("Device fingerprint never seen before: no device history.")
    cl = data.q("SELECT individual_id, cluster_id, cluster_size FROM identity_clusters WHERE individual_id IN (SELECT unnest(?))",
                [[x for x in (ind, cp_ind) if x] or ["__none__"]]).set_index("individual_id")
    cluster_size = int(cl.loc[ind, "cluster_size"]) if ind in cl.index else 1
    cp_same = int(ind in cl.index and cp_ind in cl.index and cl.loc[ind, "cluster_id"] == cl.loc[cp_ind, "cluster_id"])
    nominee = data.scalar("""SELECT count(*) FROM ownership_links WHERE link_type = 'Nominee' AND effective_date <= ?
                             AND (parent_entity_id = ? OR child_entity_id = ?)""", [ts, ent, ent]) if ent else 0
    wl = data.q("""SELECT list_type FROM watchlists WHERE coalesce(individual_id, entity_id) = ? AND listed_date < ?""",
                [ind or ent or "__none__", ts])
    cp_wl = data.scalar("SELECT count(*) FROM watchlists WHERE coalesce(individual_id, entity_id) = ? AND listed_date < ?",
                        [cp_ind or cp_ent or "__none__", ts])
    own = data.q("SELECT eff_share, root_listed_date FROM ownership_exposure WHERE entity_id = ? AND NOT is_sanctions_listed_itself", [ent or "__none__"])
    owner_eff = float(own.iloc[0]["eff_share"]) if len(own) and pd.Timestamp(own.iloc[0]["root_listed_date"]) < ts else 0.0
    prior = data.q("""SELECT count(*) AS n, count(*) FILTER (WHERE is_false_positive = false) AS t FROM risk_alerts
                      WHERE account_id = ? AND closed_at < ?""", [acc_row["account_id"], ts]).iloc[0]
    if ind is None and ent is None:
        notes.append("No network history: no linked identities, devices, owners or prior alerts.")
    elif holder_fp <= 1 and cluster_size <= 1 and not cp_same:
        notes.append("No shared identifiers found for this holder.")

    merchant = t.get("merchant_category")
    row = {
        "rule_id": None, "rule_type": None, "channel": t.get("channel"),
        "merchant_category": None if merchant in (None, "", "(none)") else merchant,
        "account_type": acc_row.get("account_type"), "risk_rating": acc_row.get("risk_rating"), "holder_type": acc_row.get("holder_type"),
        "amount": amount, "amount_usd": amount_usd, "log_amount_usd": math.log1p(amount_usd), "txn_hour": ts.hour,
        "account_age_days": max(0, (ts - pd.Timestamp(acc_row.get("opened_at") or ts)).days),
        "is_cross_border": int(bool(t.get("is_cross_border"))), "night": int(0 <= ts.hour <= 5),
        "near_10k": int(9000 <= amount_usd < 10000), "round_amount": int(amount % 1000 == 0),
        "holder_fp_identities": int(holder_fp or 0), "txn_fp_identities": int(txn_fp or 0), "cluster_size": cluster_size,
        "cp_same_cluster": cp_same, "nominee_links": int(nominee or 0),
        "wl_sanctions": int((wl["list_type"] == "Sanctions-like").any()), "wl_pep": int((wl["list_type"] == "PEP-like").any()),
        "wl_adverse": int((wl["list_type"] == "Adverse media-like").any()), "wl_law": int((wl["list_type"] == "Law enforcement-like").any()),
        "wl_hits": int(len(wl)), "cp_watchlisted": int((cp_wl or 0) > 0), "owner_sanctioned_eff": owner_eff,
        "prior_alerts": int(prior["n"]), "prior_true": int(prior["t"] or 0),
        "individual_id": ind, "entity_id": ent, "cp_individual_id": cp_ind, "account_id": acc_row["account_id"],
        "counterparty_account_id": cp_id, "device_fingerprint": fp, "timestamp": ts,
    }
    df = pd.DataFrame([row])
    precompute.add_signals(df)
    return df, notes


def score_new_transaction(t: dict) -> dict:
    df, notes = txn_features(t)
    row = df.iloc[0].to_dict()
    lr = likelihood_ratios()
    prior = lr["_prior"]
    odds = prior / (1 - prior)
    fired = [k for k in precompute.SIGNALS if int(row.get(f"sig_{k}", 0)) == 1]
    for k in fired:
        odds *= lr[k]
    p = odds / (1 + odds)
    lane = precompute.assign_lanes(df).iloc[0]
    sanctions = bool(row["wl_sanctions"]) or row["owner_sanctioned_eff"] >= 0.5
    if sanctions:
        level = "Critical"
    elif p >= 0.6 or (lane == "HOT" and p >= 0.4):
        level = "High"
    elif p >= 0.3:
        level = "Medium"
    else:
        level = "Low"
    reasons = [{"code": k, "label": precompute.SIGNALS[k], "likelihood_ratio": lr[k]} for k in fired]
    reasons.sort(key=lambda r: -r["likelihood_ratio"])
    if sanctions:
        notes.append("Sanctions exposure always requires compliance review, whatever the score.")
    return {"probability": round(p, 4), "prior": round(prior, 4), "risk_level": level, "lane": lane,
            "reasons": reasons, "notes": notes, "features": {k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in row.items()},
            "method": "Naive-Bayes combination of likelihood ratios learned from 29,982 analyst decisions (transparent; no demographics)."}


def lane_order() -> dict:
    return {"HOT": 0, "PRIORITY": 1, "STANDARD": 2, "NOISE": 3}


def queue(lanes: list[str] | None = None, start: str = config.TRAIN_CUTOFF, only_open: bool = False, rule: str | None = None,
          limit: int = 300) -> pd.DataFrame:
    where = ["created_at >= ?"]
    params: list = [start]
    if lanes:
        where.append("lane IN (SELECT unnest(?))")
        params.append(lanes)
    if only_open:
        where.append("y IS NULL")
    if rule:
        where.append("rule_id = ?")
        params.append(rule)
    # Within a lane: strength of network/risk evidence first (count of fired signals), then the ML score.
    # The ML learns from past decisions, which closed most ring alerts as false positives, so it cannot rank them alone.
    signals = " + ".join(f"sig_{k}" for k in precompute.SIGNALS if k != "model_rule")
    sql = f"""SELECT alert_id, lane, ({signals}) AS signals, argus_score, argus_pct, legacy_score, rule_id, rule_name, created_at,
                     account_id, amount_usd, channel, reasons, disposition, cluster_id
              FROM alert_features WHERE {' AND '.join(where)}
              ORDER BY CASE lane WHEN 'HOT' THEN 0 WHEN 'PRIORITY' THEN 1 WHEN 'STANDARD' THEN 2 ELSE 3 END, signals DESC, argus_score DESC
              LIMIT {int(limit)}"""
    return data.q(sql, params)


def network_alerts_for(alert_id: str) -> list[str]:
    """Alerts on accounts held by the same identity network (for consolidation)."""
    r = alert_row(alert_id)
    if not r or not isinstance(r.get("cluster_id"), str):
        return [alert_id]
    df = data.q("SELECT alert_id FROM alert_features WHERE cluster_id = ? ORDER BY created_at", [r["cluster_id"]])
    return df["alert_id"].tolist()


def np_safe(x):
    return x.item() if isinstance(x, np.generic) else x
