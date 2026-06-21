from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from signal_group_sender import cli
from signal_group_sender.config import Settings
from signal_group_sender.groups import GroupTarget
from signal_group_sender.service import build_broadcast_plan


class FakeSignalClient:
    sent: list[tuple[str, str]] = []

    def __init__(self, settings: object) -> None:
        self.settings = settings

    def list_groups(self) -> list[dict[str, object]]:
        return [
            {
                "id": "group.abc=",
                "name": "Operations",
                "blocked": False,
            }
        ]

    def send_group(self, group_id: str, message: str) -> dict[str, int]:
        self.sent.append((group_id, message))
        return {"timestamp": 1}


def _write_config(tmp_path: Path) -> tuple[Path, Path, str]:
    groups_file = tmp_path / "groups.json"
    groups_file.write_text(
        json.dumps({"ops": {"id": "group.abc=", "description": "Operations"}}),
        encoding="utf-8",
    )
    allowlist_digest = hashlib.sha256(groups_file.read_bytes()).hexdigest()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SIGNAL_NUMBER=+420123456789",
                "SIGNAL_API_URL=http://127.0.0.1:8080",
                f"SIGNAL_GROUPS_FILE={groups_file}",
                f"SIGNAL_ALLOWLIST_SHA256={allowlist_digest}",
                f"SIGNAL_STATE_FILE={tmp_path / 'state.json'}",
                f"SIGNAL_STATE_SECRET_FILE={tmp_path / 'state.secret'}",
                f"SIGNAL_LOCK_FILE={tmp_path / 'sender.lock'}",
                "SIGNAL_MIN_INTERVAL_SECONDS=0",
                "SIGNAL_PER_GROUP_COOLDOWN_SECONDS=1",
            ]
        ),
        encoding="utf-8",
    )
    message_file = tmp_path / "message.txt"
    message_file.write_text("Service is healthy", encoding="utf-8")
    settings = Settings.from_env(env_file)
    confirm_token = build_broadcast_plan(
        settings,
        [GroupTarget("ops", "group.abc=")],
        "Service is healthy",
    ).confirm_token
    return env_file, message_file, confirm_token


def test_groups_command_outputs_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file, _, _ = _write_config(tmp_path)
    monkeypatch.setattr(cli, "SignalApiClient", FakeSignalClient)

    exit_code = cli.main(["--env-file", str(env_file), "groups"])

    assert exit_code == 0
    assert "Operations\tavailable\tgroup.abc=" in capsys.readouterr().out


def test_dry_run_verifies_group_without_sending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeSignalClient.sent = []
    env_file, message_file, _ = _write_config(tmp_path)
    monkeypatch.setattr(cli, "SignalApiClient", FakeSignalClient)

    exit_code = cli.main(
        [
            "--env-file",
            str(env_file),
            "send",
            "--group",
            "ops",
            "--message-file",
            str(message_file),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "groups=1 aliases=ops message_chars=18" in output
    assert "dry-run: no messages sent" in output
    assert FakeSignalClient.sent == []
    assert not (tmp_path / "state.json").exists()
    assert not (tmp_path / "state.secret").exists()


def test_execute_sends_only_after_exact_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeSignalClient.sent = []
    env_file, message_file, confirm_token = _write_config(tmp_path)
    monkeypatch.setattr(cli, "SignalApiClient", FakeSignalClient)

    exit_code = cli.main(
        [
            "--env-file",
            str(env_file),
            "send",
            "--group",
            "ops",
            "--message-file",
            str(message_file),
            "--execute",
            "--confirm-count",
            "1",
            "--confirm-token",
            confirm_token,
        ]
    )

    assert exit_code == 0
    assert "ops: sent" in capsys.readouterr().out
    assert FakeSignalClient.sent == [("group.abc=", "Service is healthy")]


def test_execute_without_confirmation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    FakeSignalClient.sent = []
    env_file, message_file, _ = _write_config(tmp_path)
    monkeypatch.setattr(cli, "SignalApiClient", FakeSignalClient)

    exit_code = cli.main(
        [
            "--env-file",
            str(env_file),
            "send",
            "--group",
            "ops",
            "--message-file",
            str(message_file),
            "--execute",
        ]
    )

    assert exit_code == 1
    assert "requires --confirm-count 1" in caplog.text
    assert FakeSignalClient.sent == []


def test_history_command_empty_and_populated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import os
    for key in list(os.environ.keys()):
        if key.startswith("SIGNAL_"):
            monkeypatch.delenv(key, raising=False)

    env_file, message_file, confirm_token = _write_config(tmp_path)
    monkeypatch.setattr(cli, "SignalApiClient", FakeSignalClient)

    exit_code = cli.main(["--env-file", str(env_file), "history"])
    assert exit_code == 0
    assert "No state secret file found" in capsys.readouterr().out

    cli.main(
        [
            "--env-file",
            str(env_file),
            "send",
            "--group",
            "ops",
            "--message-file",
            str(message_file),
            "--execute",
            "--confirm-count",
            "1",
            "--confirm-token",
            confirm_token,
        ]
    )
    capsys.readouterr()

    exit_code = cli.main(["--env-file", str(env_file), "history"])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Time" in output
    assert "Alias" in output
    assert "ops" in output
    assert "sent" in output
