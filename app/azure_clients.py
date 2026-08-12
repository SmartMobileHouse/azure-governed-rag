"""Keyless Azure clients (Entra tokens via Managed Identity / `az login`).

`DefaultAzureCredential` uses the user-assigned managed identity in Azure
(AZURE_CLIENT_ID is set on the container) and your `az login` locally.
"""

from __future__ import annotations

from azure.ai.contentsafety import ContentSafetyClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from .config import settings

_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
_credential = DefaultAzureCredential()


def openai_client() -> AzureOpenAI:
    token_provider = get_bearer_token_provider(_credential, _COGNITIVE_SCOPE)
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        azure_ad_token_provider=token_provider,
        api_version=settings.azure_openai_api_version,
    )


def content_safety_client() -> ContentSafetyClient:
    return ContentSafetyClient(
        endpoint=settings.content_safety_endpoint, credential=_credential
    )
