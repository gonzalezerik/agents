"""Central runtime configuration for every LUNA process.

All four entrypoints (luna-api, luna-discord, luna-slack, luna-worker) import
``Settings`` from here rather than reading `os.environ` directly, so the
canonical env var names in CONTRACT.md have exactly one home.

Credential handling policy (CONTRACT.md "Environment variables"): an unset or
placeholder credential must make the *specific* feature that needs it fail
loudly and specifically, never silently no-op and never crash-loop the whole
process where avoidable. This module therefore does not raise on missing
Jira/Discord/Slack/Garage credentials at import time -- callers that need
them (JiraAdapter, DiscordAdapter, ...) are responsible for checking and
raising a clear, actionable error. The one thing this module *does* enforce
at construction time is the cloud-decisions gate (see `allow_jev_provider`),
because that is a safety/policy invariant, not a "feature unavailable" case.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database -----------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://luna:luna@localhost:5432/luna",
        alias="DATABASE_URL",
    )

    # --- Decision Engine / local LLM -----------------------------------
    # Real, reachable cluster endpoint -- defaults point at it so the JEV
    # conformance tests work out of the box with no .env required. See
    # luna/decision/local_provider.py's module docstring for exactly what
    # this endpoint does and doesn't support.
    llm_base_url: str = Field(
        default="http://localhost:8080/v1",
        alias="LLM_BASE_URL",
    )
    llm_api_key: str = Field(
        default="",
        alias="LLM_API_KEY",
    )
    llm_model: str = Field(default="qwen35-4b", alias="LLM_MODEL")

    decision_provider: str = Field(default="local", alias="DECISION_PROVIDER")
    typesafe_api_key: str = Field(default="", alias="TYPESAFE_API_KEY")
    allow_cloud_decisions: bool = Field(default=False, alias="ALLOW_CLOUD_DECISIONS")

    # --- Jira ------------------------------------------------------------
    jira_site: str = Field(default="", alias="JIRA_SITE")
    jira_email: str = Field(default="", alias="JIRA_EMAIL")
    jira_api_token: str = Field(default="", alias="JIRA_API_TOKEN")
    jira_webhook_mode: bool = Field(default=False, alias="JIRA_WEBHOOK_MODE")
    jira_poll_interval_seconds: int = Field(default=120, alias="JIRA_POLL_INTERVAL_SECONDS")

    # --- Chat adapters -----------------------------------------------
    discord_bot_token: str = Field(default="", alias="DISCORD_BOT_TOKEN")
    slack_bot_token: str = Field(default="", alias="SLACK_BOT_TOKEN")
    slack_app_token: str = Field(default="", alias="SLACK_APP_TOKEN")

    # --- Internal service auth -----------------------------------------
    internal_service_token: str = Field(default="", alias="INTERNAL_SERVICE_TOKEN")

    # --- luna-api base URL, as seen by luna-discord/luna-slack ----------
    # Not in CONTRACT.md's original env var list -- added by the chat-layer
    # build (luna/adapters/_api_client.py) because the bot processes are
    # HTTP clients of their own API (CONTRACT.md: "the bot calls its own
    # API, not the other way around") and need to know where it lives.
    # Default matches the in-cluster k8s Service name from CONTRACT.md's
    # deployment section (namespace `luna`, Service `luna-api`).
    luna_api_base: str = Field(default="http://luna-api:8000", alias="LUNA_API_BASE")

    # --- Object storage (Garage / S3-compatible) ------------------------
    garage_endpoint: str = Field(default="", alias="GARAGE_ENDPOINT")
    garage_access_key_id: str = Field(default="", alias="GARAGE_ACCESS_KEY_ID")
    garage_secret_access_key: str = Field(default="", alias="GARAGE_SECRET_ACCESS_KEY")
    garage_bucket: str = Field(default="luna-artifacts", alias="GARAGE_BUCKET")

    # --- Embeddings / docs KB -------------------------------------------
    embedding_model: str = Field(default="", alias="EMBEDDING_MODEL")
    docs_repo_url: str = Field(default="", alias="DOCS_REPO_URL")
    docs_repo_token: str = Field(default="", alias="DOCS_REPO_TOKEN")

    def allow_jev_provider(self) -> bool:
        """The cloud-decisions gate (spec Part 2, CONTRACT.md "Decision Engine").

        `JevProvider` must never be constructible unless *both* a TypeSafe API
        key is configured *and* the operator has explicitly opted in via
        ALLOW_CLOUD_DECISIONS=true. Presence of the key alone is not enough --
        this is deliberate so a leaked/placeholder key can't silently flip the
        default provider to a cloud model.
        """
        return bool(self.typesafe_api_key) and self.allow_cloud_decisions


@lru_cache
def get_settings() -> Settings:
    return Settings()
