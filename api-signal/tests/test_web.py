from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient

from signal_group_sender.client import SignalApiClient
from signal_group_sender.config import Settings
from signal_group_sender.service import BroadcastError, BroadcastResult, BroadcastService
from signal_group_sender.state import DeliveryRecord
from signal_group_sender.web import _validated_attachments, create_app


def test_dashboard_renders(settings: Settings) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_and_dashboard_render(settings: Settings) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        login = client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"password": "correct-horse-battery"},
        )
        response = client.get("/")

    assert login.status_code == 200
    assert response.status_code == 200
    assert "Количество отправок" in response.text
    assert "Подключить другой аккаунт" in response.text
    assert "Выйти" in response.text


def test_post_requires_same_origin(settings: Settings) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.post(
            "/api/plan",
            json={"aliases": ["ops"], "message": "hello"},
        )

    assert response.status_code == 403


def test_wrong_password_is_rejected(settings: Settings) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"password": "wrong-password"},
        )

    assert response.status_code == 401


def test_status_requires_authentication(settings: Settings) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.get("/api/status")

    assert response.status_code == 401


def test_history_requires_authentication(settings: Settings) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.get("/api/history")

    assert response.status_code == 401


def test_get_history_returns_records(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy_records = [
        DeliveryRecord(
            fingerprint="fp1",
            alias="ops",
            target_token="tok1",
            sent_at=1000.0,
            status="sent",
        ),
        DeliveryRecord(
            fingerprint="fp2",
            alias="team",
            target_token="tok2",
            sent_at=2000.0,
            status="failed",
        ),
    ]

    monkeypatch.setattr(BroadcastService, "get_history", lambda self: dummy_records)

    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"password": "correct-horse-battery"},
        )
        response = client.get("/api/history")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert payload[0]["alias"] == "team"
    assert payload[0]["status"] == "failed"
    assert payload[0]["sent_at"] == 2000.0
    assert payload[1]["alias"] == "ops"
    assert payload[1]["status"] == "sent"
    assert payload[1]["sent_at"] == 1000.0


def test_static_asset_is_served(settings: Settings) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "--blue:" in response.text


def test_favicon_redirects_to_static_asset(settings: Settings) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.get("/favicon.ico", follow_redirects=False)
        asset = client.get("/static/favicon.svg")

    assert response.status_code == 307
    assert response.headers["location"] == "/static/favicon.svg"
    assert asset.status_code == 200
    assert "<svg" in asset.text


def test_status_lists_accounts_and_live_groups(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SignalApiClient,
        "list_accounts",
        lambda self: [settings.number, "+420987654321"],
    )
    monkeypatch.setattr(
        SignalApiClient,
        "list_groups",
        lambda self: [
            {
                "id": "group.abc=",
                "name": "Operations",
                "blocked": False,
            }
        ],
    )
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"password": "correct-horse-battery"},
        )
        response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_number"] == settings.number
    assert payload["accounts"] == [settings.number, "+420987654321"]
    assert payload["groups"][0]["name"] == "Operations"


def test_plan_limits_alias_count_to_50(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dataclasses
    settings_50 = dataclasses.replace(settings, max_groups_per_run=50)
    groups = [
        {"id": f"group.{index:02d}=", "name": f"Group {index}", "blocked": False}
        for index in range(52)
    ]
    monkeypatch.setattr(SignalApiClient, "list_accounts", lambda self: [settings.number])
    monkeypatch.setattr(SignalApiClient, "list_groups", lambda self: groups)
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()
    attachments = [f"data:image/png;base64,{encoded}" for _ in range(5)]

    with TestClient(create_app(settings_50, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"password": "correct-horse-battery"},
        )
        status = client.get("/api/status")
        aliases_51 = [group["alias"] for group in status.json()["groups"][:51]]
        response_51 = client.post(
            "/api/plan",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"aliases": aliases_51, "message": "hello", "attachments": attachments},
        )
        assert response_51.status_code == 200

        aliases_50 = [group["alias"] for group in status.json()["groups"][:50]]
        response_50 = client.post(
            "/api/plan",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"aliases": aliases_50, "message": "hello", "attachments": attachments},
        )

    assert response_50.status_code == 200
    payload = response_50.json()
    assert payload["group_count"] == 50
    assert payload["attachment_count"] == 5


def test_link_qr_requires_authenticated_same_origin(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.post("/api/accounts/link-qr", json={})

    assert response.status_code == 403


def test_validates_png_attachment() -> None:
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()

    attachments, digests = _validated_attachments([f"data:image/png;base64,{encoded}"])

    assert attachments == [f"data:image/png;base64,{encoded}"]
    assert len(digests[0]) == 64


def test_validates_mp4_attachment() -> None:
    encoded = base64.b64encode(b"\x00\x00\x00\x18ftypmp42payload").decode()

    attachments, digests = _validated_attachments([f"data:video/mp4;base64,{encoded}"])

    assert attachments == [f"data:video/mp4;base64,{encoded}"]
    assert len(digests[0]) == 64


def test_rejects_attachment_with_mismatched_signature() -> None:
    encoded = base64.b64encode(b"not a png").decode()

    with pytest.raises(BroadcastError, match="does not match"):
        _validated_attachments([f"data:image/png;base64,{encoded}"])


def test_stats_returns_aggregated_data(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SignalApiClient, "list_accounts", lambda self: [settings.number])
    monkeypatch.setattr(
        SignalApiClient,
        "list_groups",
        lambda self: [{"id": "group.abc=", "name": "Ops", "blocked": False}],
    )
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"password": "correct-horse-battery"},
        )
        response = client.get("/api/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["hourly_count"] == 0
    assert payload["daily_count"] == 0
    assert payload["success_rate"] == 100
    assert payload["last_sent_at"] is None


def test_stats_requires_auth(settings: Settings) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.get("/api/stats")

    assert response.status_code == 401


def test_server_campaign_runs_repeats_without_browser_timer(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SignalApiClient, "list_accounts", lambda self: [settings.number])
    monkeypatch.setattr(
        SignalApiClient,
        "list_groups",
        lambda self: [{"id": "group.abc=", "name": "Ops", "blocked": False}],
    )
    delivery_scopes: list[str] = []

    def fake_send(
        self: BroadcastService,
        targets: object,
        message: str,
        **kwargs: object,
    ) -> list[BroadcastResult]:
        del self, message
        delivery_scopes.append(str(kwargs["delivery_scope"]))
        return [BroadcastResult(alias=target.alias, status="sent") for target in targets]

    monkeypatch.setattr(BroadcastService, "send", fake_send)

    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"password": "correct-horse-battery"},
        )
        status = client.get("/api/status")
        alias = status.json()["groups"][0]["alias"]
        plan = client.post(
            "/api/plan",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={
                "aliases": [alias],
                "message": "hello",
                "repeat_count": 2,
                "interval_seconds": 0,
            },
        ).json()
        start = client.post(
            "/api/campaign",
            headers={"Origin": "http://127.0.0.1:8787"},
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



