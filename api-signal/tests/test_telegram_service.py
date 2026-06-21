from __future__ import annotations

from pathlib import Path

import pytest

from signal_group_sender.state import DeliveryLedger
from signal_group_sender.telegram_client import TelegramAttachment, TelegramDeliveryUncertainError
from signal_group_sender.telegram_config import TelegramSettings
from signal_group_sender.telegram_service import (
    TelegramBroadcastError,
    TelegramBroadcastService,
    build_broadcast_plan,
)
from signal_group_sender.telegram_targets import ChatTarget


class FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.attachments: list[list[TelegramAttachment]] = []

    def send_chat(
        self,
        peer_id: str,
        message: str,
        *,
        attachments: list[TelegramAttachment] | None = None,
    ) -> dict[str, object]:
        self.sent.append((peer_id, message))
        self.attachments.append(attachments or [])
        return {"result": "ok"}

    def list_dialogs(self) -> list[dict[str, object]]:
        return [
            {"id": "1001", "name": "Ops", "kind": "group", "available": True},
            {"id": "1002", "name": "Team", "kind": "group", "available": True},
        ]


class UncertainTelegramClient(FakeTelegramClient):
    def send_chat(
        self,
        peer_id: str,
        message: str,
        *,
        attachments: list[TelegramAttachment] | None = None,
    ) -> dict[str, object]:
        self.sent.append((peer_id, message))
        raise TelegramDeliveryUncertainError("delivery unknown")


def _service(
    settings: TelegramSettings,
    client: FakeTelegramClient,
    state_file: Path,
) -> TelegramBroadcastService:
    ledger = DeliveryLedger(
        state_file,
        integrity_key=b"x" * 32,
        duplicate_window_seconds=3600,
        clock=lambda: 1000.0,
    )
    return TelegramBroadcastService(
        settings,
        client,  # type: ignore[arg-type]
        ledger,
        b"x" * 32,
        sleeper=lambda _: None,
    )


def _confirm(settings: TelegramSettings, targets: list[ChatTarget], message: str) -> str:
    return build_broadcast_plan(settings, targets, message).confirm_token


def test_plan_binds_images_to_confirmation_token(
    telegram_settings: TelegramSettings,
) -> None:
    target = ChatTarget("ops", "1001", "Operations")

    without_image = build_broadcast_plan(telegram_settings, [target], "hello").confirm_token
    with_image = build_broadcast_plan(
        telegram_settings,
        [target],
        "hello",
        attachment_digests=("a" * 64,),
    ).confirm_token

    assert without_image != with_image


def test_plan_rejects_long_caption_with_images(
    telegram_settings: TelegramSettings,
) -> None:
    target = ChatTarget("ops", "1001", "Operations")

    with pytest.raises(TelegramBroadcastError, match="1024"):
        build_broadcast_plan(
            telegram_settings,
            [target],
            "x" * 1025,
            attachment_digests=("a" * 64,),
        )


def test_service_forwards_attachments(telegram_settings: TelegramSettings) -> None:
    client = FakeTelegramClient()
    service = _service(telegram_settings, client, telegram_settings.state_file)
    targets = [ChatTarget("ops", "1001", "Operations")]
    attachment = TelegramAttachment("image.png", "image/png", b"png")
    token = build_broadcast_plan(
        telegram_settings,
        targets,
        "hello",
        attachment_digests=("a" * 64,),
    ).confirm_token

    service.send(
        targets,
        "hello",
        confirm_count=1,
        confirm_token=token,
        retry_unknown=False,
        attachments=[attachment],
        attachment_digests=("a" * 64,),
    )

    assert client.attachments == [[attachment]]


def test_uncertain_delivery_stops_campaign(telegram_settings: TelegramSettings) -> None:
    client = UncertainTelegramClient()
    service = _service(telegram_settings, client, telegram_settings.state_file)
    targets = [
        ChatTarget("ops", "1001", "Operations"),
        ChatTarget("team", "1002", "Team"),
    ]

    results = service.send(
        targets,
        "hello",
        confirm_count=2,
        confirm_token=_confirm(telegram_settings, targets, "hello"),
        retry_unknown=False,
    )

    assert [result.status for result in results] == ["delivery_unknown", "not_attempted"]
    assert client.sent == [("1001", "hello")]
