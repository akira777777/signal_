from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from signal_group_sender.state import (
    DeliveryLedger,
    DeliveryRecord,
    delivery_fingerprint,
    target_token,
)
from signal_group_sender.telegram_client import (
    TelegramApiClient,
    TelegramApiError,
    TelegramAttachment,
    TelegramDeliveryUncertainError,
)
from signal_group_sender.telegram_config import TelegramSettings
from signal_group_sender.telegram_targets import ChatTarget


class TelegramBroadcastError(RuntimeError):
    """Raised when a Telegram campaign violates a safety invariant."""


@dataclass(frozen=True, slots=True)
class TelegramBroadcastResult:
    alias: str
    status: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class TelegramBroadcastPlan:
    aliases: tuple[str, ...]
    message_chars: int
    confirm_token: str


def build_broadcast_plan(
    settings: TelegramSettings,
    targets: list[ChatTarget],
    message: str,
    *,
    repeat_count: int = 1,
    interval_seconds: int = 0,
    attachment_digests: tuple[str, ...] = (),
) -> TelegramBroadcastPlan:
    if not message.strip() and not attachment_digests:
        raise TelegramBroadcastError("Message must not be empty")
    if len(message) > settings.max_message_chars:
        raise TelegramBroadcastError(
            f"Message exceeds {settings.max_message_chars} characters"
        )
    if attachment_digests and len(message) > 1024:
        raise TelegramBroadcastError(
            "Telegram captions with attachments must not exceed 1024 characters"
        )
    if not targets:
        raise TelegramBroadcastError("At least one chat must be selected")
    if len(targets) > settings.max_chats_per_run:
        raise TelegramBroadcastError(
            "Number of selected chats exceeds the maximum limit of "
            f"{settings.max_chats_per_run}"
        )
    if repeat_count < 1 or repeat_count > 20:
        raise TelegramBroadcastError("Repeat count must be between 1 and 20")
    if repeat_count > 1 and interval_seconds < settings.per_chat_cooldown_seconds:
        raise TelegramBroadcastError(
            "Repeat interval must be at least "
            f"{settings.per_chat_cooldown_seconds} seconds"
        )
    if interval_seconds > 86_400:
        raise TelegramBroadcastError("Repeat interval must not exceed 86400 seconds")

    payload = {
        "phone_number": settings.phone_number,
        "targets": [
            {"alias": target.alias, "peer_id": target.peer_id}
            for target in targets
        ],
        "message": message,
        "repeat_count": repeat_count,
        "interval_seconds": interval_seconds,
        "attachment_digests": attachment_digests,
    }
    confirm_token = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    return TelegramBroadcastPlan(
        aliases=tuple(target.alias for target in targets),
        message_chars=len(message),
        confirm_token=confirm_token,
    )


def verify_chat_targets(client: TelegramApiClient, targets: list[ChatTarget]) -> None:
    dialogs = client.list_dialogs()
    available = {
        str(dialog["id"])
        for dialog in dialogs
        if dialog.get("available") is True and isinstance(dialog.get("id"), str)
    }
    missing = [target.alias for target in targets if target.peer_id not in available]
    if missing:
        raise TelegramBroadcastError(
            "Selected chats are unavailable, read-only, or no longer visible: "
            + ", ".join(missing)
        )


class TelegramBroadcastService:
    def __init__(
        self,
        settings: TelegramSettings,
        client: TelegramApiClient,
        ledger: DeliveryLedger,
        fingerprint_key: bytes,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._client = client
        self._ledger = ledger
        self._fingerprint_key = fingerprint_key
        self._sleeper = sleeper

    def get_history(self) -> list[DeliveryRecord]:
        return self._ledger.get_records()

    def get_stats(self) -> dict[str, object]:
        return self._ledger.get_stats(
            max_sends_per_hour=self._settings.max_sends_per_hour,
            max_sends_per_day=self._settings.max_sends_per_day,
        )

    def send(
        self,
        targets: list[ChatTarget],
        message: str,
        *,
        confirm_count: int | None,
        confirm_token: str | None,
        retry_unknown: bool,
        repeat_count: int = 1,
        interval_seconds: int = 0,
        delivery_scope: str = "",
        attachments: list[TelegramAttachment] | None = None,
        attachment_digests: tuple[str, ...] = (),
    ) -> list[TelegramBroadcastResult]:
        plan = build_broadcast_plan(
            self._settings,
            targets,
            message,
            repeat_count=repeat_count,
            interval_seconds=interval_seconds,
            attachment_digests=attachment_digests,
        )
        verify_chat_targets(self._client, targets)
        if confirm_count != len(targets):
            raise TelegramBroadcastError(
                f"Live send requires --confirm-count {len(targets)}"
            )
        if confirm_token != plan.confirm_token:
            raise TelegramBroadcastError(
                f"Live send requires --confirm-token {plan.confirm_token}"
            )

        fingerprint_message = (
            message if not delivery_scope else f"{message}\0{delivery_scope}"
        )
        fingerprints = {
            target.alias: delivery_fingerprint(
                self._fingerprint_key,
                self._settings.phone_number,
                target.peer_id,
                fingerprint_message,
            )
            for target in targets
        }
        target_tokens = {
            target.alias: target_token(
                self._fingerprint_key,
                self._settings.phone_number,
                target.peer_id,
            )
            for target in targets
        }
        recent_statuses = {
            target.alias: self._ledger.recent_status(fingerprints[target.alias])
            for target in targets
        }
        uncertain = [
            alias
            for alias, status in recent_statuses.items()
            if status in {"dispatching", "unknown"}
        ]
        if uncertain and not retry_unknown:
            raise TelegramBroadcastError(
                "Previous delivery is unknown for: "
                + ", ".join(uncertain)
                + ". Verify Telegram manually, then use --retry-unknown only if "
                "intentional."
            )

        pending_targets = [
            target
            for target in targets
            if recent_statuses[target.alias] != "sent"
        ]
        self._ledger.assert_capacity(
            [
                (target.alias, target_tokens[target.alias])
                for target in pending_targets
            ],
            per_group_cooldown_seconds=self._settings.per_chat_cooldown_seconds,
            max_sends_per_hour=self._settings.max_sends_per_hour,
            max_sends_per_day=self._settings.max_sends_per_day,
        )

        results_by_alias = {
            target.alias: TelegramBroadcastResult(
                alias=target.alias,
                status="already_sent",
            )
            for target in targets
            if recent_statuses[target.alias] == "sent"
        }
        for index, target in enumerate(pending_targets):
            if index:
                self._sleeper(self._settings.min_interval_seconds)
            fingerprint = fingerprints[target.alias]
            self._ledger.record_attempt(
                fingerprint,
                target.alias,
                target_tokens[target.alias],
            )
            try:
                self._client.send_chat(
                    target.peer_id,
                    message,
                    attachments=attachments,
                )
            except TelegramApiError as exc:
                uncertain_delivery = isinstance(exc, TelegramDeliveryUncertainError)
                self._ledger.update_status(
                    fingerprint, "unknown" if uncertain_delivery else "failed"
                )
                results_by_alias[target.alias] = TelegramBroadcastResult(
                    alias=target.alias,
                    status="delivery_unknown" if uncertain_delivery else "failed",
                    detail=str(exc),
                )
                for remaining in pending_targets[index + 1 :]:
                    results_by_alias[remaining.alias] = TelegramBroadcastResult(
                        alias=remaining.alias,
                        status="not_attempted",
                    )
                break
            self._ledger.update_status(fingerprint, "sent")
            results_by_alias[target.alias] = TelegramBroadcastResult(
                alias=target.alias,
                status="sent",
            )
        return [results_by_alias[target.alias] for target in targets]
