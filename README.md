# ARGUS — Alert Reasoning & Graph-Unified Screening

**REPH AI Summit 2026 · Academe Hackathon (Iloilo, 9 Oct 2026) · Track 4: Fraud & Identity Intelligence (+ Supplier Risk 360)**

ARGUS is an AI investigation copilot for Sentinel Risk analysts. It links every alert to the people, devices, phones, addresses,
accounts, companies and owners behind it, ranks real risk with ML, and drafts a cited case file with Claude on Amazon Bedrock.
**A human analyst always makes the call**, and every decision is audited.

> **Live demo (AWS EC2, ap-southeast-2):** http://3.24.237.168:8501
> Try `ALR0005789`, `fp_0e79cb1b294b`, `ENT000783`, `SUP000272`, `Cameron Beard`, or *"Who shares a phone with IND0046429?"*

> The rule engine flagged one fraud ring **137 times**. **100 different analysts** each saw one alert and closed **72** as false
> positives. **99.96%** of its $3.9M moved after the first alert. ARGUS shows the whole ring in the first case.

All numbers are computed live from the REPH synthetic data package (`python -m analysis.argus_evidence` reproduces them).
They are prototype findings on synthetic data, **not validated REPH results**.

## In 30 seconds

| | |
|---|---|
| **Problem** | 84% of risk alerts are false positives, and analysts review them one at a time, so organised fraud rings and hidden sanctioned owners go unseen. |
| **Solution** | One screen that turns any alert, ID, name or new transaction into a **network case**: who is linked, how risky it is, a cited AI-written case file, and a human decision. |
| **AI used** | Graph analytics (who is connected) + ML ranking (what is really risky) + Claude on Amazon Bedrock (writes the cited case). |
| **Proof** | Out-of-time backtest on 2026 alerts: ranking AUC 0.68 vs 0.51 today, a third fewer false-positive reviews at 90% recall. |
| **Safety** | The human always decides; every AI claim is citation-checked; every decision and LLM call is logged. |

**Which document do I read?**

| If you want… | Read |
|---|---|
| The 10-minute pitch and demo script | [PITCH.md](PITCH.md) |
| The submission write-up (problem, users, AI, impact, next steps) | [WRITEUP.md](WRITEUP.md) |
| How it is built and deployed | [ARCHITECTURE.md](ARCHITECTURE.md) |
| How to run and test it | [Run it locally](#run-it-locally-windows-python-312314) and [Tests](#tests) below |
| What a term means (AUC, lane, FP, effective ownership…) | [Glossary](#glossary) below |

---

## What it does (input → outcome)

**Input:** any ID (alert, transaction, account, person, entity, supplier, device, fingerprint, investigation, invoice, KYC, watchlist,
ownership link, rule), a name, a free-text question, or a **new** transaction (form or JSON).

| Step | What happens | Produces |
|---|---|---|
| 1. **Resolve** | Identity graph (shared device / phone / email / ID / address) + ownership chain (effective %, loop-safe) + watchlists + prior alerts and investigations | Evidence pack |
| 2. **Rank** | ML triage score + reasons with historical lift | Lane: HOT / PRIORITY / STANDARD / NOISE |
| 3. **Write** | Claude (Bedrock) drafts a cited case from the evidence pack; the citation check blocks unknown IDs | Draft case file |
| 4. **Decide** | Analyst accepts / edits / overrides with a rationale and can consolidate linked alerts into **one** network case; SAR-like referrals and supplier holds need a second approver | Decision |

**Outcome:** case file + audit log + LLM call log + impact counters.

| Page | What it shows |
|---|---|
| Overview | The ring story, baseline KPIs, alert-volume trend, one-click demo inputs |
| Triage Queue | 2026 backtest replay in lanes with ARGUS score, today's score, reasons and what really happened |
| Investigate | Universal search → subject card, network graph, money flow, ownership chain, alert history, evidence pack → AI case → human decision |
| Score a New Transaction | Real-time scoring of an unseen transaction (network signals as of its timestamp) + AI narrative |
| Rule Studio | FP rate per rule, what-if routing simulation, AI-drafted change request with human approval |
| Supplier 360 | Sanctioned suppliers and owners, invoices after listing, AI hold memo, two-person approval |
| Impact & Governance | Baseline vs ARGUS, AI-assistant audit, model card, fairness parity, decisions, LLM call log, audit log |
| Help & Guide | 3-minute tour, page guide, accepted input formats (with one-click examples), glossary, FAQ and limitations |

Every page has a **How to use** button (top right) with numbered steps; the sidebar has a **Quick start** and your name for the audit log.

## Run it locally (Windows, Python 3.12–3.14)

```powershell
cd argus
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install "botocore[crt]"     # only for 'aws login' credentials on a laptop
$env:ARGUS_DATA_DIR = "..\center_data"                     # folder that holds D_risk\ and raw\ (default: ..\center_data)
.\.venv\Scripts\python -m core.precompute                  # ~3 min: clusters, ownership, features, model -> cache\
.\.venv\Scripts\streamlit run app.py                       # http://localhost:8501
```

The LLM needs AWS credentials with Bedrock access in `ap-southeast-2` (`aws login`). Without them ARGUS still runs: the
graph, ML score and evidence pack work, and the narrative falls back to a template labelled **"AI unavailable – template mode"**.

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q tests                 # 11 unit tests (router, loop-safe ownership, clusters, guardrails)
.\.venv\Scripts\python -m scripts.smoke_test               # judge test matrix (16 checks) without the UI
.\.venv\Scripts\python -m scripts.smoke_test --llm         # + 2 live Bedrock cases with citation check
.\.venv\Scripts\python -m scripts.ui_check                 # every page + 19 inputs through Streamlit AppTest
.\.venv\Scripts\python -m analysis.argus_evidence          # reproduces every number in the pitch
.\.venv\Scripts\python -m scripts.screenshots http://localhost:8501 shots   # visual QA (pip install playwright; playwright install chromium)
```

### Judge test matrix (all passing)

| Input | Expected behaviour |
|---|---|
| `ALR0005789` | HOT lane, 15-person network, 137 alerts across 30 rules; originally closed as FP by one analyst |
| `ALR0010490` | NOISE lane (R023, $225 ATM, nothing corroborating) → suggest close via batch review; human confirms |
| `IND0057606` | Sanctions-like since 2020-07-17, onboarded 2025-11-20, ring member |
| `fp_0e79cb1b294b` | Device fingerprint shared by 7 identities |
| `ENT000783` | Not listed itself; 83.9% effectively owned by sanctioned ENT002274 over 4 hops (50% rule) |
| `ENT009514` | Ownership loop with ENT001538 flagged; traversal terminates |
| `SUP000272` | Talvale Holdings (ENT003006), sanctions-like since 2017-01-12; 84 invoices ($0.73M) still approved or on hold |
| New txn ACC0051505 → ACC0049415, $9,850, mobile wallet, 02:30 | High: member-to-member flow, shared device, ring member, night, just under $10K |
| New txn, brand-new account, unknown device, $120 groceries, 14:00 | Low; says "no network history"; invents no links |
| "Who shares a phone with IND0046429?" | Phone hash 3ee5f74bbbad048b: IND0004584, IND0044857, IND0048669, IND0050629, IND0054794 (cited) |
| "Talvale Holdings" / "Cameron Beard" | Fuzzy match → pick list → profile |
| "XYZ-123" / amount −50 | Friendly validation message, no crash |
| `INV000001` vs `INV0000001` | Investigation vs invoice |

## Deploy on AWS (what is running now)

```powershell
powershell -ExecutionPolicy Bypass -File deploy\aws\provision.ps1   # S3 bucket, IAM role, SG :8501, Elastic IP, EC2
powershell -ExecutionPolicy Bypass -File deploy\aws\deploy.ps1      # package -> S3 -> SSM Run Command -> restart + smoke test
```

| Resource (all tagged `Project=ARGUS`) | Configuration |
|---|---|
| EC2 `argus-app` | m7i.large, Amazon Linux 2023, Python 3.12 venv, systemd service `argus`, IMDSv2 required, encrypted gp3, **no SSH** (SSM only) |
| Elastic IP | 3.24.237.168 |
| Security group `argus-web-sg` | inbound TCP 8501 only (judges must reach it: rule NET-04) |
| IAM role `argus-ec2-role` | SSM core + read the ARGUS bucket + `bedrock:InvokeModel` on two Claude AU inference profiles. **No API keys anywhere.** |
| S3 `argus-<account>-ap-southeast-2` | private, TLS-only, SSE; holds releases and the REPH data copy (stays inside the REPH AWS account) |
| Amazon Bedrock | `au.anthropic.claude-haiku-4-5-20251001-v1:0` (fast, default), `au.anthropic.claude-sonnet-4-6` (thorough). AU profiles keep inference in Australia. |

Teardown after the event: terminate the instance, release the Elastic IP, delete the security group, empty and delete the bucket,
delete the instance profile and role (`aws ec2 terminate-instances …`, `aws ec2 release-address …`, `aws s3 rb s3://… --force`, …).

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `ARGUS_DATA_DIR` | `./data` or `../center_data` | folder with `D_risk/` and `raw/` |
| `ARGUS_CACHE_DIR` | `./cache` | derived tables and model |
| `ARGUS_DB_PATH` | `./argus.db` | SQLite: decisions, audit log, LLM call log, LLM cache |
| `ARGUS_LLM_PROVIDER` | `bedrock` | `template` disables LLM calls |
| `ARGUS_LLM_FAST_MODEL` / `ARGUS_LLM_MODEL` | Haiku 4.5 / Sonnet 4.6 (AU profiles) | fast default / "thorough" toggle |
| `ARGUS_LLM_MAX_CALLS_PER_SESSION` / `_PER_DAY` | 40 / 800 | cost guard for a public URL |
| `ARGUS_ACCESS_CODE` | empty | optional shared access code for the hosted demo |

## Disclosures

**Data.** REPH synthetic package only: `D_risk/*.parquet`, `raw/suppliers_raw.csv`, `raw/invoices_raw.csv`. No external data.
Transformations: near-duplicate rows dropped by primary key (36 suppliers, 1,800 invoices), three date formats parsed
(0 failures), IDs trimmed and upper-cased, 1,151 invoices whose supplier ID matches no supplier flagged and excluded from supplier
totals. Derived tables: identity links and clusters, ownership exposure, alert features and lanes, supplier exposure.
USD values use the dataset's synthetic FX rates.

**AI.** Triage model: scikit-learn `HistGradientBoostingClassifier` trained on REPH alerts before 2026-01-01 and tested on 2026
alerts. New transactions: naive-Bayes combination of signal likelihood ratios learned from the same decisions (the ML has no lift
without a rule context: AUC 0.50). LLM: Anthropic Claude via Amazon Bedrock (REPH AWS account, AU inference profiles); system prompt,
schemas and forced tool-use output are in `core/llm.py`; every call is logged (time, page, subject, model, prompt hash, tokens,
latency, guardrail result) and shown on the Impact page (DATA-05). No external embeddings. The plan named GPT-4o / GPT-4o-mini;
we used the REPH-provisioned Claude models on Bedrock instead (no keys to manage; the instance role authorises calls).

**Development assistants.** GitHub Copilot and an AI coding assistant (Claude Code) were used for analysis, planning and code.

**Open-source components.** Streamlit, DuckDB, pandas, PyArrow, NumPy, networkx, scikit-learn, joblib, Plotly, pyvis (vis.js inlined),
RapidFuzz, boto3, pytest.

**Simulated / manual.** No live link to the alert engine or case systems: "consolidate", "refer" and "hold" are recorded only in
ARGUS's SQLite database. No SSO: the analyst name is a text field. The Triage Queue replays 2026 alerts (the backtest) because almost
no alerts are open in the data. Template narrative if the LLM is unavailable (labelled).

**Limitations.** Synthetic data; labels are past analyst decisions and can be wrong (the ring proves it). Modest ML lift
(AUC 0.68); network signals are rare. Effective ownership is a single-path lower bound. Value estimates are assumptions until a pilot.

## Responsible AI controls

* **Human oversight** — ARGUS never closes, files, freezes or holds anything; every recommendation needs an analyst decision and
  rationale; SAR-like referrals and supplier holds need a second, different approver. NOISE is batch-reviewed, never auto-closed.
* **Transparency** — reason codes with historical lift, cited narratives, model card, "AI-generated draft" label on every output.
* **Grounding** — evidence-only prompt; forced JSON schema; citation check blocks *Record decision* if the narrative cites an ID that
  is not in the evidence; "No record found" when evidence is missing.
* **Privacy** — data minimisation before any LLM call (no names, dates of birth, demographics, addresses or staff IDs); Bedrock in the
  REPH AWS account with Australia-only routing; REPH data never committed to Git.
* **Fairness** — nationality, gender, age and occupation (and transaction country) are excluded from every model; FP rate, score and
  lane parity by nationality are monitored; **no individual analyst is ranked** anywhere.
* **Security** — IAM role (no keys), IMDSv2, no SSH, TLS-only private bucket, read-only DuckDB, LLM output treated as untrusted data,
  free text quoted as data (prompt-injection guard), per-session and daily LLM call caps.

## Glossary

| Term | Meaning |
|---|---|
| **Alert** | A flag raised by the rule engine on a transaction or customer, reviewed by an analyst. |
| **False positive (FP)** | An alert that an analyst closed as not suspicious. **Real hit** = closed true positive, monitoring or escalated. |
| **AUC** | How well a score ranks real hits above false positives: 0.5 = coin flip, 1.0 = perfect. |
| **Recall** | Share of real hits found. "90% recall" = 9 in 10 real alerts reached. |
| **Out-of-time backtest** | Model trained on 2024–25 alerts and scored on 2026 alerts it never saw, as it would run in production. |
| **Lane** | Routing bucket. **HOT**: network or shared-device signals (ring member, shared device, more than one nominee link, night). **PRIORITY**: model-based rule. **NOISE**: R017 / R023 with nothing corroborating (batch review, never auto-closed). **STANDARD**: everything else. |
| **Identity graph / cluster / ring** | People linked by a shared device fingerprint, phone, email, ID hash or address. A cluster of 5+ identities is treated as a network (ring). |
| **Network case** | One case that consolidates all alerts on a linked cluster, instead of one case per alert. |
| **Effective ownership** | % of an entity held by a sanctioned party through a chain of owners (multiply % along the chain, up to 4 hops). **50% rule**: ≥50% counts as owned by the sanctioned party. |
| **Sanctions-like list** | Watchlist entries in the synthetic data that play the role of sanctions lists. |
| **Evidence pack** | The facts ARGUS gathers for a subject (IDs, hashes, amounts, dates, flags). The only thing the LLM may cite. |
| **Citation check** | Every ID in the AI narrative must exist in the evidence pack, or the decision cannot be recorded. |
| **Likelihood ratio** | How much more often a signal appears on real hits than on false positives (used to score new transactions). |
| **SAR-like referral** | Escalation to file a suspicious-activity-style report; needs a second approver. |
| **MLRO** | Money Laundering Reporting Officer: the compliance owner who signs off. |
| **Shadow-mode pilot** | ARGUS runs alongside normal work; analysts decide as usual and results are compared. |
| **Scale 0.2** | The data package is about one fifth of full volume; full-scale estimates multiply by ~5. |

## Prototype declaration

"This submission is a hackathon prototype developed for demonstration and evaluation only. It is not production-ready, approved for
deployment, or endorsed by REPH for operational use. The team confirms that it has complied with the event rules; used only permitted
data, tools, accounts, and services; and disclosed all simulated elements, external dependencies, generated or additional data,
third-party components, known limitations, security or privacy considerations, and material assumptions."

## Repository layout

```
app.py                     Streamlit entry + navigation
pages/                     0_Overview … 6_Impact_Governance
core/config.py             environment configuration
core/data.py               DuckDB views over parquet + raw-file cleaning
core/precompute.py         identity graph, ownership exposure, alert features, lanes, triage model, supplier exposure
core/insights.py           portfolio findings (aggregate only)
core/evidence.py           evidence pack for any record type
core/router.py             universal input router (regex + fuzzy names + questions + JSON)
core/triage.py             alert scores, new-transaction scoring, queue
core/graph.py              pyvis network and ownership views
core/llm.py                Bedrock case writer / Q&A / memos, cache, caps, fallback
core/guardrails.py         data minimisation + citation check
core/audit.py              SQLite decisions, audit log, LLM call log, cache
analysis/argus_evidence.py reproduces every pitch number
scripts/                   smoke_test (judge matrix), ui_check (AppTest)
tests/                     unit tests
deploy/aws/                provision.ps1, deploy.ps1, user-data.sh, remote_deploy.sh, IAM policies
WRITEUP.md, ARCHITECTURE.md, PITCH.md
```
