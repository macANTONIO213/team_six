"""Pre-warm the LLM cache for the demo subjects so the live demo is instant.
Uses exactly the same evidence, task text and model as the Investigate page.

    python -m scripts.prewarm
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import evidence, llm, router  # noqa: E402

SUBJECTS = ["ALR0005789", "ALR0010490", "IND0057606", "fp_0e79cb1b294b", "ENT000783", "SUP000272"]


def main() -> None:
    for text in SUBJECTS:
        r = router.route(text)
        ev = evidence.build(r.kind, r.value)
        sid = ev["subject"]["id"]
        res = llm.run("case", evidence.for_llm(ev), llm.case_task(sid), page="investigate", subject=sid, session_id="prewarm",
                      fast=True, template=llm.case_template(ev))
        out = res["output"]
        print(f"{text:18} {res['meta'].get('status'):28} {res['meta'].get('latency_ms', 0):>6} ms  "
              f"{out.get('risk_level')} / {out.get('recommended_action')}  citations={res['citations']['status']}", flush=True)


if __name__ == "__main__":
    main()
