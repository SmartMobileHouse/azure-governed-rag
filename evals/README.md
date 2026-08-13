# Evals

Two tiers, deliberately separated by what they can honestly guarantee.

## 1. Deterministic governance gate (CI)

`tests/test_governance_evals.py` + `dataset.jsonl` + `harness.py`.

Runs the **real** LangGraph pipeline with the Azure leaf calls (embeddings,
Prompt Shields, groundedness, PII, retrieval) **stubbed per case**, and asserts
the governance *behaviour*: injection is blocked, poisoned chunks are
quarantined, PII is masked, ungrounded/sensitive/PII turns route to human
approval, approve releases / reject withholds.

* **No cloud dependency** — runs on every PR via `uv run pytest`.
* **Threshold = 100%** — these behaviours are deterministic, so any single
  failure is a red build. A coverage test also fails if a critical control loses
  its case.

This gate answers *"does the orchestration enforce the controls correctly?"* It
does **not** answer *"is the model any good?"* — see tier 2.

```bash
uv run pytest tests/test_governance_evals.py -q
```

## 2. Live quality scorecard (manual / nightly)

`live_eval.py` — an adversarial golden set fired at a **running** app, hitting
the real Azure services. Results are non-deterministic (model + service
behaviour), so this is **not a per-PR gate**; run it against a deploy or on a
schedule.

```bash
AGR_BASE_URL=https://<app>.<region>.azurecontainerapps.io \
AGR_TOKEN=$(az account get-access-token --resource api://<appId> --query accessToken -o tsv) \
uv run python evals/live_eval.py
```

Exits non-zero below its threshold, so a nightly workflow can gate on it.

## Why the split

A quality claim ("94% grounded", "catches injections") measured once against a
non-deterministic system is not a gate you can hang a red/green build on without
flakiness. Gating the **deterministic control logic** at 100% and reporting
**live quality** as a scorecard keeps `main` honest without pretending model
behaviour is reproducible. Hosted evals (e.g. Azure AI Foundry) are the natural
next step for tier 2 and would slot in here.
