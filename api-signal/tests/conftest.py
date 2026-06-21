from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_DIRECTORY = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from signal_group_sender.config import Settings
from signal_group_sender.telegram_config import TelegramSettings


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
        get_max_retries=2,
    )


@pytest.fixture
def telegram_settings(tmp_path: Path) -> TelegramSettings:
    return TelegramSettings(
        api_id=123456,
        api_hash="0123456789abcdef0123456789abcdef",
        phone_number="+420123456789",
        session_file=tmp_path / "telegram.session",
        state_file=tmp_path / "telegram-state.json",
        state_secret_file=tmp_path / "telegram-secret",
        lock_file=tmp_path / "telegram.lock",
        max_chats_per_run=5,
        max_message_chars=4096,
        min_interval_seconds=0,
        duplicate_window_seconds=3600,
        per_chat_cooldown_seconds=0,
        max_sends_per_hour=20,
        max_sends_per_day=100,
    )
