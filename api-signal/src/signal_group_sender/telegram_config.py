from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class TelegramConfigError(ValueError):
    """Raised when Telegram configuration is missing or invalid."""


def _env_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise TelegramConfigError(f"{name} must be an integer") from exc
    if value < minimum:
        raise TelegramConfigError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise TelegramConfigError(f"{name} must be <= {maximum}")
    return value


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise TelegramConfigError(f"{name} must be a number") from exc
    if not math.isfinite(value) or value < minimum:
        raise TelegramConfigError(f"{name} must be >= {minimum}")
    return value


def _resolve_path(value: str, base_directory: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base_directory / path


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    api_id: int
    api_hash: str
    phone_number: str
    session_file: Path
    state_file: Path
    state_secret_file: Path
    lock_file: Path
    max_chats_per_run: int
    max_message_chars: int
    min_interval_seconds: float
    duplicate_window_seconds: int
    per_chat_cooldown_seconds: int
    max_sends_per_hour: int
    max_sends_per_day: int

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> TelegramSettings:
        resolved_env_file = env_file.resolve() if env_file is not None else None
        load_dotenv(dotenv_path=resolved_env_file, override=False)
        base_directory = (
            resolved_env_file.parent if resolved_env_file is not None else Path.cwd()
        )

        raw_api_id = os.getenv("TELEGRAM_API_ID", "").strip()
        if not raw_api_id:
            raise TelegramConfigError("TELEGRAM_API_ID must be set")
        try:
            api_id = int(raw_api_id)
        except ValueError as exc:
            raise TelegramConfigError("TELEGRAM_API_ID must be an integer") from exc
        if api_id <= 0:
            raise TelegramConfigError("TELEGRAM_API_ID must be positive")

        api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
        if not _API_HASH_RE.fullmatch(api_hash):
            raise TelegramConfigError("TELEGRAM_API_HASH must be a 32-character hex string")

        phone_number = os.getenv("TELEGRAM_PHONE", "").strip()
        if not _E164_RE.fullmatch(phone_number):
            raise TelegramConfigError(
                "TELEGRAM_PHONE must use E.164 format, for example +420123456789"
            )

        return cls(
            api_id=api_id,
            api_hash=api_hash,
            phone_number=phone_number,
            session_file=_resolve_path(
                os.getenv("TELEGRAM_SESSION_FILE", ".telegram.session"),
                base_directory,
            ),
            state_file=_resolve_path(
                os.getenv("TELEGRAM_STATE_FILE", ".telegram-sender-state.json"),
                base_directory,
            ),
            state_secret_file=_resolve_path(
                os.getenv("TELEGRAM_STATE_SECRET_FILE", ".telegram-sender-secret"),
                base_directory,
            ),
            lock_file=_resolve_path(
                os.getenv("TELEGRAM_LOCK_FILE", ".telegram-sender.lock"),
                base_directory,
            ),
            max_chats_per_run=_env_int(
                "TELEGRAM_MAX_CHATS_PER_RUN", 25, minimum=1, maximum=100
            ),
            max_message_chars=_env_int(
                "TELEGRAM_MAX_MESSAGE_CHARS", 4096, minimum=1, maximum=4096
            ),
            min_interval_seconds=_env_float(
                "TELEGRAM_MIN_INTERVAL_SECONDS", 2.0, minimum=0.0
            ),
            duplicate_window_seconds=_env_int(
                "TELEGRAM_DUPLICATE_WINDOW_SECONDS",
                3600,
                minimum=60,
                maximum=604_800,
            ),
            per_chat_cooldown_seconds=_env_int(
                "TELEGRAM_PER_CHAT_COOLDOWN_SECONDS",
                5,
                minimum=0,
                maximum=3600,
            ),
            max_sends_per_hour=_env_int(
                "TELEGRAM_MAX_SENDS_PER_HOUR", 100, minimum=1, maximum=500
            ),
            max_sends_per_day=_env_int(
                "TELEGRAM_MAX_SENDS_PER_DAY", 300, minimum=1, maximum=2_000
            ),
        )
