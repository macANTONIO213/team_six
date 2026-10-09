# ARGUS — 10-minute pitch and live demo runbook

> **The pitch in one sentence:** the rule engine flagged one fraud ring 137 times and 100 analysts each saw one piece of it;
> ARGUS shows **one** analyst the whole ring, ranks it, writes the cited case, and the human decides.

**Live app:** http://3.24.237.168:8501
All numbers below are computed live from the REPH data; the Overview and Impact pages show the same values.
Unfamiliar term? See the [glossary in the README](README.md#glossary).

## Before going on stage

- [ ] App open on the presenting laptop **and** on a phone (backup screen).
- [ ] The six demo subjects are pre-warmed (cached), so the AI case appears quickly.
- [ ] IDs ready to type: `ALR0005789` (ring alert), `ENT000783` (hidden owner), `SUP000272` (sanctioned supplier).

## The 10 minutes at a glance

| Time | Beat | Goal of the beat | On screen |
|---|---|---|---|
| 0:00–0:50 | 1. Problem | Make the missed ring real | Overview page |
| 0:50–1:30 | 2. AI idea | ARGUS in one sentence | Overview page / slide 2 |
| 1:30–5:30 | 3. Live proof | One alert → whole network → AI case → human decision | Triage Queue → Investigate → Score |
| 5:30–6:30 | 4. Judge input | Run *their* input live | Investigate or Score form |
| 6:30–8:15 | 5. Integrity | Value, assumptions, limitations, safeguards, what is simulated | Impact & Governance page |
| 8:15–9:15 | 6. Traction | The metric and the one next step | Slide 4 |
| 9:15–10:00 | 7. Close | Strongest takeaway | — |

## Beat-by-beat script

### 1. Problem (0:00–0:50) · *Overview page on screen*

> "Between November and February, 15 new 'students' and 'self-employed' customers opened 49 accounts.
> Your rule engine fired **137 alerts** on them across **30 rules**. **100 different analysts** each saw one alert.
> **72 were closed as false positives.**"
>
> "34 separate investigations, 487 analyst-hours, 21 ended 'no further action'. One of the 15 had been on a sanctions-like list
> since 2020."
>
> "$3.9M moved, **99.96% of it after the first alert**. Meanwhile 84% of all alerts are noise, and volume has tripled since 2024."

### 2. AI idea (0:50–1:30)

> "In Greek myth Argus had 100 eyes. The Center had 100 analysts on this ring, each seeing one alert.
> **ARGUS gives one analyst the whole picture**: graph AI links the network, ML ranks real risk, Claude on Amazon Bedrock writes the
> cited case, and the human decides."

### 3. Live proof (1:30–5:30) · *one complete input-to-outcome scenario*

| Step | Page | Do | Point out |
|---|---|---|---|
| a | Triage Queue | Filter rule `R017` | The HOT lane is on top. `ALR0005789` is **HOT**, but the column *what really happened* says *Closed – False Positive*. |
| b | Investigate | Click **Investigate** on that alert | Network graph: 15 people, 4 shared devices, 1 phone, 2 addresses. "137 alerts · 30 rules · 72 closed FP". |
| c | Investigate | Click **Write case with AI** | Green *citations verified* badge and a recommendation. |
| d | Investigate | **Record decision**: name, rationale, tick *Consolidate 137 linked alerts into ONE network case* | Decision ID and audit entry. The human made the call. |
| e | Score a New Transaction | Preset *Ring flow* ($9,850, 02:30) | **High**, with reasons and likelihood ratios. |
| f | Score a New Transaction | Preset *Brand-new account* | **Low**, "no network history". ARGUS invents no links. |
| g | *20-second flash (pick one)* | `ENT000783` in Investigate, or the **Supplier 360** page → `SUP000272` | 83.9% owned by sanctioned ENT002274 over 4 hops, or $0.73M in 84 invoices still payable. |

### 4. Judge input (5:30–6:30)

> "Give us any ID, any name, or a transaction."

Type it into **Investigate**, or use the **Score a New Transaction** form. ARGUS accepts any record ID, a name (fuzzy match), a free-text
question or a new transaction. Bad input such as `XYZ-123` or a negative amount gets a friendly message, not a crash.

### 5. Integrity (6:30–8:15) · *Impact & Governance page*

* **Show:** the baseline vs ARGUS table (the effort saving is labelled as an assumption), model card, fairness parity, LLM call log.
* **Limitations:** synthetic data; modest ML lift (AUC 0.68); effective ownership is a lower bound; analyst labels can be wrong.
* **Safeguards:** the human decides; second approver; citation check; data minimisation; Australia-only Bedrock; no keys.
* **Simulated:** no link to the alert or case systems; decisions are stored in ARGUS only.

### 6. Traction (8:15–9:15)

* **Primary metric:** false-positive reviews per real hit.
* **Next step:** a 6-week shadow-mode pilot with one Sentinel team.
* **Success criteria:** ≥15% fewer FP reviews at ≥95% recall; ≥30% less hands-on time.

### 7. Close (9:15–10:00)

> "Your rule engine flagged this ring 137 times. With ARGUS, one analyst sees all of it in the first case."

## Numbers to quote (live) and what they mean

**The problem**

| Number | In plain words |
|---|---|
| 84.2% FP (25,242 of 29,982 closed alerts) | About 5 in every 6 alerts are noise. |
| 1,429 → 4,269 alerts per quarter (×3.0) | Volume tripled (Q1-2024 to Q3-2026); the FP rate did not improve. |
| R017 + R023 = 30.8% of alerts at ~94.5% FP | Two rules create almost a third of all alerts, and nearly all of them are noise. |
| Model-based rules 67.3% FP vs fixed rules 88.0% | Fixed rules are far noisier than model-based ones. |

**Ranking (backtest: trained on 2024–25, tested on 11,614 alerts from 2026)**

| Number | In plain words |
|---|---|
| Today's score AUC **0.51**; ARGUS **0.68** | Today's sort order is a coin flip (0.5); ARGUS ranks real alerts higher on data it never saw. |
| 90% of real alerts in the first 70.5% of the queue → **−33% FP reviews** (today's score: −10%) | Work the queue in ARGUS order and stop once 90% of real alerts are found: a third fewer false-positive reviews than reviewing everything. |
| HOT + PRIORITY lanes: 19.1% of alerts, 39.6% of real hits | The top fifth of the queue holds two-fifths of the real hits. |
| NOISE lane: 28.2% of volume at 94.5% FP | Batch-reviewed, **never auto-closed**. |

**Investigator effort**

| Number | In plain words |
|---|---|
| Median 863 hands-on minutes (14.4 h), 56 steps per investigation | Each case is about two working days of hands-on effort. |
| Evidence + narrative = 63% of that time | Most of the effort is gathering and writing, which is what ARGUS drafts. |
| Saving **assumption**: 70% cut on those actions ≈ 4,900 h/yr ≈ 2.7 FTE (~13.7 FTE at full scale) | Say "assumption" out loud; the pilot must measure it. |
| Existing AI assistant: 50% of actions since Q3-2025; time to decision 73 → 53 h; hands-on effort 859 → 867 min; tools 4.0 → 4.9 | Faster on the calendar, but no less work, and one more tool. |

**Sanctions exposure**

| Number | In plain words |
|---|---|
| 158 entities ≥50% owned by sanctioned parents (not listed themselves); 136 hold 300 accounts; 80 of their 103 alerts closed FP | Screening checks the account holder, not who owns it. |
| 115 sanctioned suppliers (73 rated Low); $41.2M paid after listing | Suppliers on sanctions-like lists keep getting paid. |
| **$4.26M (487 invoices) payable now** | Money that can still be held, with compliance approval. |

## Four slides (the app is the show)

1. **The ring:** the 137 / 100 / 72 / 99.96% story + the alerts-per-quarter chart (Overview page).
2. **ARGUS flow:** Resolve → Rank → Write → Decide, and why each AI layer is needed.
3. **Value & integrity:** the baseline vs ARGUS table, assumptions labelled, limitations, safeguards.
4. **Next step + the ask:** 6-week shadow pilot, success criteria, gate (model risk, PIA, threat model, MLRO sign-off).

## Judge Q&A crib

| Question | Short answer |
|---|---|
| "Couldn't SQL find the ring?" | Once you know to look. ARGUS makes looking the default for every alert, at alert time, with the case written. |
| "AUC 0.68 is not high." | True, and labels are noisy (analysts closed 72 ring alerts as FP). The bigger wins are network context and effort. It already beats today's score (0.51) out of time. |
| "Hallucinations?" | Evidence-only prompt, forced JSON schema, a citation check that blocks unknown IDs, "No record found", human approval. |
| "Privacy with an LLM?" | Minimised payload (IDs and hashes; no names, birth dates, demographics or staff IDs), Bedrock inside the REPH AWS account, Australia-only inference profiles, every call logged. |
| "If the LLM is down?" | Graph, score and evidence still work; the narrative falls back to a labelled template. |
| "Why not auto-close NOISE?" | Accountability stays with people. ARGUS pre-fills and batches; QA sampling; rule changes go through governance. |
| "Fairness?" | Demographics (and transaction country) are excluded; parity by nationality is monitored on the Impact page; no analyst ranking. |

## If something breaks on stage

| Symptom | Do this |
|---|---|
| App unreachable | Check the laptop's network. Fallback: run locally (`streamlit run app.py`) and show http://localhost:8501. |
| AI slow | The six demo subjects are cached. Otherwise toggle off *Thorough AI model* (Haiku takes ~10–18 s). |
| AI unavailable | The labelled template narrative appears. Say so and continue with the decision flow. |
