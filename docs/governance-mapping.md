# Governance mapping

How the technical controls in this template **support** recognised AI governance
control objectives. It maps *engineering features* to *control themes* in the
NIST AI RMF, the EU AI Act, and ISO/IEC 42001.

> [!IMPORTANT]
> **This is not a compliance claim, a certification, or legal advice.**
> A control that *supports* an objective is not the same as *satisfying* it.
> Compliance depends on your use case, jurisdiction, data, risk classification,
> and the organisational processes around this system — none of which a code
> template can provide. Whether the EU AI Act applies to you at all (and whether
> your system is "high-risk"), whether GDPR applies, and what each framework
> requires of you are determinations only you and your legal/compliance advisors
> can make. Treat this document as an engineering starting point for a
> conversation with those advisors — nothing more.

## How to read the table

- **Supports** — the objective this feature contributes evidence or capability
  toward. References are to the *theme* (and, for the EU AI Act, the article),
  not a certification that the article is met.
- **You still must** — the non-delegable work this feature does **not** do for
  you. This column is the point of the document.

| Feature | What it does | Supports | You still must |
|---|---|---|---|
| **Keyless managed identity** (no secrets in code/config) | Every service + DB call authenticates as an Entra managed identity; no API keys or connection strings | NIST *Secure & Resilient* (MANAGE) · EU AI Act Art. 15 (cybersecurity) · ISO 42001 security of AI resources | Enforce least-privilege RBAC, review and rotate role assignments, monitor identity use |
| **Entra authentication (Easy Auth)** | Rejects unauthenticated callers before app code runs | NIST *Secure* · EU AI Act Art. 15 · ISO 42001 access control | Decide *who* may access, wire authorization/roles, review access periodically |
| **Prompt Shields** on the user prompt **and** retrieved chunks | Detects direct and indirect (document) prompt-injection; blocks or quarantines | NIST *Safe*, *Secure & Resilient* (MEASURE/MANAGE) · EU AI Act Art. 15 (robustness, resilience to manipulation) | Tune thresholds, layer additional defenses, monitor for bypasses — detection is best-effort, not a guarantee |
| **Groundedness check + fallback** | Judges whether the answer is supported by retrieved context; withholds/flags unsupported answers | NIST *Valid & Reliable* (MEASURE) · EU AI Act Art. 15 (accuracy) · ISO 42001 performance monitoring | Set thresholds for *your* risk tolerance, validate on *your* data; it reduces, not eliminates, ungrounded output |
| **PII detection/redaction** on output (Azure AI Language) | Masks detected personal data in answers; records entity *types* + counts only | NIST *Privacy-Enhanced* · EU AI Act Art. 10 (data governance) · ISO 42001 data-for-AI / privacy | Run a DPIA, establish lawful basis + retention/erasure (GDPR is a **separate** legal regime); detection misses and over-flags — tune categories |
| **Human-in-the-loop approval gate** | Low-groundedness / sensitive / PII turns pause for an authorized human to approve or reject before release | NIST *Accountable* (MANAGE) · **EU AI Act Art. 14 (human oversight)** · ISO 42001 human oversight | Staff and authorize approvers, define the criteria + SLAs, ensure oversight is real (not rubber-stamped), train reviewers |
| **Privacy-safe audit trail** | One record per turn: decision, hashed excerpts, pseudonymous actor, sources, version stamps — no raw content or identity | NIST *Accountable & Transparent* · **EU AI Act Art. 12 (record-keeping / logging)** · ISO 42001 logging | Set retention to *your* regulatory duration, protect and review the logs, separate audit storage in production |
| **Version stamps + reproducible IaC** | Policy/prompt/model versions stamped on every audit event; whole stack is `azd up`-reproducible with model version as a parameter | NIST GOVERN/MAP · EU AI Act Art. 11 (technical documentation), Art. 12 · ISO 42001 lifecycle / change management | Maintain the technical documentation and change control around versions |
| **`governance` envelope in responses** | Each answer carries the checks that ran and their verdicts | NIST *Transparent* · EU AI Act Art. 13 (transparency) · ISO 42001 information to interested parties | Decide what to surface to end users vs. operators, and log it |
| **Preflight region/quota/cost checks** | Advisory checks before provisioning | NIST MANAGE · EU AI Act Art. 9 (risk management — partial) · ISO 42001 operational planning | Run a full, documented risk-management process |

## What this template does NOT provide

- A risk classification of your system (e.g., EU AI Act "high-risk" determination)
- A DPIA, GDPR lawful-basis analysis, or data-subject-rights handling
- Bias / fairness testing, or evaluation of the model on *your* data and tasks
- An incident-response process, model-monitoring/drift program, or SLAs
- A data retention, minimisation, or deletion policy
- Conformity assessment, CE marking, certification, or any legal attestation

## Customer obligations (non-exhaustive)

1. Determine which frameworks/laws apply to your use case and jurisdiction, and
   classify the system's risk — with qualified legal/compliance advice.
2. Complete the assessments those frameworks require (risk management, DPIA, etc.).
3. Staff, authorize, and train the humans in the approval loop.
4. Evaluate model quality, safety, and bias on your own corpus and tasks
   (extend `evals/`), and set thresholds to your risk tolerance.
5. Set audit-log retention, access control, and review cadence to your
   regulatory requirements.
6. Maintain technical documentation and change control over model/policy/prompt
   versions.
7. Establish monitoring, incident response, and periodic re-evaluation.

## References

- **NIST AI RMF 1.0** — functions GOVERN / MAP / MEASURE / MANAGE and the
  trustworthiness characteristics.
- **EU AI Act** (Regulation (EU) 2024/1689) — esp. Arts. 9–15 for high-risk
  systems; applicability depends on your system's classification.
- **ISO/IEC 42001:2023** — AI management system; Annex A control objectives.

Article/theme references are provided to orient an assessment, not to assert
conformance. Verify every reference and its applicability with your advisors.
