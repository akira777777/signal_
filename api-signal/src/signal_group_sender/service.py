from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from signal_group_sender.client import (
    DeliveryUncertainError,
    SignalApiClient,
    SignalApiError,
)
from signal_group_sender.config import Settings
from signal_group_sender.groups import GroupTarget
from signal_group_sender.state import (
    DeliveryLedger,
    DeliveryRecord,
    delivery_fingerprint,
    target_token,
)


class BroadcastError(RuntimeError):
    """Raised when a campaign violates a safety invariant."""


@dataclass(frozen=True, slots=True)
class BroadcastResult:
    alias: str
    status: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class BroadcastPlan:
    aliases: tuple[str, ...]
    message_chars: int
    confirm_token: str


def build_broadcast_plan(
    settings: Settings,
    targets: list[GroupTarget],
    message: str,
    *,
    repeat_count: int = 1,
    interval_seconds: int = 0,
    attachment_digests: tuple[str, ...] = (),
) -> BroadcastPlan:
    if not message.strip():
        raise BroadcastError("Message must not be empty")
    if len(message) > settings.max_message_chars:
        raise BroadcastError(
            f"Message exceeds {settings.max_message_chars} characters"
        )
    if not targets:
        raise BroadcastError("At least one group must be selected")
    if repeat_count < 1 or repeat_count > 20:
        raise BroadcastError("Repeat count must be between 1 and 20")
    if repeat_count > 1 and interval_seconds < settings.per_group_cooldown_seconds:
        raise BroadcastError(
            "Repeat interval must be at least "
            f"{settings.per_group_cooldown_seconds} seconds"
        )
    if interval_seconds > 86_400:
        raise BroadcastError("Repeat interval must not exceed 86400 seconds")
    confirmation_payload = {
        "number": settings.number,
        "targets": [
            {"alias": target.alias, "group_id": target.group_id}
            for target in targets
        ],
        "message": message,
        "repeat_count": repeat_count,
        "interval_seconds": interval_seconds,
        "attachment_digests": attachment_digests,
    }
    confirm_token = hashlib.sha256(
        json.dumps(
            confirmation_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    return BroadcastPlan(
        aliases=tuple(target.alias for target in targets),
        message_chars=len(message),
        confirm_token=confirm_token,
    )


def verify_group_targets(
    client: SignalApiClient, targets: list[GroupTarget]
) -> None:
    groups = client.list_groups()
    available: set[str] = set()
    for group in groups:
        group_id = group.get("id")
        if not isinstance(group_id, str):
            continue
        blocked = group.get("blocked", group.get("isBlocked"))
        if blocked is False:
            available.add(group_id)
    missing = [target.alias for target in targets if target.group_id not in available]
    if missing:
        raise BroadcastError(
            "Selected groups are unavailable, blocked, or no longer joined: "
            + ", ".join(missing)
        )


class BroadcastService:
    def __init__(
        self,
        settings: Settings,
        client: SignalApiClient,
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

    def plan(self, targets: list[GroupTarget], message: str) -> BroadcastPlan:
        return build_broadcast_plan(self._settings, targets, message)

    def verify_targets(self, targets: list[GroupTarget]) -> None:
        verify_group_targets(self._client, targets)

    def get_history(self) -> list[DeliveryRecord]:
        return self._ledger.get_records()

    def send(
        self,
        targets: list[GroupTarget],
        message: str,
        *,
        confirm_count: int | None,
        confirm_token: str | None,
        retry_unknown: bool,
        repeat_count: int = 1,
        interval_seconds: int = 0,
        delivery_scope: str = "",
        base64_attachments: list[str] | None = None,
        attachment_digests: tuple[str, ...] = (),
    ) -> list[BroadcastResult]:
        plan = build_broadcast_plan(
            self._settings,
            targets,
            message,
            repeat_count=repeat_count,
            interval_seconds=interval_seconds,
            attachment_digests=attachment_digests,
        )
        self.verify_targets(targets)
        if confirm_count != len(targets):
            raise BroadcastError(
                f"Live send requires --confirm-count {len(targets)}"
            )
        if confirm_token != plan.confirm_token:
            raise BroadcastError(
                f"Live send requires --confirm-token {plan.confirm_token}"
            )

        fingerprint_message = (
            message if not delivery_scope else f"{message}\0{delivery_scope}"
        )
        fingerprints = {
            target.alias: delivery_fingerprint(
                self._fingerprint_key,
                self._settings.number,
                target.group_id,
                fingerprint_message,
            )
            for target in targets
        }
        target_tokens = {
            target.alias: target_token(
                self._fingerprint_key,
                self._settings.number,
                target.group_id,
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
            raise BroadcastError(
                "Previous delivery is unknown for: "
                + ", ".join(uncertain)
                + ". Verify Signal manually, then use --retry-unknown only if "
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
            per_group_cooldown_seconds=self._settings.per_group_cooldown_seconds,
            max_sends_per_hour=self._settings.max_sends_per_hour,
            max_sends_per_day=self._settings.max_sends_per_day,
        )

        results_by_alias = {
            target.alias: BroadcastResult(
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
                if base64_attachments:
                    self._client.send_group(
                        target.group_id,
                        message,
                        base64_attachments=base64_attachments,
                    )
                else:
                    self._client.send_group(target.group_id, message)
            except SignalApiError as exc:
                uncertain_delivery = isinstance(exc, DeliveryUncertainError)
                self._ledger.update_status(
                    fingerprint, "unknown" if uncertain_delivery else "failed"
                )
                results_by_alias[target.alias] = BroadcastResult(
                    alias=target.alias,
                    status="delivery_unknown" if uncertain_delivery else "failed",
                    detail=str(exc),
                )
                for remaining in pending_targets[index + 1 :]:
                    results_by_alias[remaining.alias] = BroadcastResult(
                        alias=remaining.alias,
                        status="not_attempted",
                    )
                break
            self._ledger.update_status(fingerprint, "sent")
            results_by_alias[target.alias] = BroadcastResult(
                alias=target.alias,
                status="sent",
            )
        return [results_by_alias[target.alias] for target in targets]
