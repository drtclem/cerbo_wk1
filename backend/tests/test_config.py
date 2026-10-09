"""T20: config reads DATABASE_URL and DEMO_MODE from the environment."""

import importlib

import app.config as config_module


def test_config_reads_database_url_and_demo_mode_from_the_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/cerbo-from-env.db")
    monkeypatch.setenv("DEMO_MODE", "true")
    reloaded = importlib.reload(config_module)
    assert reloaded.database_url == "sqlite:////tmp/cerbo-from-env.db"
    assert reloaded.demo_mode is True

    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reloaded = importlib.reload(config_module)
    assert reloaded.database_url == "sqlite:///./cerbo.db"
    assert reloaded.demo_mode is False

    # Restore defaults for later tests that import app.config / app.main.
    monkeypatch.delenv("DEMO_MODE", raising=False)
    importlib.reload(config_module)
