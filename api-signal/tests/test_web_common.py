from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from signal_group_sender.web_common import (
    SignedSessionManager,
    require_json_same_origin,
    validate_image_data_urls,
)


def _request(
    *,
    method: str = "POST",
    origin: str | None = "http://127.0.0.1:8787",
    content_type: str = "application/json",
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if content_type:
        headers.append((b"content-type", content_type.encode()))
    scope = {
        "type": "http",
        "method": method,
        "headers": headers,
        "path": "/api/plan",
    }
    return Request(scope)


def test_signed_session_manager_accepts_issued_token() -> None:
    manager = SignedSessionManager(b"secret-key")

    token = manager.issue()

    assert manager.valid(token) is True


def test_signed_session_manager_rejects_tampered_token() -> None:
    manager = SignedSessionManager(b"secret-key")

    token = manager.issue() + "tampered"

    assert manager.valid(token) is False


def test_same_origin_allows_json_requests() -> None:
    request = _request()

    require_json_same_origin(
        request,
        allowed_origins={"http://127.0.0.1:8787", "http://localhost:8787"},
    )


def test_same_origin_rejects_wrong_origin() -> None:
    request = _request(origin="https://example.com")

    with pytest.raises(HTTPException, match="Invalid request origin"):
        require_json_same_origin(
            request,
            allowed_origins={"http://127.0.0.1:8787", "http://localhost:8787"},
        )


def test_same_origin_rejects_non_json_content_type() -> None:
    request = _request(content_type="text/plain")

    with pytest.raises(HTTPException, match="JSON request required"):
        require_json_same_origin(
            request,
            allowed_origins={"http://127.0.0.1:8787", "http://localhost:8787"},
        )


def test_validate_image_data_urls_returns_digest_and_data_url() -> None:
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()

    validated = validate_image_data_urls(
        [f"data:image/png;base64,{encoded}"],
        error_type=RuntimeError,
    )

    assert validated[0].data_url == f"data:image/png;base64,{encoded}"
    assert len(validated[0].digest) == 64


def test_validate_image_data_urls_rejects_signature_mismatch() -> None:
    encoded = base64.b64encode(b"not a png").decode()

    with pytest.raises(RuntimeError, match="does not match"):
        validate_image_data_urls(
            [f"data:image/png;base64,{encoded}"],
            error_type=RuntimeError,
        )
