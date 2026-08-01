"""A production deployment must never silently run without authentication."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_requires_api_token():
    with pytest.raises(ValidationError, match="API_TOKEN"):
        Settings(_env_file=None, app_env="production", api_token="")


def test_production_accepts_api_token():
    settings = Settings(_env_file=None, app_env="production", api_token="secret")
    assert settings.auth_enabled is True


def test_development_allows_empty_token():
    settings = Settings(_env_file=None, app_env="development", api_token="")
    assert settings.auth_enabled is False
