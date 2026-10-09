"""Offline precompute. Builds every derived table ARGUS serves, from the REPH data.

    python -m core.precompute

Outputs (cache/):
  identity_links.parquet      shared fingerprint / phone / email / ID / address -> individuals
  identity_clusters.parquet   individual -> connected component (cluster) and size
  ownership_exposure.parquet  entity -> strongest effective share held by a sanctions-listed party
  alert_features.parquet      one row per alert: as-of-time features, label, lane, ARGUS score, reasons
  suppliers_clean / invoices_clean / supplier_exposure.parquet   cleaned raw finance + sanctions join
  triage_model.joblib         backtest model bundle (+ metrics) ; precompute_meta.json
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

import joblib
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from core import config, data

# Features deliberately EXCLUDED from every model: nationality, gender, date of birth / age, occupation.
CAT_FEATURES = ["rule_id", "rule_type", "channel", "merchant_category", "account_type", "risk_rating", "holder_type"]
NUM_FEATURES = [
    "log_amount_usd", "txn_hour", "account_age_days", "is_cross_border", "night", "near_10k", "round_amount",
    "holder_fp_identities", "txn_fp_identities", "cluster_size", "cp_same_cluster", "nominee_links",
    "wl_sanctions", "wl_pep", "wl_adverse", "wl_law", "cp_watchlisted", "owner_sanctioned_eff",
    "prior_alerts", "prior_true",
]
TXN_CAT_FEATURES = [c for c in CAT_FEATURES if c not in ("rule_id", "rule_type")]

# Reason signals: (column expression on the feature frame, label shown to analysts)
SIGNALS = {
    "shared_fp": "Device fingerprint shared with other identities",
    "night": "Transaction between 00:00 and 05:59",
    "model_rule": "Raised by a model-based rule",
    "nominee_gt1": "More than 1 nominee ownership link",
    "pep": "Holder on a PEP-like list",
    "sanctions": "Holder on a sanctions-like list",
    "ring_member": "Holder is in a linked identity network",
    "member_flow": "Counterparty in the same identity network",
    "near_10k": "Amount just below USD 10,000",
    "owner_sanctioned": "Owned >=50% by a sanctions-listed party",
    "cp_watchlisted": "Counterparty on a watchlist",
}


def _log(msg: str) -> None:
    print(f"[precompute {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- identity graph
def build_identity_graph() -> tuple[pd.DataFrame, pd.DataFrame]:
    links = data.q(
        """
        WITH fp AS (
            SELECT 'device_fingerprint' AS link_type, device_fingerprint AS link_value, individual_id FROM devices
        ), attrs AS (
            SELECT lower(replace(attribute_type, ' ', '_')) AS link_type, attribute_value_hash AS link_value, individual_id
            FROM identity_attributes
        ), addr AS (
            SELECT 'address' AS link_type,
                   lower(trim(address_line)) || ' | ' || coalesce(CAST(postal_code AS VARCHAR), '') AS link_value,
                   individual_id
            FROM addresses
        ), allv AS (SELECT * FROM fp UNION ALL SELECT * FROM attrs UNION ALL SELECT * FROM addr),
        shared AS (
            SELECT link_type, link_value, count(DISTINCT individual_id) AS n_members
            FROM allv GROUP BY 1, 2 HAVING count(DISTINCT individual_id) > 1
        )
        SELECT DISTINCT s.link_type, s.link_value, a.individual_id, s.n_members
        FROM shared s JOIN allv a USING (link_type, link_value)
        """
    )
    g = nx.Graph()
    for lt, lv, ind in links[["link_type", "link_value", "individual_id"]].itertuples(index=False):
        g.add_edge(f"L|{lt}|{lv}", f"I|{ind}")
    rows = []
    comps = sorted((c for c in nx.connected_components(g)), key=lambda c: -sum(1 for n in c if n.startswith("I|")))
    for i, comp in enumerate(comps, start=1):
        inds = sorted(n[2:] for n in comp if n.startswith("I|"))
        types = sorted({n.split("|")[1] for n in comp if n.startswith("L|")})
        for ind in inds:
            rows.append((ind, f"CL{i:05d}", len(inds), ",".join(types)))
    clusters = pd.DataFrame(rows, columns=["individual_id", "cluster_id", "cluster_size", "cluster_link_types"])
    return links, clusters


# --------------------------------------------------------------------------- ownership
def build_ownership_exposure(max_hops: int = 4, min_share: float = 0.10) -> tuple[pd.DataFrame, dict]:
    links = data.q("SELECT ownership_link_id, parent_entity_id, child_entity_id, ownership_pct, link_type FROM ownership_links")
    roots = data.q(
        """SELECT entity_id, min(listed_date) AS listed_date, arg_min(watchlist_entry_id, listed_date) AS watchlist_entry_id
           FROM watchlists WHERE entity_id IS NOT NULL AND list_type = 'Sanctions-like' GROUP BY 1"""
    )
    children: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for lid, parent, child, pct, _lt in links.itertuples(index=False):
        children[parent].append((child, float(pct) / 100.0, lid))

    best: dict[str, tuple] = {}
    for root, listed, wl_id in roots.itertuples(index=False):
        stack = [(root, 1.0, (root,), ())]
        while stack:
            node, eff, path, lpath = stack.pop()
            if len(path) - 1 >= max_hops:
                continue
            for child, share, lid in children.get(node, ()):
                if child in path:  # loop-safe: never revisit a node on the current path
                    continue
                e = eff * share
                if e < min_share:
                    continue
                npath, nl = path + (child,), lpath + (lid,)
                cur = best.get(child)
                if cur is None or e > cur[0]:
                    best[child] = (e, npath, nl, root, listed, wl_id)
                stack.append((child, e, npath, nl))

    listed_any = set(data.q("SELECT DISTINCT entity_id FROM watchlists WHERE entity_id IS NOT NULL")["entity_id"])
    listed_sanc = set(roots["entity_id"])
    out = pd.DataFrame(
        [
            (ent, round(v[0], 4), len(v[1]) - 1, " > ".join(v[1]), " > ".join(v[2]), v[3], v[4], v[5])
            for ent, v in best.items()
        ],
        columns=["entity_id", "eff_share", "hops", "path", "path_links", "sanctioned_root", "root_listed_date", "root_watchlist_entry_id"],
    )
    out["is_sanctions_listed_itself"] = out["entity_id"].isin(listed_sanc)
    out["is_watchlisted_itself"] = out["entity_id"].isin(listed_any)
    out["flag_50"] = out["eff_share"] >= 0.5
    out["flag_25"] = out["eff_share"] >= 0.25

    dg = nx.DiGraph()
    dg.add_edges_from(zip(links["parent_entity_id"], links["child_entity_id"]))
    mutual = sorted({tuple(sorted((a, b))) for a, b in dg.edges() if a != b and dg.has_edge(b, a)})
    sccs = sorted((len(c) for c in nx.strongly_connected_components(dg)), reverse=True)
    graph_stats = {
        "mutual_pairs": [list(p) for p in mutual],
        "n_mutual_pairs": len(mutual),
        "self_loops": int(sum(1 for a, b in dg.edges() if a == b)),
        "largest_cyclic_block": int(sccs[0]) if sccs else 0,
        "n_cyclic_blocks": int(sum(1 for s in sccs if s > 1)),
        "n_sanctioned_roots": int(len(roots)),
    }
    return out, graph_stats


# --------------------------------------------------------------------------- alert features
def build_alert_features() -> pd.DataFrame:
    base = data.q(
        """
        SELECT ra.alert_id, ra.rule_id, r.rule_name, r.rule_type, ra.txn_id, ra.account_id, ra.created_at, ra.closed_at,
               ra.score AS legacy_score, ra.disposition,
               CASE WHEN ra.is_false_positive IS NULL THEN NULL WHEN ra.is_false_positive THEN 0 ELSE 1 END AS y,
               t.amount_usd, t.amount, t.currency, t.channel, t.merchant_category,
               CAST(t.is_cross_border AS INTEGER) AS is_cross_border, t.txn_ts, hour(t.txn_ts) AS txn_hour,
               t.device_id AS txn_device_id, t.counterparty_account_id, t.txn_country,
               acc.holder_type, acc.individual_id, acc.entity_id, acc.account_type, acc.risk_rating,
               date_diff('day', acc.opened_at, ra.created_at) AS account_age_days,
               cp.individual_id AS cp_individual_id, cp.entity_id AS cp_entity_id
        FROM risk_alerts ra
        LEFT JOIN alert_rules r USING (rule_id)
        LEFT JOIN transactions t ON t.txn_id = ra.txn_id
        LEFT JOIN accounts acc ON acc.account_id = ra.account_id
        LEFT JOIN accounts cp ON cp.account_id = t.counterparty_account_id
        """
    )
    con = data.connection().cursor()
    try:
        con.register("af_base", base[["alert_id", "created_at", "account_id", "individual_id", "entity_id", "txn_device_id",
                                       "cp_individual_id", "cp_entity_id"]])
        extra = {
            # identities sharing any of the holder's device fingerprints, counting devices first seen before the alert
            "holder_fp": """
                SELECT a.alert_id, count(DISTINCT d2.individual_id) AS holder_fp_identities
                FROM af_base a
                JOIN devices d1 ON d1.individual_id = a.individual_id AND d1.first_seen_at <= a.created_at
                JOIN devices d2 ON d2.device_fingerprint = d1.device_fingerprint AND d2.first_seen_at <= a.created_at
                GROUP BY 1""",
            "txn_fp": """
                SELECT a.alert_id, count(DISTINCT d2.individual_id) AS txn_fp_identities
                FROM af_base a
                JOIN devices d1 ON d1.device_id = a.txn_device_id
                JOIN devices d2 ON d2.device_fingerprint = d1.device_fingerprint AND d2.first_seen_at <= a.created_at
                GROUP BY 1""",
            "nominee": """
                WITH n AS (
                    SELECT child_entity_id AS entity_id, effective_date FROM ownership_links WHERE link_type = 'Nominee'
                    UNION ALL
                    SELECT parent_entity_id, effective_date FROM ownership_links WHERE link_type = 'Nominee')
                SELECT a.alert_id, count(*) AS nominee_links
                FROM af_base a JOIN n ON n.entity_id = a.entity_id AND n.effective_date <= a.created_at
                GROUP BY 1""",
            "wl": """
                WITH w AS (SELECT coalesce(individual_id, entity_id) AS subject_id, list_type, listed_date FROM watchlists)
                SELECT a.alert_id,
                       max(CASE WHEN w.list_type = 'Sanctions-like' THEN 1 ELSE 0 END) AS wl_sanctions,
                       max(CASE WHEN w.list_type = 'PEP-like' THEN 1 ELSE 0 END) AS wl_pep,
                       max(CASE WHEN w.list_type = 'Adverse media-like' THEN 1 ELSE 0 END) AS wl_adverse,
                       max(CASE WHEN w.list_type = 'Law enforcement-like' THEN 1 ELSE 0 END) AS wl_law,
                       count(*) AS wl_hits
                FROM af_base a JOIN w ON w.subject_id = coalesce(a.individual_id, a.entity_id) AND w.listed_date < a.created_at
                GROUP BY 1""",
            "cp_wl": """
                WITH w AS (SELECT coalesce(individual_id, entity_id) AS subject_id, listed_date FROM watchlists)
                SELECT a.alert_id, 1 AS cp_watchlisted
                FROM af_base a JOIN w ON w.subject_id = coalesce(a.cp_individual_id, a.cp_entity_id) AND w.listed_date < a.created_at
                GROUP BY 1""",
            "prior": """
                SELECT a.alert_id, count(p.alert_id) AS prior_alerts,
                       sum(CASE WHEN p.is_false_positive = false THEN 1 ELSE 0 END) AS prior_true
                FROM af_base a JOIN risk_alerts p
                  ON p.account_id = a.account_id AND p.closed_at < a.created_at AND p.alert_id <> a.alert_id
                GROUP BY 1""",
        }
        frames = {k: con.execute(sql).df() for k, sql in extra.items()}
    finally:
        con.close()

    df = base
    for frame in frames.values():
        df = df.merge(frame, on="alert_id", how="left")

    clusters = pd.read_parquet(data.cache_path("identity_clusters.parquet"))
    cl = clusters.set_index("individual_id")
    df["cluster_id"] = df["individual_id"].map(cl["cluster_id"])
    df["cluster_size"] = df["individual_id"].map(cl["cluster_size"]).fillna(1)
    cp_cluster = df["cp_individual_id"].map(cl["cluster_id"])
    df["cp_same_cluster"] = ((cp_cluster == df["cluster_id"]) & df["cluster_id"].notna()).astype(int)

    own = pd.read_parquet(data.cache_path("ownership_exposure.parquet"))
    own = own[~own["is_sanctions_listed_itself"]].set_index("entity_id")
    eff = df["entity_id"].map(own["eff_share"])
    listed_before = pd.to_datetime(df["entity_id"].map(own["root_listed_date"])) < pd.to_datetime(df["created_at"])
    df["owner_sanctioned_eff"] = eff.where(listed_before, 0).fillna(0)

    for col in ("holder_fp_identities", "txn_fp_identities"):
        df[col] = df[col].fillna(0)
    for col in ("nominee_links", "wl_sanctions", "wl_pep", "wl_adverse", "wl_law", "wl_hits", "cp_watchlisted",
                "prior_alerts", "prior_true"):
        df[col] = df[col].fillna(0).astype(int)
    df["log_amount_usd"] = np.log1p(df["amount_usd"].fillna(0))
    df["night"] = df["txn_hour"].between(0, 5).astype(int)
    df["near_10k"] = df["amount_usd"].between(9000, 9999.99).astype(int)
    df["round_amount"] = ((df["amount"].fillna(0) % 1000 == 0) & (df["amount"].fillna(0) > 0)).astype(int)
    df["is_cross_border"] = df["is_cross_border"].fillna(0).astype(int)

    add_signals(df)
    df["lane"] = assign_lanes(df)
    return df


def add_signals(df: pd.DataFrame) -> None:
    """Binary reason signals (same definitions for alerts and new transactions)."""
    df["sig_shared_fp"] = ((df["holder_fp_identities"] > 1) | (df["txn_fp_identities"] > 1)).astype(int)
    df["sig_night"] = df["night"].astype(int)
    df["sig_model_rule"] = (df.get("rule_type", pd.Series("", index=df.index)) == "Model-based").astype(int)
    df["sig_nominee_gt1"] = (df["nominee_links"] > 1).astype(int)
    df["sig_pep"] = (df["wl_pep"] > 0).astype(int)
    df["sig_sanctions"] = (df["wl_sanctions"] > 0).astype(int)
    df["sig_ring_member"] = (df["cluster_size"] >= config.RING_MIN_SIZE).astype(int)
    df["sig_member_flow"] = df["cp_same_cluster"].astype(int)
    df["sig_near_10k"] = df["near_10k"].astype(int)
    df["sig_owner_sanctioned"] = (df["owner_sanctioned_eff"] >= 0.5).astype(int)
    df["sig_cp_watchlisted"] = (df["cp_watchlisted"] > 0).astype(int)


def assign_lanes(df: pd.DataFrame) -> pd.Series:
    hot = (df["sig_ring_member"] == 1) | (df["sig_shared_fp"] == 1) | (df["sig_nominee_gt1"] == 1) | (df["sig_night"] == 1)
    priority = df["sig_model_rule"] == 1
    corroborated = (df.get("wl_hits", 0) > 0) | (df["cp_watchlisted"] > 0) | (df["owner_sanctioned_eff"] >= 0.5)
    noise = df.get("rule_id", pd.Series("", index=df.index)).isin(config.NOISE_RULES) & ~corroborated
    return pd.Series(np.select([hot, priority, noise], ["HOT", "PRIORITY", "NOISE"], "STANDARD"), index=df.index)


def signal_lifts(df: pd.DataFrame) -> dict:
    closed = df[df["y"].notna()]
    base = closed["y"].mean()
    out = {}
    for key, label in SIGNALS.items():
        col = f"sig_{key}"
        hit = closed[closed[col] == 1]
        out[key] = {
            "label": label,
            "n_alerts": int(len(hit)),
            "true_rate": round(float(hit["y"].mean()), 4) if len(hit) else None,
            "lift": round(float(hit["y"].mean() / base), 2) if len(hit) and base else None,
        }
    out["_base_true_rate"] = round(float(base), 4)
    return out


def reasons_for(row: pd.Series | dict, lifts: dict) -> list[dict]:
    out = []
    for key, label in SIGNALS.items():
        if int(row.get(f"sig_{key}", 0) or 0) == 1:
            lift = (lifts.get(key) or {}).get("lift")
            out.append({"code": key, "label": label, "lift": lift})
    out.sort(key=lambda r: -(r["lift"] or 0))
    return out


# --------------------------------------------------------------------------- model
def _pipeline(cats: list[str], nums: list[str]) -> Pipeline:
    pre = ColumnTransformer(
        [("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1, encoded_missing_value=-1), cats),
         ("num", "passthrough", nums)],
        verbose_feature_names_out=False,
    )
    clf = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=40, l2_regularization=1.0,
        categorical_features=[True] * len(cats) + [False] * len(nums), random_state=7,
    )
    return Pipeline([("pre", pre), ("clf", clf)])


def _prep(df: pd.DataFrame, cats: list[str], nums: list[str]) -> pd.DataFrame:
    x = df[cats + nums].copy()
    for c in cats:
        x[c] = x[c].astype("object").where(x[c].notna(), "(missing)").astype(str)
    for c in nums:
        x[c] = pd.to_numeric(x[c], errors="coerce").astype(float)
    return x


def queue_metrics(y: np.ndarray, score: np.ndarray, recall_target: float = 0.90) -> dict:
    order = np.argsort(-score, kind="stable")
    ys = y[order]
    tp_cum = np.cumsum(ys)
    k = int(np.searchsorted(tp_cum, recall_target * ys.sum(), side="left")) + 1
    fp_total = int((ys == 0).sum())
    fp_in_queue = int((ys[:k] == 0).sum())
    return {
        "recall_target": recall_target,
        "queue_share_for_target": round(k / len(ys), 4),
        "fp_reviews_avoided_share": round(1 - fp_in_queue / fp_total, 4) if fp_total else None,
        "fp_reviews_avoided": fp_total - fp_in_queue,
        "n": int(len(ys)),
    }


def train_models(df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    closed = df[df["y"].notna()].copy()
    train = closed[pd.to_datetime(closed["created_at"]) < pd.Timestamp(config.TRAIN_CUTOFF)]
    test = closed[pd.to_datetime(closed["created_at"]) >= pd.Timestamp(config.TRAIN_CUTOFF)]

    model = _pipeline(CAT_FEATURES, NUM_FEATURES).fit(_prep(train, CAT_FEATURES, NUM_FEATURES), train["y"].astype(int))
    txn_model = _pipeline(TXN_CAT_FEATURES, NUM_FEATURES).fit(_prep(train, TXN_CAT_FEATURES, NUM_FEATURES), train["y"].astype(int))

    p_test = model.predict_proba(_prep(test, CAT_FEATURES, NUM_FEATURES))[:, 1]
    p_txn_test = txn_model.predict_proba(_prep(test, TXN_CAT_FEATURES, NUM_FEATURES))[:, 1]
    y_test = test["y"].astype(int).to_numpy()
    metrics = {
        "train_rows": int(len(train)), "test_rows": int(len(test)),
        "train_period": f"< {config.TRAIN_CUTOFF}", "test_period": f">= {config.TRAIN_CUTOFF}",
        "test_true_rate": round(float(y_test.mean()), 4),
        "auc_argus": round(float(roc_auc_score(y_test, p_test)), 4),
        "auc_argus_txn_model": round(float(roc_auc_score(y_test, p_txn_test)), 4),
        "auc_legacy_score": round(float(roc_auc_score(y_test, test["legacy_score"].fillna(0))), 4),
        "queue_argus": queue_metrics(y_test, p_test),
        "queue_legacy": queue_metrics(y_test, test["legacy_score"].fillna(0).to_numpy()),
    }
    all_p = model.predict_proba(_prep(df, CAT_FEATURES, NUM_FEATURES))[:, 1]
    df = df.copy()
    df["argus_score"] = np.round(all_p, 4)
    df["argus_pct"] = df["argus_score"].rank(pct=True).round(4)
    hist = np.sort(all_p[df["y"].notna().to_numpy()])
    bundle = {
        "model": model, "txn_model": txn_model,
        "cat_features": CAT_FEATURES, "txn_cat_features": TXN_CAT_FEATURES, "num_features": NUM_FEATURES,
        "metrics": metrics,
        "score_quantiles": {q: float(np.quantile(hist, q)) for q in (0.5, 0.75, 0.9, 0.95)},
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "excluded_features": ["nationality", "gender", "date_of_birth/age", "occupation", "txn_country"],
    }
    return bundle, df


# --------------------------------------------------------------------------- suppliers
def build_supplier_exposure() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    sup, s_stats = data.load_raw_suppliers()
    inv, i_stats = data.load_raw_invoices(set(sup["supplier_id"].dropna()))
    wl = data.q(
        """SELECT entity_id, list_type, min(listed_date) AS listed_date,
                  arg_min(watchlist_entry_id, listed_date) AS watchlist_entry_id,
                  arg_min(list_source, listed_date) AS list_source, arg_min(reason, listed_date) AS reason
           FROM watchlists WHERE entity_id IS NOT NULL GROUP BY 1, 2"""
    )
    sanc = wl[wl["list_type"] == "Sanctions-like"]
    own = pd.read_parquet(data.cache_path("ownership_exposure.parquet"))
    own50 = own[own["flag_50"] & ~own["is_sanctions_listed_itself"]]

    exp = sup.merge(sanc, on="entity_id", how="left")
    exp = exp.merge(own50[["entity_id", "eff_share", "path", "sanctioned_root", "root_listed_date"]], on="entity_id", how="left")
    exp["exposure"] = np.where(exp["list_type"].notna(), "Sanctions-listed",
                               np.where(exp["eff_share"].notna(), "Owned >=50% by sanctioned party", None))
    exp = exp[exp["exposure"].notna()].copy()
    exp["exposure_date"] = pd.to_datetime(exp["listed_date"]).fillna(pd.to_datetime(exp["root_listed_date"]))

    inv_ok = inv[~inv["orphan_supplier"]]
    after = inv_ok.merge(exp[["supplier_id", "exposure_date", "exposure"]], on="supplier_id", how="inner")
    after = after[after["received_at"] > after["exposure_date"]].copy()
    agg = after.groupby("supplier_id").agg(
        invoices_after=("invoice_id", "count"),
        paid_after_usd=("amount_usd", lambda s: float(s[after.loc[s.index, "status"] == "Paid"].sum())),
        pending_after_usd=("amount_usd", lambda s: float(s[after.loc[s.index, "status"].isin(["Approved", "On hold - exception"])].sum())),
        pending_invoices=("status", lambda s: int(s.isin(["Approved", "On hold - exception"]).sum())),
    ).reset_index()
    exp = exp.merge(agg, on="supplier_id", how="left").fillna(
        {"invoices_after": 0, "paid_after_usd": 0.0, "pending_after_usd": 0.0, "pending_invoices": 0})
    stats = {"suppliers": s_stats, "invoices": i_stats}
    return sup, inv, exp, stats


# --------------------------------------------------------------------------- main
def run() -> dict:
    t0 = time.time()
    meta: dict = {}
    _log(f"data dir {config.DATA_DIR}  cache dir {config.CACHE_DIR}")

    links, clusters = build_identity_graph()
    links.to_parquet(data.cache_path("identity_links.parquet"), index=False)
    clusters.to_parquet(data.cache_path("identity_clusters.parquet"), index=False)
    sizes = clusters.drop_duplicates("cluster_id")["cluster_size"]
    meta["clusters"] = {"n_clusters": int(len(sizes)), "n_networks_ge_min": int((sizes >= config.RING_MIN_SIZE).sum()),
                        "largest": int(sizes.max()) if len(sizes) else 0}
    _log(f"identity clusters: {meta['clusters']}")

    own, gstats = build_ownership_exposure()
    own.to_parquet(data.cache_path("ownership_exposure.parquet"), index=False)
    meta["ownership"] = gstats | {"n_flag_50_not_listed": int((own["flag_50"] & ~own["is_sanctions_listed_itself"]).sum())}
    _log(f"ownership exposure: {meta['ownership'] | {'mutual_pairs': '...'}}")

    data.refresh_views()
    feats = build_alert_features()
    bundle, feats = train_models(feats)
    lifts = signal_lifts(feats)
    bundle["lifts"] = lifts
    feats["reasons"] = [" | ".join(f"{r['label']} (x{r['lift']})" for r in reasons_for(row, lifts))
                        for row in feats.to_dict("records")]
    feats.drop(columns=["txn_ts"]).to_parquet(data.cache_path("alert_features.parquet"), index=False)
    joblib.dump(bundle, data.cache_path("triage_model.joblib"))
    meta["model"] = bundle["metrics"]
    _log(f"model: {bundle['metrics']}")

    sup, inv, exp, cstats = build_supplier_exposure()
    sup.to_parquet(data.cache_path("suppliers_clean.parquet"), index=False)
    inv.to_parquet(data.cache_path("invoices_clean.parquet"), index=False)
    exp.to_parquet(data.cache_path("supplier_exposure.parquet"), index=False)
    meta["cleaning"] = cstats
    _log(f"cleaning: {cstats}")

    meta["seconds"] = round(time.time() - t0, 1)
    meta["built_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    data.cache_path("precompute_meta.json").write_text(json.dumps(meta, indent=2, default=str))
    data.refresh_views()
    _log(f"done in {meta['seconds']}s")
    return meta


if __name__ == "__main__":
    run()
