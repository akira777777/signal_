from __future__ import annotations

import json
from pathlib import Path

import pytest

from signal_group_sender.groups import AllowlistError, load_allowlist, select_targets


def test_loads_and_selects_allowlisted_groups(tmp_path: Path) -> None:
    path = tmp_path / "groups.json"
    path.write_text(
        json.dumps(
            {
                "ops": {"id": "group.abc=", "description": "Operations"},
                "team": "group.def=",
            }
        ),
        encoding="utf-8",
    )

    allowlist = load_allowlist(path)
    selected = select_targets(allowlist, ["team"], all_allowed=False)

    assert selected[0].alias == "team"
    assert selected[0].group_id == "group.def="


def test_rejects_non_group_recipient(tmp_path: Path) -> None:
    path = tmp_path / "groups.json"
    path.write_text(json.dumps({"ops": "+420123456789"}), encoding="utf-8")

    with pytest.raises(AllowlistError, match="starting with 'group.'"):
        load_allowlist(path)


def test_rejects_unknown_alias(tmp_path: Path) -> None:
    path = tmp_path / "groups.json"
    path.write_text(json.dumps({"ops": "group.abc="}), encoding="utf-8")
    allowlist = load_allowlist(path)

    with pytest.raises(AllowlistError, match="Unknown"):
        select_targets(allowlist, ["other"], all_allowed=False)

