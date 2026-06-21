from __future__ import annotations

from pathlib import Path

import pytest

from signal_group_sender.config import ConfigError, Settings


def test_rejects_remote_api_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIGNAL_NUMBER", "+420123456789")
    monkeypatch.setenv("SIGNAL_API_URL", "http://signal.example:8080")

    with pytest.raises(ConfigError, match="loopback"):
        Settings.from_env(tmp_path / "missing.env")


def test_allows_remote_https_api_with_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIGNAL_NUMBER", "+420123456789")
    monkeypatch.setenv("SIGNAL_API_URL", "https://signal.example")
    monkeypatch.setenv("SIGNAL_ALLOW_REMOTE_API", "true")

    settings = Settings.from_env(tmp_path / "missing.env")

    assert settings.api_url == "https://signal.example"


def test_rejects_remote_http_api_even_with_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIGNAL_NUMBER", "+420123456789")
    monkeypatch.setenv("SIGNAL_API_URL", "http://signal.example:8080")
    monkeypatch.setenv("SIGNAL_ALLOW_REMOTE_API", "true")

    with pytest.raises(ConfigError, match="https"):
        Settings.from_env(tmp_path / "missing.env")


def test_allows_compose_service_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIGNAL_NUMBER", "+420123456789")
    monkeypatch.setenv("SIGNAL_API_URL", "http://signal-api:8080")

    settings = Settings.from_env(tmp_path / "missing.env")

    assert settings.api_url == "http://signal-api:8080"


def test_rejects_invalid_signal_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIGNAL_NUMBER", "123")

    with pytest.raises(ConfigError, match="E.164"):
        Settings.from_env(tmp_path / "missing.env")


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_rejects_non_finite_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str,
) -> None:
    monkeypatch.setenv("SIGNAL_NUMBER", "+420123456789")
    monkeypatch.setenv("SIGNAL_API_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_REQUEST_TIMEOUT_SECONDS", value)

    with pytest.raises(ConfigError, match="must be >="):
        Settings.from_env(tmp_path / "missing.env")


def test_relative_files_are_resolved_from_env_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    env_file = config_directory / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("SIGNAL_NUMBER", "+420123456789")
    monkeypatch.setenv("SIGNAL_API_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_GROUPS_FILE", "groups.json")
    monkeypatch.setenv("SIGNAL_STATE_FILE", "state.json")
    monkeypatch.setenv("SIGNAL_STATE_SECRET_FILE", "state.secret")
    monkeypatch.setenv("SIGNAL_LOCK_FILE", "sender.lock")

    settings = Settings.from_env(env_file)

    assert settings.groups_file == config_directory / "groups.json"
    assert settings.state_file == config_directory / "state.json"
    assert settings.state_secret_file == config_directory / "state.secret"
    assert settings.lock_file == config_directory / "sender.lock"
