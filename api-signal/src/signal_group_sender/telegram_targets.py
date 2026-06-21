from __future__ import annotations

import re
from dataclasses import dataclass

_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class TelegramTargetError(ValueError):
    """Raised when Telegram target selection is invalid."""


@dataclass(frozen=True, slots=True)
class ChatTarget:
    alias: str
    peer_id: str
    description: str
    kind: str = "chat"


def select_targets(
    targets: dict[str, ChatTarget],
    aliases: list[str],
    *,
    all_live: bool,
) -> list[ChatTarget]:
    requested = list(targets) if all_live else aliases
    if not requested:
        raise TelegramTargetError("Select at least one chat")
    if len(requested) != len(set(requested)):
        raise TelegramTargetError("A chat alias was selected more than once")

    invalid = [alias for alias in requested if not _ALIAS_RE.fullmatch(alias)]
    if invalid:
        raise TelegramTargetError(f"Invalid chat aliases: {', '.join(invalid)}")

    unknown = [alias for alias in requested if alias not in targets]
    if unknown:
        raise TelegramTargetError(f"Unknown chat aliases: {', '.join(unknown)}")

    return [targets[alias] for alias in requested]
