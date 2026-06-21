from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import requests

from signal_group_sender.config import Settings

_RETRYABLE_GET_STATUS = {429, 502, 503, 504}


class SignalApiError(RuntimeError):
    """Raised when signal-cli-rest-api rejects or cannot complete a request."""


class DeliveryUncertainError(SignalApiError):
    """Raised when a send may have reached the API but no response was received."""


class SignalApiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._session = session or requests.Session()
        self._session.trust_env = False
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "signal-group-sender/0.1",
            }
        )
        self._sleeper = sleeper

    def _url(self, path: str) -> str:
        return f"{self._settings.api_url}{path}"

    def list_accounts(self) -> list[str]:
        try:
            response = self._session.get(
                self._url("/v1/accounts"),
                timeout=self._settings.request_timeout_seconds,
                allow_redirects=False,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise SignalApiError("Signal API is unavailable") from exc
        if not response.ok:
            raise SignalApiError(
                f"Signal API returned HTTP {response.status_code} while listing accounts"
            )
        try:
            payload = response.json()
        except requests.JSONDecodeError as exc:
            raise SignalApiError("Signal API returned invalid accounts JSON") from exc
        if not isinstance(payload, list) or not all(
            isinstance(number, str) for number in payload
        ):
            raise SignalApiError("Signal API returned an unexpected accounts response")
        return payload

    def link_qr(self, device_name: str) -> tuple[bytes, str]:
        try:
            response = self._session.get(
                self._url(
                    f"/v1/qrcodelink?device_name={quote(device_name, safe='')}"
                ),
                headers={"Accept": "image/png"},
                timeout=self._settings.request_timeout_seconds,
                allow_redirects=False,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise SignalApiError("Signal API did not generate a linking QR code") from exc
        if not response.ok:
            raise SignalApiError(
                f"Signal API returned HTTP {response.status_code} while linking account"
            )
        content_type = response.headers.get("Content-Type", "image/png").split(";", 1)[0]
        if not content_type.startswith("image/") or not response.content:
            raise SignalApiError("Signal API returned an invalid linking QR code")
        return response.content, content_type

    def list_groups(self) -> list[dict[str, Any]]:
        number = quote(self._settings.number, safe="")
        url = self._url(f"/v1/groups/{number}")

        for attempt in range(self._settings.get_max_retries + 1):
            try:
                response = self._session.get(
                    url,
                    timeout=self._settings.request_timeout_seconds,
                    allow_redirects=False,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self._settings.get_max_retries:
                    raise SignalApiError("Signal API is unavailable") from exc
                self._sleeper(0.5 * (2**attempt))
                continue

            if (
                response.status_code in _RETRYABLE_GET_STATUS
                and attempt < self._settings.get_max_retries
            ):
                retry_after = response.headers.get("Retry-After")
                delay = (
                    min(float(retry_after), 30.0)
                    if retry_after and retry_after.replace(".", "", 1).isdigit()
                    else 0.5 * (2**attempt)
                )
                self._sleeper(delay)
                continue

            if not response.ok:
                raise SignalApiError(
                    f"Signal API returned HTTP {response.status_code} while listing groups"
                )

            try:
                payload = response.json()
            except requests.JSONDecodeError as exc:
                raise SignalApiError("Signal API returned invalid JSON") from exc
            if not isinstance(payload, list) or not all(
                isinstance(item, dict) for item in payload
            ):
                raise SignalApiError("Signal API returned an unexpected groups response")
            return payload

        raise AssertionError("unreachable")

    def send_group(
        self,
        group_id: str,
        message: str,
        *,
        base64_attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "message": message,
            "number": self._settings.number,
            "recipients": [group_id],
        }
        if base64_attachments:
            payload["base64_attachments"] = base64_attachments
        try:
            response = self._session.post(
                self._url("/v2/send"),
                json=payload,
                timeout=self._settings.request_timeout_seconds,
                allow_redirects=False,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise DeliveryUncertainError(
                "No response from Signal API; delivery is unknown and was not retried"
            ) from exc

        if response.status_code != 201:
            raise DeliveryUncertainError(
                f"Signal API returned HTTP {response.status_code}; delivery is unknown"
            )

        try:
            result = response.json()
        except requests.JSONDecodeError as exc:
            raise DeliveryUncertainError(
                "Signal API returned an invalid success response; delivery is unknown"
            ) from exc
        if not isinstance(result, dict) or not isinstance(
            result.get("timestamp"), (str, int)
        ):
            raise DeliveryUncertainError(
                "Signal API omitted the delivery timestamp; delivery is unknown"
            )
        return result
