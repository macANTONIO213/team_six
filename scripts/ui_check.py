"""Headless UI check: runs every page through Streamlit's AppTest and reports exceptions.

    python -m scripts.ui_check
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

PAGES = ["pages/0_Overview.py", "pages/1_Triage_Queue.py", "pages/2_Investigate.py", "pages/3_Score_Transaction.py",
         "pages/4_Rule_Studio.py", "pages/5_Supplier_360.py", "pages/6_Impact_Governance.py", "pages/7_Help.py"]
INVESTIGATE = ["ALR0005789", "ALR0010490", "IND0057606", "fp_0e79cb1b294b", "ENT000783", "ENT009514", "SUP000272",
               "Cameron Beard", "Who shares a phone with IND0046429?", "INV000001", "INV0000001", "R017", "XYZ-123", "TXN00190688",
               "ACC0051505", "DEV0060659", "KYC010667", "WL001493", "OWN0008019"]


def run_page(path: str, state: dict | None = None) -> AppTest:
    """Run through the real entry point (app.py + st.navigation), then switch to the page."""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    at.run()
    if path != "pages/0_Overview.py":
        at.switch_page(path)
        at.run()
    return at


def main() -> int:
    bad = 0
    for p in PAGES:
        at = run_page(p)
        errs = [e.value for e in at.exception]
        print(f"[{'FAIL' if errs else 'PASS'}] {p} {errs[:1]}")
        bad += bool(errs)
    for q in INVESTIGATE:
        at = run_page("pages/2_Investigate.py", {"pending_query": q})
        errs = [e.value for e in at.exception]
        heads = [h.value for h in at.subheader][:1]
        warns = [w.value[:70] for w in at.warning][:1]
        print(f"[{'FAIL' if errs else 'PASS'}] investigate {q!r}: {heads or warns} {errs[:1]}")
        bad += bool(errs)
    print(f"\n{'ALL PAGES OK' if not bad else f'{bad} FAILURES'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
