from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, cast

from signal_group_sender.client import SignalApiClient, SignalApiError
from signal_group_sender.config import ConfigError, Settings
from signal_group_sender.groups import (
    AllowlistError,
    allowlist_sha256,
    load_allowlist,
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

LOGGER = logging.getLogger("signal_group_sender")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signal-groups",
        description="Safe Signal group sender over signal-cli-rest-api",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="dotenv file (default: .env)",
    )
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    groups_parser = subparsers.add_parser(
        "groups", help="List groups visible to the linked Signal account"
    )
    groups_parser.add_argument("--json", action="store_true", dest="as_json")

    send_parser = subparsers.add_parser(
        "send", help="Plan or execute an allowlist-based group broadcast"
    )
    destination = send_parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--group", action="append", default=[])
    destination.add_argument("--all-allowed", action="store_true")

    content = send_parser.add_mutually_exclusive_group(required=True)
    content.add_argument("--message-file", type=Path)
    content.add_argument("--stdin", action="store_true")

    send_parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform delivery; without this flag the command is a dry-run",
    )
    send_parser.add_argument("--confirm-count", type=int)
    send_parser.add_argument("--confirm-token")
    send_parser.add_argument(
        "--retry-unknown",
        action="store_true",
        help="Retry only targets whose previous delivery is unknown",
    )

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
            raise BroadcastError(f"Cannot read message file: {message_file}") from exc
    return sys.stdin.read()


def _group_sort_key(group: dict[str, Any]) -> tuple[str, str]:
    return (str(group.get("name", "")).casefold(), str(group.get("id", "")))


def _print_groups(groups: list[dict[str, Any]], *, as_json: bool) -> None:
    ordered = sorted(groups, key=_group_sort_key)
    if as_json:
        safe_groups = [
            {
                "id": group.get("id"),
                "name": group.get("name"),
                "blocked": group.get("blocked", group.get("isBlocked")),
            }
            for group in ordered
        ]
        print(json.dumps(safe_groups, ensure_ascii=False, indent=2))
        return
    if not ordered:
        print("No groups returned by Signal API.")
        return
    for group in ordered:
        name = str(group.get("name") or "(unnamed)")
        group_id = str(group.get("id") or group.get("internal_id") or "(missing id)")
        blocked = group.get("blocked", group.get("isBlocked"))
        state = "available" if blocked is False else "blocked-or-unknown"
        print(f"{name}\t{state}\t{group_id}")


def _run_send(args: argparse.Namespace, settings: Settings) -> int:
    actual_allowlist_sha256 = allowlist_sha256(settings.groups_file)
    if (
        settings.allowlist_sha256 is not None
        and settings.allowlist_sha256 != actual_allowlist_sha256
    ):
        raise BroadcastError(
            "groups.json does not match SIGNAL_ALLOWLIST_SHA256"
        )
    if args.execute and settings.allowlist_sha256 is None:
        raise BroadcastError(
            "Live send requires SIGNAL_ALLOWLIST_SHA256 to pin groups.json"
        )
    allowlist = load_allowlist(settings.groups_file)
    targets = select_targets(
        allowlist,
        args.group,
        all_allowed=args.all_allowed,
    )
    message = _read_message(args)
    client = SignalApiClient(settings)
    plan = build_broadcast_plan(settings, targets, message)

    print(
        f"groups={len(plan.aliases)} aliases={','.join(plan.aliases)} "
        f"message_chars={plan.message_chars} "
        f"confirm_token={plan.confirm_token} "
        f"allowlist_sha256={actual_allowlist_sha256}"
    )
    if not args.execute:
        verify_group_targets(client, targets)
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
        service = BroadcastService(settings, client, ledger, fingerprint_key)
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


def _run_history(args: argparse.Namespace, settings: Settings) -> int:
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
    for r in ordered:
        dt = datetime.datetime.fromtimestamp(r.sent_at).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{dt:<20} | {r.alias:<15} | {r.target_token:<16} | {r.status:<12}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    LOGGER.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    try:
        settings = Settings.from_env(args.env_file)
        if args.command == "groups":
            _print_groups(
                SignalApiClient(settings).list_groups(),
                as_json=args.as_json,
            )
            return 0
        if args.command == "send":
            return _run_send(args, settings)
        if args.command == "history":
            return _run_history(args, settings)
    except (
        AllowlistError,
        BroadcastError,
        ConfigError,
        LockError,
        SignalApiError,
        StateError,
    ) as exc:
        LOGGER.error("%s", exc)
        return 1

    parser.error("Unknown command")
    return 2
