"""Shared Streamlit UI: design system, help patterns, AI case rendering and the human decision form."""
from __future__ import annotations

import uuid

import streamlit as st

from core import audit, config, evidence, guardrails, llm, router

LANE_COLORS = {"HOT": "#dc2626", "PRIORITY": "#ea580c", "STANDARD": "#2563eb", "NOISE": "#64748b"}
RISK_COLORS = {"Critical": "#7f1d1d", "High": "#dc2626", "Medium": "#d97706", "Low": "#16a34a"}
LANE_MEANING = {
    "HOT": "Network signals: linked identities, shared device, >1 nominee link, or a 00:00-05:59 transaction. Review first.",
    "PRIORITY": "Raised by a model-based rule (FP rate 67% vs 88% for fixed rules).",
    "STANDARD": "Everything else, ordered by risk signals, then ML score.",
    "NOISE": "R017 / R023 with nothing corroborating. Batch review with QA sampling; never auto-closed.",
}

# (input, what it shows) - used by Overview, Investigate and Help
EXAMPLES = [
    ("ALR0005789", "The hidden ring: a HOT alert analysts closed as a false positive"),
    ("ALR0010490", "A NOISE alert: $225 ATM, name-similarity rule, nothing corroborating"),
    ("IND0057606", "Ring member on a sanctions-like list since 2020"),
    ("fp_0e79cb1b294b", "One device fingerprint shared by 7 identities"),
    ("ENT000783", "Not listed, but 83.9% owned by a sanctioned company (4 hops)"),
    ("ENT009514", "Ownership loop: two companies own each other"),
    ("SUP000272", "Sanctions-listed supplier with invoices still payable"),
    ("Who shares a phone with IND0046429?", "A free-text question answered with citations"),
    ("Cameron Beard", "A name: fuzzy match, then pick the record"),
    ("INV000001", "An investigation (INV + 6 digits; INV + 7 digits is an invoice)"),
]
DEMO_INPUTS = [e[0] for e in EXAMPLES]

INPUT_FORMATS = [
    ("Alert", "ALR + 7 digits", "ALR0005789"), ("Transaction", "TXN + 8 digits", "TXN00190688"),
    ("Account", "ACC + 7 digits", "ACC0051505"), ("Person", "IND + 7 digits", "IND0057606"),
    ("Company", "ENT + 6 digits", "ENT000783"), ("Supplier", "SUP + 6 digits", "SUP000272"),
    ("Device", "DEV + 7 digits", "DEV0060659"), ("Device fingerprint", "fp_ + 12 hex", "fp_0e79cb1b294b"),
    ("Investigation", "INV + 6 digits", "INV000001"), ("Invoice", "INV + 7 digits", "INV0000001"),
    ("KYC case", "KYC + 6 digits", "KYC010667"), ("Watchlist entry", "WL + 6 digits", "WL001493"),
    ("Ownership link", "OWN + 7 digits", "OWN0008019"), ("Alert rule", "R + 3 digits", "R017"),
    ("Name", "person, company or supplier", "Cameron Beard"),
    ("Question", "free text containing an ID", "Who shares a phone with IND0046429?"),
    ("New transaction", "JSON with account_id and amount", '{"account_id": "ACC0051505", "amount": 9850}'),
]

GLOSSARY = {
    "Lane": "Where an alert lands in the queue: HOT, PRIORITY, STANDARD or NOISE. Lanes order work; they never close alerts.",
    "ARGUS score": "Probability that an alert is a real hit, from a model trained on 2024-25 analyst decisions. 2026 scores are out of time.",
    "Today's score": "The score analysts sort by today (MDL0005 / rule score). Its AUC is 0.51: no better than chance.",
    "Real hit": "An alert analysts did not close as a false positive (true positive, monitoring or escalated).",
    "Lift": "How much more often a signal appears on real hits than on average. x3.1 means three times the base rate of real hits.",
    "Likelihood ratio": "P(signal | real hit) / P(signal | false positive). Used to score new transactions transparently.",
    "Network": "People linked by shared device fingerprints, phones, emails, ID numbers or addresses (connected components of the identity graph).",
    "Effective ownership": "Product of ownership % along a chain (max 4 hops, loops skipped). A lower bound: it follows the strongest single path.",
    "50% rule": "An entity owned 50% or more by sanctioned parties is treated as sanctioned even if it is not listed itself.",
    "Citation badge": "Green: every ID in the AI text exists in the evidence. Red: an unknown ID was cited; recording the decision is blocked until you edit or regenerate.",
    "Consolidate": "Merge all alerts on a linked network into ONE network case so one analyst sees everything.",
    "Second approver": "SAR-like referrals and supplier holds need a different person to approve (Impact & Governance page).",
    "Replay": "The queue replays 2026 alerts that the model never saw, showing what analysts really did, for comparison.",
}

_CSS = """
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 3rem;}
[data-testid="stMetric"] {background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 14px;}
[data-testid="stMetricLabel"] p {font-size: 0.82rem; color: #475569;}
.argus-story {border-left: 6px solid #dc2626; background: #fef2f2; padding: 14px 18px; border-radius: 8px; color: #1f2937; line-height: 1.55;}
.argus-note {border-left: 4px solid #7c3aed; background: #f5f3ff; padding: 10px 14px; border-radius: 6px; color: #1f2937;}
.argus-steps {display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0 10px 0;}
.argus-step {padding: 5px 12px; border-radius: 16px; font-size: 0.85rem; font-weight: 600; border: 1px solid #cbd5e1; color: #475569; background: #fff;}
.argus-step.done {background: #dcfce7; border-color: #16a34a; color: #14532d;}
.argus-step.now {background: #ede9fe; border-color: #7c3aed; color: #3b0764;}
.argus-chip {display: inline-block; padding: 2px 9px; margin: 2px 4px 2px 0; border-radius: 12px; font-size: 0.8rem; background: #f1f5f9; border: 1px solid #e2e8f0; color: #334155;}
.argus-legend span {display: inline-flex; align-items: center; margin-right: 14px; font-size: 0.82rem; color: #334155;}
.argus-legend i {display: inline-block; width: 12px; height: 12px; margin-right: 5px; border-radius: 50%;}
.argus-sub {color: #64748b; font-size: 0.95rem; margin-top: -0.6rem; margin-bottom: 0.6rem;}
</style>
"""


def apply_style() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def pill(text: str, color: str) -> str:
    return (f"<span style='background:{color};color:#fff;padding:2px 10px;border-radius:12px;"
            f"font-size:0.85rem;font-weight:600;white-space:nowrap'>{text}</span>")


def lane_pill(lane: str | None) -> str:
    return pill(lane or "-", LANE_COLORS.get(lane or "", "#64748b"))


def risk_pill(level: str | None) -> str:
    return pill(level or "-", RISK_COLORS.get(level or "", "#64748b"))


def chips(items: list[str]) -> str:
    return "".join(f"<span class='argus-chip'>{i}</span>" for i in items)


def stepper(steps: list[str], done: int, current: int | None = None) -> None:
    html = []
    for i, s in enumerate(steps):
        cls = "done" if i < done else ("now" if i == (current if current is not None else done) else "")
        mark = "&#10003; " if i < done else f"{i + 1}. "
        html.append(f"<span class='argus-step {cls}'>{mark}{s}</span>")
    st.markdown(f"<div class='argus-steps'>{''.join(html)}</div>", unsafe_allow_html=True)


def page_intro(title: str, subtitle: str, steps: list[str], tips: list[str] | None = None) -> None:
    """Title + one-line purpose + a 'How to use this page' popover."""
    left, right = st.columns([6, 1], vertical_alignment="bottom")
    left.title(title)
    with right.popover("How to use", icon=":material/help:", use_container_width=True):
        for i, s in enumerate(steps, 1):
            st.markdown(f"**{i}.** {s}")
        for t in tips or []:
            st.caption(t)
        st.page_link("pages/7_Help.py", label="Full help & glossary", icon=":material/menu_book:")
    st.markdown(f"<div class='argus-sub'>{subtitle}</div>", unsafe_allow_html=True)


def access_gate() -> None:
    if not config.ACCESS_CODE or st.session_state.get("authed"):
        return
    st.title("ARGUS")
    code = st.text_input("Access code", type="password")
    if code and code == config.ACCESS_CODE:
        st.session_state["authed"] = True
        st.rerun()
    elif code:
        st.error("Wrong code")
    st.stop()


def session_id() -> str:
    if "sid" not in st.session_state:
        st.session_state["sid"] = uuid.uuid4().hex[:12]
    return st.session_state["sid"]


def sidebar() -> None:
    with st.sidebar:
        st.markdown("### ARGUS")
        st.caption("Alert Reasoning & Graph-Unified Screening: an AI investigation copilot for Sentinel Risk analysts.")
        with st.container(border=True):
            st.markdown("**Quick start (3 min)**")
            st.page_link("pages/1_Triage_Queue.py", label="1. See the queue in lanes", icon=":material/list:")
            if st.button("2. Investigate the hidden ring", icon=":material/search:", use_container_width=True):
                go_investigate("ALR0005789")
            st.caption("3. Click **Write case with AI**, then **Record decision**.")
            st.page_link("pages/3_Score_Transaction.py", label="4. Score a new transaction", icon=":material/bolt:")
        st.text_input("Your name (for the audit log)", key="analyst", placeholder="e.g. Judge 1",
                      help="Recorded with every decision. No individual is ever ranked.")
        st.toggle("Thorough AI model (slower)", key="thorough",
                  help=f"Off: {config.LLM_FAST_MODEL} (~10-18 s).\n\nOn: {config.LLM_MODEL} (~20-40 s, more detailed).")
        st.page_link("pages/7_Help.py", label="Help, glossary & FAQ", icon=":material/menu_book:")
        st.caption("REPH synthetic data, as of 2026-09-30. Prototype, not production-ready. ARGUS recommends; a human analyst always decides.")


@st.cache_data(show_spinner=False, ttl=3600)
def labels_for(ids: tuple[str, ...]) -> dict[str, str]:
    """Display names for the UI only (never sent to the LLM)."""
    idx = router._name_index()
    sub = idx[idx["id"].isin(ids)]
    return dict(zip(sub["id"], sub["label"]))


@st.cache_data(show_spinner=False, ttl=3600)
def cached_evidence(kind: str, rec_id: str) -> dict:
    return evidence.build(kind, rec_id)


def go_investigate(value: str) -> None:
    st.session_state["pending_query"] = value
    st.switch_page("pages/2_Investigate.py")


# --------------------------------------------------------------------------- AI case rendering
def citation_badge(c: dict) -> str:
    status = c.get("status")
    if status == "verified":
        return pill(f"&#10003; citations verified ({c.get('n_cited', 0)} IDs)", "#16a34a")
    if status == "uncited":
        return pill("no citations in narrative", "#d97706")
    return pill(f"&#9888; unverified citation: {', '.join(c.get('unknown', [])[:4])}", "#dc2626")


def render_case(res: dict) -> None:
    out, meta, cites = res["output"], res["meta"], res["citations"]
    if meta.get("template"):
        st.warning(f"{meta.get('status')}. This narrative is a template filled from the same live evidence.")
    st.markdown(f"#### {out.get('headline', '')}")
    st.markdown(f"{risk_pill(out.get('risk_level'))} &nbsp; **Recommended:** {out.get('recommended_action', '-')} "
                f"&nbsp; confidence {float(out.get('confidence') or 0):.2f} &nbsp; {citation_badge(cites)}", unsafe_allow_html=True)
    st.caption(f"AI-generated draft for the analyst to review. Model {meta.get('model')} · "
               f"{'cached' if meta.get('cached') else str(meta.get('latency_ms', 0)) + ' ms'} · call {meta.get('call_id')}")
    st.markdown(out.get("narrative", ""))
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Key findings**")
        for f in out.get("key_findings") or []:
            st.markdown(f"- {f.get('finding')}  \n  {chips(f.get('citations') or [])}", unsafe_allow_html=True)
        st.markdown("**Next steps**")
        for s in out.get("next_steps") or []:
            st.markdown(f"- {s}")
    with c2:
        st.markdown("**Counter-evidence** (what argues against)")
        for s in out.get("counter_evidence") or ["None stated"]:
            st.markdown(f"- {s}")
        st.markdown("**Open questions**")
        for s in out.get("open_questions") or ["None stated"]:
            st.markdown(f"- {s}")


def write_case(ev: dict, subject: str, page: str, use_cache: bool = True) -> dict:
    return llm.run("case", evidence.for_llm(ev), llm.case_task(subject),
                   page=page, subject=subject, session_id=session_id(), fast=not st.session_state.get("thorough", False),
                   template=llm.case_template(ev), use_cache=use_cache)


ACTION_HELP = {
    "Suggest close as FP": "Nothing corroborates the alert.",
    "Monitor": "Weak signals; keep watching.",
    "Escalate to investigation": "Credible risk on a single subject.",
    "Open network case": "Linked identities: handle all their alerts as one case.",
    "Refer to MLRO (SAR-like)": "Sanctions exposure, structuring or mule activity. Needs a second approver.",
    "Hold supplier payments pending review": "Supplier with sanctions exposure and payable invoices. Needs a second approver.",
}


def decision_form(*, key: str, subject_type: str, subject_id: str, lane: str | None, res: dict | None, ev: dict | None = None,
                  linked_alerts: list[str] | None = None, actions: list[str] | None = None) -> None:
    case = (res or {}).get("output") or {}
    cites = (res or {}).get("citations") or {}
    actions = actions or llm.ACTIONS
    default = actions.index(case["recommended_action"]) if case.get("recommended_action") in actions else None
    with st.form(f"decision-{key}", border=True):
        if not res:
            st.caption("You can decide without the AI, or write the AI case first and review it.")
        c1, c2 = st.columns([1, 1])
        analyst = c1.text_input("Analyst", value=st.session_state.get("analyst", ""), placeholder="your name")
        disposition = c2.selectbox("Disposition", actions, index=default, placeholder="Choose a disposition",
                                   help="\n\n".join(f"**{a}**: {ACTION_HELP.get(a, '')}" for a in actions))
        narrative = st.text_area("Case narrative (edit before accepting)", value=case.get("narrative", ""), height=150,
                                 help="Any record ID you add must exist in the evidence pack.")
        rationale = st.text_area("Rationale (required)", placeholder="Why you agree or disagree with the AI recommendation", height=80)
        consolidate = False
        if linked_alerts and len(linked_alerts) > 1:
            consolidate = st.checkbox(f"Consolidate {len(linked_alerts)} linked alerts into ONE network case", value=True,
                                      help="One analyst owns the whole network instead of one alert each.")
        second = st.text_input("Second approver (only for SAR-like referral or supplier hold)", placeholder="a different person",
                               help="Leave empty to record the decision as 'Pending second approval'.")
        submitted = st.form_submit_button("Record decision", type="primary", icon=":material/gavel:")
    if not submitted:
        return
    if not analyst.strip() or not rationale.strip() or not disposition:
        st.error("Analyst name, disposition and rationale are required.")
        return
    known = guardrails.extract_ids(guardrails.minimise(evidence.for_llm(ev or {})))
    unknown = sorted(guardrails.extract_ids(narrative) - known)
    if cites.get("status") == "unverified" and narrative.strip() == case.get("narrative", "").strip():
        st.error("The AI narrative cites records that are not in the evidence. Regenerate it or edit the narrative before accepting.")
        return
    if unknown:
        st.error(f"Edited narrative cites records not in the evidence: {', '.join(unknown[:6])}")
        return
    try:
        rec = audit.save_decision(analyst=analyst.strip(), subject_type=subject_type, subject_id=subject_id, lane=lane,
                                  case=case or None, disposition=disposition, rationale=rationale.strip(),
                                  consolidated=linked_alerts if consolidate else None, second_approver=second,
                                  citation_status=cites.get("status"), llm_call_id=(res or {}).get("meta", {}).get("call_id"))
    except ValueError as e:
        st.error(str(e))
        return
    st.session_state[f"decided:{key}"] = rec
    with st.container(border=True):
        st.success(f"Decision **{rec['decision_id']}** recorded: **{disposition}** · status **{rec['status']}**", icon=":material/task_alt:")
        if rec["n_consolidated"]:
            st.markdown(f"{rec['n_consolidated']} alerts consolidated into one network case.")
        if rec["override"]:
            st.markdown("You overrode the AI recommendation; the override is tracked on the Impact page.")
        if rec["status"] == "Pending second approval":
            st.markdown("A second, different approver must confirm it on the Impact & Governance page.")
        st.caption("Recorded in ARGUS only (SQLite audit log). No external system was changed.")
        st.page_link("pages/6_Impact_Governance.py", label="See it in the audit log", icon=":material/fact_check:")


def legend(items: list[tuple[str, str]]) -> None:
    st.markdown("<div class='argus-legend'>" + "".join(f"<span><i style='background:{c}'></i>{t}</span>" for t, c in items) + "</div>",
                unsafe_allow_html=True)
