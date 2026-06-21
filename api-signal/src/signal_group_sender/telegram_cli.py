from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from pathlib import Path
from typing import Any, cast

from signal_group_sender.locking import LockError, RunLock
from signal_group_sender.state import (
    DeliveryLedger,
    StateError,
    load_or_create_hmac_key,
)
from signal_group_sender.telegram_client import (
    TelegramApiClient,
    TelegramApiError,
    TelegramAuthRequiredError,
    TelegramPasswordRequiredError,
)
from signal_group_sender.telegram_config import TelegramConfigError, TelegramSettings
from signal_group_sender.telegram_service import (
    TelegramBroadcastError,
    TelegramBroadcastService,
    build_broadcast_plan,
    verify_chat_targets,
)
from signal_group_sender.telegram_targets import TelegramTargetError, select_targets

LOGGER = logging.getLogger("signal_group_sender.telegram")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telegram-groups",
        description="Safe Telegram broadcaster over a logged-in Telegram user session",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="dotenv file (default: .env)",
    )
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="Sign in to Telegram using the configured phone")

    chats_parser = subparsers.add_parser(
        "chats", help="List chats visible to the logged-in Telegram account"
    )
    chats_parser.add_argument("--json", action="store_true", dest="as_json")

    send_parser = subparsers.add_parser(
        "send", help="Plan or execute a Telegram broadcast to selected live chats"
    )
    destination = send_parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--chat", action="append", default=[])
    destination.add_argument("--all-live", action="store_true")

    content = send_parser.add_mutually_exclusive_group(required=True)
    content.add_argument("--message-file", type=Path)
    content.add_argument("--stdin", action="store_true")

    send_parser.add_argument("--execute", action="store_true")
    send_parser.add_argument("--confirm-count", type=int)
    send_parser.add_argument("--confirm-token")
    send_parser.add_argument("--retry-unknown", action="store_true")

    history_parser = subparsers.add_parser(
        "history", help="List past delivery attempts from the local secure state file"
    )
    history_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Limit the number of history records shown (default: 20, use 0 for all)",
    )
    return parser


def _read_message(args: argparse.Namespace) -> str:
    if args.message_file is not None:
        message_file = cast(Path, args.message_file)
        try:
            return message_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise TelegramBroadcastError(f"Cannot read message file: {message_file}") from exc
    return sys.stdin.read()


def _chat_sort_key(chat: dict[str, Any]) -> tuple[str, str]:
    return (str(chat.get("name", "")).casefold(), str(chat.get("id", "")))


def _targets(client: TelegramApiClient) -> dict[str, Any]:
    dialogs = client.list_dialogs()
    result: dict[str, Any] = {}
    import hashlib

    for dialog in dialogs:
        peer_id = dialog.get("id")
        name = dialog.get("name")
        kind = dialog.get("kind")
        if not isinstance(peer_id, str) or not isinstance(name, str) or not isinstance(kind, str):
            continue
        alias = "t-" + hashlib.sha256(peer_id.encode()).hexdigest()[:16]
        from signal_group_sender.telegram_targets import ChatTarget

        result[alias] = ChatTarget(alias=alias, peer_id=peer_id, description=name, kind=kind)
    return result


def _print_chats(chats: list[dict[str, Any]], *, as_json: bool) -> None:
    ordered = sorted(chats, key=_chat_sort_key)
    if as_json:
        print(json.dumps(ordered, ensure_ascii=False, indent=2))
        return
    if not ordered:
        print("No chats returned by Telegram.")
        return
    for chat in ordered:
        name = str(chat.get("name") or "(unnamed)")
        peer_id = str(chat.get("id") or "(missing id)")
        kind = str(chat.get("kind") or "chat")
        state = "available" if chat.get("available") is True else "read-only-or-unavailable"
        print(f"{name}\t{kind}\t{state}\t{peer_id}")


def _run_login(settings: TelegramSettings) -> int:
    client = TelegramApiClient(settings)
    phone_code_hash = client.request_code()
    if phone_code_hash is None:
        print(f"Telegram already authorized for {settings.phone_number}.")
        return 0
    print(f"Login code sent to {settings.phone_number}.")
    code = input("Enter Telegram code: ").strip()
    try:
        client.authorize(code, phone_code_hash)
    except TelegramPasswordRequiredError:
        password = getpass.getpass("Enter Telegram two-step password: ")
        client.authorize(code, phone_code_hash, password=password)
    print("Telegram login completed.")
    return 0


def _run_send(args: argparse.Namespace, settings: TelegramSettings) -> int:
    client = TelegramApiClient(settings)
    live_targets = _targets(client)
    targets = select_targets(live_targets, args.chat, all_live=args.all_live)
    message = _read_message(args)
    plan = build_broadcast_plan(settings, targets, message)

    print(
        f"chats={len(plan.aliases)} aliases={','.join(plan.aliases)} "
        f"message_chars={plan.message_chars} "
        f"confirm_token={plan.confirm_token}"
    )
    if not args.execute:
        verify_chat_targets(client, targets)
        print("dry-run: no messages sent")
        return 0

    with RunLock(settings.lock_file):
        secret_existed = settings.state_secret_file.exists()
        fingerprint_key = load_or_create_hmac_key(settings.state_secret_file)
        ledger = DeliveryLedger(
            settings.state_file,
            integrity_key=fingerprint_key,
            duplicate_window_seconds=settings.duplicate_window_seconds,
        )
        ledger.initialize(allow_create=not secret_existed)
        service = TelegramBroadcastService(settings, client, ledger, fingerprint_key)
        results = service.send(
            targets,
            message,
            confirm_count=args.confirm_count,
            confirm_token=args.confirm_token,
            retry_unknown=args.retry_unknown,
        )

    for result in results:
        suffix = f": {result.detail}" if result.detail else ""
        print(f"{result.alias}: {result.status}{suffix}")
    successful_statuses = {"sent", "already_sent"}
    return 2 if any(result.status not in successful_statuses for result in results) else 0


def _run_history(args: argparse.Namespace, settings: TelegramSettings) -> int:
    if not settings.state_secret_file.exists():
        print("No state secret file found. No sending history exists yet.")
        return 0
    fingerprint_key = load_or_create_hmac_key(settings.state_secret_file)
    ledger = DeliveryLedger(
        settings.state_file,
        integrity_key=fingerprint_key,
        duplicate_window_seconds=settings.duplicate_window_seconds,
    )
    ledger.initialize(allow_create=False)
    records = ledger.get_records()
    if not records:
        print("No delivery history records found.")
        return 0

    import datetime

    ordered = list(reversed(records))
    if args.limit > 0:
        ordered = ordered[:args.limit]

    print(f"{'Time':<20} | {'Alias':<15} | {'Target Token':<16} | {'Status':<12}")
    print("-" * 71)
    for record in ordered:
        dt = datetime.datetime.fromtimestamp(record.sent_at).strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"{dt:<20} | {record.alias:<15} | {record.target_token:<16} | {record.status:<12}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    LOGGER.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    try:
        settings = TelegramSettings.from_env(args.env_file)
        if args.command == "login":
            return _run_login(settings)
        if args.command == "chats":
            _print_chats(TelegramApiClient(settings).list_dialogs(), as_json=args.as_json)
            return 0
        if args.command == "send":
            return _run_send(args, settings)
        if args.command == "history":
            return _run_history(args, settings)
    except TelegramAuthRequiredError as exc:
        LOGGER.error("%s", exc)
        LOGGER.error("Run `telegram-groups login` first or sign in via the web panel.")
        return 1
    except (
        LockError,
        StateError,
        TelegramApiError,
        TelegramBroadcastError,
        TelegramConfigError,
        TelegramTargetError,
    ) as exc:
        LOGGER.error("%s", exc)
        return 1

    parser.error("Unknown command")
    return 2
