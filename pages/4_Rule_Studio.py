import streamlit as st

from core import audit, config, data, insights, llm, ui

ui.page_intro(
    "Rule Studio",
    "Evidence for tuning detection rules. ARGUS simulates the change and drafts the request; the rule owner and governance approve it.",
    steps=["Scan the table: which rules produce many alerts and almost only false positives?",
           "In **What-if**, pick rules to route to the NOISE lane unless something corroborates them (watchlist hit, sanctioned owner).",
           "Adjust the assumptions (minutes per review, QA sample) and read the impact, including real hits that would move.",
           "Click **Draft change request with AI**, review it, then approve it for governance. Nothing changes in the alert engine."],
)


@st.cache_data(ttl=900, show_spinner=False)
def stats():
    return insights.rule_stats(), insights.rule_type_fp()


rs, rt = stats()
c = st.columns(3)
for i, r in rt.iterrows():
    c[i].metric(f"{r['rule_type']} rules: false-positive rate", f"{r['fp_rate'] * 100:.1f}%", f"{r['alerts']:,} alerts", delta_color="off", delta_arrow="off")
top2 = rs[rs["rule_id"].isin(config.NOISE_RULES)]
c[2].metric("R017 + R023 share of all alerts", f"{top2['share'].sum() * 100:.1f}%",
            f"{(top2['alerts'] * top2['fp_rate']).sum() / top2['alerts'].sum() * 100:.1f}% false positives", delta_color="off", delta_arrow="off")
focus = st.session_state.get("rule_focus")
st.dataframe(rs, hide_index=True, width="stretch", height=300,
             column_config={"rule_id": "Rule", "rule_name": "Rule name", "rule_type": "Type", "alerts": "Alerts",
                            "share": st.column_config.ProgressColumn("Share of alerts", format="percent", min_value=0, max_value=float(rs["share"].max())),
                            "fp_rate": st.column_config.ProgressColumn("False-positive rate", format="percent", min_value=0, max_value=1),
                            "true_hits": "Real hits"})

st.markdown("### What-if: route rules to the NOISE lane unless corroborated")
with st.container(border=True):
    c1, c2, c3 = st.columns([2, 1, 1])
    default = [focus] if focus in rs["rule_id"].tolist() else list(config.NOISE_RULES)
    sel = c1.multiselect("Rules", rs["rule_id"].tolist(), default=default)
    minutes = c2.number_input("Minutes per alert review", 1, 120, 12, help="Assumption: hands-on time to review one alert.")
    qa = c3.slider("QA sample re-reviewed", 0, 50, 10, format="%d%%", help="Share of NOISE alerts still re-checked by a person.")
    if sel:
        df = data.q("""SELECT rule_id, lane, y, wl_hits, cp_watchlisted, owner_sanctioned_eff, created_at FROM alert_features
                       WHERE rule_id IN (SELECT unnest(?)) AND y IS NOT NULL""", [sel])
        corroborated = (df["wl_hits"] > 0) | (df["cp_watchlisted"] > 0) | (df["owner_sanctioned_eff"] >= 0.5)
        moved = df[~corroborated & (df["lane"] != "HOT")]
        months = data.scalar("SELECT date_diff('month', min(created_at), max(created_at)) + 1 FROM risk_alerts")
        fp_moved = int((moved["y"] == 0).sum())
        hits_moved = int(moved["y"].sum())
        hours = fp_moved * minutes * (1 - qa / 100) / 60
        m = st.columns(4)
        m[0].metric("Alerts moved to batch review", f"{len(moved):,}", f"of {len(df):,} from these rules", delta_color="off", delta_arrow="off")
        m[1].metric("Real hits among them", f"{hits_moved:,}", f"{hits_moved / max(len(moved), 1) * 100:.1f}%: still reviewed in batch", delta_color="off", delta_arrow="off",
                    help="Residual risk: these real hits are de-prioritised, not closed.")
        m[2].metric("False-positive reviews de-prioritised", f"{fp_moved:,}")
        m[3].metric("Analyst hours saved per year (est.)", f"{hours / months * 12:,.0f}", f"{minutes} min/alert, {qa}% QA", delta_color="off", delta_arrow="off")
        sim = {"rules": sel, "alerts_from_rules": int(len(df)), "alerts_moved": int(len(moved)), "fp_moved": fp_moved, "real_hits_moved": hits_moved,
               "est_hours_saved_per_year": round(hours / months * 12), "assumptions": {"minutes_per_alert": minutes, "qa_sample_pct": qa},
               "rule_stats": rs[rs["rule_id"].isin(sel)].round(4).to_dict("records")}
        if st.button("Draft change request with AI", type="primary", icon=":material/auto_awesome:"):
            with st.spinner("Drafting..."):
                st.session_state["rule_memo"] = (sim, llm.run("memo", {"subject": {"type": "rule_change", "id": ",".join(sel)}, "simulation": sim},
                                                              "Draft a detection-rule change request: route these rules to batch review unless corroborated. "
                                                              "State the evidence, the residual risk from the real hits moved, the QA control, and who must approve.",
                                                              page="rule-studio", subject=",".join(sel), session_id=ui.session_id(),
                                                              fast=not st.session_state.get("thorough", False),
                                                              template={"title": "Rule change request (template)", "summary": str(sim), "proposal": "", "evidence": [],
                                                                        "risks_and_mitigations": [], "approval_required": "Rule owner + model risk", "narrative": ""}))
    else:
        st.info("Pick at least one rule.")

if "rule_memo" in st.session_state:
    sim_, res = st.session_state["rule_memo"]
    o = res["output"]
    with st.container(border=True):
        st.markdown(f"#### {o.get('title', '')} &nbsp; {ui.citation_badge(res['citations'])}", unsafe_allow_html=True)
        st.caption(f"AI-generated draft for the rule owner · model {res['meta'].get('model')}")
        st.markdown(o.get("summary", ""))
        st.markdown(f"**Proposal:** {o.get('proposal', '')}")
        for e in o.get("evidence") or []:
            st.markdown(f"- {e.get('point')}")
        for r in o.get("risks_and_mitigations") or []:
            st.markdown(f"- Risk / mitigation: {r}")
        st.markdown(f"**Approval required:** {o.get('approval_required', '')}")
    with st.form("approve-rule", border=True):
        who = st.text_input("Rule owner approving this request", value=st.session_state.get("analyst", ""))
        note = st.text_area("Comment", height=70)
        if st.form_submit_button("Approve for governance review", icon=":material/gavel:"):
            if who.strip():
                audit.log_event(who.strip(), "rule_change_request_approved", ",".join(sim_["rules"]), {"simulation": sim_, "comment": note})
                st.success("Logged in the audit trail. The rule itself is unchanged until governance applies it in the alert engine.")
            else:
                st.error("Name required.")
