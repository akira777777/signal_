from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class AllowlistError(ValueError):
    """Raised when the group allowlist is missing or invalid."""


@dataclass(frozen=True, slots=True)
class GroupTarget:
    alias: str
    group_id: str
    description: str = ""


def allowlist_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise AllowlistError(f"Cannot read allowlist: {path}") from exc


def _parse_target(alias: str, value: Any) -> GroupTarget:
    if not _ALIAS_RE.fullmatch(alias):
        raise AllowlistError(f"Invalid group alias: {alias!r}")

    raw_group_id: object
    if isinstance(value, str):
        raw_group_id = value
        description = ""
    elif isinstance(value, dict):
        raw_group_id = value.get("id")
        description = value.get("description", "")
    else:
        raise AllowlistError(f"Group {alias!r} must be a string or object")

    if not isinstance(raw_group_id, str) or not raw_group_id.startswith("group."):
        raise AllowlistError(f"Group {alias!r} must have an id starting with 'group.'")
    group_id = raw_group_id
    if any(character.isspace() or ord(character) < 32 for character in group_id):
        raise AllowlistError(f"Group {alias!r} contains an invalid id")
    if not isinstance(description, str):
        raise AllowlistError(f"Group {alias!r} description must be a string")

    return GroupTarget(alias=alias, group_id=group_id, description=description)


def load_allowlist(path: Path) -> dict[str, GroupTarget]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AllowlistError(
            f"Allowlist not found: {path}. Copy groups.example.json to this path."
        ) from exc
    except json.JSONDecodeError as exc:
        raise AllowlistError(f"Allowlist is not valid JSON: {path}") from exc
    except (OSError, UnicodeError) as exc:
        raise AllowlistError(f"Cannot read allowlist: {path}") from exc

    if not isinstance(raw, dict) or not raw:
        raise AllowlistError("Allowlist must be a non-empty JSON object")

    targets = {alias: _parse_target(alias, value) for alias, value in raw.items()}
    ids = [target.group_id for target in targets.values()]
    if len(ids) != len(set(ids)):
        raise AllowlistError("The same Signal group id is assigned to multiple aliases")
    return targets


def select_targets(
    allowlist: dict[str, GroupTarget],
    aliases: list[str],
    *,
    all_allowed: bool,
) -> list[GroupTarget]:
    requested = list(allowlist) if all_allowed else aliases
    if not requested:
        raise AllowlistError("Select at least one group")
    if len(requested) != len(set(requested)):
        raise AllowlistError("A group alias was selected more than once")

    unknown = [alias for alias in requested if alias not in allowlist]
    if unknown:
        raise AllowlistError(f"Unknown group aliases: {', '.join(unknown)}")
    return [allowlist[alias] for alias in requested]
