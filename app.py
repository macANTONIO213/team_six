"""ARGUS - Alert Reasoning & Graph-Unified Screening. Streamlit entry point."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="ARGUS", page_icon=":material/visibility:", layout="wide",
                   menu_items={"About": "ARGUS - hackathon prototype on REPH synthetic data. A human analyst always decides."})

from core import ui  # noqa: E402

ui.apply_style()
ui.access_gate()

pages = st.navigation(
    {
        "Investigate": [
            st.Page("pages/0_Overview.py", title="Overview", icon=":material/home:", default=True),
            st.Page("pages/1_Triage_Queue.py", title="Triage Queue", icon=":material/list:"),
            st.Page("pages/2_Investigate.py", title="Investigate", icon=":material/search:"),
            st.Page("pages/3_Score_Transaction.py", title="Score a New Transaction", icon=":material/bolt:"),
        ],
        "Governance & cross-area": [
            st.Page("pages/4_Rule_Studio.py", title="Rule Studio", icon=":material/tune:"),
            st.Page("pages/5_Supplier_360.py", title="Supplier 360", icon=":material/storefront:"),
            st.Page("pages/6_Impact_Governance.py", title="Impact & Governance", icon=":material/verified_user:"),
        ],
        "Help": [
            st.Page("pages/7_Help.py", title="Help & Guide", icon=":material/menu_book:"),
        ],
    }
)
ui.sidebar()  # after st.navigation: page links resolve only once pages are registered
pages.run()
