from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated, Any, cast

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from signal_group_sender.client import SignalApiClient, SignalApiError
from signal_group_sender.config import ConfigError, Settings
from signal_group_sender.groups import (
    AllowlistError,
    GroupTarget,
    select_targets,
)
from signal_group_sender.locking import LockError, RunLock
from signal_group_sender.service import (
    BroadcastError,
    BroadcastService,
    build_broadcast_plan,
    verify_group_targets,
)
from signal_group_sender.state import (
    DeliveryLedger,
    StateError,
    load_or_create_hmac_key,
)

LOGGER = logging.getLogger("signal_group_sender.web")
PACKAGE_DIRECTORY = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIRECTORY / "templates")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_DATA_URL_CHARS = 11_200_000
IMAGE_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aliases: list[str] = Field(min_length=1, max_length=50)
    message: str = Field(min_length=1, max_length=20_000)
    repeat_count: int = Field(default=1, ge=1, le=20)
    interval_seconds: int = Field(default=0, ge=0, le=86_400)
    images: list[Annotated[str, Field(max_length=MAX_IMAGE_DATA_URL_CHARS)]] = Field(
        default_factory=list,
    )


class SendRequest(PlanRequest):
    confirm_token: str = Field(pattern=r"^[0-9a-f]{16}$")
    retry_unknown: bool = False
    round_index: int = Field(default=1, ge=1, le=20)


class AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)


class WebContext:
    def __init__(self, settings: Settings, web_password: str) -> None:
        self._base_settings = settings
        self._active_number = settings.number
        self._account_lock = threading.RLock()
        self.web_password = web_password
        self.session_secret = load_or_create_hmac_key(settings.state_secret_file)

    @property
    def settings(self) -> Settings:
        with self._account_lock:
            return replace(self._base_settings, number=self._active_number)

    def selected(self, aliases: list[str]) -> list[GroupTarget]:
        return select_targets(self.live_targets(), aliases, all_allowed=False)

    def accounts(self) -> list[str]:
        return SignalApiClient(self._base_settings).list_accounts()

    def link_qr(self) -> tuple[bytes, str]:
        return SignalApiClient(self._base_settings).link_qr(
            "signal-broadcast-panel"
        )

    def select_account(self, number: str) -> None:
        if number not in self.accounts():
            raise BroadcastError("Selected Signal account is not linked")
        with self._account_lock:
            self._active_number = number

    def live_targets(self) -> dict[str, GroupTarget]:
        targets: dict[str, GroupTarget] = {}
        for group in self.client().list_groups():
            group_id = group.get("id")
            blocked = group.get("blocked", group.get("isBlocked"))
            if not isinstance(group_id, str) or not group_id.startswith("group."):
                continue
            if blocked is not False:
                continue
            name = group.get("name")
            description = name if isinstance(name, str) and name.strip() else group_id
            alias = "g-" + hashlib.sha256(group_id.encode()).hexdigest()[:16]
            targets[alias] = GroupTarget(alias, group_id, description)
        return targets

    def client(self) -> SignalApiClient:
        return SignalApiClient(self.settings)

    def service(self) -> BroadcastService:
        key = self.session_secret
        ledger = DeliveryLedger(
            self.settings.state_file,
            integrity_key=key,
            duplicate_window_seconds=self.settings.duplicate_window_seconds,
        )
        ledger.initialize(allow_create=not self.settings.state_file.exists())
        return BroadcastService(self.settings, self.client(), ledger, key)

    def issue_session(self) -> str:
        expires_at = int(time.time()) + 8 * 3600
        nonce = secrets.token_hex(16)
        payload = f"{expires_at}.{nonce}"
        signature = hmac.new(
            self.session_secret, payload.encode(), hashlib.sha256
        ).hexdigest()
        return f"{payload}.{signature}"

    def valid_session(self, token: str | None) -> bool:
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
            self.session_secret, payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(supplied_signature, expected)


def _same_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin not in {"http://127.0.0.1:8787", "http://localhost:8787"}:
        raise HTTPException(status_code=403, detail="Invalid request origin")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise HTTPException(status_code=415, detail="JSON request required")


def _context(request: Request) -> WebContext:
    return cast(WebContext, request.app.state.context)


def _authenticated(
    request: Request,
    context: Annotated[WebContext, Depends(_context)],
) -> None:
    if not context.valid_session(request.cookies.get("signal_session")):
        raise HTTPException(status_code=401, detail="Authentication required")


ContextDependency = Annotated[WebContext, Depends(_context)]
OriginDependency = Annotated[None, Depends(_same_origin)]
AuthDependency = Annotated[None, Depends(_authenticated)]


def _group_view(target: GroupTarget, available: set[str]) -> dict[str, Any]:
    return {
        "alias": target.alias,
        "name": target.description or target.alias,
        "available": target.group_id in available,
    }


def _validated_images(images: list[str]) -> tuple[list[str], tuple[str, ...]]:
    validated: list[str] = []
    digests: list[str] = []
    total_bytes = 0
    for image in images:
        if not image.startswith("data:") or ";base64," not in image:
            raise BroadcastError("Image must use a base64 data URL")
        header, encoded = image.split(",", 1)
        media_type = header[5:].split(";", 1)[0].lower()
        signatures = IMAGE_SIGNATURES.get(media_type)
        if signatures is None:
            raise BroadcastError("Only PNG, JPEG, WebP and GIF images are allowed")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise BroadcastError("Image contains invalid base64 data") from exc
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise BroadcastError("Each image must be between 1 byte and 8 MB")
        if media_type == "image/webp":
            valid_signature = raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"
        else:
            valid_signature = any(raw.startswith(prefix) for prefix in signatures)
        if not valid_signature:
            raise BroadcastError("Image content does not match its MIME type")
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise BroadcastError("Total image size must not exceed 20 MB")
        validated.append(f"data:{media_type};base64,{encoded}")
        digests.append(hashlib.sha256(raw).hexdigest())
    return validated, tuple(digests)


def create_app(
    settings: Settings | None = None,
    web_password: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        password = web_password if web_password is not None else os.getenv(
            "SIGNAL_WEB_PASSWORD", ""
        )
        if len(password) < 4:
            raise ConfigError("SIGNAL_WEB_PASSWORD must contain at least 4 characters")
        app.state.context = WebContext(
            settings or Settings.from_env(Path(".env")),
            password,
        )
        yield

    app = FastAPI(
        title="Signal Панель",
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

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, context: ContextDependency) -> Response:
        if not context.valid_session(request.cookies.get("signal_session")):
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request, "index.html")

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, context: ContextDependency) -> Response:
        if context.valid_session(request.cookies.get("signal_session")):
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "login.html")

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
            "signal_session",
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
        response.delete_cookie("signal_session", path="/")
        return response

    @app.get("/api/status")
    def status(context: ContextDependency, _: AuthDependency) -> dict[str, Any]:
        try:
            accounts = context.accounts()
            targets = context.live_targets()
        except SignalApiError as exc:
            return {
                "connected": False,
                "message": str(exc),
                "accounts": [],
                "active_number": context.settings.number,
                "groups": [],
            }
        return {
            "connected": True,
            "message": f"Signal подключён: {context.settings.number}",
            "accounts": accounts,
            "active_number": context.settings.number,
            "groups": [
                _group_view(target, {target.group_id}) for target in targets.values()
            ],
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

    @app.post("/api/accounts/select")
    def select_account(
        payload: AccountRequest,
        context: ContextDependency,
        _: OriginDependency,
        __: AuthDependency,
    ) -> dict[str, Any]:
        context.select_account(payload.number)
        return {"active_number": payload.number}

    @app.post("/api/accounts/link-qr")
    def link_account_qr(
        context: ContextDependency,
        _: OriginDependency,
        __: AuthDependency,
    ) -> dict[str, str]:
        content, content_type = context.link_qr()
        encoded = base64.b64encode(content).decode("ascii")
        return {"image": f"data:{content_type};base64,{encoded}"}

    @app.post("/api/plan")
    def plan(
        payload: PlanRequest,
        context: ContextDependency,
        _: OriginDependency,
        __: AuthDependency,
    ) -> dict[str, Any]:
        targets = context.selected(payload.aliases)
        validated_images, attachment_digests = _validated_images(payload.images)
        del validated_images
        plan_result = build_broadcast_plan(
            context.settings,
            targets,
            payload.message,
            repeat_count=payload.repeat_count,
            interval_seconds=payload.interval_seconds,
            attachment_digests=attachment_digests,
        )
        verify_group_targets(context.client(), targets)
        return {
            "aliases": plan_result.aliases,
            "group_count": len(plan_result.aliases),
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
        images, attachment_digests = _validated_images(payload.images)
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
                base64_attachments=images,
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
        AllowlistError,
        BroadcastError,
        ConfigError,
        LockError,
        SignalApiError,
        StateError,
    ):
        app.add_exception_handler(exception_type, domain_error)

    return app


app = create_app()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    uvicorn.run(
        "signal_group_sender.web:app",
        host="0.0.0.0",
        port=8787,
        workers=1,
        proxy_headers=False,
        server_header=False,
    )
