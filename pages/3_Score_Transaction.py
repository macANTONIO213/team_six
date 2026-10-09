import datetime as dt

import pandas as pd
import streamlit as st

from core import evidence, llm, triage, ui

ui.page_intro(
    "Score a new transaction",
    "Real-time risk for a transaction ARGUS has never seen: network links as of its timestamp, explained signal by signal.",
    steps=["Pick a preset (the ring flow, or a brand-new account) or start blank.",
           "Edit any field. Only **Account ID** and **Amount** are required; unknown accounts and devices are treated as having no history.",
           "Press **Score transaction**: you get a risk level, a lane, the probability of a real hit and the reasons.",
           "Optionally click **Write case with AI** and record a decision."],
    tips=["Why not the ML model here? Without an alert rule the ML has no lift (AUC 0.50), so ARGUS combines signal likelihood ratios "
          "learned from 29,982 analyst decisions. Sanctions exposure is always Critical."],
)

PRESETS = {
    "Ring flow ($9,850 at 02:30)": dict(account_id="ACC0051505", counterparty_account_id="ACC0049415", amount=9850.0, currency="USD",
                                        channel="Mobile wallet", merchant_category="(none)", is_cross_border=True, device_fingerprint="",
                                        date=dt.date(2026, 9, 30), time=dt.time(2, 30)),
    "Brand-new account ($120 groceries)": dict(account_id="ACC9999999", counterparty_account_id="", amount=120.0, currency="USD", channel="Card",
                                               merchant_category="Groceries", is_cross_border=False, device_fingerprint="fp_ffffffffffff",
                                               date=dt.date(2026, 9, 30), time=dt.time(14, 0)),
}
pre = st.session_state.pop("txn_payload", None) or {}
choice = st.segmented_control("Start from", ["Blank"] + list(PRESETS), default="Blank" if pre else "Ring flow ($9,850 at 02:30)")
d = PRESETS.get(choice or "", {}) | {k: v for k, v in pre.items() if v is not None}

with st.form("txn", border=True):
    c = st.columns(3)
    account = c[0].text_input("Account ID *", d.get("account_id", ""), placeholder="ACC + 7 digits", help="The paying account.")
    cp = c[1].text_input("Counterparty account ID", d.get("counterparty_account_id", ""), placeholder="optional",
                         help="Receiving account. Flows between members of the same identity network are a strong signal.")
    amount = c[2].number_input("Amount *", min_value=0.0, value=float(d.get("amount", 0.0)), step=50.0,
                               help="In the selected currency. Converted to USD with the dataset's synthetic FX rates.")
    c = st.columns(4)
    currency = c[0].selectbox("Currency", triage.CURRENCIES, index=triage.CURRENCIES.index(d.get("currency", "USD")) if d.get("currency", "USD") in triage.CURRENCIES else 0)
    channel = c[1].selectbox("Channel", triage.CHANNELS, index=triage.CHANNELS.index(d["channel"]) if d.get("channel") in triage.CHANNELS else 0)
    merchant = c[2].selectbox("Merchant category", triage.MERCHANTS, index=triage.MERCHANTS.index(d["merchant_category"]) if d.get("merchant_category") in triage.MERCHANTS else 0)
    xb = c[3].checkbox("Cross-border", value=bool(d.get("is_cross_border", False)))
    c = st.columns(3)
    fp = c[0].text_input("Device fingerprint", d.get("device_fingerprint", ""), placeholder="optional, fp_ + 12 hex",
                         help="If other identities used the same device, that is a strong signal.")
    day = c[1].date_input("Date", d.get("date", dt.date(2026, 9, 30)))
    tm = c[2].time_input("Time", d.get("time", dt.time(12, 0)), help="Transactions between 00:00 and 05:59 carry more risk in the data.")
    go = st.form_submit_button("Score transaction", type="primary", icon=":material/bolt:")

if go:
    if not account.strip():
        st.error("Account ID is required.")
        st.stop()
    payload = {"account_id": account.strip().upper(), "counterparty_account_id": cp.strip().upper(), "amount": amount, "currency": currency,
               "channel": channel, "merchant_category": merchant, "is_cross_border": xb, "device_fingerprint": fp.strip(),
               "timestamp": f"{day} {tm.strftime('%H:%M')}"}
    try:
        with st.spinner("Resolving the account's network as of the transaction time..."):
            st.session_state["txn_result"] = (payload, triage.score_new_transaction(payload))
        st.session_state.pop("txn_case", None)
    except ValueError as e:
        st.error(str(e))
        st.stop()

if "txn_result" not in st.session_state:
    st.info("Pick a preset or fill in the form, then press **Score transaction**.", icon=":material/arrow_upward:")
    st.stop()

payload, s = st.session_state["txn_result"]
with st.container(border=True):
    st.markdown(f"### {ui.risk_pill(s['risk_level'])} &nbsp; {ui.lane_pill(s['lane'])} &nbsp; {payload['account_id']} "
                f"→ {payload.get('counterparty_account_id') or '(external)'} · {payload['amount']:,.2f} {payload['currency']} · {payload['timestamp']}",
                unsafe_allow_html=True)
    a, b = st.columns([2, 3])
    with a:
        st.metric("Probability of a real hit", f"{s['probability'] * 100:.1f}%", f"base rate {s['prior'] * 100:.1f}%", delta_color="off", delta_arrow="off")
        st.progress(min(1.0, s["probability"]))
    with b:
        if s["reasons"]:
            st.markdown("**Why** (each signal multiplies the odds by its likelihood ratio):")
            for r in s["reasons"]:
                st.markdown(f"- {r['label']} · **x{r['likelihood_ratio']:.2f}**")
        else:
            st.markdown("**Why:** no risk signals fired, so the probability stays at the base rate.")
    for n in s["notes"]:
        st.info(n, icon=":material/info:")
    st.caption(s["method"])

f = s["features"]
with st.expander("Signals computed from live data (as of the transaction time)"):
    rows = [("Amount in USD", f"{f['amount_usd']:,.2f}"), ("Hour", f["txn_hour"]),
            ("Identities sharing the holder's devices", f["holder_fp_identities"]), ("Identities on this device fingerprint", f["txn_fp_identities"]),
            ("Holder's identity network size", f["cluster_size"]), ("Counterparty in the same network", bool(f["cp_same_cluster"])),
            ("Nominee ownership links", f["nominee_links"]), ("Holder on sanctions-like list", bool(f["wl_sanctions"])),
            ("Holder on PEP-like list", bool(f["wl_pep"])), ("Counterparty on a watchlist", bool(f["cp_watchlisted"])),
            ("Owned by sanctioned party (effective %)", f"{f['owner_sanctioned_eff'] * 100:.1f}%"), ("Prior alerts on the account", f["prior_alerts"]),
            ("Account age (days)", f["account_age_days"]), ("Account type / risk rating", f"{f['account_type']} / {f['risk_rating']}")]
    st.dataframe(pd.DataFrame(rows, columns=["Signal", "Value"]).astype(str), hide_index=True, width="stretch")

st.markdown("### AI narrative")
with st.container(border=True):
    st.caption("Optional: Claude drafts a cited assessment of this transaction in its network context. If there is no history, it says so.")
    if st.button("Write case with AI", type="primary", icon=":material/auto_awesome:"):
        base_ev = evidence.build("account", payload["account_id"]) if f.get("individual_id") or f.get("entity_id") else {"subject": {"type": "account", "id": payload["account_id"]}, "note": "No record found for this account."}
        ev = {**evidence.for_llm(base_ev), "subject": {"type": "new_transaction", "id": "NEW-TXN", "account_id": payload["account_id"]},
              "new_transaction": {k: v for k, v in payload.items()}, "argus_scoring": {k: s[k] for k in ("probability", "risk_level", "lane", "reasons", "notes")}}
        with st.spinner("Claude on Amazon Bedrock is drafting..."):
            st.session_state["txn_case"] = (ev, llm.run("case", ev, "Assess the NEW transaction in new_transaction using the account's network context. "
                                                        "If there is no history, say so plainly and do not invent links.", page="score", subject=payload["account_id"],
                                                        session_id=ui.session_id(), fast=not st.session_state.get("thorough", False), template=llm.case_template(ev)))
    if "txn_case" in st.session_state:
        ev, res = st.session_state["txn_case"]
        ui.render_case(res)
if "txn_case" in st.session_state:
    ev, res = st.session_state["txn_case"]
    st.markdown("### Human decision")
    ui.decision_form(key=f"txn-{payload['account_id']}", subject_type="new_transaction", subject_id=payload["account_id"], lane=s["lane"], res=res, ev=ev)
