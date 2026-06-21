from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from signal_group_sender.client import SignalApiClient
from signal_group_sender.config import Settings
from signal_group_sender.service import BroadcastError
from signal_group_sender.web import _validated_images, create_app


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


def test_static_asset_is_served(settings: Settings) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "--blue:" in response.text


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


def test_plan_does_not_limit_alias_or_image_count(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = [
        {"id": f"group.{index:02d}=", "name": f"Group {index}", "blocked": False}
        for index in range(12)
    ]
    monkeypatch.setattr(SignalApiClient, "list_accounts", lambda self: [settings.number])
    monkeypatch.setattr(SignalApiClient, "list_groups", lambda self: groups)
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()
    images = [f"data:image/png;base64,{encoded}" for _ in range(5)]

    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        client.post(
            "/api/login",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"password": "correct-horse-battery"},
        )
        status = client.get("/api/status")
        aliases = [group["alias"] for group in status.json()["groups"][:11]]
        response = client.post(
            "/api/plan",
            headers={"Origin": "http://127.0.0.1:8787"},
            json={"aliases": aliases, "message": "hello", "images": images},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["group_count"] == 11
    assert payload["image_count"] == 5


def test_link_qr_requires_authenticated_same_origin(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings, "correct-horse-battery")) as client:
        response = client.post("/api/accounts/link-qr", json={})

    assert response.status_code == 403


def test_validates_png_image() -> None:
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()

    images, digests = _validated_images([f"data:image/png;base64,{encoded}"])

    assert images == [f"data:image/png;base64,{encoded}"]
    assert len(digests[0]) == 64


def test_rejects_image_with_mismatched_signature() -> None:
    encoded = base64.b64encode(b"not a png").decode()

    with pytest.raises(BroadcastError, match="does not match"):
        _validated_images([f"data:image/png;base64,{encoded}"])
