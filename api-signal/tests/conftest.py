from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_DIRECTORY = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from signal_group_sender.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        api_url="http://127.0.0.1:8080",
        number="+420123456789",
        groups_file=tmp_path / "groups.json",
        allowlist_sha256=None,
        state_file=tmp_path / "state.json",
        state_secret_file=tmp_path / "state.secret",
        lock_file=tmp_path / "sender.lock",
        max_groups_per_run=5,
        max_message_chars=10_000,
        min_interval_seconds=0,
        duplicate_window_seconds=3600,
        per_group_cooldown_seconds=0,
        max_sends_per_hour=20,
        max_sends_per_day=100,
        request_timeout_seconds=5,
        send_timeout_seconds=10,
        get_max_retries=2,
    )



