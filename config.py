"""
Settings.

The previous code read the environment directly in five modules, validated
nothing, and had no notion of a webhook secret, an allowed repository, or a
dry run. The endpoint that starts a workflow accepted any caller; the tools
that write -- a GitHub comment, a PagerDuty status change -- ran whenever a
model asked.

Two settings carry the safety posture:

* ``WEBHOOK_SECRET`` -- every ``POST /webhook`` must carry an HMAC-SHA256 of
  its body under ``X-Hub-Signature-256`` (GitHub's scheme). Empty is allowed
  in development only.
* ``DRY_RUN`` -- **on by default**. Tools that would change something outside
  this process (comment on GitHub, acknowledge or resolve a PagerDuty
  incident) describe what they would do instead of doing it. Turning it off is
  a deliberate act.
"""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_OPENAI_MODEL = "gpt-4o"

_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # -- inbound ------------------------------------------------------------
    WEBHOOK_SECRET: str = ""
    # Manual triggers (no GitHub signature) may use this instead.
    API_KEY: str = ""

    # -- outbound writes ----------------------------------------------------
    DRY_RUN: bool = True
    # Repositories the GitHub tools may read from or comment on. Empty means
    # none: an allowlist that defaults to everything is not an allowlist.
    ALLOWED_REPOS: str = ""
    MAX_COMMENT_CHARS: int = Field(default=20_000, ge=100, le=65_000)

    # -- providers ------------------------------------------------------------
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = DEFAULT_ANTHROPIC_MODEL
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = DEFAULT_OPENAI_MODEL

    GITHUB_TOKEN: str = ""
    PAGERDUTY_API_KEY: str = ""
    PAGERDUTY_FROM_EMAIL: str = ""  # PagerDuty requires a real user email in From
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_DEFAULT_REGION: str = "us-east-1"

    # -- storage --------------------------------------------------------------
    DATABASE_URL: str = "sqlite:///./devops_os.db"

    # -- execution ------------------------------------------------------------
    MAX_EVENTS_IN_MEMORY: int = Field(default=1000, ge=10)

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "production"

    @property
    def allowed_repos(self) -> frozenset[str]:
        return frozenset(r.lower() for r in _split(self.ALLOWED_REPOS))

    @property
    def has_webhook_secret(self) -> bool:
        return bool(self.WEBHOOK_SECRET.strip())

    @property
    def has_api_key(self) -> bool:
        return bool(self.API_KEY.strip())

    @field_validator("DRY_RUN", mode="before")
    @classmethod
    def _blank_is_default(cls, value: object) -> object:
        # `DRY_RUN=` with nothing after it in .env must not crash the process,
        # and must not silently enable writes: blank keeps the safe default.
        if isinstance(value, str) and not value.strip():
            return True
        return value

    @model_validator(mode="after")
    def _normalise(self) -> Settings:
        level = self.LOG_LEVEL.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL={self.LOG_LEVEL!r} is not one of {sorted(_LOG_LEVELS)}")
        object.__setattr__(self, "LOG_LEVEL", level)
        if self.DATABASE_URL.startswith("postgres://"):
            object.__setattr__(self, "DATABASE_URL", "postgresql://" + self.DATABASE_URL[len("postgres://") :])
        return self

    def problems(self) -> list[str]:
        """Everything that makes this configuration unfit to serve."""
        found: list[str] = []
        if self.is_production and not (self.has_webhook_secret or self.has_api_key):
            found.append(
                "Neither WEBHOOK_SECRET nor API_KEY is set. POST /webhook would accept any caller, "
                "and a caller can make the bot comment on GitHub and change PagerDuty incidents."
            )
        if not self.DRY_RUN and not self.allowed_repos and self.GITHUB_TOKEN.strip():
            found.append(
                "DRY_RUN is off and ALLOWED_REPOS is empty: a GITHUB_TOKEN is configured but no "
                "repository is allowed, so every GitHub write would be refused. Set ALLOWED_REPOS."
            )
        if not self.DRY_RUN and self.PAGERDUTY_API_KEY.strip() and not self.PAGERDUTY_FROM_EMAIL.strip():
            found.append("PAGERDUTY_FROM_EMAIL is required to change incidents; PagerDuty rejects requests without it.")
        return found


settings = Settings()
