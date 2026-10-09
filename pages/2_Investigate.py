import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

from core import evidence, graph, llm, router, triage, ui

ui.page_intro(
    "Investigate anything",
    "Type any record ID, a name, a question or new-transaction JSON. ARGUS builds the evidence, the AI drafts a cited case, you decide.",
    steps=["Type an input and press **Enter**, or click an example chip.",
           "Review the evidence: summary card, then the **Network**, **Money flow**, **Ownership** and **Alert history** tabs.",
           "Click **Write case with AI**. Check the citation badge: green means every cited ID exists in the evidence.",
           "Fill in **Record decision**: your disposition and rationale. For a network, keep **Consolidate** ticked."],
    tips=["Names are shown to you but never sent to the AI. The AI sees only the Evidence pack tab."],
)


def _pick_example():
    v = st.session_state.get("example_pills")
    if v:
        st.session_state["pending_query"] = v
    st.session_state["example_pills"] = None


if st.session_state.get("pending_query"):
    st.session_state["investigate_query"] = st.session_state.pop("pending_query")

s1, s2 = st.columns([5, 1.2], vertical_alignment="bottom")
s1.text_input("Search", key="investigate_query", placeholder="e.g. ALR0005789 · fp_0e79cb1b294b · Cameron Beard · Who shares a phone with IND0046429?")
with s2.popover("Accepted inputs", icon=":material/info:", use_container_width=True):
    st.dataframe(pd.DataFrame(ui.INPUT_FORMATS, columns=["Input", "Format", "Example"]), hide_index=True, width="stretch")
st.pills("Examples", ui.DEMO_INPUTS, key="example_pills", on_change=_pick_example, label_visibility="collapsed")

q = (st.session_state.get("investigate_query") or "").strip()
if not q:
    with st.container(border=True):
        st.markdown("**Start here:** click **ALR0005789** above. Analysts closed this alert as a false positive; ARGUS puts it at the top of the HOT lane.")
        st.caption("Or open the Triage Queue and pick any alert, or type an ID from the 'Accepted inputs' list.")
    st.stop()

route = router.route(q)

if route.kind == "invalid":
    st.warning(route.message, icon=":material/help:")
    st.stop()

if route.kind == "rule":
    st.session_state["rule_focus"] = route.value
    st.info(f"{route.value} is an alert rule. Rule Studio shows its false-positive rate and lets you simulate routing it.")
    if st.button(f"Open {route.value} in Rule Studio", type="primary", icon=":material/tune:"):
        st.switch_page("pages/4_Rule_Studio.py")
    st.stop()

if route.kind == "new_txn":
    st.session_state["txn_payload"] = route.payload
    st.info("That is a new transaction. Score it in real time on the Score a New Transaction page (the form will be pre-filled).")
    if st.button("Score this transaction", type="primary", icon=":material/bolt:"):
        st.switch_page("pages/3_Score_Transaction.py")
    st.stop()

if route.kind == "name":
    st.markdown(f"**Records matching '{route.value}'.** Pick one:")
    for c in route.candidates:
        with st.container(border=True):
            a, b = st.columns([4, 1], vertical_alignment="center")
            a.markdown(f"**{c['label']}** · {c['kind']} `{c['id']}` · match {c['score']:.0f}%")
            if b.button("Open", key=f"cand-{c['id']}", icon=":material/arrow_forward:", use_container_width=True):
                st.session_state["pending_query"] = c["id"]
                st.rerun()
    st.stop()

if route.kind == "question":
    st.markdown(f"<div class='argus-note'><b>Question:</b> {route.value}</div>", unsafe_allow_html=True)
    st.write("")
    if not route.ids:
        st.warning("No record found: the question names no record ID or known name. Add an ID, e.g. IND0046429.")
        st.stop()
    packs = {rid: ui.cached_evidence(kind, rid) for kind, rid in route.ids[:2]}
    combined = {"question": route.value, "evidence_by_subject": {k: evidence.for_llm(v) for k, v in packs.items()}}
    key = f"qa:{route.value}"
    st.caption(f"ARGUS found {', '.join(packs)} in your question and built the evidence. The AI answers only from that evidence.")
    if key not in st.session_state and st.button("Answer with AI (cited)", type="primary", icon=":material/auto_awesome:"):
        with st.spinner("Claude on Amazon Bedrock is reading the evidence..."):
            st.session_state[key] = llm.run("qa", combined, f"Answer the analyst's question using only EVIDENCE: {route.value}",
                                            page="investigate-qa", subject=",".join(packs), session_id=ui.session_id(),
                                            fast=not st.session_state.get("thorough", False), template=llm.qa_template(route.value, combined))
    if key in st.session_state:
        res = st.session_state[key]
        with st.container(border=True):
            st.markdown(ui.citation_badge(res["citations"]), unsafe_allow_html=True)
            if res["meta"].get("template"):
                st.warning(res["meta"]["status"])
            st.markdown(res["output"].get("answer", ""))
            for p in res["output"].get("key_points") or []:
                st.markdown(f"- {p.get('point')}  \n  {ui.chips(p.get('citations') or [])}", unsafe_allow_html=True)
            st.caption(f"AI-generated answer grounded in the evidence below · model {res['meta'].get('model')}")
    cols = st.columns(len(packs))
    for i, rid in enumerate(packs):
        if cols[i].button(f"Open {rid} as a full investigation", key=f"open-{rid}", icon=":material/search:"):
            st.session_state["pending_query"] = rid
            st.rerun()
    with st.expander("Evidence the AI used"):
        st.json(combined, expanded=False)
    st.stop()

# ------------------------------------------------------------------ a record
with st.spinner("Resolving identities, ownership and history..."):
    ev = ui.cached_evidence(route.kind, route.value)
if ev.get("not_found"):
    st.warning(ev["note"])
    st.stop()

subj = ev["subject"]
net = ev.get("network") or {}
own = ev.get("ownership") or {}
alerts = ev.get("alerts") or {}
tx = ev.get("transactions") or {}
model = ev.get("model") or {}
case_key = f"case:{subj['id']}"
res = st.session_state.get(case_key)
decided = st.session_state.get(f"decided:{subj['id']}")
ui.stepper(["Evidence", "AI case", "Human decision"], done=1 + bool(res) + bool(decided))

ids_for_labels = tuple(set((net.get("members") or []) + [subj.get("id"), subj.get("holder_id"), subj.get("entity_id"), own.get("sanctioned_root")]
                           + [h.get("parent_entity_id") for h in own.get("chain") or []] + [h.get("child_entity_id") for h in own.get("chain") or []]) - {None})
labels = ui.labels_for(ids_for_labels)
holder = subj.get("holder_id")
name = labels.get(subj["id"]) or labels.get(holder or "")

with st.container(border=True):
    st.subheader(f"{subj['type'].replace('_', ' ').title()} {subj['id']}" + (f"  ·  {name}" if name else ""))
    pills = []
    if model.get("lane"):
        pills.append(ui.lane_pill(model["lane"]))
    if net.get("is_network"):
        pills.append(ui.pill(f"network {net['cluster_id']}: {net['cluster_size']} identities", "#7c3aed"))
    if own.get("fifty_percent_rule"):
        pills.append(ui.pill(f"{own['eff_share'] * 100:.1f}% owned by sanctioned {own['sanctioned_root']}", "#dc2626"))
    if any(w.get("list_type") == "Sanctions-like" for w in ev.get("watchlist_hits") or []):
        pills.append(ui.pill("sanctions-like list hit", "#dc2626"))
    if pills:
        st.markdown(" &nbsp; ".join(pills), unsafe_allow_html=True)
    if model.get("lane"):
        pct = model.get("argus_percentile") or 0
        st.markdown(f"**ML score {model.get('argus_score', 0):.2f}** (percentile {pct * 100:.0f} of all alerts) · "
                    f"today's score {model.get('legacy_score', 0):.2f}")
        if model.get("lane") == "HOT" and pct < 0.5:
            st.markdown("<div class='argus-note'>The ML score is low because it learns from past analyst decisions, and analysts closed most "
                        "of this network's alerts as false positives. That is exactly the blind spot: the <b>network signals override it</b> "
                        "and send this alert to the HOT lane.</div>", unsafe_allow_html=True)
    if model.get("reasons"):
        st.markdown("**Why:** " + ui.chips(model["reasons"]), unsafe_allow_html=True)
    if ev.get("replay_only", {}).get("original_disposition"):
        st.caption(f"Backtest replay: in reality one analyst marked this alert **{ev['replay_only']['original_disposition']}**. "
                   "Shown for comparison only; never sent to the AI.")

m = st.columns(5)
m[0].metric("Identities in network", net.get("cluster_size", 1), help="People linked by shared devices, phones, emails, IDs or addresses.")
m[1].metric("Accounts", len(ev.get("accounts") or []))
m[2].metric("Money moved", f"${tx.get('total_usd', 0) / 1e6:.2f}M" if tx.get("total_usd", 0) >= 1e5 else f"${tx.get('total_usd', 0):,.0f}",
            help="Total value of transactions on these accounts (USD, synthetic FX).")
m[3].metric("Alerts on these accounts", alerts.get("count", 0),
            f"{alerts.get('n_rules', 0)} rules · {alerts.get('closed_false_positive', 0)} closed FP" if alerts.get("count") else None, delta_color="off", delta_arrow="off")
m[4].metric("Separate investigations", (alerts.get("investigations") or {}).get("count", 0),
            f"{(alerts.get('investigations') or {}).get('analyst_hours', 0):,.0f} analyst-hours" if alerts.get("count") else None, delta_color="off", delta_arrow="off")

tabs = st.tabs([":material/hub: Network", ":material/payments: Money flow", ":material/account_tree: Ownership",
                ":material/notifications: Alert history", ":material/description: Evidence pack"])
with tabs[0]:
    html = graph.identity_network(ev, labels)
    if html and (net.get("shared_links") or len(net.get("members", [])) > 1):
        st.caption("Who is linked to whom, and through what. Drag nodes to explore; hover for details.")
        ui.legend([("person", "#3b82f6"), ("on a watchlist", "#dc2626"), ("shared device (diamond)", "#f59e0b"),
                   ("shared phone", "#a855f7"), ("shared address", "#10b981"), ("account (square)", "#64748b")])
        components.html(html, height=580, scrolling=False)
        rows = [{"shared": l["type"].replace("_", " "), "value": l.get("value") or ", ".join(l.get("address_ids", [])[:3]),
                 "identities": l["n_identities"], "members": ", ".join(l["members"])} for l in net.get("shared_links") or []]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("No shared devices, phones, emails, IDs or addresses: this subject is not part of a linked identity network.")
with tabs[1]:
    if tx.get("count"):
        st.caption("Transactions on these accounts. Member-to-member flows and amounts just under $10K are classic mule and structuring patterns.")
        c = st.columns(4)
        c[0].metric("Transactions", tx["count"])
        c[1].metric("Between network members", f"{tx.get('member_flow_share', 0) * 100:.0f}%")
        c[2].metric("Just under $10K", tx.get("near_10k_count", 0))
        c[3].metric("Between 00:00 and 05:59", tx.get("night_count", 0))
        s = pd.DataFrame(tx.get("sample") or [])
        if len(s):
            s["kind"] = s["member_flow"].map({True: "member-to-member", False: "external"})
            fig = px.scatter(s, x="txn_ts", y="amount_usd", color="kind", hover_data=["txn_id", "account_id", "counterparty_account_id", "device_fingerprint"],
                             title="Sample of flagged and recent transactions", height=330,
                             color_discrete_map={"member-to-member": "#dc2626", "external": "#64748b"})
            st.plotly_chart(fig, width="stretch")
            st.dataframe(s.drop(columns=["kind"]), hide_index=True, width="stretch",
                         column_config={"amount_usd": st.column_config.NumberColumn("amount", format="dollar")})
    else:
        st.info("No transactions on these accounts.")
with tabs[2]:
    if own:
        st.caption("Who owns this company, directly and through chains. Red arrows: the strongest path from a sanctions-listed owner.")
        if own.get("sanctioned_root"):
            st.markdown(f"**Effective ownership by sanctions-listed {own['sanctioned_root']}: {own['eff_share'] * 100:.1f}%** over {own['hops']} hops "
                        f"(listed {own['root_listed_date']}). 50% rule: **{'YES' if own.get('fifty_percent_rule') else 'no'}**.")
            st.caption(own.get("note", ""))
        for lp in own.get("ownership_loops") or []:
            st.warning(f"Ownership loop: {lp['pair'][0]} and {lp['pair'][1]} each own part of the other. The traversal skips nodes it has already "
                       "visited, so it always terminates.")
        ui.legend([("this company", "#111827"), ("sanctions-listed", "#dc2626"), ("other company", "#0ea5e9")])
        html = graph.ownership_network(ev, labels)
        if html:
            components.html(html, height=500)
    else:
        st.info("Ownership applies to companies and suppliers. Try ENT000783 or SUP000272.")
with tabs[3]:
    if alerts.get("count"):
        st.markdown(f"**{alerts['count']} alerts · {alerts['n_rules']} rules · {alerts['distinct_analysts']} different analysts · "
                    f"{alerts['closed_false_positive']} closed as false positive** · first {alerts['first_alert']} · last {alerts['last_alert']}")
        st.caption("Alerts per rule on these accounts. Different rules fired on the same network, and each alert went to whoever was on shift.")
        st.bar_chart(pd.Series(alerts["rules"], name="alerts"), horizontal=True, height=300)
        inv = alerts.get("investigations") or {}
        if inv.get("count"):
            st.markdown(f"{inv['count']} separate investigations · {inv['analyst_hours']:,.0f} analyst-hours · outcomes: "
                        + ", ".join(f"{k} ({v})" for k, v in inv["outcomes"].items()))
    else:
        st.info("No alerts on these accounts.")
with tabs[4]:
    st.caption("Exactly what the AI may use: record IDs, hashes, amounts, dates and flags. Names, demographics and staff IDs are stripped before sending.")
    st.json(evidence.for_llm(ev), expanded=False)

# ------------------------------------------------------------------ AI case + human decision
st.markdown("### AI case writer")
with st.container(border=True):
    if not res:
        st.caption("Claude on Amazon Bedrock reads the evidence pack and drafts a structured case: risk level, recommended action, findings with "
                   "citations, counter-evidence and open questions. Typically 10-18 seconds; demo subjects are cached.")
    c1, c2, _ = st.columns([1.3, 1, 3])
    if c1.button("Write case with AI" if not res else "Rewrite with AI", type="primary" if not res else "secondary",
                 icon=":material/auto_awesome:", key=f"write-{subj['id']}", use_container_width=True):
        with st.spinner("Claude on Amazon Bedrock is drafting a cited case..."):
            st.session_state[case_key] = ui.write_case(ev, subj["id"], "investigate", use_cache=res is None)
        st.rerun()
    if res and c2.button("Clear", key=f"clear-{subj['id']}", icon=":material/close:", use_container_width=True):
        st.session_state.pop(case_key)
        st.rerun()
    if res:
        ui.render_case(res)

st.markdown("### Human decision")
linked = alerts.get("all_alert_ids") if net.get("is_network") or subj["type"] in ("alert", "investigation") else None
if subj["type"] == "alert" and not net.get("is_network"):
    linked = triage.network_alerts_for(subj["id"])
ui.decision_form(key=subj["id"], subject_type=subj["type"], subject_id=subj["id"], lane=model.get("lane"), res=res, ev=ev,
                 linked_alerts=linked)
