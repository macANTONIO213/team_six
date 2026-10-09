"""Evidence pack builder: everything ARGUS knows about a subject as JSON-serialisable
facts keyed by record IDs. No names, dates of birth, demographics or staff IDs go
into the pack (the UI re-attaches display names locally)."""
from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np
import pandas as pd

from core import config, data

MAX_TXN_SAMPLE = 15
MAX_LIST = 25


def _v(x):
    if x is None:
        return None
    if isinstance(x, (pd.Timestamp, datetime)):
        return None if pd.isna(x) else x.strftime("%Y-%m-%d %H:%M") if (x.hour or x.minute) else x.strftime("%Y-%m-%d")
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if math.isnan(x) else round(float(x), 4)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if x is pd.NaT:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return x


def _records(df: pd.DataFrame, limit: int | None = None) -> list[dict]:
    if limit is not None:
        df = df.head(limit)
    return [{k: _v(v) for k, v in row.items()} for row in df.to_dict("records")]


def _in(ids) -> list:
    ids = [i for i in ids if i]
    return ids or ["__none__"]


# --------------------------------------------------------------------------- building blocks
def network_block(individual_ids: list[str]) -> dict:
    cl = data.q("SELECT * FROM identity_clusters WHERE individual_id IN (SELECT unnest(?))", [_in(individual_ids)])
    members = set(individual_ids)
    cluster_id, cluster_size = None, 1
    if len(cl):
        top = cl.sort_values("cluster_size", ascending=False).iloc[0]
        cluster_id, cluster_size = str(top["cluster_id"]), int(top["cluster_size"])
        if cluster_size <= 60:
            members |= set(data.q("SELECT individual_id FROM identity_clusters WHERE cluster_id = ?", [cluster_id])["individual_id"])
    members = sorted(members)
    ind = data.q("SELECT individual_id, created_at FROM individuals WHERE individual_id IN (SELECT unnest(?))", [_in(members)])
    links = data.q("""SELECT link_type, link_value, individual_id, n_members FROM identity_links
                      WHERE individual_id IN (SELECT unnest(?))""", [_in(members)])
    addr = data.q("""SELECT address_id, individual_id, country,
                            lower(trim(address_line)) || ' | ' || coalesce(CAST(postal_code AS VARCHAR), '') AS lv
                     FROM addresses WHERE individual_id IN (SELECT unnest(?))""", [_in(members)])
    shared = []
    for (lt, lv), g in links.groupby(["link_type", "link_value"], sort=True):
        entry = {"type": lt, "members": sorted(g["individual_id"].unique().tolist()), "n_identities": int(g["n_members"].max())}
        if lt == "address":
            a = addr[addr["lv"] == lv]
            entry["address_ids"] = sorted(a["address_id"].tolist())[:MAX_LIST]
            entry["country"] = a["country"].iloc[0] if len(a) else None
        else:
            entry["value"] = lv
        shared.append(entry)
    shared.sort(key=lambda e: -e["n_identities"])
    return {
        "cluster_id": cluster_id, "cluster_size": cluster_size,
        "is_network": cluster_size >= config.RING_MIN_SIZE,
        "members": members,
        "onboarded": {r["individual_id"]: _v(pd.Timestamp(r["created_at"]).date()) for r in ind.to_dict("records")},
        "shared_links": shared,
    }


def accounts_block(where: str, ids: list[str]) -> list[dict]:
    df = data.q(f"""SELECT account_id, holder_type, individual_id, entity_id, account_type, currency, risk_rating, status,
                           CAST(opened_at AS DATE) AS opened
                    FROM accounts WHERE {where} IN (SELECT unnest(?)) ORDER BY account_id""", [_in(ids)])
    return _records(df)


def transactions_block(account_ids: list[str], member_accounts: set[str] | None = None) -> dict:
    tx = data.q("""SELECT t.txn_id, t.account_id, t.counterparty_account_id, t.amount_usd, t.channel, t.merchant_category,
                          t.is_cross_border, t.txn_ts, d.device_fingerprint
                   FROM transactions t LEFT JOIN devices d ON d.device_id = t.device_id
                   WHERE t.account_id IN (SELECT unnest(?)) ORDER BY t.txn_ts""", [_in(account_ids)])
    if tx.empty:
        return {"count": 0}
    members = member_accounts or set(account_ids)
    tx["member_flow"] = tx["counterparty_account_id"].isin(members)
    tx["hour"] = pd.to_datetime(tx["txn_ts"]).dt.hour
    tx["near_10k"] = tx["amount_usd"].between(9000, 9999.99)
    tx["night"] = tx["hour"].between(0, 5)
    total = float(tx["amount_usd"].sum())
    flagged = tx[tx["member_flow"] | tx["near_10k"] | tx["night"]]
    sample = pd.concat([flagged.sort_values("amount_usd", ascending=False).head(8), tx.tail(7)]).drop_duplicates("txn_id")
    sample = sample.sort_values("txn_ts").head(MAX_TXN_SAMPLE)
    return {
        "count": int(len(tx)), "total_usd": round(total, 2),
        "member_flow_usd": round(float(tx.loc[tx["member_flow"], "amount_usd"].sum()), 2),
        "member_flow_share": round(float(tx.loc[tx["member_flow"], "amount_usd"].sum()) / total, 4) if total else 0,
        "near_10k_count": int(tx["near_10k"].sum()), "night_count": int(tx["night"].sum()),
        "cross_border_count": int(tx["is_cross_border"].fillna(False).astype(bool).sum()),
        "first": _v(pd.Timestamp(tx["txn_ts"].min())), "last": _v(pd.Timestamp(tx["txn_ts"].max())),
        "devices_used": sorted(tx["device_fingerprint"].dropna().unique().tolist())[:MAX_LIST],
        "sample": _records(sample[["txn_id", "account_id", "counterparty_account_id", "amount_usd", "channel",
                                   "txn_ts", "device_fingerprint", "member_flow", "near_10k", "night"]]),
    }


def alerts_block(account_ids: list[str], exclude_alert: str | None = None) -> dict:
    al = data.q("""SELECT f.alert_id, f.rule_id, f.created_at, r.is_false_positive, f.disposition, f.lane, f.argus_score,
                          r.analyst_employee_id
                   FROM alert_features f JOIN risk_alerts r USING (alert_id)
                   WHERE f.account_id IN (SELECT unnest(?)) ORDER BY f.created_at""", [_in(account_ids)])
    if al.empty:
        return {"count": 0}
    inv = data.q("""SELECT i.investigation_id, i.alert_id, i.outcome, i.time_to_decision_hours, i.steps_count,
                           (SELECT sum(duration_min) FROM analyst_actions a WHERE a.investigation_id = i.investigation_id) AS minutes
                    FROM investigations i WHERE i.alert_id IN (SELECT unnest(?)) ORDER BY i.opened_at""", [_in(al["alert_id"].tolist())])
    hist = al[al["alert_id"] != exclude_alert]
    return {
        "count": int(len(al)), "rules": hist["rule_id"].value_counts().head(12).to_dict(), "n_rules": int(al["rule_id"].nunique()),
        "closed_false_positive": int((hist["is_false_positive"] == True).sum()),  # noqa: E712
        "closed_true_or_escalated": int((hist["is_false_positive"] == False).sum()),  # noqa: E712
        "open": int(hist["is_false_positive"].isna().sum()),
        "distinct_analysts": int(al["analyst_employee_id"].nunique()),
        "first_alert": _v(pd.Timestamp(al["created_at"].min())), "last_alert": _v(pd.Timestamp(al["created_at"].max())),
        "lanes": al["lane"].value_counts().to_dict(),
        "alert_ids": al["alert_id"].tolist()[:MAX_LIST],
        "all_alert_ids": al["alert_id"].tolist(),
        "investigations": {
            "count": int(len(inv)), "analyst_hours": round(float(inv["minutes"].fillna(0).sum()) / 60, 1),
            "outcomes": inv["outcome"].value_counts().to_dict(),
            "investigation_ids": inv["investigation_id"].tolist()[:MAX_LIST],
        },
    }


def watchlist_block(subject_ids: list[str]) -> list[dict]:
    df = data.q("""SELECT watchlist_entry_id AS entry_id, coalesce(individual_id, entity_id) AS subject_id, subject_type,
                          list_type, list_source, CAST(listed_date AS DATE) AS listed_date, reason
                   FROM watchlists WHERE coalesce(individual_id, entity_id) IN (SELECT unnest(?)) ORDER BY listed_date""", [_in(subject_ids)])
    return _records(df)


def ownership_block(entity_id: str) -> dict:
    own = data.q("SELECT * FROM ownership_exposure WHERE entity_id = ?", [entity_id])
    parents = data.q("""SELECT ownership_link_id, parent_entity_id, ownership_pct, link_type, CAST(effective_date AS DATE) AS effective_date
                        FROM ownership_links WHERE child_entity_id = ? ORDER BY ownership_pct DESC LIMIT 10""", [entity_id])
    children = data.q("""SELECT ownership_link_id, child_entity_id, ownership_pct, link_type, CAST(effective_date AS DATE) AS effective_date
                         FROM ownership_links WHERE parent_entity_id = ? ORDER BY ownership_pct DESC LIMIT 10""", [entity_id])
    out = {"direct_owners": _records(parents), "direct_holdings": _records(children)}
    if len(own):
        r = own.iloc[0]
        link_ids = [x.strip() for x in str(r["path_links"]).split(">") if x.strip()]
        hops = data.q("""SELECT ownership_link_id, parent_entity_id, child_entity_id, ownership_pct, link_type
                         FROM ownership_links WHERE ownership_link_id IN (SELECT unnest(?))""", [_in(link_ids)])
        hops = hops.set_index("ownership_link_id").loc[[i for i in link_ids if i in set(hops["ownership_link_id"])]].reset_index()
        out.update({
            "sanctioned_root": r["sanctioned_root"], "root_watchlist_entry_id": r["root_watchlist_entry_id"],
            "root_listed_date": _v(pd.Timestamp(r["root_listed_date"]).date()),
            "eff_share": round(float(r["eff_share"]), 4), "hops": int(r["hops"]),
            "chain": _records(hops), "is_sanctions_listed_itself": bool(r["is_sanctions_listed_itself"]),
            "fifty_percent_rule": bool(r["flag_50"]), "ubo_25_percent": bool(r["flag_25"]),
            "note": "Effective % = product of ownership % along the strongest single path (lower bound; max 4 hops; loops skipped).",
        })
    loops = [p for p in _mutual_pairs() if entity_id in p]
    if loops:
        out["ownership_loops"] = [{"pair": p, "note": "Each entity holds shares in the other"} for p in loops]
    return out


def _mutual_pairs() -> list[list[str]]:
    import json
    p = data.cache_path("precompute_meta.json")
    return json.loads(p.read_text()).get("ownership", {}).get("mutual_pairs", []) if p.exists() else []


def model_block(alert_row: dict) -> dict:
    reasons = [x for x in str(alert_row.get("reasons") or "").split(" | ") if x]
    return {"lane": alert_row.get("lane"), "argus_score": _v(alert_row.get("argus_score")),
            "argus_percentile": _v(alert_row.get("argus_pct")), "legacy_score": _v(alert_row.get("legacy_score")),
            "reasons": reasons}


# --------------------------------------------------------------------------- subject builders
def individual_evidence(ind_id: str, focus: dict | None = None) -> dict:
    net = network_block([ind_id])
    members = net["members"] if net["is_network"] else [ind_id]
    accts = accounts_block("individual_id", members)
    acc_ids = [a["account_id"] for a in accts]
    ev = {
        "subject": {"type": "individual", "id": ind_id, **(focus or {})},
        "network": net, "accounts": accts,
        "transactions": transactions_block(acc_ids, set(acc_ids)),
        "alerts": alerts_block(acc_ids, exclude_alert=(focus or {}).get("alert_id")),
        "watchlist_hits": watchlist_block(members),
    }
    return ev


def entity_evidence(ent_id: str, focus: dict | None = None) -> dict:
    e = data.q("""SELECT entity_id, country, industry, entity_type, CAST(incorporation_date AS DATE) AS incorporated,
                         employee_band, annual_revenue_usd, status, is_listed
                  FROM business_entities WHERE entity_id = ?""", [ent_id])
    own = ownership_block(ent_id)
    accts = accounts_block("entity_id", [ent_id])
    acc_ids = [a["account_id"] for a in accts]
    sup = data.q("SELECT supplier_id, risk_tier, category, status FROM suppliers_clean WHERE entity_id = ?", [ent_id]) if data.has_table("suppliers_clean") else pd.DataFrame()
    wl_subjects = [ent_id] + ([own["sanctioned_root"]] if own.get("sanctioned_root") else [])
    return {
        "subject": {"type": "entity", "id": ent_id, **(focus or {})},
        "entity": _records(e)[0] if len(e) else {"entity_id": ent_id, "note": "No record found"},
        "ownership": own, "accounts": accts,
        "transactions": transactions_block(acc_ids),
        "alerts": alerts_block(acc_ids, exclude_alert=(focus or {}).get("alert_id")),
        "watchlist_hits": watchlist_block(wl_subjects),
        "supplier_records": _records(sup),
    }


def account_evidence(acc_id: str, focus: dict | None = None) -> dict:
    a = data.q("SELECT account_id, holder_type, individual_id, entity_id FROM accounts WHERE account_id = ?", [acc_id])
    if a.empty:
        return not_found("account", acc_id)
    r = a.iloc[0]
    focus = {"account_id": acc_id, **(focus or {})}
    if r["individual_id"]:
        ev = individual_evidence(r["individual_id"], focus)
    else:
        ev = entity_evidence(r["entity_id"], focus)
    ev["subject"]["type"] = focus.get("type", "account")
    ev["subject"]["id"] = focus.get("id", acc_id)
    ev["subject"]["holder_id"] = r["individual_id"] or r["entity_id"]
    return ev


def alert_evidence(alert_id: str) -> dict:
    a = data.q("SELECT * FROM alert_features WHERE alert_id = ?", [alert_id])
    if a.empty:
        return not_found("alert", alert_id)
    row = {k: _v(v) for k, v in a.iloc[0].to_dict().items()}
    alert = {k: row.get(k) for k in ("alert_id", "rule_id", "rule_name", "rule_type", "created_at", "txn_id", "account_id",
                                     "amount_usd", "channel", "merchant_category", "is_cross_border", "txn_hour",
                                     "counterparty_account_id", "txn_device_id")}
    ev = account_evidence(row["account_id"], {"type": "alert", "id": alert_id, "alert_id": alert_id})
    ev["alert"] = alert
    ev["model"] = model_block(row)
    ev["replay_only"] = {"original_disposition": row.get("disposition"), "note": "Shown to the analyst for the backtest replay; never sent to the LLM."}
    return ev


def transaction_evidence(txn_id: str) -> dict:
    t = data.q("""SELECT t.*, d.device_fingerprint FROM transactions t LEFT JOIN devices d ON d.device_id = t.device_id
                  WHERE t.txn_id = ?""", [txn_id])
    if t.empty:
        return not_found("transaction", txn_id)
    row = {k: _v(v) for k, v in t.iloc[0].to_dict().items()}
    ev = account_evidence(row["account_id"], {"type": "transaction", "id": txn_id})
    ev["transaction"] = {k: row.get(k) for k in ("txn_id", "account_id", "counterparty_account_id", "amount_usd", "currency",
                                                  "channel", "merchant_category", "is_cross_border", "txn_ts", "status", "device_fingerprint")}
    alerts = data.q("SELECT alert_id, rule_id, lane, argus_score FROM alert_features WHERE txn_id = ?", [txn_id])
    ev["transaction"]["alerts_on_txn"] = _records(alerts)
    return ev


def device_evidence(device_id: str | None = None, fingerprint: str | None = None) -> dict:
    if device_id:
        d = data.q("SELECT device_fingerprint FROM devices WHERE device_id = ?", [device_id])
        if d.empty:
            return not_found("device", device_id)
        fingerprint = d.iloc[0, 0]
    devs = data.q("""SELECT device_id, individual_id, device_type, os, CAST(first_seen_at AS DATE) AS first_seen,
                            CAST(last_seen_at AS DATE) AS last_seen, ip_country
                     FROM devices WHERE device_fingerprint = ? ORDER BY first_seen_at""", [fingerprint])
    if devs.empty:
        return not_found("device fingerprint", fingerprint)
    inds = sorted(devs["individual_id"].unique().tolist())
    ev = individual_evidence(inds[0])
    if len(inds) > 1 and not ev["network"]["is_network"]:
        ev["network"] = network_block(inds)
    ev["subject"] = {"type": "device", "id": device_id or fingerprint, "fingerprint": fingerprint}
    ev["device"] = {"fingerprint": fingerprint, "identities": inds, "n_identities": len(inds), "devices": _records(devs, MAX_LIST)}
    return ev


def supplier_evidence(sup_id: str) -> dict:
    s = data.q("""SELECT supplier_id, entity_id, category, country, payment_terms_days, risk_tier, preferred,
                         CAST(onboarded_date AS DATE) AS onboarded, status FROM suppliers_clean WHERE supplier_id = ?""", [sup_id])
    if s.empty:
        return not_found("supplier", sup_id)
    srow = _records(s)[0]
    ev = entity_evidence(srow["entity_id"], {"supplier_id": sup_id})
    ev["subject"] = {"type": "supplier", "id": sup_id, "entity_id": srow["entity_id"]}
    ev["supplier"] = srow
    exp = data.q("SELECT * FROM supplier_exposure WHERE supplier_id = ?", [sup_id])
    if len(exp):
        e = exp.iloc[0]
        inv = data.q("""SELECT invoice_id, po_id, amount_usd, status, CAST(received_at AS DATE) AS received, CAST(due_date AS DATE) AS due
                        FROM invoices_clean WHERE supplier_id = ? AND received_at > ? ORDER BY received_at DESC""",
                     [sup_id, pd.Timestamp(e["exposure_date"]).to_pydatetime()])
        pend = inv[inv["status"].isin(["Approved", "On hold - exception"])]
        ev["supplier_exposure"] = {
            "exposure": e["exposure"], "list_type": _v(e.get("list_type")), "watchlist_entry_id": _v(e.get("watchlist_entry_id")),
            "exposure_date": _v(pd.Timestamp(e["exposure_date"]).date()),
            "invoices_after_exposure": int(len(inv)),
            "paid_after_usd": round(float(inv.loc[inv["status"] == "Paid", "amount_usd"].sum()), 2),
            "pending_after_usd": round(float(pend["amount_usd"].sum()), 2), "pending_invoices": int(len(pend)),
            "pending_sample": _records(pend, 12), "paid_sample": _records(inv[inv["status"] == "Paid"], 6),
        }
    else:
        ev["supplier_exposure"] = {"exposure": None, "note": "No sanctions-like listing or >=50% sanctioned ownership found"}
    return ev


def investigation_evidence(inv_id: str) -> dict:
    i = data.q("""SELECT investigation_id, alert_id, kyc_case_id, CAST(opened_at AS DATE) AS opened, CAST(closed_at AS DATE) AS closed,
                         time_to_decision_hours, outcome, steps_count FROM investigations WHERE investigation_id = ?""", [inv_id])
    if i.empty:
        return not_found("investigation", inv_id)
    row = _records(i)[0]
    acts = data.q("""SELECT action_type, count(*) AS n, round(sum(duration_min), 1) AS minutes
                     FROM analyst_actions WHERE investigation_id = ? GROUP BY 1 ORDER BY minutes DESC""", [inv_id])
    tools = data.q("SELECT tool_used, count(*) AS n FROM analyst_actions WHERE investigation_id = ? GROUP BY 1 ORDER BY n DESC", [inv_id])
    ev = alert_evidence(row["alert_id"])
    ev["subject"] = {"type": "investigation", "id": inv_id, "alert_id": row["alert_id"]}
    ev["investigation"] = {**row, "hands_on_minutes": round(float(acts["minutes"].sum()), 1), "actions": _records(acts),
                           "tools": _records(tools)}
    return ev


def invoice_evidence(invoice_id: str) -> dict:
    i = data.q("""SELECT invoice_id, supplier_id, po_id, amount_usd, currency, status, channel, approval_level,
                         CAST(received_at AS DATE) AS received, CAST(due_date AS DATE) AS due, orphan_supplier
                  FROM invoices_clean WHERE invoice_id = ?""", [invoice_id])
    if i.empty:
        return not_found("invoice", invoice_id)
    row = _records(i)[0]
    if row.get("orphan_supplier"):
        return {"subject": {"type": "invoice", "id": invoice_id}, "invoice": row,
                "data_quality": "Supplier ID matches no supplier record (orphan) - route to AP data quality."}
    ev = supplier_evidence(row["supplier_id"])
    ev["subject"] = {"type": "invoice", "id": invoice_id, "supplier_id": row["supplier_id"]}
    ev["invoice"] = row
    return ev


def simple_record(kind: str, rec_id: str) -> dict:
    if kind == "kyc":
        r = data.q("""SELECT kyc_case_id, client_customer_id, subject_type, subject_individual_id, subject_entity_id, case_type,
                             CAST(opened_at AS DATE) AS opened, CAST(closed_at AS DATE) AS closed, documents_requested, risk_level, outcome
                      FROM kyc_cases WHERE kyc_case_id = ?""", [rec_id])
        if r.empty:
            return not_found("KYC case", rec_id)
        row = _records(r)[0]
        ev = individual_evidence(row["subject_individual_id"]) if row["subject_individual_id"] else entity_evidence(row["subject_entity_id"])
        ev["kyc_case"] = row
    elif kind == "watchlist":
        r = data.q("""SELECT watchlist_entry_id, subject_type, individual_id, entity_id, list_type, list_source,
                             CAST(listed_date AS DATE) AS listed_date, reason FROM watchlists WHERE watchlist_entry_id = ?""", [rec_id])
        if r.empty:
            return not_found("watchlist entry", rec_id)
        row = _records(r)[0]
        ev = individual_evidence(row["individual_id"]) if row["individual_id"] else entity_evidence(row["entity_id"])
        ev["watchlist_entry"] = row
    elif kind == "ownership_link":
        r = data.q("SELECT * FROM ownership_links WHERE ownership_link_id = ?", [rec_id])
        if r.empty:
            return not_found("ownership link", rec_id)
        row = _records(r)[0]
        ev = entity_evidence(row["child_entity_id"])
        ev["ownership_link"] = row
    else:
        return not_found(kind, rec_id)
    ev["subject"] = {"type": kind, "id": rec_id}
    return ev


def not_found(kind: str, rec_id: str) -> dict:
    return {"subject": {"type": kind, "id": rec_id}, "not_found": True, "note": f"No record found for {kind} {rec_id}."}


def build(kind: str, rec_id: str) -> dict:
    fn = {
        "alert": alert_evidence, "transaction": transaction_evidence, "account": account_evidence,
        "individual": individual_evidence, "entity": entity_evidence, "supplier": supplier_evidence,
        "device": lambda x: device_evidence(device_id=x), "fingerprint": lambda x: device_evidence(fingerprint=x),
        "investigation": investigation_evidence, "invoice": invoice_evidence,
        "kyc": lambda x: simple_record("kyc", x), "watchlist": lambda x: simple_record("watchlist", x),
        "ownership_link": lambda x: simple_record("ownership_link", x),
    }.get(kind)
    if fn is None:
        return not_found(kind, rec_id)
    ev = fn(rec_id)
    ev.setdefault("data_notes", [
        "REPH synthetic data, as of 2026-09-30. Labels are past analyst decisions and can be wrong.",
        "Demographic fields (nationality, gender, age, occupation) are excluded by design.",
    ])
    return ev


def for_llm(ev: dict) -> dict:
    """The pack minus replay-only fields and long ID lists the narrative does not need."""
    out = {k: v for k, v in ev.items() if k not in ("replay_only",)}
    if isinstance(out.get("alerts"), dict):
        out["alerts"] = {k: v for k, v in out["alerts"].items() if k != "all_alert_ids"}
    return out
