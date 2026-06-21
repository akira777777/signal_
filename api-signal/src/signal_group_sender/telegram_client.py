from __future__ import annotations

import asyncio
import importlib
import io
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TypeVar

from signal_group_sender.telegram_config import TelegramSettings

T = TypeVar("T")


class TelegramApiError(RuntimeError):
    """Raised when Telegram rejects or cannot complete a request."""


class TelegramAuthRequiredError(TelegramApiError):
    """Raised when the Telegram session is not authorized."""


class TelegramPasswordRequiredError(TelegramApiError):
    """Raised when Telegram two-step verification is required."""


class TelegramDeliveryUncertainError(TelegramApiError):
    """Raised when a message may have been sent but no reliable result is known."""


@dataclass(frozen=True, slots=True)
class TelegramAttachment:
    name: str
    mime_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class TelethonRuntime:
    client_type: Any
    rpc_error: type[BaseException]
    session_password_needed_error: type[BaseException]
    channel_type: type[Any]
    chat_type: type[Any]
    user_type: type[Any]
    get_peer_id: Callable[[Any], int]


@lru_cache(maxsize=1)
def _telethon_runtime() -> TelethonRuntime:
    try:
        telethon_module = importlib.import_module("telethon")
        errors_module = importlib.import_module("telethon.errors")
        types_module = importlib.import_module("telethon.tl.types")
        utils_module = importlib.import_module("telethon.utils")
    except ModuleNotFoundError as exc:
        raise TelegramApiError(
            "Telethon is not installed. "
            "Install project dependencies before using Telegram features."
        ) from exc

    return TelethonRuntime(
        client_type=telethon_module.TelegramClient,
        rpc_error=errors_module.RPCError,
        session_password_needed_error=errors_module.SessionPasswordNeededError,
        channel_type=types_module.Channel,
        chat_type=types_module.Chat,
        user_type=types_module.User,
        get_peer_id=utils_module.get_peer_id,
    )


class TelegramApiClient:
    def __init__(
        self,
        settings: TelegramSettings,
        *,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory or self._default_client_factory

    def _default_client_factory(self) -> Any:
        runtime = _telethon_runtime()
        self._settings.session_file.parent.mkdir(parents=True, exist_ok=True)
        return runtime.client_type(
            str(self._settings.session_file),
            self._settings.api_id,
            self._settings.api_hash,
            device_model="codex-telegram-sender",
            system_version="Codex",
            app_version="0.1",
        )

    def _run(self, operation: Callable[[Any], Awaitable[T]]) -> T:
        return asyncio.run(self._with_client(operation))

    async def _with_client(self, operation: Callable[[Any], Awaitable[T]]) -> T:
        client = self._client_factory()
        try:
            await client.connect()
            return await operation(client)
        finally:
            await client.disconnect()

    async def _ensure_authorized(self, client: Any) -> None:
        if not await client.is_user_authorized():
            raise TelegramAuthRequiredError(
                "Telegram session is not authorized. Sign in first."
            )

    def is_authorized(self) -> bool:
        return self._run(self._is_authorized)

    async def _is_authorized(self, client: Any) -> bool:
        try:
            return bool(await client.is_user_authorized())
        except (OSError, TimeoutError) as exc:
            raise TelegramApiError("Telegram is unavailable") from exc

    def request_code(self) -> str | None:
        return self._run(self._request_code)

    async def _request_code(self, client: Any) -> str | None:
        runtime = _telethon_runtime()
        try:
            if await client.is_user_authorized():
                return None
            result = await client.send_code_request(self._settings.phone_number)
        except runtime.rpc_error as exc:
            raise TelegramApiError(f"Telegram rejected the login request: {exc}") from exc
        except (OSError, TimeoutError) as exc:
            raise TelegramApiError("Telegram did not send a login code") from exc
        phone_code_hash = getattr(result, "phone_code_hash", None)
        if not isinstance(phone_code_hash, str) or not phone_code_hash:
            raise TelegramApiError("Telegram did not return a valid login challenge")
        return phone_code_hash

    def authorize(
        self,
        code: str,
        phone_code_hash: str,
        *,
        password: str | None = None,
    ) -> None:
        self._run(
            lambda client: self._authorize(
                client,
                code=code,
                phone_code_hash=phone_code_hash,
                password=password,
            )
        )

    async def _authorize(
        self,
        client: Any,
        *,
        code: str,
        phone_code_hash: str,
        password: str | None,
    ) -> None:
        runtime = _telethon_runtime()
        try:
            await client.sign_in(
                phone=self._settings.phone_number,
                code=code,
                phone_code_hash=phone_code_hash,
            )
        except runtime.session_password_needed_error as exc:
            if not password:
                raise TelegramPasswordRequiredError(
                    "Telegram two-step verification password required"
                ) from exc
            try:
                await client.sign_in(password=password)
            except runtime.rpc_error as password_exc:
                raise TelegramApiError(
                    f"Telegram rejected the two-step verification password: {password_exc}"
                ) from password_exc
        except runtime.rpc_error as exc:
            raise TelegramApiError(f"Telegram rejected the login code: {exc}") from exc
        except (OSError, TimeoutError) as exc:
            raise TelegramApiError("Telegram authorization did not complete") from exc

        if not await client.is_user_authorized():
            raise TelegramApiError("Telegram authorization did not complete")

    def list_dialogs(self) -> list[dict[str, Any]]:
        return self._run(self._list_dialogs)

    async def _list_dialogs(self, client: Any) -> list[dict[str, Any]]:
        runtime = _telethon_runtime()
        try:
            await self._ensure_authorized(client)
            dialogs: list[dict[str, Any]] = []
            async for dialog in client.iter_dialogs():
                rendered = self._dialog_record(dialog, runtime)
                if rendered is not None:
                    dialogs.append(rendered)
            return dialogs
        except TelegramAuthRequiredError:
            raise
        except runtime.rpc_error as exc:
            raise TelegramApiError(f"Telegram rejected the dialog listing request: {exc}") from exc
        except (OSError, TimeoutError) as exc:
            raise TelegramApiError("Telegram is unavailable") from exc

    def _dialog_record(
        self,
        dialog: Any,
        runtime: TelethonRuntime,
    ) -> dict[str, Any] | None:
        entity = getattr(dialog, "entity", None)
        if entity is None:
            return None
        if isinstance(entity, runtime.user_type):
            if getattr(entity, "is_self", False) or getattr(entity, "deleted", False):
                return None
            kind = "user"
            available = True
        elif isinstance(entity, runtime.chat_type):
            kind = "group"
            available = not getattr(entity, "left", False) and not getattr(
                entity, "deactivated", False
            )
        elif isinstance(entity, runtime.channel_type):
            if getattr(entity, "megagroup", False):
                kind = "supergroup"
                available = not getattr(entity, "left", False)
            elif getattr(entity, "broadcast", False):
                kind = "channel"
                admin_rights = getattr(entity, "admin_rights", None)
                can_post = bool(
                    getattr(entity, "creator", False)
                    or getattr(admin_rights, "post_messages", False)
                )
                available = can_post and not getattr(entity, "left", False)
            else:
                kind = "channel"
                available = not getattr(entity, "left", False)
        else:
            return None

        peer_id = str(runtime.get_peer_id(entity))
        title = getattr(dialog, "title", None)
        if isinstance(title, str) and title.strip():
            name = title.strip()
        else:
            first_name = getattr(entity, "first_name", "") or ""
            last_name = getattr(entity, "last_name", "") or ""
            username = getattr(entity, "username", "") or ""
            name = " ".join(part for part in (first_name, last_name) if part).strip()
            if not name:
                name = username or peer_id

        return {
            "id": peer_id,
            "name": name,
            "kind": kind,
            "available": available,
        }

    def send_chat(
        self,
        peer_id: str,
        message: str,
        *,
        attachments: list[TelegramAttachment] | None = None,
    ) -> dict[str, Any]:
        return self._run(
            lambda client: self._send_chat(
                client,
                peer_id=peer_id,
                message=message,
                attachments=attachments,
            )
        )

    async def _send_chat(
        self,
        client: Any,
        *,
        peer_id: str,
        message: str,
        attachments: list[TelegramAttachment] | None,
    ) -> dict[str, Any]:
        runtime = _telethon_runtime()
        try:
            await self._ensure_authorized(client)
            entity = await self._resolve_entity(client, peer_id, runtime)
            if attachments:
                files: list[io.BytesIO] = []
                for attachment in attachments:
                    buffer = io.BytesIO(attachment.content)
                    buffer.name = attachment.name
                    files.append(buffer)
                result = await client.send_file(
                    entity,
                    files,
                    caption=message or None,
                    force_document=False,
                )
            else:
                result = await client.send_message(entity, message)
        except TelegramAuthRequiredError:
            raise
        except runtime.rpc_error as exc:
            raise TelegramApiError(f"Telegram rejected the send request: {exc}") from exc
        except (OSError, TimeoutError) as exc:
            raise TelegramDeliveryUncertainError(
                "No response from Telegram; delivery is unknown and was not retried"
            ) from exc

        return {"result": "ok", "message": bool(result)}

    async def _resolve_entity(
        self,
        client: Any,
        peer_id: str,
        runtime: TelethonRuntime,
    ) -> Any:
        async for dialog in client.iter_dialogs():
            entity = getattr(dialog, "entity", None)
            if entity is not None and str(runtime.get_peer_id(entity)) == peer_id:
                return entity
        raise TelegramApiError(f"Telegram chat {peer_id} is no longer visible")
