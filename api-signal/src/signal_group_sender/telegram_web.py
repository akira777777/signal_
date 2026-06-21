from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, cast

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from signal_group_sender.locking import LockError, RunLock
from signal_group_sender.state import (
    DeliveryLedger,
    StateError,
    load_or_create_hmac_key,
)
from signal_group_sender.telegram_client import (
    TelegramApiClient,
    TelegramApiError,
    TelegramAttachment,
    TelegramPasswordRequiredError,
)
from signal_group_sender.telegram_config import TelegramConfigError, TelegramSettings
from signal_group_sender.telegram_service import (
    TelegramBroadcastError,
    TelegramBroadcastService,
    build_broadcast_plan,
    verify_chat_targets,
)
from signal_group_sender.telegram_targets import (
    ChatTarget,
    TelegramTargetError,
    select_targets,
)
from signal_group_sender.web_common import (
    MAX_IMAGE_DATA_URL_CHARS,
    SignedSessionManager,
    require_json_same_origin,
    validate_image_data_urls,
)

LOGGER = logging.getLogger("signal_group_sender.telegram_web")
PACKAGE_DIRECTORY = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIRECTORY / "templates")
ALLOWED_ORIGINS = {"http://127.0.0.1:8788", "http://localhost:8788"}
IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aliases: list[str] = Field(min_length=1, max_length=100)
    message: str = Field(default="", max_length=4096)
    repeat_count: int = Field(default=1, ge=1, le=20)
    interval_seconds: int = Field(default=0, ge=0, le=86_400)
    images: list[Annotated[str, Field(max_length=MAX_IMAGE_DATA_URL_CHARS)]] = Field(
        default_factory=list,
    )


class SendRequest(PlanRequest):
    confirm_token: str = Field(pattern=r"^[0-9a-f]{16}$")
    retry_unknown: bool = False
    round_index: int = Field(default=1, ge=1, le=20)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)


class AuthCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    password: str | None = Field(default=None, max_length=256)


class TelegramWebContext:
    def __init__(self, settings: TelegramSettings, web_password: str) -> None:
        self.settings = settings
        self.web_password = web_password
        self.session_secret = load_or_create_hmac_key(settings.state_secret_file)
        self._session_manager = SignedSessionManager(self.session_secret)
        self._auth_lock = threading.RLock()
        self._pending_phone_code_hash: str | None = None

    def client(self) -> TelegramApiClient:
        return TelegramApiClient(self.settings)

    def service(self) -> TelegramBroadcastService:
        key = self.session_secret
        ledger = DeliveryLedger(
            self.settings.state_file,
            integrity_key=key,
            duplicate_window_seconds=self.settings.duplicate_window_seconds,
        )
        ledger.initialize(allow_create=not self.settings.state_file.exists())
        return TelegramBroadcastService(self.settings, self.client(), ledger, key)

    def live_targets(self) -> dict[str, ChatTarget]:
        targets: dict[str, ChatTarget] = {}
        for dialog in self.client().list_dialogs():
            peer_id = dialog.get("id")
            name = dialog.get("name")
            kind = dialog.get("kind")
            available = dialog.get("available")
            if (
                not isinstance(peer_id, str)
                or not isinstance(name, str)
                or not isinstance(kind, str)
                or available is not True
            ):
                continue
            alias = "t-" + hashlib.sha256(peer_id.encode()).hexdigest()[:16]
            targets[alias] = ChatTarget(alias, peer_id, name, kind)
        return targets

    def selected(self, aliases: list[str]) -> list[ChatTarget]:
        return select_targets(self.live_targets(), aliases, all_live=False)

    def is_authorized(self) -> bool:
        return self.client().is_authorized()

    def request_code(self) -> bool:
        phone_code_hash = self.client().request_code()
        with self._auth_lock:
            self._pending_phone_code_hash = phone_code_hash
        return phone_code_hash is None

    def complete_auth(self, code: str, password: str | None) -> bool:
        with self._auth_lock:
            phone_code_hash = self._pending_phone_code_hash
        if not phone_code_hash:
            raise TelegramBroadcastError("Request a Telegram login code first")
        self.client().authorize(code, phone_code_hash, password=password)
        with self._auth_lock:
            self._pending_phone_code_hash = None
        return True

    def issue_session(self) -> str:
        return self._session_manager.issue()

    def valid_session(self, token: str | None) -> bool:
        return self._session_manager.valid(token)


def _same_origin(request: Request) -> None:
    require_json_same_origin(request, allowed_origins=ALLOWED_ORIGINS)


def _context(request: Request) -> TelegramWebContext:
    return cast(TelegramWebContext, request.app.state.context)


def _authenticated(
    request: Request,
    context: Annotated[TelegramWebContext, Depends(_context)],
) -> None:
    if not context.valid_session(request.cookies.get("telegram_session")):
        raise HTTPException(status_code=401, detail="Authentication required")


ContextDependency = Annotated[TelegramWebContext, Depends(_context)]
OriginDependency = Annotated[None, Depends(_same_origin)]
AuthDependency = Annotated[None, Depends(_authenticated)]


def _chat_view(target: ChatTarget) -> dict[str, Any]:
    return {
        "alias": target.alias,
        "name": target.description or target.alias,
        "kind": target.kind,
        "available": True,
    }


def _validated_images(images: list[str]) -> tuple[list[TelegramAttachment], tuple[str, ...]]:
    validated = validate_image_data_urls(images, error_type=TelegramBroadcastError)
    attachments = [
        TelegramAttachment(
            name=f"telegram-image-{index}{IMAGE_EXTENSIONS[image.media_type]}",
            mime_type=image.media_type,
            content=image.raw,
        )
        for index, image in enumerate(validated, start=1)
    ]
    return attachments, tuple(image.digest for image in validated)


def create_app(
    settings: TelegramSettings | None = None,
    web_password: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        password = web_password if web_password is not None else os.getenv(
            "TELEGRAM_WEB_PASSWORD", ""
        )
        if len(password) < 4:
            raise TelegramConfigError("TELEGRAM_WEB_PASSWORD must contain at least 4 characters")
        app.state.context = TelegramWebContext(
            settings or TelegramSettings.from_env(Path(".env")),
            password,
        )
        yield

    app = FastAPI(
        title="Telegram Панель",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )
    app.mount(
        "/static",
        StaticFiles(directory=PACKAGE_DIRECTORY / "static"),
        name="static",
    )

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return RedirectResponse("/static/favicon.svg", status_code=307)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, context: ContextDependency) -> Response:
        if not context.valid_session(request.cookies.get("telegram_session")):
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request, "telegram_index.html")

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, context: ContextDependency) -> Response:
        if context.valid_session(request.cookies.get("telegram_session")):
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "telegram_login.html")

    @app.post("/api/login")
    def login(
        payload: LoginRequest,
        context: ContextDependency,
        _: OriginDependency,
    ) -> JSONResponse:
        if not hmac.compare_digest(payload.password, context.web_password):
            raise HTTPException(status_code=401, detail="Неверный пароль")
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            "telegram_session",
            context.issue_session(),
            max_age=8 * 3600,
            httponly=True,
            secure=False,
            samesite="strict",
            path="/",
        )
        return response

    @app.post("/api/logout")
    def logout(_: OriginDependency) -> JSONResponse:
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("telegram_session", path="/")
        return response

    @app.get("/api/status")
    def status(context: ContextDependency, _: AuthDependency) -> dict[str, Any]:
        try:
            authorized = context.is_authorized()
            targets = context.live_targets() if authorized else {}
        except TelegramApiError as exc:
            return {
                "connected": False,
                "authorized": False,
                "message": str(exc),
                "phone": context.settings.phone_number,
                "chats": [],
            }
        if not authorized:
            return {
                "connected": True,
                "authorized": False,
                "message": f"Нужен вход в Telegram: {context.settings.phone_number}",
                "phone": context.settings.phone_number,
                "chats": [],
            }
        return {
            "connected": True,
            "authorized": True,
            "message": f"Telegram подключён: {context.settings.phone_number}",
            "phone": context.settings.phone_number,
            "chats": [_chat_view(target) for target in targets.values()],
        }

    @app.get("/api/history")
    def get_history(
        context: ContextDependency,
        _: AuthDependency,
    ) -> list[dict[str, Any]]:
        records = context.service().get_history()
        return [
            {
                "alias": record.alias,
                "target_token": record.target_token,
                "sent_at": record.sent_at,
                "status": record.status,
            }
            for record in reversed(records)
        ]

    @app.get("/api/stats")
    def get_stats(
        context: ContextDependency,
        _: AuthDependency,
    ) -> dict[str, Any]:
        return context.service().get_stats()

    @app.post("/api/auth/request-code")
    def request_code(
        context: ContextDependency,
        _: OriginDependency,
        __: AuthDependency,
    ) -> dict[str, Any]:
        already_authorized = context.request_code()
        return {
            "authorized": already_authorized,
            "code_sent": not already_authorized,
            "phone": context.settings.phone_number,
        }

    @app.post("/api/auth/complete")
    def complete_auth(
        payload: AuthCompleteRequest,
        context: ContextDependency,
        _: OriginDependency,
        __: AuthDependency,
    ) -> dict[str, Any]:
        try:
            context.complete_auth(payload.code.strip(), payload.password)
        except TelegramPasswordRequiredError:
            return {"authorized": False, "password_required": True}
        return {"authorized": True, "password_required": False}

    @app.post("/api/plan")
    def plan(
        payload: PlanRequest,
        context: ContextDependency,
        _: OriginDependency,
        __: AuthDependency,
    ) -> dict[str, Any]:
        targets = context.selected(payload.aliases)
        attachments, attachment_digests = _validated_images(payload.images)
        del attachments
        plan_result = build_broadcast_plan(
            context.settings,
            targets,
            payload.message,
            repeat_count=payload.repeat_count,
            interval_seconds=payload.interval_seconds,
            attachment_digests=attachment_digests,
        )
        verify_chat_targets(context.client(), targets)
        return {
            "aliases": plan_result.aliases,
            "chat_count": len(plan_result.aliases),
            "message_chars": plan_result.message_chars,
            "confirm_token": plan_result.confirm_token,
            "repeat_count": payload.repeat_count,
            "interval_seconds": payload.interval_seconds,
            "image_count": len(attachment_digests),
        }

    @app.post("/api/send")
    def send(
        payload: SendRequest,
        context: ContextDependency,
        _: OriginDependency,
        __: AuthDependency,
    ) -> dict[str, Any]:
        targets = context.selected(payload.aliases)
        attachments, attachment_digests = _validated_images(payload.images)
        with RunLock(context.settings.lock_file):
            results = context.service().send(
                targets,
                payload.message,
                confirm_count=len(targets),
                confirm_token=payload.confirm_token,
                retry_unknown=payload.retry_unknown,
                repeat_count=payload.repeat_count,
                interval_seconds=payload.interval_seconds,
                delivery_scope=f"{payload.confirm_token}:{payload.round_index}",
                attachments=attachments,
                attachment_digests=attachment_digests,
            )
        return {
            "results": [asdict(result) for result in results],
            "round_index": payload.round_index,
            "complete": all(
                result.status in {"sent", "already_sent"} for result in results
            ),
        }

    def domain_error(_: Request, exc: Exception) -> Any:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    for exception_type in (
        LockError,
        StateError,
        TelegramApiError,
        TelegramBroadcastError,
        TelegramConfigError,
        TelegramTargetError,
    ):
        app.add_exception_handler(exception_type, domain_error)

    return app


app = create_app()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    uvicorn.run(
        "signal_group_sender.telegram_web:app",
        host="0.0.0.0",
        port=8788,
        workers=1,
        proxy_headers=False,
        server_header=False,
    )
