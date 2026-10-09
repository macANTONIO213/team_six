import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core import data, evidence, graph, insights, llm, ui

ui.page_intro(
    "Supplier Risk 360",
    "Cross-area: suppliers → company → sanctions lists and ownership chains → invoices received after the listing date. "
    "ARGUS recommends a hold; two people must approve it.",
    steps=["Read the totals: sanctioned suppliers, money already paid after listing, and money still payable.",
           "**Click a supplier row** in the table (sorted by money still payable). SUP000272 is pre-selected.",
           "Review its pending invoices and ownership, then click **Draft hold memo with AI**.",
           "Record the decision. A hold needs a second, different approver (Impact & Governance page)."],
    tips=["Supplier data comes from the raw finance files, cleaned: near-duplicates dropped, 3 date formats parsed, orphan supplier IDs excluded."],
)


@st.cache_data(ttl=900, show_spinner=False)
def load():
    return insights.supplier_summary(), data.q("""SELECT supplier_id, entity_id, risk_tier, category, country, exposure, list_type,
                                                         CAST(exposure_date AS DATE) AS exposure_date, eff_share, invoices_after,
                                                         paid_after_usd, pending_after_usd, pending_invoices
                                                  FROM supplier_exposure ORDER BY pending_after_usd DESC""")


s, exp = load()
c = st.columns(4)
c[0].metric("Suppliers on sanctions-like lists", s["n_sanctions_listed"], f"{s['n_listed_rated_low']} rated Low risk on file", delta_color="off", delta_arrow="off")
c[1].metric("Paid after listing", f"${s['paid_after_usd'] / 1e6:.1f}M", "on invoices received after the listing date", delta_color="off", delta_arrow="off")
c[2].metric("Approved or on hold now", f"${s['pending_after_usd'] / 1e6:.2f}M", f"{s['pending_invoices']} invoices: can still be stopped", delta_color="off", delta_arrow="off")
c[3].metric("Owned ≥50% by a sanctioned party", s["n_owned_ge50"], "suppliers not listed themselves", delta_color="off", delta_arrow="off")
cl = s["cleaning"]
st.caption(f"Data cleaning: {cl['suppliers']['near_duplicates_dropped']} near-duplicate suppliers and {cl['invoices']['near_duplicates_dropped']:,} "
           f"near-duplicate invoices dropped; 3 date formats parsed ({cl['invoices']['received_at_unparsed']} failures); "
           f"{cl['invoices']['orphan_supplier_invoices']:,} invoices with a supplier ID matching no supplier flagged and excluded.")

event = st.dataframe(
    exp, hide_index=True, width="stretch", height=260, on_select="rerun", selection_mode="single-row", key="sup_table",
    column_config={"supplier_id": "Supplier", "entity_id": "Company", "risk_tier": "Risk tier on file", "category": "Category",
                   "country": "Country", "exposure": "Exposure", "list_type": "List", "exposure_date": "Exposed since",
                   "eff_share": st.column_config.NumberColumn("Sanctioned ownership", format="percent"),
                   "invoices_after": "Invoices after", "paid_after_usd": st.column_config.NumberColumn("Paid after", format="dollar"),
                   "pending_after_usd": st.column_config.NumberColumn("Payable now", format="dollar"), "pending_invoices": "Invoices payable"},
)
rows = event.selection.rows if event and event.selection else []
options = exp["supplier_id"].tolist()
sup = exp.iloc[rows[0]]["supplier_id"] if rows else ("SUP000272" if "SUP000272" in options else options[0])

ev = ui.cached_evidence("supplier", sup)
labels = ui.labels_for(tuple({sup, ev["subject"].get("entity_id"), (ev.get("ownership") or {}).get("sanctioned_root")} - {None}))
se = ev.get("supplier_exposure") or {}
with st.container(border=True):
    st.subheader(f"{sup} · {labels.get(sup, '')} ({ev['subject'].get('entity_id')})")
    st.markdown(f"Risk tier on file: **{(ev.get('supplier') or {}).get('risk_tier')}** · exposure: **{se.get('exposure')}** since **{se.get('exposure_date')}** · "
                f"{se.get('invoices_after_exposure', 0)} invoices after · paid **USD {se.get('paid_after_usd', 0):,.0f}** · "
                f"payable now **USD {se.get('pending_after_usd', 0):,.0f}** ({se.get('pending_invoices', 0)} invoices)")
    t1, t2 = st.tabs([":material/receipt_long: Invoices payable now", ":material/account_tree: Ownership"])
    with t1:
        st.dataframe(pd.DataFrame(se.get("pending_sample") or []), hide_index=True, width="stretch",
                     column_config={"amount_usd": st.column_config.NumberColumn("amount", format="dollar")})
    with t2:
        ui.legend([("this company", "#111827"), ("sanctions-listed", "#dc2626"), ("other company", "#0ea5e9")])
        html = graph.ownership_network(ev, labels)
        if html:
            components.html(html, height=460)

key = f"hold:{sup}"
st.markdown("### AI hold memo")
with st.container(border=True):
    st.caption("Claude drafts a cited assessment and recommends whether to hold payments. Compliance must confirm.")
    if st.button("Draft hold memo with AI", type="primary", icon=":material/auto_awesome:"):
        with st.spinner("Drafting..."):
            st.session_state[key] = llm.run("case", evidence.for_llm(ev), f"Assess supplier {sup}. If sanctions exposure exists and invoices are pending, "
                                            "recommend 'Hold supplier payments pending review' and say compliance must confirm.",
                                            page="supplier-360", subject=sup, session_id=ui.session_id(), fast=not st.session_state.get("thorough", False),
                                            template=llm.case_template(ev))
    if key in st.session_state:
        ui.render_case(st.session_state[key])
st.markdown("### Human decision")
ui.decision_form(key=key, subject_type="supplier", subject_id=sup, lane=None, res=st.session_state.get(key), ev=ev,
                 actions=["Hold supplier payments pending review", "Monitor", "Escalate to investigation", "Suggest close as FP"])
