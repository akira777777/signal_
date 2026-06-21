from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated, Any, cast
from urllib.parse import urlparse

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from signal_group_sender.campaign import CampaignError, PersistentCampaignManager
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
from signal_group_sender.web_common import (
    MAX_ATTACHMENT_DATA_URL_CHARS,
    SignedSessionManager,
    allowed_origins_from_env,
    require_json_same_origin,
    trusted_hosts_from_env,
    validate_attachment_data_urls,
)

LOGGER = logging.getLogger("signal_group_sender.web")
PACKAGE_DIRECTORY = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIRECTORY / "templates")
ALLOWED_ORIGINS = allowed_origins_from_env(
    "SIGNAL_ALLOWED_ORIGINS",
    {"http://127.0.0.1:8787", "http://localhost:8787"},
)
STATIC_ASSET_VERSION = str(
    max(
        (PACKAGE_DIRECTORY / "static" / "app.css").stat().st_mtime_ns,
        (PACKAGE_DIRECTORY / "static" / "app.js").stat().st_mtime_ns,
        (PACKAGE_DIRECTORY / "static" / "favicon.svg").stat().st_mtime_ns,
    )
)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aliases: list[str] = Field(min_length=1, max_length=999999)
    message: str = Field(min_length=1, max_length=99999999)
    repeat_count: int = Field(default=1, ge=1, le=999999)
    interval_seconds: int = Field(default=0, ge=0, le=99999999)
    attachments: list[
        Annotated[str, Field(max_length=MAX_ATTACHMENT_DATA_URL_CHARS)]
    ] = Field(
        default_factory=list,
    )


class SendRequest(PlanRequest):
    confirm_token: str = Field(pattern=r"^[0-9a-f]{16}$")
    retry_unknown: bool = False
    round_index: int = Field(default=1, ge=1, le=999999)


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
        self._session_manager = SignedSessionManager(self.session_secret)
        self._campaign_manager = PersistentCampaignManager(
            self._campaign_file,
            self._send_campaign_round,
        )

    @property
    def _campaign_file(self) -> Path:
        return self._base_settings.state_file.with_name(
            f"{self._base_settings.state_file.stem}-campaign.json"
        )

    @property
    def settings(self) -> Settings:
        with self._account_lock:
            return replace(self._base_settings, number=self._active_number)

    def settings_for_number(self, number: str) -> Settings:
        return replace(self._base_settings, number=number)

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

    def client_for_settings(self, settings: Settings) -> SignalApiClient:
        return SignalApiClient(settings)

    def service(self) -> BroadcastService:
        return self.service_for_settings(self.settings)

    def service_for_settings(self, settings: Settings) -> BroadcastService:
        key = self.session_secret
        ledger = DeliveryLedger(
            settings.state_file,
            integrity_key=key,
            duplicate_window_seconds=settings.duplicate_window_seconds,
        )
        ledger.initialize(allow_create=not settings.state_file.exists())
        return BroadcastService(settings, self.client_for_settings(settings), ledger, key)

    def start_campaign(
        self,
        *,
        targets: list[GroupTarget],
        message: str,
        confirm_token: str,
        retry_unknown: bool,
        repeat_count: int,
        interval_seconds: int,
        attachments: list[str],
        attachment_digests: tuple[str, ...],
    ) -> dict[str, Any]:
        settings = self.settings
        plan = build_broadcast_plan(
            settings,
            targets,
            message,
            repeat_count=repeat_count,
            interval_seconds=interval_seconds,
            attachment_digests=attachment_digests,
        )
        verify_group_targets(self.client_for_settings(settings), targets)
        if confirm_token != plan.confirm_token:
            raise BroadcastError(f"Live send requires --confirm-token {plan.confirm_token}")
        return self._campaign_manager.start(
            {
                "transport": "signal",
                "number": settings.number,
                "targets": [
                    {
                        "alias": target.alias,
                        "group_id": target.group_id,
                        "description": target.description,
                    }
                    for target in targets
                ],
                "message": message,
                "confirm_token": confirm_token,
                "retry_unknown": retry_unknown,
                "repeat_count": repeat_count,
                "interval_seconds": interval_seconds,
                "attachments": attachments,
                "attachment_digests": list(attachment_digests),
            }
        )

    def campaign_status(self) -> dict[str, Any]:
        return self._campaign_manager.status()

    def cancel_campaign(self) -> dict[str, Any]:
        return self._campaign_manager.cancel()

    def resume_campaign(self) -> None:
        self._campaign_manager.resume_active()

    def shutdown_campaign(self) -> None:
        self._campaign_manager.shutdown()

    def _send_campaign_round(
        self,
        snapshot: dict[str, Any],
        round_index: int,
    ) -> list[dict[str, Any]]:
        number = str(snapshot["number"])
        settings = self.settings_for_number(number)
        targets = [
            GroupTarget(
                str(item["alias"]),
                str(item["group_id"]),
                str(item.get("description", "")),
            )
            for item in snapshot["targets"]
        ]
        with RunLock(settings.lock_file):
            results = self.service_for_settings(settings).send(
                targets,
                str(snapshot["message"]),
                confirm_count=len(targets),
                confirm_token=str(snapshot["confirm_token"]),
                retry_unknown=bool(snapshot.get("retry_unknown")),
                repeat_count=int(snapshot["repeat_count"]),
                interval_seconds=int(snapshot["interval_seconds"]),
                delivery_scope=f"{snapshot['confirm_token']}:{round_index}",
                base64_attachments=list(snapshot.get("attachments", [])),
                attachment_digests=tuple(snapshot.get("attachment_digests", [])),
            )
        return [asdict(result) for result in results]

    def issue_session(self) -> str:
        return self._session_manager.issue()

    def valid_session(self, token: str | None) -> bool:
        return self._session_manager.valid(token)


def _same_origin(request: Request) -> None:
    require_json_same_origin(request, allowed_origins=ALLOWED_ORIGINS)


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


def _validated_attachments(
    attachments: list[str],
) -> tuple[list[str], tuple[str, ...]]:
    validated = validate_attachment_data_urls(
        attachments, error_type=BroadcastError
    )
    return [attachment.data_url for attachment in validated], tuple(
        attachment.digest for attachment in validated
    )

def _template_context(**extra: Any) -> dict[str, Any]:
    return {
        "asset_version": STATIC_ASSET_VERSION,
        **extra,
    }


def create_app(
    settings: Settings | None = None,
    web_password: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        env_file = Path(".env")
        load_dotenv(dotenv_path=env_file, override=False)
        password = web_password if web_password is not None else os.getenv(
            "SIGNAL_WEB_PASSWORD", ""
        )
        if len(password) < 4:
            raise ConfigError("SIGNAL_WEB_PASSWORD must contain at least 4 characters")
        app.state.context = WebContext(
            settings or Settings.from_env(env_file),
            password,
        )
        app.state.context.resume_campaign()
        yield
        app.state.context.shutdown_campaign()

    app = FastAPI(
        title="Signal Панель",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=trusted_hosts_from_env("SIGNAL_ALLOWED_HOSTS"),
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["Permissions-Policy"] = "unload=*"
        return response

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
        if not context.valid_session(request.cookies.get("signal_session")):
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "index.html",
            _template_context(),
        )

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, context: ContextDependency) -> Response:
        if context.valid_session(request.cookies.get("signal_session")):
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request,
            "login.html",
            _template_context(),
        )

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
        except SignalApiError as exc:
            return {
                "connected": False,
                "message": f"Signal API is unavailable: {exc}",
                "accounts": [],
                "active_number": context.settings.number,
                "groups": [],
            }

        try:
            targets = context.live_targets()
        except SignalApiError as exc:
            return {
                "connected": False,
                "message": str(exc),
                "accounts": accounts,
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

    @app.get("/api/stats")
    def get_stats(
        context: ContextDependency,
        _: AuthDependency,
    ) -> dict[str, Any]:
        return context.service().get_stats()

    @app.get("/api/campaign")
    def get_campaign(
        context: ContextDependency,
        _: AuthDependency,
    ) -> dict[str, Any]:
        return context.campaign_status()



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
        validated_attachments, attachment_digests = _validated_attachments(
            payload.attachments
        )
        del validated_attachments
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
            "attachment_count": len(attachment_digests),
        }

    @app.post("/api/send")
    def send(
        payload: SendRequest,
        context: ContextDependency,
        _: OriginDependency,
        __: AuthDependency,
    ) -> dict[str, Any]:
        targets = context.selected(payload.aliases)
        attachments, attachment_digests = _validated_attachments(
            payload.attachments
        )
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
                base64_attachments=attachments,
                attachment_digests=attachment_digests,
            )
        return {
            "results": [asdict(result) for result in results],
            "round_index": payload.round_index,
            "complete": all(
                result.status in {"sent", "already_sent"} for result in results
            ),
        }

    @app.post("/api/campaign")
    def start_campaign(
        payload: SendRequest,
        context: ContextDependency,
        _: OriginDependency,
        __: AuthDependency,
    ) -> dict[str, Any]:
        targets = context.selected(payload.aliases)
        attachments, attachment_digests = _validated_attachments(
            payload.attachments
        )
        return context.start_campaign(
            targets=targets,
            message=payload.message,
            confirm_token=payload.confirm_token,
            retry_unknown=payload.retry_unknown,
            repeat_count=payload.repeat_count,
            interval_seconds=payload.interval_seconds,
            attachments=attachments,
            attachment_digests=attachment_digests,
        )

    @app.post("/api/campaign/cancel")
    def cancel_campaign(
        context: ContextDependency,
        _: OriginDependency,
        __: AuthDependency,
    ) -> dict[str, Any]:
        return context.cancel_campaign()

    def domain_error(_: Request, exc: Exception) -> Any:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    for exception_type in (
        AllowlistError,
        BroadcastError,
        CampaignError,
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
