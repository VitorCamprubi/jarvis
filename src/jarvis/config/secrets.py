"""Secrets read from environment variables or the git-ignored .env file."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    # SecretStr masks the value in repr() and logs; call .get_secret_value() only where needed.
    # An empty value (the untouched .env.example line) counts as not set.
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8", extra="ignore", frozen=True, env_ignore_empty=True
    )

    anthropic_api_key: SecretStr | None = None


def load_secrets(env_file: Path) -> Secrets:
    """Real environment variables take precedence over values in ``env_file``."""
    return Secrets(_env_file=env_file)
