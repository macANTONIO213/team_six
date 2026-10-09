import pandas as pd
import streamlit as st

from core import config, ui

st.title("Help & guide")
st.markdown("<div class='argus-sub'>Everything you need to use ARGUS in five minutes, and what is behind each number.</div>", unsafe_allow_html=True)

t1, t2, t3, t4, t5 = st.tabs([":material/rocket_launch: Quick start", ":material/dashboard: Pages", ":material/keyboard: Inputs",
                              ":material/menu_book: Glossary", ":material/quiz: FAQ & limits"])

with t1:
    st.markdown("#### What ARGUS is")
    st.markdown("An AI investigation copilot for Sentinel Risk analysts. Alerts today are reviewed one at a time, so a fraud ring that trips "
                "30 different rules looks like 137 unrelated alerts. ARGUS **links** each alert to the people, devices, phones, addresses, "
                "accounts and owners behind it, **ranks** real risk, **writes** a cited case, and lets the analyst **decide**.")
    ui.stepper(["Resolve (graph AI)", "Rank (ML)", "Write (LLM)", "Decide (human)"], done=0, current=-1)
    st.markdown("#### A 3-minute tour")
    tour = [
        ("Triage Queue", "See the 2026 alerts in four lanes. The HOT lane holds the ring that analysts closed as false positives.", "pages/1_Triage_Queue.py", None),
        ("Investigate ALR0005789", "Network graph: 15 people, 4 shared devices, 1 phone, 2 addresses. Alert history: 137 alerts, 30 rules, 100 analysts.", None, "ALR0005789"),
        ("Write case with AI", "Claude drafts a cited case. The green badge means every cited ID exists in the evidence.", None, None),
        ("Record decision", "Pick a disposition, write a rationale, keep 'Consolidate 137 alerts' ticked. The decision lands in the audit log.", None, None),
        ("Score a New Transaction", "The 'Ring flow' preset scores High; the 'Brand-new account' preset scores Low with 'no network history'.", "pages/3_Score_Transaction.py", None),
        ("Supplier 360 and Impact", "Sanctioned suppliers still being paid, then baseline vs ARGUS, model card and audit trail.", "pages/5_Supplier_360.py", None),
    ]
    for i, (head, text, page, inv) in enumerate(tour, 1):
        with st.container(border=True):
            a, b = st.columns([5, 1.3], vertical_alignment="center")
            a.markdown(f"**{i}. {head}**  \n{text}")
            if page:
                b.page_link(page, label="Open", icon=":material/arrow_forward:")
            elif inv and b.button("Open", key=f"tour-{i}", icon=":material/arrow_forward:", use_container_width=True):
                ui.go_investigate(inv)

with t2:
    pages = [
        ("Overview", "The ring story, baseline numbers, and example inputs.", "Start here; click an example card."),
        ("Triage Queue", "2026 alerts in lanes with ARGUS score, today's score, reasons and what analysts did.", "Click a row, then 'Investigate this alert'."),
        ("Investigate", "Universal search → evidence (network, money, ownership, alerts) → AI case → decision.", "Type any ID, name or question."),
        ("Score a New Transaction", "Real-time risk for an unseen transaction, explained signal by signal.", "Pick a preset or fill in the form."),
        ("Rule Studio", "False-positive rate per rule, what-if routing, AI-drafted change request.", "Pick rules, adjust assumptions, draft, approve."),
        ("Supplier 360", "Sanctioned suppliers and owners, invoices after listing, AI hold memo.", "Click a supplier row, draft the memo, decide."),
        ("Impact & Governance", "Baseline vs ARGUS, model card, fairness, decisions, LLM call log, audit log.", "Approve pending holds or referrals here."),
    ]
    st.dataframe(pd.DataFrame(pages, columns=["Page", "What it shows", "How to use it"]), hide_index=True, width="stretch")
    st.markdown("**Sidebar:** enter your name once (it pre-fills every decision form) and switch on **Thorough AI model** for longer, "
                f"more detailed drafts ({config.LLM_MODEL}). The default is the fast model ({config.LLM_FAST_MODEL}).")

with t3:
    st.markdown("Type any of these on **Investigate** (case and spaces do not matter):")
    df = pd.DataFrame(ui.INPUT_FORMATS, columns=["Input", "Format", "Example"])
    st.dataframe(df, hide_index=True, width="stretch")
    st.markdown("**Try one now:**")
    cols = st.columns(5)
    for i, (value, desc) in enumerate(ui.EXAMPLES):
        if cols[i % 5].button(value if len(value) < 22 else value[:20] + "...", key=f"try-{i}", help=desc, use_container_width=True):
            ui.go_investigate(value)
    st.caption("Unknown or malformed input gives a friendly message, never an error. Unknown accounts on the Score page are treated as brand new.")

with t4:
    for term, text in ui.GLOSSARY.items():
        st.markdown(f"**{term}**: {text}")
    st.markdown("**Lanes**")
    for lane, text in ui.LANE_MEANING.items():
        st.markdown(f"{ui.lane_pill(lane)} &nbsp; {text}", unsafe_allow_html=True)

with t5:
    faq = [
        ("Does ARGUS close alerts or freeze accounts?", "No. It recommends; a person decides. SAR-like referrals and supplier holds need a second, "
         "different approver. Decisions are stored in ARGUS only; no external system is changed."),
        ("What does the AI see?", "Only the evidence pack: record IDs, hashes, amounts, dates and flags. Names, dates of birth, nationality, gender, "
         "occupation, addresses and staff IDs are removed before any call. Calls go to Claude on Amazon Bedrock inside the REPH AWS account, "
         "routed within Australia, and every call is logged."),
        ("How do I know the AI did not make things up?", "Every ID it cites is checked against the evidence. A red badge blocks recording the decision "
         "until the narrative is edited or regenerated. If evidence is missing it must say 'No record found'."),
        ("What if the AI is down?", "The graph, scores and evidence still work. The narrative falls back to a template built from the same live evidence, "
         "clearly labelled 'AI unavailable - template mode'."),
        ("Why does the queue show closed alerts?", "Almost every alert in the data is closed, so the queue replays 2026 alerts that the model never saw "
         "and shows what analysts really did, to compare."),
        ("How good is the model?", "AUC 0.68 vs 0.51 for today's score on 11,614 out-of-time alerts; 33% fewer false-positive reviews at 90% recall. "
         "Labels are past analyst decisions and can be wrong (72 ring alerts were closed as false positives)."),
        ("Is it fair?", "Nationality, gender, age, occupation and transaction country are excluded from every model. Score and lane parity by "
         "nationality are monitored on the Impact page. No individual analyst is ranked anywhere."),
        ("What is simulated?", "No link to the alert engine or case system; no single sign-on (your name is a text field); USD uses the dataset's "
         "synthetic FX rates. All data is REPH synthetic data as of 2026-09-30."),
        ("Known limitations", "Synthetic data at scale 0.2; modest ML lift; network signals are rare; effective ownership follows the strongest single "
         "path (a lower bound); value estimates are assumptions until a pilot."),
    ]
    for q, a in faq:
        with st.expander(q):
            st.markdown(a)
