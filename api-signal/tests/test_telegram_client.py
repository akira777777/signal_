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
class FakeRights:
    send_messages: bool | None = None
    until_date: int | None = None


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
    id: int = 0
    out: bool = False
    message: str = ""
    media: object | None = None
    action: object | None = None
    entities: tuple[object, ...] = ()
    reply_markup: object | None = None
    date: float | None = None
    reply_to_msg_id: int | None = None


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
        dialog: object,
        limit: int,
    ) -> AsyncIterator[FakeMessage]:
        dialog_id = getattr(dialog, "dialog_id", None)
        for message in self._messages_by_id.get(str(dialog_id), [])[:limit]:
            yield message

    async def send_message(self, entity: object, message: str) -> FakeMessage:
        return FakeMessage(id=77, out=True, message=message)

    async def send_file(
        self,
        entity: object,
        files: object,
        *,
        caption: str | None,
        force_document: bool,
    ) -> list[FakeMessage]:
        return [FakeMessage(id=78, out=True, message=caption or "")]


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


def _client(
    telegram_settings: TelegramSettings,
    fake_client: FakeClient,
) -> TelegramApiClient:
    return TelegramApiClient(
        telegram_settings,
        client_factory=lambda: fake_client,
    )


def test_list_dialogs_keeps_sorted_targets_with_broadcast_pattern(
    telegram_settings: TelegramSettings,
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    dialogs = [
        FakeDialog(FakeChat(), "1001", "Promo Group"),
        FakeDialog(FakeChannel(megagroup=True), "1003", "Zulu Supergroup"),
        FakeDialog(FakeChannel(broadcast=True), "1004", "Alpha Channel"),
        FakeDialog(FakeUser(), "1005", "Direct User"),
    ]
    for dialog in dialogs:
        dialog.entity.dialog_id = dialog.dialog_id
    messages = {
        "1001": [
            FakeMessage(message="Check https://example.com"),
            FakeMessage(message="Second post"),
        ],
        "1003": [
            FakeMessage(media=object()),
            FakeMessage(message="Second post"),
        ],
        "1004": [
            FakeMessage(message="Visit t.me/sale"),
            FakeMessage(message="Second post"),
        ],
        "1005": [
            FakeMessage(message="Visit t.me/direct"),
            FakeMessage(message="Second post"),
        ],
    }

    client = _client(telegram_settings, FakeClient(dialogs, messages))

    assert client.list_dialogs() == [
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
    ]



def test_list_dialogs_excludes_group_with_send_restriction(
    telegram_settings: TelegramSettings,
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    dialogs = [
        FakeDialog(
            FakeChat(banned_rights=FakeRights(send_messages=True)),
            "1001",
            "Restricted Group",
        )
    ]
    dialogs[0].entity.dialog_id = dialogs[0].dialog_id
    messages = {
        "1001": [
            FakeMessage(message="Check https://example.com"),
            FakeMessage(message="Second post"),
        ],
    }

    client = _client(telegram_settings, FakeClient(dialogs, messages))

    assert client.list_dialogs() == []


def test_list_dialogs_excludes_supergroup_with_temporary_restriction(
    telegram_settings: TelegramSettings,
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    dialogs = [
        FakeDialog(
            FakeChannel(
                megagroup=True,
                default_banned_rights=FakeRights(send_messages=True, until_date=3600),
            ),
            "1001",
            "Restricted Supergroup",
        )
    ]
    dialogs[0].entity.dialog_id = dialogs[0].dialog_id
    messages = {
        "1001": [
            FakeMessage(media=object()),
            FakeMessage(message="Second post"),
        ],
    }

    client = _client(telegram_settings, FakeClient(dialogs, messages))

    assert client.list_dialogs() == []


def test_send_chat_returns_message_ids(
    telegram_settings: TelegramSettings,
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    dialog = FakeDialog(FakeChat(), "1001", "Target")
    dialog.entity.dialog_id = dialog.dialog_id
    client = _client(telegram_settings, FakeClient([dialog], {}))

    assert client.send_chat("1001", "hello")["message_ids"] == [77]


def test_collect_engagement_counts_replies_and_activity(
    telegram_settings: TelegramSettings,
    monkeypatch,
) -> None:
    from signal_group_sender.telegram_campaigns import TelegramCampaignDelivery

    _patch_runtime(monkeypatch)
    dialog = FakeDialog(FakeChat(), "1001", "Target")
    dialog.entity.dialog_id = dialog.dialog_id
    messages = {
        "1001": [
            FakeMessage(id=90, out=False, message="reply", date=1010.0, reply_to_msg_id=77),
            FakeMessage(id=91, out=False, message="later", date=1020.0),
            FakeMessage(id=92, out=True, message="own", date=1030.0),
        ],
    }
    client = _client(telegram_settings, FakeClient([dialog], messages))
    records = [
        TelegramCampaignDelivery(
            campaign_id="tg-1",
            created_at=1000.0,
            alias="chat-a",
            target_token="token-a",
            peer_id="1001",
            variant_id="A",
            round_index=1,
            status="sent",
            message_ids=(77,),
            attachment_count=0,
        )
    ]

    assert client.collect_engagement(records) == {("chat-a", 1, "A"): (1, 2)}


