"""Judge test matrix (plan section 9) without the UI.

    python -m scripts.smoke_test            # engine only (router, evidence, scoring)
    python -m scripts.smoke_test --llm      # also calls Bedrock for two cases and checks citations
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import evidence, llm, router, triage  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {detail}", flush=True)


def ev_for(text: str) -> tuple[router.Route, dict]:
    r = router.route(text)
    return r, evidence.build(r.kind, r.value)


def main(with_llm: bool) -> int:
    t0 = time.time()
    r, ev = ev_for("ALR0005789")
    net = ev["network"]
    check("1 ALR0005789 -> HOT lane, 15-person network", r.kind == "alert" and ev["model"]["lane"] == "HOT" and net["cluster_size"] == 15,
          f"lane={ev['model']['lane']} cluster={net['cluster_size']} alerts={ev['alerts']['count']} rules={ev['alerts']['n_rules']} "
          f"closed_fp={ev['alerts']['closed_false_positive']} original={ev['replay_only']['original_disposition']}")
    check("1b ring alert history 137 alerts / 30 rules", ev["alerts"]["count"] == 137 and ev["alerts"]["n_rules"] == 30)

    r, ev = ev_for("ALR0010490")
    check("2 ALR0010490 -> NOISE lane (R023)", ev["model"]["lane"] == "NOISE", f"rule={ev['alert']['rule_id']} amount={ev['alert']['amount_usd']} channel={ev['alert']['channel']}")

    r, ev = ev_for("IND0057606")
    wl = [w for w in ev["watchlist_hits"] if w["subject_id"] == "IND0057606"]
    check("3 IND0057606 sanctions-like since 2020-07-17, ring member", bool(wl) and wl[0]["listed_date"] == "2020-07-17" and ev["network"]["is_network"],
          f"onboarded={ev['network']['onboarded'].get('IND0057606')}")

    r, ev = ev_for("fp_0e79cb1b294b")
    check("4 fp_0e79cb1b294b shared by 7 identities", r.kind == "fingerprint" and ev["device"]["n_identities"] == 7, f"n={ev['device']['n_identities']}")

    r, ev = ev_for("ENT000783")
    own = ev["ownership"]
    check("5 ENT000783 >=50% owned by sanctioned ENT002274 over 4 hops", own.get("sanctioned_root") == "ENT002274" and own.get("fifty_percent_rule"),
          f"eff={own.get('eff_share')} hops={own.get('hops')}")

    r, ev = ev_for("ENT009514")
    check("6 ENT009514 ownership loop flagged, traversal terminates", bool(ev["ownership"].get("ownership_loops")),
          json.dumps(ev["ownership"].get("ownership_loops")))

    r, ev = ev_for("SUP000272")
    se = ev["supplier_exposure"]
    check("7 SUP000272 sanctions-listed supplier with invoices after listing", se.get("exposure") == "Sanctions-listed" and se.get("invoices_after_exposure", 0) > 0,
          f"entity={ev['subject'].get('entity_id')} listed={se.get('exposure_date')} pending={se.get('pending_invoices')} usd={se.get('pending_after_usd')}")

    s = triage.score_new_transaction({"account_id": "ACC0051505", "counterparty_account_id": "ACC0049415", "amount": 9850, "currency": "USD",
                                      "channel": "Mobile wallet", "is_cross_border": True, "timestamp": "2026-09-30 02:30"})
    check("8 new ring txn $9,850 02:30 -> High or Critical", s["risk_level"] in ("High", "Critical"),
          f"level={s['risk_level']} p={s['probability']} lane={s['lane']} reasons={[x['code'] for x in s['reasons']]}")

    s = triage.score_new_transaction({"account_id": "ACC9999999", "amount": 120, "currency": "USD", "channel": "Card",
                                      "merchant_category": "Groceries", "device_fingerprint": "fp_ffffffffffff", "timestamp": "2026-09-30 14:00"})
    check("9 brand-new account $120 groceries 14:00 -> Low, no network history", s["risk_level"] == "Low" and any("no network history" in n.lower() for n in s["notes"]),
          f"level={s['risk_level']} notes={s['notes']}")

    r = router.route("Who shares a phone with IND0046429?")
    ev = evidence.build(r.ids[0][0], r.ids[0][1]) if r.ids else {}
    phones = [l for l in ev.get("network", {}).get("shared_links", []) if l["type"] == "phone"]
    check("10 question -> phone hash 3ee5f74bbbad048b shared", r.kind == "question" and phones and phones[0].get("value") == "3ee5f74bbbad048b",
          f"members={phones[0]['members'] if phones else None}")

    r = router.route("Talvale Holdings")
    check("11a name 'Talvale Holdings' -> fuzzy candidates", r.kind == "name" and any(c["kind"] in ("supplier", "entity") for c in r.candidates),
          str(r.candidates[:3]))
    r = router.route("Cameron Beard")
    check("11b name 'Cameron Beard' -> candidates", r.kind == "name" and len(r.candidates) > 0, str(r.candidates[:2]))

    r = router.route("XYZ-123")
    check("12a garbage input -> friendly message", r.kind == "invalid" and bool(r.message), r.message[:80])
    try:
        triage.score_new_transaction({"account_id": "ACC0051505", "amount": -50})
        check("12b negative amount rejected", False)
    except ValueError as e:
        check("12b negative amount rejected", True, str(e))

    a, b = router.route("INV000001"), router.route("INV0000001")
    check("13 INV000001 = investigation, INV0000001 = invoice", a.kind == "investigation" and b.kind == "invoice", f"{a.kind} / {b.kind}")

    if with_llm:
        for subj in ("ALR0005789", "ALR0010490"):
            r, ev = ev_for(subj)
            res = llm.run("case", evidence.for_llm(ev), f"Write the case assessment for subject {subj}.", page="smoke", subject=subj,
                          template=llm.case_template(ev))
            out = res["output"]
            check(f"LLM case {subj}: citations verified", res["citations"]["status"] == "verified",
                  f"model={res['meta'].get('model')} {res['meta'].get('latency_ms')}ms action={out.get('recommended_action')} "
                  f"risk={out.get('risk_level')} unknown={res['citations']['unknown']}")
    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} passed in {time.time() - t0:.1f}s" + (f"; FAILED: {fails}" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main("--llm" in sys.argv))
