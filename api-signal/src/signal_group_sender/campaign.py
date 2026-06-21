from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any


class CampaignError(RuntimeError):
    """Raised when a persistent campaign cannot be managed safely."""


RoundSender = Callable[[dict[str, Any], int], list[dict[str, Any]]]

ACTIVE_STATUSES = {"pending", "running", "waiting", "cancel_requested"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class PersistentCampaignManager:
    def __init__(
        self,
        path: Path,
        round_sender: RoundSender,
        *,
        clock: Callable[[], float] = time.time,
        wait_slice_seconds: float = 1.0,
    ) -> None:
        self._path = path
        self._round_sender = round_sender
        self._clock = clock
        self._wait_slice_seconds = wait_slice_seconds
        self._lock = threading.RLock()
        self._wake_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._thread: threading.Thread | None = None

    def resume_active(self) -> None:
        with self._lock:
            snapshot = self._load_or_none()
            if snapshot is None or snapshot["status"] not in ACTIVE_STATUSES:
                return
            if snapshot["status"] == "running":
                snapshot["status"] = "waiting"
                snapshot["next_run_at"] = self._clock()
                snapshot["updated_at"] = self._clock()
                self._write(snapshot)
            self._ensure_worker_locked()

    def shutdown(self, *, timeout: float = 2.0) -> None:
        self._shutdown_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            current = self._load_or_none()
            if current is not None and current["status"] in ACTIVE_STATUSES:
                raise CampaignError("Another campaign is already running")
            snapshot = {
                "schema_version": 1,
                "id": uuid.uuid4().hex,
                "created_at": now,
                "updated_at": now,
                "status": "pending",
                "current_round": 0,
                "next_run_at": now,
                "results": [],
                "error": None,
                **payload,
            }
            self._write(snapshot)
            self._ensure_worker_locked()
            self._wake_event.set()
            return self._public(snapshot)

    def status(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self._load_or_none()
            if snapshot is None:
                return {
                    "status": "idle",
                    "current_round": 0,
                    "repeat_count": 0,
                    "results": [],
                    "error": None,
                    "next_run_at": None,
                }
            return self._public(snapshot)

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self._load_or_none()
            if snapshot is None or snapshot["status"] not in ACTIVE_STATUSES:
                return self.status()
            snapshot["status"] = "cancel_requested"
            snapshot["updated_at"] = self._clock()
            self._write(snapshot)
            self._wake_event.set()
            return self._public(snapshot)

    def _ensure_worker_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._shutdown_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name=f"campaign-worker-{self._path.stem}",
            daemon=True,
        )
        self._thread.start()

    def _worker_loop(self) -> None:
        while not self._shutdown_event.is_set():
            snapshot = self._load_or_none()
            if snapshot is None or snapshot["status"] not in ACTIVE_STATUSES:
                return

            if snapshot["status"] == "cancel_requested":
                self._finish(snapshot, "cancelled")
                return

            repeat_count = int(snapshot["repeat_count"])
            current_round = int(snapshot["current_round"])
            if current_round >= repeat_count:
                self._finish(snapshot, "completed")
                return

            next_run_at = float(snapshot.get("next_run_at") or self._clock())
            now = self._clock()
            if next_run_at > now:
                self._wait_until(next_run_at)
                continue

            round_index = current_round + 1
            snapshot["status"] = "running"
            snapshot["updated_at"] = self._clock()
            snapshot["next_run_at"] = None
            self._write(snapshot)

            try:
                round_results = self._round_sender(snapshot, round_index)
            except Exception as exc:
                snapshot = self._load_or_none() or snapshot
                snapshot["status"] = "failed"
                snapshot["error"] = str(exc)
                snapshot["updated_at"] = self._clock()
                self._write(snapshot)
                return

            snapshot = self._load_or_none() or snapshot
            results = list(snapshot.get("results", []))
            results.extend(
                {**result, "round_index": round_index} for result in round_results
            )
            snapshot["results"] = results
            snapshot["current_round"] = round_index
            snapshot["updated_at"] = self._clock()

            if snapshot["status"] == "cancel_requested":
                self._finish(snapshot, "cancelled")
                return
            if round_index >= repeat_count:
                self._finish(snapshot, "completed")
                return

            snapshot["status"] = "waiting"
            snapshot["next_run_at"] = self._clock() + int(snapshot["interval_seconds"])
            self._write(snapshot)

    def _wait_until(self, deadline: float) -> None:
        while not self._shutdown_event.is_set():
            remaining = deadline - self._clock()
            if remaining <= 0:
                return
            self._wake_event.wait(min(remaining, self._wait_slice_seconds))
            self._wake_event.clear()

    def _finish(self, snapshot: dict[str, Any], status: str) -> None:
        snapshot["status"] = status
        snapshot["next_run_at"] = None
        snapshot["updated_at"] = self._clock()
        self._write(snapshot)

    def _public(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        target_count = len(snapshot.get("targets", []))
        return {
            "id": snapshot.get("id"),
            "status": snapshot["status"],
            "transport": snapshot.get("transport"),
            "created_at": snapshot.get("created_at"),
            "updated_at": snapshot.get("updated_at"),
            "current_round": int(snapshot.get("current_round", 0)),
            "repeat_count": int(snapshot.get("repeat_count", 0)),
            "interval_seconds": int(snapshot.get("interval_seconds", 0)),
            "next_run_at": snapshot.get("next_run_at"),
            "target_count": target_count,
            "attachment_count": len(snapshot.get("attachment_digests", [])),
            "results": list(snapshot.get("results", [])),
            "error": snapshot.get("error"),
        }

    def _load_or_none(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignError(f"Cannot read campaign state: {self._path}") from exc
        if not isinstance(payload, dict):
            raise CampaignError(f"Invalid campaign state: {self._path}")
        status = payload.get("status")
        if not isinstance(status, str):
            raise CampaignError(f"Invalid campaign state: {self._path}")
        return payload

    def _write(self, snapshot: dict[str, Any]) -> None:
        temporary: Path | None = None
        try:
            parent = self._path.parent
            parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_name(f"{self._path.name}.{os.getpid()}.tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise CampaignError(f"Cannot persist campaign state: {self._path}") from exc
