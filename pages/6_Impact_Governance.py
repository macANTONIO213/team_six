import pandas as pd
import streamlit as st

from core import audit, config, data, insights, ui

ui.page_intro(
    "Impact & governance",
    "What ARGUS changes against the baseline, how the AI is governed, and every human decision. Preliminary backtest values on REPH synthetic "
    "data (scale 0.2; full scale is roughly x5), not validated REPH findings.",
    steps=["**Baseline vs ARGUS**: each lever, its basis, and which numbers are assumptions.",
           "**Audit of the AI assistant already in use**: a KPI that improved while effort did not.",
           "**Model card** and **fairness check**: data, features, exclusions, parity by nationality.",
           "**Decisions, LLM calls and audit trail**: approve pending SAR-like referrals or supplier holds as the second approver."],
)


@st.cache_data(ttl=900, show_spinner="Computing live...")
def numbers():
    ring_ids = insights.ring_cluster_ids()
    return {"b": insights.baseline(), "card": insights.model_card(), "lanes": insights.lane_stats(),
            "eff": insights.investigation_effort(), "ai": insights.ai_assistant_audit(), "own": insights.ownership_summary(),
            "sup": insights.supplier_summary(), "ring": insights.ring_summary(ring_ids[0]) if ring_ids else {}}


n = numbers()
m = n["card"]["metrics"]
eff = n["eff"]
lanes = n["lanes"].set_index("lane")
hp = lanes.loc[["HOT", "PRIORITY"]]
saved_h = eff["hours_per_year"] * eff["core_evidence_time_share"] * 0.70
st.subheader("Baseline vs ARGUS")
value = pd.DataFrame([
    ["False-positive reviews", f"{n['b']['fp_rate'] * 100:.1f}% FP; today's score AUC {m['auc_legacy_score']:.2f}",
     f"AUC {m['auc_argus']:.2f}; 90% of real alerts in first {m['queue_argus']['queue_share_for_target'] * 100:.1f}% of queue = "
     f"-{m['queue_argus']['fp_reviews_avoided_share'] * 100:.0f}% FP reviews", f"Backtest: train < 2026, test 2026 ({m['test_rows']:,} alerts)"],
    ["Alert routing", "One undifferentiated queue",
     f"HOT+PRIORITY: {hp['share_alerts'].sum() * 100:.1f}% of alerts hold {hp['share_true_hits'].sum() * 100:.1f}% of real hits; "
     f"NOISE: {lanes.loc['NOISE', 'share_alerts'] * 100:.1f}% of volume at {lanes.loc['NOISE', 'fp_rate'] * 100:.1f}% FP -> batch review",
     f"Backtest on {n['b']['closed']:,} closed alerts"],
    ["Investigator effort", f"{eff['median_minutes']:.0f} min per case; {eff['hours_per_year']:,.0f} h/yr",
     f"~{saved_h / eff['hours_per_year'] * 100:.0f}% less hands-on effort = {saved_h:,.0f} h/yr = {saved_h / 1800:.1f} FTE (x5 at full scale)",
     f"ASSUMPTION: evidence + drafting actions ({eff['core_evidence_time_share'] * 100:.0f}% of time) cut by 70%. Pilot must measure."],
    ["Fragmented cases", f"Ring: {n['ring'].get('n_alerts')} alerts, {n['ring'].get('n_investigations')} investigations, {n['ring'].get('investigation_hours')} h",
     "1 network case", "Data + assumption on effort per case"],
    ["Sanctions leakage (suppliers)", f"${n['sup']['paid_after_usd'] / 1e6:.1f}M paid after listing",
     f"${n['sup']['pending_after_usd'] / 1e6:.2f}M ({n['sup']['pending_invoices']} invoices) flagged for hold, pending compliance approval", "Raw finance files, cleaned"],
    ["Hidden ownership exposure", "Subject-level screening only", f"{n['own']['n_entities_ge50']} entities >=50% owned by sanctioned parties surfaced", "Ownership graph, 4 hops"],
], columns=["Lever", "Baseline (data)", "With ARGUS", "Basis / status"])
st.dataframe(value, hide_index=True, width="stretch")

st.subheader("Audit of the AI assistant already in use")
ai = n["ai"]
st.markdown(f"Since {ai['cutover']} the AI Investigation Assistant is used in **{ai['ai_action_share_after'] * 100:.0f}%** of analyst actions. "
            "Calendar time to decision fell, but hands-on effort did not, and analysts use more tools per case: "
            "it looks good on one KPI and hurts another. ARGUS replaces steps instead of adding a tool.")
st.dataframe(ai["before_after"].rename(index={False: "before", True: "after"}), width="stretch")

c1, c2 = st.columns(2)
with c1:
    st.subheader("Model card")
    card = n["card"]
    st.json({"model": "HistGradientBoostingClassifier (scikit-learn), alert triage", "trained": card["trained_at"],
             "train/test": f"{m['train_rows']:,} alerts {m['train_period']} / {m['test_rows']:,} alerts {m['test_period']} (out of time)",
             "AUC": {"ARGUS": m["auc_argus"], "today's score": m["auc_legacy_score"], "transaction-only model (no rule)": m["auc_argus_txn_model"]},
             "queue at 90% recall": m["queue_argus"], "features (categorical)": card["cat_features"], "features (numeric)": card["num_features"],
             "excluded by design": card["excluded_features"],
             "new transactions": "Network-signal likelihood ratios (ML without rule context has no lift).",
             "LLM": {"provider": "Amazon Bedrock (Australia inference profiles)", "fast": config.LLM_FAST_MODEL, "thorough": config.LLM_MODEL,
                     "temperature": config.LLM_TEMPERATURE, "guardrails": "evidence-only prompt, JSON schema, data minimisation, citation check, call log"},
             "limits": ["Synthetic data; labels are analyst decisions and can be wrong (72 ring alerts closed as FP).",
                        "Modest ML lift; network signals are rare.", "Effective ownership % is a single-path lower bound."]}, expanded=False)
with c2:
    st.subheader("Fairness check (aggregate)")
    fair = data.q("""SELECT i.nationality, count(*) AS alerts, avg(1 - f.y) AS fp_rate, avg(f.argus_score) AS mean_argus_score,
                            avg(CASE WHEN f.lane IN ('HOT', 'PRIORITY') THEN 1.0 ELSE 0 END) AS share_hot_priority
                     FROM alert_features f JOIN individuals i ON i.individual_id = f.individual_id
                     WHERE f.y IS NOT NULL GROUP BY 1 ORDER BY alerts DESC""")
    st.dataframe(fair.round(3), hide_index=True, width="stretch")
    st.caption("Nationality is not a model input; it is used here only to monitor score and lane parity. No individual analyst is ranked anywhere in ARGUS.")

st.subheader("Human decisions, LLM calls and audit trail")
dec = audit.frame("decisions")
calls = audit.frame("llm_calls")
k = st.columns(4)
k[0].metric("Decisions recorded", len(dec))
k[1].metric("Override rate (human differs from AI)", f"{dec['override'].mean() * 100:.0f}%" if len(dec) else "-")
k[2].metric("LLM calls logged", len(calls))
k[3].metric("Citation check pass rate", f"{(calls['guardrail'] == 'verified').mean() * 100:.0f}%" if len(calls) else "-")
pending = dec[dec["status"] == "Pending second approval"] if len(dec) else dec
if len(pending):
    with st.form("second-approval"):
        st.markdown("**Pending second approval** (SAR-like referrals and supplier holds)")
        pick = st.selectbox("Decision", pending["decision_id"].tolist())
        who = st.text_input("Second approver (must differ from the analyst)")
        if st.form_submit_button("Approve"):
            try:
                st.success(audit.approve_pending(pick, who.strip()))
            except ValueError as e:
                st.error(str(e))
t1, t2, t3 = st.tabs(["Decisions", "LLM call log (DATA-05)", "Audit log"])
t1.dataframe(dec, hide_index=True, width="stretch")
t2.dataframe(calls, hide_index=True, width="stretch")
t3.dataframe(audit.frame("audit_log"), hide_index=True, width="stretch")
