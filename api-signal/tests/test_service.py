from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from signal_group_sender.client import DeliveryUncertainError
from signal_group_sender.config import Settings
from signal_group_sender.groups import GroupTarget
from signal_group_sender.service import (
    BroadcastError,
    BroadcastService,
    build_broadcast_plan,
)
from signal_group_sender.state import DeliveryLedger


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.attachments: list[list[str]] = []

    def send_group(
        self,
        group_id: str,
        message: str,
        *,
        base64_attachments: list[str] | None = None,
    ) -> dict[str, int]:
        self.sent.append((group_id, message))
        self.attachments.append(base64_attachments or [])
        return {"timestamp": 1}

    def list_groups(self) -> list[dict[str, object]]:
        return [
            {"id": "group.abc=", "name": "Ops", "blocked": False},
            {"id": "group.def=", "name": "Team", "blocked": False},
        ]


class UncertainClient(FakeClient):
    def send_group(
        self,
        group_id: str,
        message: str,
        *,
        base64_attachments: list[str] | None = None,
    ) -> dict[str, int]:
        self.sent.append((group_id, message))
        raise DeliveryUncertainError("delivery unknown")


def _service(
    settings: Settings,
    client: FakeClient,
    state_file: Path,
) -> BroadcastService:
    ledger = DeliveryLedger(
        state_file,
        integrity_key=b"x" * 32,
        duplicate_window_seconds=3600,
        clock=lambda: 1000.0,
    )
    return BroadcastService(
        settings,
        client,  # type: ignore[arg-type]
        ledger,
        b"x" * 32,
        sleeper=lambda _: None,
    )


def _confirm(
    settings: Settings, targets: list[GroupTarget], message: str
) -> str:
    return build_broadcast_plan(settings, targets, message).confirm_token


def test_repeat_options_are_bound_to_confirmation_token(
    settings: Settings,
) -> None:
    target = GroupTarget("ops", "group.abc=", "Operations")

    single = build_broadcast_plan(settings, [target], "hello").confirm_token
    repeated = build_broadcast_plan(
        settings,
        [target],
        "hello",
        repeat_count=3,
        interval_seconds=10,
    ).confirm_token

    assert single != repeated


def test_repeat_interval_respects_group_cooldown(settings: Settings) -> None:
    guarded = replace(settings, per_group_cooldown_seconds=10)
    target = GroupTarget("ops", "group.abc=", "Operations")

    with pytest.raises(BroadcastError, match="at least 10 seconds"):
        build_broadcast_plan(
            guarded,
            [target],
            "hello",
            repeat_count=2,
            interval_seconds=5,
        )


def test_image_digest_is_bound_to_confirmation_token(settings: Settings) -> None:
    target = GroupTarget("ops", "group.abc=", "Operations")

    without_image = build_broadcast_plan(settings, [target], "hello").confirm_token
    with_image = build_broadcast_plan(
        settings,
        [target],
        "hello",
        attachment_digests=("a" * 64,),
    ).confirm_token

    assert without_image != with_image


def test_service_forwards_images(settings: Settings) -> None:
    client = FakeClient()
    service = _service(settings, client, settings.state_file)
    targets = [GroupTarget("ops", "group.abc=")]
    attachment = "data:image/png;base64,iVBORw0KGgo="
    digest = "a" * 64
    token = build_broadcast_plan(
        settings,
        targets,
        "hello",
        attachment_digests=(digest,),
    ).confirm_token

    service.send(
        targets,
        "hello",
        confirm_count=1,
        confirm_token=token,
        retry_unknown=False,
        base64_attachments=[attachment],
        attachment_digests=(digest,),
    )

    assert client.attachments == [[attachment]]


def test_requires_exact_confirmation_count(settings: Settings) -> None:
    client = FakeClient()
    service = _service(settings, client, settings.state_file)
    targets = [GroupTarget("ops", "group.abc=")]

    with pytest.raises(BroadcastError, match="--confirm-count 1"):
        service.send(
            targets,
            "hello",
            confirm_count=None,
            confirm_token=_confirm(settings, targets, "hello"),
            retry_unknown=False,
        )

    assert client.sent == []


def test_requires_campaign_confirmation_token(settings: Settings) -> None:
    client = FakeClient()
    service = _service(settings, client, settings.state_file)
    targets = [GroupTarget("ops", "group.abc=")]

    with pytest.raises(BroadcastError, match="--confirm-token"):
        service.send(
            targets,
            "hello",
            confirm_count=1,
            confirm_token="wrong",
            retry_unknown=False,
        )

    assert client.sent == []


def test_resume_skips_already_sent_target(settings: Settings) -> None:
    client = FakeClient()
    service = _service(settings, client, settings.state_file)
    targets = [GroupTarget("ops", "group.abc=")]

    first = service.send(
        targets,
        "hello",
        confirm_count=1,
        confirm_token=_confirm(settings, targets, "hello"),
        retry_unknown=False,
    )
    assert first[0].status == "sent"

    resumed = service.send(
        targets,
        "hello",
        confirm_count=1,
        confirm_token=_confirm(settings, targets, "hello"),
        retry_unknown=False,
    )

    assert resumed[0].status == "already_sent"
    assert len(client.sent) == 1


def test_plan_does_not_limit_group_count(settings: Settings) -> None:
    limited = replace(settings, max_groups_per_run=1)
    targets = [
        GroupTarget("ops", "group.abc="),
        GroupTarget("team", "group.def="),
    ]

    plan = build_broadcast_plan(limited, targets, "hello")

    assert plan.aliases == ("ops", "team")



def test_unavailable_group_is_blocked_before_send(settings: Settings) -> None:
    client = FakeClient()
    service = _service(settings, client, settings.state_file)

    with pytest.raises(BroadcastError, match="unavailable"):
        targets = [GroupTarget("other", "group.missing=")]
        service.send(
            targets,
            "hello",
            confirm_count=1,
            confirm_token=_confirm(settings, targets, "hello"),
            retry_unknown=False,
        )

    assert client.sent == []


def test_v0100_group_schema_without_active_is_accepted(settings: Settings) -> None:
    client = FakeClient()
    service = _service(settings, client, settings.state_file)
    targets = [GroupTarget("ops", "group.abc=")]

    results = service.send(
        targets,
        "hello",
        confirm_count=1,
        confirm_token=_confirm(settings, targets, "hello"),
        retry_unknown=False,
    )

    assert results[0].status == "sent"


def test_group_without_blocked_flag_is_rejected(settings: Settings) -> None:
    client = FakeClient()
    client.list_groups = lambda: [{"id": "group.abc=", "name": "Ops"}]  # type: ignore[method-assign]
    service = _service(settings, client, settings.state_file)
    targets = [GroupTarget("ops", "group.abc=")]

    with pytest.raises(BroadcastError, match="unavailable"):
        service.send(
            targets,
            "hello",
            confirm_count=1,
            confirm_token=_confirm(settings, targets, "hello"),
            retry_unknown=False,
        )


def test_uncertain_delivery_stops_campaign(settings: Settings) -> None:
    client = UncertainClient()
    service = _service(settings, client, settings.state_file)

    targets = [
        GroupTarget("ops", "group.abc="),
        GroupTarget("team", "group.def="),
    ]
    results = service.send(
        targets,
        "hello",
        confirm_count=2,
        confirm_token=_confirm(settings, targets, "hello"),
        retry_unknown=False,
    )

    assert [result.status for result in results] == [
        "delivery_unknown",
        "not_attempted",
    ]
    assert client.sent == [("group.abc=", "hello")]


def test_retry_unknown_retries_unknown_and_keeps_sent_skipped(
    settings: Settings,
) -> None:
    uncertain_client = UncertainClient()
    service = _service(settings, uncertain_client, settings.state_file)
    targets = [
        GroupTarget("ops", "group.abc="),
        GroupTarget("team", "group.def="),
    ]
    first = service.send(
        targets,
        "hello",
        confirm_count=2,
        confirm_token=_confirm(settings, targets, "hello"),
        retry_unknown=False,
    )
    assert [result.status for result in first] == [
        "delivery_unknown",
        "not_attempted",
    ]

    healthy_client = FakeClient()
    resumed = _service(settings, healthy_client, settings.state_file).send(
        targets,
        "hello",
        confirm_count=2,
        confirm_token=_confirm(settings, targets, "hello"),
        retry_unknown=True,
    )

    assert [result.status for result in resumed] == ["sent", "sent"]
    assert healthy_client.sent == [
        ("group.abc=", "hello"),
        ("group.def=", "hello"),
    ]
