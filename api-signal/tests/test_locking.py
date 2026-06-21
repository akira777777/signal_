from __future__ import annotations

from pathlib import Path

import pytest

from signal_group_sender.locking import AlreadyRunningError, RunLock


def test_second_process_lock_is_rejected(tmp_path: Path) -> None:
    lock_path = tmp_path / "sender.lock"

    with (
        RunLock(lock_path),
        pytest.raises(AlreadyRunningError),
        RunLock(lock_path),
    ):
        pass


def test_lock_can_be_reacquired_after_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "sender.lock"

    with RunLock(lock_path):
        pass
    with RunLock(lock_path):
        pass
