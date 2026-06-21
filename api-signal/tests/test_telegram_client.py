from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace

from signal_group_sender import telegram_client
from signal_group_sender.telegram_client import TelegramApiClient
from signal_group_sender.telegram_config import TelegramSettings


@dataclass
class FakeUser:
    is_self: bool = False
    deleted: bool = False


@dataclass
class FakeChat:
    left: bool = False
    deactivated: bool = False
    creator: bool = False
    admin_rights: object | None = None
    banned_rights: object | None = None
    default_banned_rights: object | None = None
    permissions: object | None = None
    restricted: bool = False


@dataclass
class FakeChannel:
    megagroup: bool = False
    broadcast: bool = False
    left: bool = False
    creator: bool = False
    admin_rights: object | None = None
    banned_rights: object | None = None
    default_banned_rights: object | None = None
    permissions: object | None = None
    restricted: bool = False


@dataclass
class FakeDialog:
    entity: object
    dialog_id: str
    title: str


@dataclass
class FakeMessage:
    out: bool = False
    message: str = ""
    media: object | None = None
    action: object | None = None


@dataclass
class FakeRights:
    send_messages: bool | None = None
    until_date: int | None = None


class FakeClient:
    def __init__(
        self,
        dialogs: list[FakeDialog],
        messages_by_id: dict[str, list[FakeMessage]],
    ) -> None:
        self._dialogs = dialogs
        self._messages_by_id = messages_by_id

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def is_user_authorized(self) -> bool:
        return True

    async def iter_dialogs(self) -> AsyncIterator[FakeDialog]:
        for dialog in self._dialogs:
            yield dialog

    async def iter_messages(
        self,
        dialog: FakeDialog,
        limit: int,
    ) -> AsyncIterator[FakeMessage]:
        for message in self._messages_by_id.get(dialog.dialog_id, [])[:limit]:
            yield message


def _client(
    telegram_settings: TelegramSettings,
    fake_client: FakeClient,
) -> TelegramApiClient:
    return TelegramApiClient(
        telegram_settings,
        client_factory=lambda: fake_client,
    )


def _patch_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_client,
        "_telethon_runtime",
        lambda: SimpleNamespace(
            client_type=object,
            rpc_error=Exception,
            session_password_needed_error=Exception,
            channel_type=FakeChannel,
            chat_type=FakeChat,
            user_type=FakeUser,
            get_peer_id=lambda entity: entity.dialog_id,
        ),
    )


def test_list_dialogs_keeps_only_targets_with_recent_posts(
    telegram_settings: TelegramSettings,
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    dialogs = [
        FakeDialog(FakeChat(), "1001", "Promo Group"),
        FakeDialog(FakeChat(), "1002", "Quiet Group"),
        FakeDialog(FakeChannel(megagroup=True), "1003", "Zulu Supergroup"),
        FakeDialog(FakeChannel(broadcast=True), "1004", "Alpha Channel"),
        FakeDialog(FakeUser(), "1005", "Direct User"),
    ]
    for dialog in dialogs:
        setattr(dialog.entity, "dialog_id", dialog.dialog_id)
    messages = {
        "1001": [FakeMessage(out=True, message="ad copy")],
        "1002": [FakeMessage(out=False, message="someone else posted")],
        "1003": [FakeMessage(out=True, media=object())],
        "1004": [FakeMessage(out=True, message="channel ad")],
        "1005": [FakeMessage(out=True, message="private message")],
    }

    client = _client(telegram_settings, FakeClient(dialogs, messages))

    result = client.list_dialogs()

    assert result == [
        {
            "id": "1004",
            "name": "Alpha Channel",
            "kind": "channel",
            "available": True,
        },
        {
            "id": "1003",
            "name": "Zulu Supergroup",
            "kind": "supergroup",
            "available": True,
        },
        {
            "id": "1001",
            "name": "Promo Group",
            "kind": "group",
            "available": True,
        },
        {
            "id": "1002",
            "name": "Quiet Group",
            "kind": "group",
            "available": True,
        },
    ]


def test_list_dialogs_ignores_service_messages_when_filtering_posts(
    telegram_settings: TelegramSettings,
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    dialogs = [FakeDialog(FakeChat(), "1001", "Service Only")]
    setattr(dialogs[0].entity, "dialog_id", dialogs[0].dialog_id)
    messages = {
        "1001": [FakeMessage(out=True, action=object())],
    }

    client = _client(telegram_settings, FakeClient(dialogs, messages))

    assert client.list_dialogs() == []


def test_list_dialogs_excludes_group_with_send_restriction(
    telegram_settings: TelegramSettings,
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    dialogs = [FakeDialog(FakeChat(banned_rights=FakeRights(send_messages=True)), "1001", "Restricted Group")]
    setattr(dialogs[0].entity, "dialog_id", dialogs[0].dialog_id)
    messages = {"1001": [FakeMessage(message="broadcast text")]}

    client = _client(telegram_settings, FakeClient(dialogs, messages))

    assert client.list_dialogs() == []


def test_list_dialogs_excludes_supergroup_with_temporary_restriction(
    telegram_settings: TelegramSettings,
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    dialogs = [
        FakeDialog(
            FakeChannel(megagroup=True, default_banned_rights=FakeRights(send_messages=True, until_date=3600)),
            "1001",
            "Restricted Supergroup",
        )
    ]
    setattr(dialogs[0].entity, "dialog_id", dialogs[0].dialog_id)
    messages = {"1001": [FakeMessage(media=object())]}

    client = _client(telegram_settings, FakeClient(dialogs, messages))

    assert client.list_dialogs() == []


def test_list_dialogs_keeps_read_only_channel_with_recent_posts(
    telegram_settings: TelegramSettings,
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    dialogs = [FakeDialog(FakeChannel(broadcast=True), "1001", "Read Only Channel")]
    setattr(dialogs[0].entity, "dialog_id", dialogs[0].dialog_id)
    messages = {"1001": [FakeMessage(message="broadcast text")]}

    client = _client(telegram_settings, FakeClient(dialogs, messages))

    assert client.list_dialogs() == [
        {
            "id": "1001",
            "name": "Read Only Channel",
            "kind": "channel",
            "available": True,
        }
    ]
