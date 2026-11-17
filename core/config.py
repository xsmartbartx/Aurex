"""Runtime configuration. Values come from the environment (prefix ``AUREX_``); secrets are never stored in code.

Secrets can also be files in ``AUREX_SECRETS_DIR`` named after the variable in lower case (``aurex_secret_key``,
``aurex_database_password``, ``aurex_anthropic_api_key``, ...), such as a Docker volume or ``/run/secrets``.
Environment variables take precedence over these files.
"""

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

DEV_SECRET = "dev-only-secret-change-me"  # noqa: S105 - placeholder, rejected outside local mode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUREX_", env_file=".env", extra="ignore")

    # Deployment
    deployment_mode: Literal["local", "self_hosted", "cloud"] = "local"
    environment: Literal["development", "staging", "production"] = "development"
    public_url: str = "http://localhost:3000"
    secret_key: str = DEV_SECRET
    log_level: str = "INFO"

    # Storage
    database_url: str = "postgresql+psycopg://aurex:aurex-dev-password@localhost:54329/aurex"
    # Replaces the password in database_url when set, so the URL itself can stay free of secrets.
    database_password: str = ""

    # Sessions
    session_ttl_hours: int = 24 * 14
    cookie_secure: bool = False
    allow_signup: bool = True
    # Accounts with these emails administer the platform. When empty, the first account does (local use only:
    # on a public site the first sign-up is a race). JSON list, e.g. ["ops@example.com"].
    platform_admin_emails: list[str] = Field(default_factory=list)
    # Header that carries the visitor's address when a trusted proxy sits in front, e.g. "CF-Connecting-IP"
    # behind Cloudflare. Only set it when the origin accepts traffic from that proxy alone.
    client_ip_header: str = ""

    # Limits
    rate_limit_per_minute: int = 240
    max_upload_bytes: int = 5 * 1024 * 1024

    # Data providers. SEC requires automated clients to declare a contact in the User-Agent.
    sec_user_agent: str = ""
    ingest_enabled: bool = True
    outbound_allow_hosts: list[str] = Field(
        default_factory=lambda: [
            "data-api.ecb.europa.eu",
            "www.ecb.europa.eu",
            "data.sec.gov",
            "www.sec.gov",
            "api.anthropic.com",
        ]
    )

    # AI. Without a key the deterministic offline engine answers from evidence only.
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ai_max_steps: int = 8
    ai_max_seconds: int = 180
    ai_external_data_classes: list[str] = Field(default_factory=lambda: ["public", "demonstration"])

    # Email (invitations). Without a host, invitation links are shown to the inviting administrator instead.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    # Operator details shown on the pricing and legal pages
    operator_name: str = "the operator of this AUREX deployment"
    sales_contact: str = ""  # an email address or URL; empty hides the "Contact sales" link
    support_contact: str = ""

    # Billing (cloud mode)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_prices: dict[str, str] = Field(default_factory=dict)  # plan -> Stripe price id
    plan_price_labels: dict[str, str] = Field(default_factory=dict)  # plan -> display label

    @property
    def billing_enabled(self) -> bool:
        return self.deployment_mode == "cloud" and bool(self.stripe_secret_key)

    @property
    def default_plan(self) -> str:
        """Self-hosted and local deployments are licensed as a whole; cloud tenants start on Community."""
        return "community" if self.deployment_mode == "cloud" else "enterprise"

    @model_validator(mode="after")
    def _apply_database_password(self) -> "Settings":
        if self.database_password:
            url = make_url(self.database_url).set(password=self.database_password)
            self.database_url = url.render_as_string(hide_password=False)
        return self

    def is_platform_admin_email(self, email: str) -> bool:
        return email.strip().lower() in {e.strip().lower() for e in self.platform_admin_emails}

    def assert_safe(self) -> None:
        if self.environment != "production":
            return
        if self.secret_key == DEV_SECRET:
            raise RuntimeError("AUREX_SECRET_KEY must be set in production")
        if not self.public_url.startswith("https://"):
            raise RuntimeError("AUREX_PUBLIC_URL must be the site's https:// address in production")


@lru_cache
def get_settings() -> Settings:
    return Settings(_secrets_dir=os.environ.get("AUREX_SECRETS_DIR") or None)
