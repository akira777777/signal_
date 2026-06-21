from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient

from signal_group_sender.telegram_client import TelegramApiClient
from signal_group_sender.telegram_config import TelegramSettings
from signal_group_sender.telegram_service import (
    TelegramBroadcastResult,
    TelegramBroadcastService,
)
from signal_group_sender.telegram_targets import ChatTarget
from signal_group_sender.telegram_web import _validated_attachments, create_app


def test_telegram_dashboard_renders(telegram_settings: TelegramSettings) -> None:
    with TestClient(create_app(telegram_settings, "correct-horse-battery")) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_telegram_login_and_dashboard_render(telegram_settings: TelegramSettings) -> None:
    with TestClient(create_app(telegram_settings, "correct-horse-battery")) as client:
        login = client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={"password": "correct-horse-battery"},
        )
        response = client.get("/")

    assert login.status_code == 200
    assert response.status_code == 200
    assert "Telegram Панель" in response.text
    assert "Войти в Telegram" in response.text


def test_status_when_telegram_not_authorized(
    telegram_settings: TelegramSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TelegramApiClient, "is_authorized", lambda self: False)

    with TestClient(create_app(telegram_settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={"password": "correct-horse-battery"},
        )
        response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authorized"] is False
    assert payload["chats"] == []


def test_auth_request_code_endpoint(
    telegram_settings: TelegramSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TelegramApiClient, "request_code", lambda self: "hash-123")
    monkeypatch.setattr(TelegramApiClient, "is_authorized", lambda self: False)

    with TestClient(create_app(telegram_settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={"password": "correct-horse-battery"},
        )
        response = client.post(
            "/api/auth/request-code",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["authorized"] is False
    assert payload["code_sent"] is True


def test_auth_complete_can_require_password(
    telegram_settings: TelegramSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TelegramApiClient, "request_code", lambda self: "hash-123")

    def require_password(
        self: TelegramApiClient,
        code: str,
        phone_code_hash: str,
        *,
        password: str | None = None,
    ) -> None:
        from signal_group_sender.telegram_client import TelegramPasswordRequiredError

        raise TelegramPasswordRequiredError("password needed")

    monkeypatch.setattr(TelegramApiClient, "authorize", require_password)

    with TestClient(create_app(telegram_settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={"password": "correct-horse-battery"},
        )
        client.post(
            "/api/auth/request-code",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={},
        )
        response = client.post(
            "/api/auth/complete",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={"code": "12345"},
        )

    assert response.status_code == 200
    assert response.json()["password_required"] is True


def test_stats_endpoint_works(
    telegram_settings: TelegramSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TelegramApiClient, "is_authorized", lambda self: False)
    monkeypatch.setattr(
        TelegramBroadcastService,
        "get_stats",
        lambda self: {
            "hourly_count": 0,
            "daily_count": 0,
            "hourly_remaining": 20,
            "daily_remaining": 100,
            "success_rate": 100,
            "last_sent_at": None,
        },
    )

    with TestClient(create_app(telegram_settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={"password": "correct-horse-battery"},
        )
        response = client.get("/api/stats")

    assert response.status_code == 200
    assert response.json()["success_rate"] == 100


def test_telegram_server_campaign_runs_repeats_without_browser_timer(
    telegram_settings: TelegramSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TelegramApiClient, "is_authorized", lambda self: True)
    monkeypatch.setattr(
        TelegramApiClient,
        "list_dialogs",
        lambda self: [
            {"id": "1001", "name": "Ops", "kind": "group", "available": True}
        ],
    )
    delivery_scopes: list[str] = []

    def fake_send(
        self: TelegramBroadcastService,
        targets: list[ChatTarget],
        message: str,
        **kwargs: object,
    ) -> list[TelegramBroadcastResult]:
        del self, message
        delivery_scopes.append(str(kwargs["delivery_scope"]))
        return [
            TelegramBroadcastResult(alias=target.alias, status="sent")
            for target in targets
        ]

    monkeypatch.setattr(TelegramBroadcastService, "send", fake_send)

    with TestClient(create_app(telegram_settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={"password": "correct-horse-battery"},
        )
        status = client.get("/api/status")
        alias = status.json()["chats"][0]["alias"]
        plan = client.post(
            "/api/plan",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={
                "aliases": [alias],
                "message": "hello",
                "repeat_count": 2,
                "interval_seconds": 0,
            },
        ).json()
        start = client.post(
            "/api/campaign",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={
                "aliases": [alias],
                "message": "hello",
                "confirm_token": plan["confirm_token"],
                "repeat_count": 2,
                "interval_seconds": 0,
            },
        )
        assert start.status_code == 200

        campaign = start.json()
        for _ in range(20):
            campaign = client.get("/api/campaign").json()
            if campaign["status"] == "completed":
                break
            time.sleep(0.05)

    assert campaign["status"] == "completed"
    assert campaign["current_round"] == 2
    assert [result["round_index"] for result in campaign["results"]] == [1, 2]
    assert delivery_scopes == [
        f"{plan['confirm_token']}:1",
        f"{plan['confirm_token']}:2",
    ]


def test_validates_telegram_png_attachment() -> None:
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()

    attachments, digests = _validated_attachments([f"data:image/png;base64,{encoded}"])

    assert len(attachments) == 1
    assert attachments[0].name.endswith(".png")
    assert len(digests[0]) == 64


def test_validates_telegram_mp4_attachment() -> None:
    encoded = base64.b64encode(b"\x00\x00\x00\x18ftypmp42payload").decode()

    attachments, digests = _validated_attachments([f"data:video/mp4;base64,{encoded}"])

    assert len(attachments) == 1
    assert attachments[0].name.endswith(".mp4")
    assert attachments[0].mime_type == "video/mp4"
    assert len(digests[0]) == 64


def test_campaign_endpoints_record_send_and_refresh_engagement(
    telegram_settings: TelegramSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TelegramApiClient, "is_authorized", lambda self: True)
    monkeypatch.setattr(
        TelegramApiClient,
        "list_dialogs",
        lambda self: [
            {"id": "1001", "name": "Ops", "kind": "group", "available": True},
        ],
    )
    monkeypatch.setattr(
        TelegramApiClient,
        "send_chat",
        lambda self, peer_id, message, attachments=None: {
            "result": "ok",
            "message_ids": [55],
        },
    )

    def collect_engagement(self: TelegramApiClient, records: list[object]) -> dict[tuple[str, int, str], tuple[int, int]]:
        record = records[0]
        return {(record.alias, record.round_index, record.variant_id): (1, 1)}

    monkeypatch.setattr(TelegramApiClient, "collect_engagement", collect_engagement)

    with TestClient(create_app(telegram_settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={"password": "correct-horse-battery"},
        )
        status = client.get("/api/status")
        alias = status.json()["chats"][0]["alias"]
        plan = client.post(
            "/api/plan",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={"aliases": [alias], "message": "hello"},
        ).json()
        send = client.post(
            "/api/send",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={
                "aliases": [alias],
                "message": "hello",
                "confirm_token": plan["confirm_token"],
                "variant_id": "A",
            },
        )
        campaigns = client.get("/api/campaigns")
        refreshed = client.post(
            f"/api/campaigns/{send.json()['campaign_id']}/refresh-engagement",
            headers={"Origin": "http://127.0.0.1:8788"},
            json={},
        )

    assert send.status_code == 200
    assert send.json()["campaign_id"].startswith("tg-")
    assert campaigns.status_code == 200
    assert campaigns.json()[0]["sent"] == 1
    assert refreshed.status_code == 200
    assert refreshed.json()["reply_rate"] == 100
