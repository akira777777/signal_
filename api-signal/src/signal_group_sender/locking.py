from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import BinaryIO


class LockError(RuntimeError):
    """Raised when the sender run lock cannot be managed."""


class AlreadyRunningError(LockError):
    """Raised when another sender process already owns the run lock."""


class RunLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: BinaryIO | None = None

    def __enter__(self) -> RunLock:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = self._path.open("a+b")
        except OSError as exc:
            raise LockError(f"Cannot open sender lock: {self._path}") from exc
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)

        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(  # type: ignore[attr-defined]
                    handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,  # type: ignore[attr-defined]
                )
        except OSError as exc:
            handle.close()
            raise AlreadyRunningError("Another sender process is already running") from exc

        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(  # type: ignore[attr-defined]
                    handle.fileno(),
                    fcntl.LOCK_UN,  # type: ignore[attr-defined]
                )
        finally:
            handle.close()
            self._handle = None
