from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import TypeAlias

from fastapi import HTTPException, Request

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_DATA_URL_CHARS = 11_200_000
IMAGE_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}

ExceptionFactory: TypeAlias = type[Exception]


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    media_type: str
    encoded: str
    raw: bytes
    digest: str

    @property
    def data_url(self) -> str:
        return f"data:{self.media_type};base64,{self.encoded}"


class SignedSessionManager:
    def __init__(self, secret: bytes, *, lifetime_seconds: int = 8 * 3600) -> None:
        self._secret = secret
        self._lifetime_seconds = lifetime_seconds

    def issue(self) -> str:
        expires_at = int(time.time()) + self._lifetime_seconds
        nonce = secrets.token_hex(16)
        payload = f"{expires_at}.{nonce}"
        signature = hmac.new(
            self._secret, payload.encode(), hashlib.sha256
        ).hexdigest()
        return f"{payload}.{signature}"

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        parts = token.split(".")
        if len(parts) != 3:
            return False
        expires_at, nonce, supplied_signature = parts
        if not expires_at.isdigit() or len(nonce) != 32:
            return False
        if int(expires_at) <= int(time.time()):
            return False
        payload = f"{expires_at}.{nonce}"
        expected = hmac.new(
            self._secret, payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(supplied_signature, expected)


def require_json_same_origin(request: Request, *, allowed_origins: set[str]) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin not in allowed_origins:
        raise HTTPException(status_code=403, detail="Invalid request origin")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise HTTPException(status_code=415, detail="JSON request required")


def validate_image_data_urls(
    images: list[str],
    *,
    error_type: ExceptionFactory,
) -> list[ValidatedImage]:
    validated: list[ValidatedImage] = []
    total_bytes = 0
    for image in images:
        if not image.startswith("data:") or ";base64," not in image:
            raise error_type("Image must use a base64 data URL")
        header, encoded = image.split(",", 1)
        media_type = header[5:].split(";", 1)[0].lower()
        signatures = IMAGE_SIGNATURES.get(media_type)
        if signatures is None:
            raise error_type("Only PNG, JPEG, WebP and GIF images are allowed")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise error_type("Image contains invalid base64 data") from exc
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise error_type("Each image must be between 1 byte and 8 MB")
        if media_type == "image/webp":
            valid_signature = raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"
        else:
            valid_signature = any(raw.startswith(prefix) for prefix in signatures)
        if not valid_signature:
            raise error_type("Image content does not match its MIME type")
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise error_type("Total image size must not exceed 20 MB")
        validated.append(
            ValidatedImage(
                media_type=media_type,
                encoded=encoded,
                raw=raw,
                digest=hashlib.sha256(raw).hexdigest(),
            )
        )
    return validated
