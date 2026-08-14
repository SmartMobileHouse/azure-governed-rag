"""Application settings, loaded from environment (Bicep outputs / .env)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Azure OpenAI (Foundry)
    azure_openai_endpoint: str = ""
    azure_openai_chat_deployment: str = ""
    azure_openai_embedding_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"

    # Azure AI Content Safety
    content_safety_endpoint: str = ""

    # Azure AI Language (PII)
    language_endpoint: str = ""

    # Postgres (pgvector + LangGraph checkpointer)
    postgres_host: str = ""
    postgres_db: str = "appdb"
    postgres_user: str = ""
    postgres_sslmode: str = "require"
    # Local dev only (docker-compose). In Azure this stays empty and access is
    # via an Entra access token (keyless).
    postgres_password: str = ""

    # RAG
    retrieval_top_k: int = 4
    chat_max_completion_tokens: int = 1024
    # gpt-5 reasoning models spend the completion budget on reasoning first; with
    # a full context an unbounded effort exhausts it and returns empty content.
    # "low" keeps reasoning minimal — enough for grounded RAG answers with cites.
    chat_reasoning_effort: str = "low"

    # M2 safety layer
    safety_enabled: bool = True  # Prompt Shields on input + chunks
    groundedness_enabled: bool = True  # LLM self-check on the answer
    # When a safety check *itself* errors (service down/unreachable): False = allow
    # but flag the failure (fail-open, availability-first); True = block/degrade
    # (fail-closed, strict). Positive detections always act regardless of this.
    safety_fail_closed: bool = False

    # M2 slice 2 — PII detection/redaction on the answer (Azure AI Language)
    pii_enabled: bool = True
    # Allowlist of PII categories to redact (comma-separated Azure Language
    # category names). Restricts detection to genuinely sensitive entities —
    # notably EXCLUDING PersonType (job titles) and Organization, whose default
    # detection over-redacts normal prose. Empty = detect all categories.
    pii_categories: str = (
        "Person,Email,PhoneNumber,Address,CreditCardNumber,USSocialSecurityNumber,"
        "InternationalBankingAccountNumber,ABARoutingNumber,SWIFTCode,IPAddress"
    )
    # PII protection fails CLOSED by default: if the check can't run, the answer
    # is withheld rather than returned unredacted. Set false only with an explicit
    # risk acceptance (availability over privacy).
    pii_fail_closed: bool = True

    # M3 human-in-the-loop approval gate
    hitl_enabled: bool = True
    # Also route answers that contain PII to the human approval gate.
    hitl_on_pii: bool = False
    # Comma-separated terms; if the question or answer contains one (case-
    # insensitive), the turn requires human approval — in addition to low
    # groundedness. A deterministic trigger for demos and sensitive topics.
    hitl_sensitive_terms: str = ""
    # Comma-separated approver allowlist (Easy Auth principal name). EMPTY = NO
    # ONE may approve/reject (fail-closed) — reviewers must be set explicitly, and
    # a requester can never approve their own turn.
    hitl_approver_emails: str = ""
    # HMAC key for audit pseudonyms + thread ownership. Set from a Key Vault
    # secret in production; unset falls back to unsalted SHA-256 (dev only).
    audit_hash_key: str = ""

    # Seed the bundled sample corpus on startup if the store is empty, so a fresh
    # deploy has a working /chat out of the box. Set false to disable.
    seed_on_startup: bool = True
    seed_corpus_dir: str = "docs/sample-corpus"

    # Auth: Easy Auth (Entra) fronts the app in Azure. This flag only bypasses
    # local checks for dev — it MUST be false anywhere deployed.
    auth_disabled: bool = False


settings = Settings()
