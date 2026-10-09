import plotly.graph_objects as go
import streamlit as st

from core import insights, ui


@st.cache_data(ttl=3600, show_spinner="Computing live from the REPH data...")
def overview_numbers():
    ring_ids = insights.ring_cluster_ids()
    return {
        "baseline": insights.baseline(),
        "quarters": insights.quarterly_volume(),
        "ring": insights.ring_summary(ring_ids[0]) if ring_ids else {},
        "card": insights.model_card(),
        "effort": {k: v for k, v in insights.investigation_effort().items() if k != "by_action"},
    }


n = overview_numbers()
b, ring, m, eff = n["baseline"], n["ring"], n["card"]["metrics"], n["effort"]

ui.page_intro(
    "ARGUS",
    "Alert Reasoning & Graph-Unified Screening. One analyst sees the whole network, not one alert at a time.",
    steps=["Read the story below: one ring, 137 alerts, 100 analysts.",
           "Open **Triage Queue** to see every 2026 alert in lanes, or click an example at the bottom of this page.",
           "On **Investigate**, review the evidence, click **Write case with AI**, then **Record decision**.",
           "Try your own input: any ID, a name, a question, or a new transaction on **Score a New Transaction**."],
    tips=["All numbers are computed live from the REPH synthetic data (as of 2026-09-30). They are prototype findings, not validated REPH results."],
)

if ring:
    st.markdown(
        f"<div class='argus-story'><b>The rule engine flagged one ring {ring['n_alerts']} times. Nobody saw the whole ring.</b><br>"
        f"{ring['n_members']} identities sharing devices, a phone and addresses moved <b>${ring['total_usd'] / 1e6:.2f}M</b> "
        f"({ring['member_flow_share'] * 100:.0f}% between themselves). <b>{ring['n_analysts']} different analysts</b> each saw one alert and closed "
        f"<b>{ring['closed_fp']}</b> as false positives. {ring['n_investigations']} separate investigations cost "
        f"{ring['investigation_hours']:,.0f} analyst-hours. <b>{ring['share_usd_after_first_alert'] * 100:.2f}%</b> of the money moved "
        f"after the first alert on {ring['first_alert']}.</div>", unsafe_allow_html=True)
    st.write("")

q = n["quarters"]
c = st.columns(5)
c[0].metric("False-positive rate", f"{b['fp_rate'] * 100:.1f}%", f"{b['fp']:,} of {b['closed']:,}", delta_color="off", delta_arrow="off",
            help="Baseline to beat (REPH hackathon package): share of closed alerts that were false positives.")
c[1].metric("Alerts per quarter", f"x{q['alerts'].iloc[-1] / q['alerts'].iloc[0]:.1f}",
            f"{q['alerts'].iloc[0]:,} to {q['alerts'].iloc[-1]:,}", delta_color="off", delta_arrow="off",
            help="Volume tripled while the FP rate stayed at ~84% every quarter.")
c[2].metric("Ranking AUC (ARGUS)", f"{m['auc_argus']:.2f}", f"vs {m['auc_legacy_score']:.2f} today", delta_color="off", delta_arrow="off",
            help=f"Area under the ROC curve on {m['test_rows']:,} alerts from 2026 that the model never saw (trained on 2024-25). 0.5 = coin flip.")
c[3].metric("FP reviews avoided", f"-{m['queue_argus']['fp_reviews_avoided_share'] * 100:.0f}%", "at 90% recall", delta_color="off", delta_arrow="off",
            help=f"Working the queue in ARGUS order finds 90% of real alerts after {m['queue_argus']['queue_share_for_target'] * 100:.1f}% of it: "
                 f"{m['queue_argus']['fp_reviews_avoided']:,} fewer false-positive reviews in 2026.")
c[4].metric("Hours per investigation", f"{eff['median_minutes'] / 60:.1f} h", f"median, {eff['median_steps']:.0f} steps", delta_color="off", delta_arrow="off",
            help="Median hands-on minutes per investigation; gathering evidence and drafting the narrative take 63% of it.")
left, right = st.columns([3, 2], gap="large")
with left:
    fig = go.Figure()
    fig.add_bar(x=q["quarter"], y=q["alerts"], name="Alerts", marker_color="#2563eb")
    fig.add_scatter(x=q["quarter"], y=q["fp_rate"] * 100, name="False-positive rate %", yaxis="y2", mode="lines+markers", line_color="#dc2626")
    fig.update_layout(height=330, margin=dict(l=10, r=10, t=40, b=10), title="Alerts per quarter tripled; the false-positive rate never moved",
                      yaxis=dict(title="alerts"), yaxis2=dict(title="FP %", overlaying="y", side="right", range=[0, 100]),
                      legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, width="stretch")
with right:
    st.markdown("#### How ARGUS works")
    for icon, head, text in [
        (":material/hub:", "Resolve", "Graph AI links each alert to the people, devices, phones, addresses, accounts and owners behind it."),
        (":material/sort:", "Rank", "ML trained on 29,982 analyst decisions puts real risk first, with reasons."),
        (":material/edit_note:", "Write", "Claude on Amazon Bedrock drafts a cited case; IDs it cannot verify are blocked."),
        (":material/gavel:", "Decide", "The analyst accepts, edits or overrides. Every decision is audited. ARGUS never acts alone."),
    ]:
        st.markdown(f"{icon} **{head}**: {text}")
    b1, b2 = st.columns(2)
    if b1.button("Investigate the ring", type="primary", icon=":material/play_arrow:", use_container_width=True):
        ui.go_investigate("ALR0005789")
    b2.page_link("pages/1_Triage_Queue.py", label="Open the triage queue", icon=":material/list:")

st.markdown("#### Try an example")
st.caption("Each card opens on the Investigate page. Judges: you can also type any ID, name or question there.")
cols = st.columns(4)
for i, (value, desc) in enumerate(ui.EXAMPLES[:8]):
    with cols[i % 4].container(border=True, height=185):
        st.markdown(f"**{value if len(value) < 26 else value[:24] + '...'}**")
        st.caption(desc)
        if st.button("Open", key=f"ex-{i}", icon=":material/arrow_forward:"):
            ui.go_investigate(value)
