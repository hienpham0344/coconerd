from dataclasses import dataclass

import pytest

from backend.application.model_selector import ModelSelector
from backend.config import Settings


@dataclass
class Config:
    provider: str = "meta"
    model_id: str = "muse-spark-1.3"
    temperature: float = 0.2
    max_tokens: int = 4096
    enabled: bool = True


def test_guild_model_override_takes_precedence_over_global():
    base = Settings(_env_file=None, meta_model_name="base")

    result = ModelSelector.select(
        base, Config(model_id="guild-model"), Config(model_id="global-model")
    )

    assert result.meta_model_name == "guild-model"
    assert result.llm_max_tokens == 4096


def test_disabled_guild_override_falls_back_to_global():
    base = Settings(_env_file=None, meta_model_name="base")

    result = ModelSelector.select(
        base,
        Config(model_id="disabled", enabled=False),
        Config(model_id="global-model"),
    )

    assert result.meta_model_name == "global-model"


def test_backend_prefixed_database_url_wins_over_legacy_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///legacy.db")
    monkeypatch.setenv("COCONERD_DATABASE_URL", "sqlite:///organizer.db")

    settings = Settings(_env_file=None)

    assert settings.database_url == "sqlite+aiosqlite:///organizer.db"


def test_model_selector_rejects_unregistered_provider():
    base = Settings(_env_file=None)

    with pytest.raises(ValueError, match="Unsupported model provider"):
        ModelSelector.select(base, Config(provider="other"), None)
