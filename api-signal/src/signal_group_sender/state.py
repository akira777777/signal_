from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class StateError(RuntimeError):
    """Raised when delivery state cannot be read or persisted safely."""


class RateLimitError(StateError):
    """Raised when a persistent send quota would be exceeded."""


def load_or_create_hmac_key(path: Path) -> bytes:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(file_descriptor, "wb") as handle:
            key = secrets.token_bytes(32)
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        _secure_secret_permissions(path)
        return key
    except FileExistsError:
        try:
            _secure_secret_permissions(path)
            key = path.read_bytes()
        except OSError as exc:
            raise StateError(f"Cannot read state secret: {path}") from exc
        if len(key) < 32:
            raise StateError(f"State secret is invalid: {path}") from None
        return key
    except OSError as exc:
        raise StateError(f"Cannot create state secret: {path}") from exc


def _secure_secret_permissions(path: Path) -> None:
    if os.name == "nt":
        username = os.environ.get("USERNAME")
        if not username:
            raise StateError("Cannot determine Windows user for state secret ACL")
        result = subprocess.run(
            [
                "icacls.exe",
                str(path),
                "/inheritance:r",
                "/remove:g",
                "*S-1-1-0",
                "*S-1-5-11",
                "*S-1-5-32-545",
                "/grant:r",
                f"{username}:(F)",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            raise StateError(f"Cannot secure state secret ACL: {path}")
        return

    os.chmod(path, 0o600)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise StateError(f"State secret permissions are unsafe: {path}")


def delivery_fingerprint(
    key: bytes, number: str, group_id: str, message: str
) -> str:
    raw = "\0".join((number, group_id, message)).encode()
    return hmac.new(key, raw, hashlib.sha256).hexdigest()


def target_token(key: bytes, number: str, group_id: str) -> str:
    raw = "\0".join((number, group_id)).encode()
    return hmac.new(key, raw, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    fingerprint: str
    alias: str
    target_token: str
    sent_at: float
    status: str


class DeliveryLedger:
    def __init__(
        self,
        path: Path,
        *,
        integrity_key: bytes,
        duplicate_window_seconds: int,
        clock: Any = time.time,
    ) -> None:
        self._path = path
        self._integrity_key = integrity_key
        self._window = duplicate_window_seconds
        self._clock = clock

    def initialize(self, *, allow_create: bool) -> None:
        if self._path.exists():
            self._load()
            return
        if not allow_create:
            raise StateError(
                f"Delivery state is missing after initialization: {self._path}"
            )
        self._write([])

    def _load(self) -> list[DeliveryRecord]:
        if not self._path.exists():
            return []
        try:
            envelope = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StateError(f"Cannot read delivery state: {self._path}") from exc
        if not isinstance(envelope, dict):
            raise StateError(f"Invalid delivery state: {self._path}")
        raw = envelope.get("records")
        supplied_mac = envelope.get("mac")
        if not isinstance(raw, list) or not isinstance(supplied_mac, str):
            raise StateError(f"Invalid delivery state: {self._path}")
        expected_mac = self._records_mac(raw)
        if not hmac.compare_digest(supplied_mac, expected_mac):
            raise StateError(f"Delivery state integrity check failed: {self._path}")

        records: list[DeliveryRecord] = []
        for item in raw:
            if not isinstance(item, dict):
                raise StateError(f"Invalid delivery state: {self._path}")
            try:
                records.append(
                    DeliveryRecord(
                        fingerprint=str(item["fingerprint"]),
                        alias=str(item["alias"]),
                        target_token=str(item["target_token"]),
                        sent_at=float(item["sent_at"]),
                        status=str(item.get("status", "sent")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise StateError(f"Invalid delivery state: {self._path}") from exc
        return records

    def was_sent_recently(self, fingerprint: str) -> bool:
        return self.recent_status(fingerprint) is not None

    def recent_status(self, fingerprint: str) -> str | None:
        if self._window == 0:
            return None
        cutoff = self._clock() - self._window
        matches = [
            record
            for record in self._load()
            if record.fingerprint == fingerprint and record.sent_at >= cutoff
        ]
        if not matches:
            return None
        return max(matches, key=lambda record: record.sent_at).status

    def assert_capacity(
        self,
        targets: list[tuple[str, str]],
        *,
        per_group_cooldown_seconds: int,
        max_sends_per_hour: int,
        max_sends_per_day: int,
    ) -> None:
        now = self._clock()
        records = self._load()
        hourly_count = sum(record.sent_at >= now - 3600 for record in records)
        daily_count = sum(record.sent_at >= now - 86_400 for record in records)
        if hourly_count + len(targets) > max_sends_per_hour:
            raise RateLimitError("Hourly Signal send limit would be exceeded")
        if daily_count + len(targets) > max_sends_per_day:
            raise RateLimitError("Daily Signal send limit would be exceeded")

        if per_group_cooldown_seconds == 0:
            return
        for alias, current_target_token in targets:
            latest = max(
                (
                    record.sent_at
                    for record in records
                    if record.target_token == current_target_token
                ),
                default=None,
            )
            if latest is not None and latest > now - per_group_cooldown_seconds:
                wait = max(1, int(latest + per_group_cooldown_seconds - now))
                raise RateLimitError(
                    f"Group {alias!r} is cooling down; retry in about {wait}s"
                )

    def record_attempt(
        self, fingerprint: str, alias: str, current_target_token: str
    ) -> None:
        now = self._clock()
        retention = max(self._window * 2, 86_400)
        records = [
            record for record in self._load() if record.sent_at >= now - retention
        ]
        records.append(
            DeliveryRecord(
                fingerprint=fingerprint,
                alias=alias,
                target_token=current_target_token,
                sent_at=now,
                status="dispatching",
            )
        )
        self._write(records)

    def update_status(self, fingerprint: str, status: str) -> None:
        records = self._load()
        for index in range(len(records) - 1, -1, -1):
            record = records[index]
            if record.fingerprint == fingerprint:
                records[index] = DeliveryRecord(
                    fingerprint=record.fingerprint,
                    alias=record.alias,
                    target_token=record.target_token,
                    sent_at=record.sent_at,
                    status=status,
                )
                self._write(records)
                return
        raise StateError("Cannot update missing delivery state")

    def _records_payload(self, records: list[DeliveryRecord]) -> list[dict[str, object]]:
        return [
            {
                "fingerprint": record.fingerprint,
                "alias": record.alias,
                "target_token": record.target_token,
                "sent_at": record.sent_at,
                "status": record.status,
            }
            for record in records
        ]

    def _records_mac(self, payload: Sequence[object]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hmac.new(
            self._integrity_key, canonical, hashlib.sha256
        ).hexdigest()

    def _write(self, records: list[DeliveryRecord]) -> None:
        temporary: Path | None = None
        try:
            parent = self._path.parent
            parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_name(f"{self._path.name}.{os.getpid()}.tmp")
            payload = self._records_payload(records)
            envelope = {"records": payload, "mac": self._records_mac(payload)}
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(envelope, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            if os.name != "nt":
                directory_fd = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise StateError(f"Cannot persist delivery state: {self._path}") from exc
