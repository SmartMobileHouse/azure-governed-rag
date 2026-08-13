# 0005 — Non-streaming responses

**Status:** Accepted

## Context
Token streaming is the default UX for chat apps. But the governance controls that
run *after* generation — groundedness, PII redaction, and the human approval gate
— operate on the **complete** answer. Streaming tokens as they are produced would
release content to the client *before* those checks can act.

## Decision
`/chat` returns a **single, complete response** after the full pipeline has run.
The answer is buffered so groundedness can judge it, PII can be masked, and the
approval gate can withhold it — before anything reaches the caller.

## Consequences
- No partial or unredacted content can leak past the output controls — the safety
  property is structural, not best-effort.
- Higher time-to-first-token; a reasoning model plus the safety chain makes a turn
  take a few seconds. Acceptable for a governed assistant; not ideal for a
  latency-sensitive consumer chat.
- If streaming is ever required, it must stream only *after* the output checks
  pass (or stream a redacted/approved buffer) — not raw model tokens.
