# 0008 — HITL requester/reviewer split

**Status:** Accepted

## Context
A first cut of the human-in-the-loop gate returned the parked answer to the
requester in the `pending_approval` response and let any authenticated caller
approve — so "held for review" withheld nothing, and a requester could approve
their own turn. A pre-release review (and our own testing) caught both.

## Decision
Separate the two roles and bind threads to their owner:
- **Requester** starts a turn (`POST /chat`) and, if it parks, receives **only a
  reason** — never the answer. They poll `GET /threads/{id}` (owner-only) and get
  the answer *only once approved*.
- **Reviewer** is on an explicit allowlist (`HITL_APPROVER_EMAILS`; empty
  authorizes **no one**), is **never** the requester (self-approval is rejected),
  reads the answer to judge via `GET /threads/{id}/pending`, and decides via
  `POST /threads/{id}/approve|reject`. The decision is an atomic compare-and-set,
  so concurrent approve/reject can't both win.
- Thread ids are **server-minted** and stored with a pseudonymous owner hash;
  every thread-scoped endpoint enforces ownership or reviewer role.

## Consequences
- The gate actually withholds: the answer is disclosed only to an authorized
  reviewer, and released to the requester only after approval.
- Multi-turn "continue this thread" is dropped (it carried no history anyway); a
  turn is a thread. Conversation memory is a future feature layered on top.
- The gate is unusable until a reviewer allowlist is configured — intentional:
  "no reviewer configured" must fail closed, not default to "anyone".
