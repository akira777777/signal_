from __future__ import annotations

import ipaddress
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ConfigError(ValueError):
    """Raised when environment configuration is missing or unsafe."""


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
        raise ConfigError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be <= {maximum}")
    return value


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if not math.isfinite(value) or value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return value


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_api_url(value: str, *, allow_remote: bool) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError("SIGNAL_API_URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ConfigError("SIGNAL_API_URL must not contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ConfigError("SIGNAL_API_URL must not contain a path, query, or fragment")
    trusted_local_host = _is_loopback(parsed.hostname) or (
        parsed.hostname.lower() == "signal-api"
    )
    if not trusted_local_host:
        if not allow_remote:
            raise ConfigError(
                "SIGNAL_API_URL must use loopback or the Compose service host "
                "'signal-api', or set SIGNAL_ALLOW_REMOTE_API=true"
            )
        if parsed.scheme != "https":
            raise ConfigError("Remote SIGNAL_API_URL must use https")
    return value.rstrip("/")


def _resolve_path(value: str, base_directory: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base_directory / path


@dataclass(frozen=True, slots=True)
class Settings:
    api_url: str
    number: str
    groups_file: Path
    allowlist_sha256: str | None
    state_file: Path
    state_secret_file: Path
    lock_file: Path
    max_groups_per_run: int
    max_message_chars: int
    min_interval_seconds: float
    duplicate_window_seconds: int
    per_group_cooldown_seconds: int
    max_sends_per_hour: int
    max_sends_per_day: int
    request_timeout_seconds: float
    get_max_retries: int

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> Settings:
        resolved_env_file = env_file.resolve() if env_file is not None else None
        load_dotenv(dotenv_path=resolved_env_file, override=False)
        base_directory = (
            resolved_env_file.parent if resolved_env_file is not None else Path.cwd()
        )

        number = os.getenv("SIGNAL_NUMBER", "").strip()
        if not _E164_RE.fullmatch(number):
            raise ConfigError("SIGNAL_NUMBER must use E.164 format, for example +420123456789")

        api_url = _validate_api_url(
            os.getenv("SIGNAL_API_URL", "http://127.0.0.1:8080").strip(),
            allow_remote=_env_bool("SIGNAL_ALLOW_REMOTE_API"),
        )
        raw_allowlist_sha256 = os.getenv("SIGNAL_ALLOWLIST_SHA256", "").strip().lower()
        if raw_allowlist_sha256 and not _SHA256_RE.fullmatch(raw_allowlist_sha256):
            raise ConfigError("SIGNAL_ALLOWLIST_SHA256 must be a 64-character SHA-256")

        return cls(
            api_url=api_url,
            number=number,
            groups_file=_resolve_path(
                os.getenv("SIGNAL_GROUPS_FILE", "groups.json"), base_directory
            ),
            allowlist_sha256=raw_allowlist_sha256 or None,
            state_file=_resolve_path(
                os.getenv("SIGNAL_STATE_FILE", ".signal-sender-state.json"),
                base_directory,
            ),
            state_secret_file=_resolve_path(
                os.getenv("SIGNAL_STATE_SECRET_FILE", ".signal-sender-secret"),
                base_directory,
            ),
            lock_file=_resolve_path(
                os.getenv("SIGNAL_LOCK_FILE", ".signal-sender.lock"),
                base_directory,
            ),
            max_groups_per_run=_env_int(
                "SIGNAL_MAX_GROUPS_PER_RUN", 999999, minimum=1, maximum=999999
            ),
            max_message_chars=_env_int(
                "SIGNAL_MAX_MESSAGE_CHARS", 99999999, minimum=1, maximum=99999999
            ),
            min_interval_seconds=_env_float(
                "SIGNAL_MIN_INTERVAL_SECONDS", 2.0, minimum=0.0
            ),
            duplicate_window_seconds=_env_int(
                "SIGNAL_DUPLICATE_WINDOW_SECONDS",
                3600,
                minimum=0,
                maximum=604_800 * 100,
            ),
            per_group_cooldown_seconds=_env_int(
                "SIGNAL_PER_GROUP_COOLDOWN_SECONDS",
                5,
                minimum=0,
                maximum=3600 * 100,
            ),
            max_sends_per_hour=_env_int(
                "SIGNAL_MAX_SENDS_PER_HOUR", 999999, minimum=1, maximum=999999
            ),
            max_sends_per_day=_env_int(
                "SIGNAL_MAX_SENDS_PER_DAY", 999999, minimum=1, maximum=999999
            ),
            request_timeout_seconds=_env_float(
                "SIGNAL_REQUEST_TIMEOUT_SECONDS", 30.0, minimum=0.1
            ),
            get_max_retries=_env_int(
                "SIGNAL_GET_MAX_RETRIES", 2, minimum=0, maximum=5
            ),
        )
