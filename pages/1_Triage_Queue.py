import streamlit as st

from core import insights, triage, ui

ui.page_intro(
    "Triage queue",
    "Every 2026 alert in a lane, ranked by risk signals and the ML score, with the reasons. The model never saw these alerts (out-of-time replay).",
    steps=["Read the four lane cards: what each lane means and how good it is at finding real hits.",
           "Filter lanes or a rule (try **R017**). The table is ordered HOT → PRIORITY → STANDARD → NOISE, then by number of risk signals, then by ML score.",
           "**Click a row** to select an alert, then press **Investigate this alert**.",
           "Compare with the last column: what analysts really did with that alert."],
    tips=["NOISE is batch-reviewed with QA sampling; ARGUS never closes an alert on its own."],
)


@st.cache_data(ttl=900, show_spinner=False)
def lanes():
    return insights.lane_stats()


ls = lanes()
cols = st.columns(4)
for i, r in ls.iterrows():
    with cols[i].container(border=True):
        st.markdown(f"{ui.lane_pill(r['lane'])} &nbsp; **{r['share_alerts'] * 100:.1f}%** of alerts", unsafe_allow_html=True)
        st.markdown(f"holds **{r['share_true_hits'] * 100:.1f}%** of real hits · FP rate **{r['fp_rate'] * 100:.1f}%**")
        st.caption(ui.LANE_MEANING[r["lane"]])

f1, f2, f3 = st.columns([2, 1, 1], vertical_alignment="bottom")
lane_sel = f1.multiselect("Lanes", ["HOT", "PRIORITY", "STANDARD", "NOISE"], default=["HOT", "PRIORITY", "STANDARD", "NOISE"])
rule = f2.text_input("Rule filter", "", placeholder="e.g. R017", help="Alert rule ID, R + 3 digits.").strip().upper() or None
only_open = f3.toggle("Open alerts only", value=False, help="Almost every alert in the data is already closed, so the default shows the 2026 replay.")


@st.cache_data(ttl=900, show_spinner="Loading queue...")
def load(lanes_: tuple, rule_: str | None, open_: bool):
    return triage.queue(list(lanes_), rule=rule_, only_open=open_, limit=400)


df = load(tuple(lane_sel), rule, only_open)
if df.empty:
    st.info("No alerts match these filters.")
    st.stop()

view = df[["alert_id", "lane", "signals", "argus_score", "legacy_score", "rule_id", "disposition", "amount_usd", "channel", "created_at",
           "reasons", "rule_name", "cluster_id", "account_id"]]
st.caption(f"Showing the top {len(view)} alerts. Click a row to select it.")
event = st.dataframe(
    view, hide_index=True, width="stretch", height=420, on_select="rerun", selection_mode="single-row", key="queue_table",
    column_config={
        "alert_id": st.column_config.TextColumn("Alert"), "lane": st.column_config.TextColumn("Lane", width="small"),
        "signals": st.column_config.NumberColumn("Signals", width="small", help="Network and risk signals fired (shared device, linked network, "
                                                 "member-to-member flow, night, just under $10K, watchlists, sanctioned owner). Orders alerts within a lane."),
        "argus_score": st.column_config.ProgressColumn("ARGUS score", min_value=0, max_value=1, format="%.2f",
                                                       help="Probability of a real hit (out-of-time)."),
        "legacy_score": st.column_config.NumberColumn("Today's score", format="%.2f", help="The score analysts sort by today (AUC 0.51)."),
        "rule_id": st.column_config.TextColumn("Rule", width="small"), "rule_name": st.column_config.TextColumn("Rule name"),
        "created_at": st.column_config.DatetimeColumn("Created", format="YYYY-MM-DD HH:mm"),
        "amount_usd": st.column_config.NumberColumn("Amount", format="dollar"), "channel": st.column_config.TextColumn("Channel"),
        "reasons": st.column_config.TextColumn("Why (historical lift)", width="large"),
        "disposition": st.column_config.TextColumn("What analysts really did"),
        "cluster_id": st.column_config.TextColumn("Network", help="Linked identity network, if any."),
        "account_id": st.column_config.TextColumn("Account"),
    },
)
rows = event.selection.rows if event and event.selection else []
pick = view.iloc[rows[0]]["alert_id"] if rows else view.iloc[0]["alert_id"]
with st.container(border=True):
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    sel = view[view["alert_id"] == pick].iloc[0]
    c1.markdown(f"{'Selected' if rows else 'Top of the queue'}: **{pick}** &nbsp; {ui.lane_pill(sel['lane'])} &nbsp; "
                f"ARGUS {sel['argus_score']:.2f} · {sel['rule_id']} {sel['rule_name']} · analysts: *{sel['disposition']}*",
                unsafe_allow_html=True)
    if c2.button("Investigate this alert", type="primary", icon=":material/search:", use_container_width=True):
        ui.go_investigate(pick)
