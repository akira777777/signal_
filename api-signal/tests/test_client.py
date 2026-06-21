from __future__ import annotations

from typing import Any, cast

import pytest
import requests

from signal_group_sender.client import (
    DeliveryUncertainError,
    SignalApiClient,
    SignalApiError,
)
from signal_group_sender.config import Settings


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.content = payload if isinstance(payload, bytes) else (
            b"x" if payload is not None else b""
        )

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> Any:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.trust_env = True
        self.get_responses: list[Any] = []
        self.post_response: Any = FakeResponse(201, {"timestamp": 1})
        self.post_calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        *,
        timeout: float,
        allow_redirects: bool,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        result = self.get_responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return cast(FakeResponse, result)

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: float,
        allow_redirects: bool,
    ) -> FakeResponse:
        self.post_calls.append(
            {
                "url": url,
                "json": json,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return cast(FakeResponse, self.post_response)


def test_send_uses_one_group_recipient(settings: Settings) -> None:
    session = FakeSession()
    client = SignalApiClient(settings, session=session)  # type: ignore[arg-type]

    client.send_group("group.abc=", "hello")

    assert session.trust_env is False
    assert session.post_calls == [
        {
            "url": "http://127.0.0.1:8080/v2/send",
            "json": {
                "message": "hello",
                "number": "+420123456789",
                "recipients": ["group.abc="],
            },
            "timeout": 5,
            "allow_redirects": False,
        }
    ]


def test_list_accounts(settings: Settings) -> None:
    session = FakeSession()
    session.get_responses = [FakeResponse(200, ["+420123456789", "+420987654321"])]
    client = SignalApiClient(settings, session=session)  # type: ignore[arg-type]

    assert client.list_accounts() == ["+420123456789", "+420987654321"]


def test_send_includes_base64_images(settings: Settings) -> None:
    session = FakeSession()
    client = SignalApiClient(settings, session=session)  # type: ignore[arg-type]

    client.send_group(
        "group.abc=",
        "hello",
        base64_attachments=["data:image/png;base64,iVBORw0KGgo="],
    )

    assert session.post_calls[0]["json"]["base64_attachments"] == [
        "data:image/png;base64,iVBORw0KGgo="
    ]


def test_link_qr_returns_image(settings: Settings) -> None:
    session = FakeSession()
    session.get_responses = [
        FakeResponse(200, b"png", headers={"Content-Type": "image/png"})
    ]
    client = SignalApiClient(settings, session=session)  # type: ignore[arg-type]

    content, content_type = client.link_qr("panel device")

    assert content == b"png"
    assert content_type == "image/png"


def test_list_groups_retries_retryable_status(settings: Settings) -> None:
    session = FakeSession()
    session.get_responses = [
        FakeResponse(503, {"error": "busy"}),
        FakeResponse(200, [{"id": "group.abc=", "name": "Ops"}]),
    ]
    sleeps: list[float] = []
    client = SignalApiClient(
        settings,
        session=session,  # type: ignore[arg-type]
        sleeper=sleeps.append,
    )

    groups = client.list_groups()

    assert groups[0]["name"] == "Ops"
    assert sleeps == [0.5]


def test_send_does_not_retry_when_delivery_is_uncertain(settings: Settings) -> None:
    session = FakeSession()
    session.post_response = requests.Timeout()
    client = SignalApiClient(settings, session=session)  # type: ignore[arg-type]

    try:
        client.send_group("group.abc=", "hello")
    except DeliveryUncertainError:
        pass
    else:
        raise AssertionError("Expected DeliveryUncertainError")

    assert len(session.post_calls) == 1


def test_list_groups_encodes_plus_in_number(settings: Settings) -> None:
    session = FakeSession()
    session.get_responses = [FakeResponse(200, [])]
    requested_urls: list[str] = []

    def capture_get(
        url: str,
        *,
        timeout: float,
        allow_redirects: bool,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        requested_urls.append(url)
        return FakeResponse(200, [])

    session.get = capture_get  # type: ignore[method-assign]
    client = SignalApiClient(settings, session=session)  # type: ignore[arg-type]

    client.list_groups()

    assert requested_urls == ["http://127.0.0.1:8080/v1/groups/%2B420123456789"]


def test_list_groups_rejects_unexpected_payload(settings: Settings) -> None:
    session = FakeSession()
    session.get_responses = [FakeResponse(200, {"id": "group.abc="})]
    client = SignalApiClient(settings, session=session)  # type: ignore[arg-type]

    with pytest.raises(SignalApiError, match="unexpected"):
        client.list_groups()


def test_send_http_error_is_uncertain_and_not_retried(settings: Settings) -> None:
    session = FakeSession()
    session.post_response = FakeResponse(503, {"error": "busy"})
    client = SignalApiClient(settings, session=session)  # type: ignore[arg-type]

    with pytest.raises(DeliveryUncertainError, match="HTTP 503"):
        client.send_group("group.abc=", "hello")

    assert len(session.post_calls) == 1


def test_send_requires_timestamp_in_success_response(settings: Settings) -> None:
    session = FakeSession()
    session.post_response = FakeResponse(201, {})
    client = SignalApiClient(settings, session=session)  # type: ignore[arg-type]

    with pytest.raises(DeliveryUncertainError, match="timestamp"):
        client.send_group("group.abc=", "hello")
