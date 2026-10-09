# ARGUS — Write-up

**Track 4: Fraud & Identity Intelligence, with a cross-area add-on (Supplier Risk 360).**
**Live prototype:** http://3.24.237.168:8501 (AWS EC2, ap-southeast-2) · Source: this repository.
All figures are computed live from the REPH synthetic data package (scale 0.2; full scale is about ×5) and are preliminary
prototype findings, not validated REPH results.

## 1. Problem statement

* **84.2%** of the Center's closed risk alerts are false positives (25,242 of 29,982), and alert volume tripled
  (1,429 → 4,269 per quarter, Q1-2024 to Q3-2026) while the FP rate never moved.
* Two rules, R017 (round-amount cross-border, 94.2% FP) and R023 (name similarity, 94.9% FP), produce 30.8% of all alerts.
* The score analysts sort by today ranks no better than chance (**AUC 0.51** on 2026 alerts).
* Alerts are reviewed one at a time, so organised fraud goes unseen. A **15-identity ring** (shared devices, a phone and addresses)
  triggered **137 alerts across 30 rules**, handled by **100 different analysts**. **72 were closed as false positives**, 34 separate
  investigations cost 487 analyst-hours, and **99.96% of its $3.92M moved after the first alert** (13-Jan-2026). One member had been
  on a sanctions-like list since 2020.
* Each investigation takes a median **863 hands-on minutes (14.4 h) and 56 steps** across five tools. Gathering evidence and drafting the
  narrative take **63%** of that time. The AI assistant introduced in Q3-2025 cut calendar time (73 → 53 h median) but not
  hands-on effort (859 → 867 min) and added a tool (4.0 → 4.9 per case).
* Screening stops at the account holder: **158 entities** are ≥50% owned by sanctions-listed parents without being listed themselves, and
  **115 suppliers** are on sanctions-like lists (73 rated *Low* risk). **$41.2M** was paid on their invoices received after the listing
  date, and **$4.26M (487 invoices)** is approved or on hold right now.

## 2. Affected users / target personas

* **Sentinel alert analysts (L1)**, e.g. the night shift serving the Americas: 84% noise, one alert at a time, five tools.
* **Investigators (L2)**: ~14 hands-on hours and ~56 steps per case.
* **Team leads / QC**: inconsistent decisions and no record of the reasoning.
* **Detection rule owners**: no evidence base to retire or tune rules.
* **MLRO / compliance**: missed rings; sanctions exposure through ownership chains.
* **Cross-area: AP / procurement (Group Shared Services Finance)**: paying sanctioned suppliers.

## 3. Proposed solution

ARGUS is a Streamlit application on AWS EC2 that turns **any** input (an alert, transaction, account, person, entity, supplier, device
fingerprint, investigation, invoice, KYC/watchlist/ownership record, a name, a free-text question, or a brand-new transaction) into a
**network case**:

1. **Resolve.** An identity graph links people through shared device fingerprints, phone/email/ID hashes and normalised addresses; an
   ownership walk computes effective % from sanctions-listed parents (up to 4 hops, loop-safe, 50% rule); watchlists, prior alerts and
   investigations are attached. The result is an evidence pack of IDs, hashes, amounts, dates and flags.
2. **Rank.** A gradient-boosting model trained on 2024–25 analyst decisions scores every alert, with reason codes showing historical lift,
   and routes it to a lane: HOT, PRIORITY, STANDARD or NOISE.
3. **Write.** Claude on Amazon Bedrock drafts a structured, cited case (headline, risk level, recommended action, findings, counter-evidence,
   open questions, narrative). A citation check blocks any ID that is not in the evidence.
4. **Decide.** The analyst accepts, edits or overrides with a rationale, can consolidate all linked alerts into **one** network case, and
   SAR-like referrals and supplier holds need a second approver. Everything is written to an audit log.

Supporting modules: real-time scoring of a new transaction, a Rule Studio (FP evidence, what-if routing, AI-drafted change request),
Supplier 360 (sanctions and ownership → invoices after listing → AI hold memo), and an Impact & Governance page (live baseline vs ARGUS,
model card, fairness parity, LLM call log, decisions, audit trail). Architecture: see `ARCHITECTURE.md`.

## 4. AI application / AI dependency

* **Graph AI / entity resolution** finds what per-transaction rules cannot see: the ring tripped 30 different rules and still went unseen;
  158 owned-by-sanctioned entities pass subject-level screening.
* **ML triage** learns from 29,982 analyst decisions and beats the score in production on an out-of-time test (**AUC 0.68 vs 0.51** on
  11,614 alerts from 2026). Ordering the queue by ARGUS reaches 90% of real alerts after 70.5% of the queue, so **33% fewer
  false-positive reviews** (3,246 in 2026), against 10% for today's score.
* **LLM case writer and Q&A** (Claude Haiku 4.5 by default, Sonnet 4.6 on demand) read mixed evidence (graph, ledgers, lists, history),
  write the narrative that takes ~16% of investigator time, answer free-text questions with citations, and draft rule-change and
  supplier-hold memos. Conditional code cannot write a defensible, cited narrative for an input it has never seen.

Without these, the analyst still sees 137 isolated alerts. With ARGUS they see one ranked, written and cited network case, and decide.

## 5. Tools and technologies

* Python 3.12 (EC2) / 3.14 (laptop); Streamlit; DuckDB over Parquet; pandas; PyArrow; NumPy; networkx; scikit-learn; joblib; Plotly;
  pyvis (vis.js inlined); RapidFuzz; SQLite; pytest.
* **Amazon Bedrock**: Anthropic Claude Haiku 4.5 and Sonnet 4.6 via Australia inference profiles, Converse API with forced tool-use
  JSON, invoked through the EC2 instance role (no API keys).
* **AWS**: EC2 (m7i.large, Amazon Linux 2023, IMDSv2), Elastic IP, security group, IAM role and instance profile, S3 (private, TLS-only),
  Systems Manager Run Command and Session Manager (no SSH).
* GitHub for source; GitHub Copilot and an AI coding assistant (Claude Code) used during development.

## 6. Expected impact or value (preliminary; synthetic data at scale 0.2)

| Lever | Baseline (data) | With ARGUS | Basis |
|---|---|---|---|
| False-positive reviews | 84.2% FP; today's score AUC 0.51 | AUC 0.68; **−33% FP reviews at 90% recall** | Out-of-time backtest, 11,614 alerts |
| Routing | One queue | HOT + PRIORITY: 19.1% of alerts hold **39.6% of real hits**; NOISE: 28.2% of volume at 94.5% FP → batch review | 29,982 closed alerts |
| Investigator effort | 863 min per case; 11,184 h/yr | **~44% less hands-on effort ≈ 4,900 h/yr ≈ 2.7 FTE** (≈13.7 FTE at full scale) | **Assumption**: evidence + drafting actions (63% of time) cut by 70%. Pilot must measure. |
| Fragmented cases | Ring: 137 alerts, 34 investigations, 487 h | **1 network case** | Data + assumption on effort per case |
| Ring loss exposure | $3.92M moved, 99.96% after the first alert | Network case opens at the first alert (13-Jan-2026) | What is stopped depends on the action taken |
| Supplier sanctions leakage | $41.2M paid after listing | **$4.26M (487 invoices)** flagged for hold, for compliance approval | Raw finance files, cleaned |
| Hidden ownership exposure | Subject-level screening only | **158 entities** ≥50% owned by sanctioned parties surfaced with chain and effective % | Ownership graph |

Primary metric for a pilot: **false-positive reviews per real hit**. Pesos: multiply hours by a REPH-validated loaded cost per hour.

## 7. Scalability

* DuckDB over Parquet handles the full package (×5) on one node; precompute takes ~3 minutes at scale 0.2 and the graph steps are incremental.
* Stateless app tier on EC2 behind an IAM role; scale out with an Auto Scaling group or ECS behind an ALB; Bedrock scales independently
  and AU or global inference profiles add throughput.
* The same graph, ownership and LLM engine serves alert triage (Sentinel), KYC refreshes and supplier due diligence (GSS Finance), and
  extends to other divisions' entity data.
* Production path: streaming scoring behind an API, a graph store for the identity and ownership graph, retraining on the decisions ARGUS
  captures, SSO and role-based access, and integration with the case-management system.

## 8. Next steps / production runway

**One validation step: a 6-week shadow-mode pilot with one Sentinel alert-review team.** ARGUS ranks and drafts alongside normal work,
and analysts decide as usual. Success criteria:

* ≥15% fewer FP reviews at ≥95% recall of real alerts.
* ≥30% less hands-on time per investigation (time-and-motion study).
* ≥80% of narratives accepted after QC with minor edits.
* 100% of linked clusters opened as a single network case.
* Zero real alerts missed because of ARGUS ordering.

Gate to a controlled pilot: model risk review, privacy impact assessment, threat model (Secure-by-Design), MLRO sign-off; then SSO / RBAC,
case-system integration, Bedrock guardrails and monitoring.

---

**Prototype declaration.** "This submission is a hackathon prototype developed for demonstration and evaluation only. It is not
production-ready, approved for deployment, or endorsed by REPH for operational use. The team confirms that it has complied with the event
rules; used only permitted data, tools, accounts, and services; and disclosed all simulated elements, external dependencies, generated or
additional data, third-party components, known limitations, security or privacy considerations, and material assumptions."
