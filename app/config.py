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

    # Auth: Easy Auth (Entra) fronts the app in Azure. This flag only bypasses
    # local checks for dev — it MUST be false anywhere deployed.
    auth_disabled: bool = False


settings = Settings()
