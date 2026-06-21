from __future__ import annotations

import json
from pathlib import Path

import pytest

from signal_group_sender.state import (
    DeliveryLedger,
    RateLimitError,
    StateError,
    delivery_fingerprint,
    load_or_create_hmac_key,
)


def test_state_secret_is_stable_and_fingerprint_is_keyed(tmp_path: Path) -> None:
    secret_path = tmp_path / "state.secret"

    first_key = load_or_create_hmac_key(secret_path)
    second_key = load_or_create_hmac_key(secret_path)

    assert len(first_key) == 32
    assert first_key == second_key
    assert delivery_fingerprint(first_key, "+420123456789", "group.abc=", "hello") != (
        delivery_fingerprint(b"y" * 32, "+420123456789", "group.abc=", "hello")
    )


def test_hourly_quota_is_persistent(tmp_path: Path) -> None:
    now = 10_000.0
    ledger = DeliveryLedger(
        tmp_path / "state.json",
        integrity_key=b"k" * 32,
        duplicate_window_seconds=3600,
        clock=lambda: now,
    )
    ledger.record_attempt("one", "ops", "ops-token")
    ledger.update_status("one", "sent")

    reloaded = DeliveryLedger(
        tmp_path / "state.json",
        integrity_key=b"k" * 32,
        duplicate_window_seconds=3600,
        clock=lambda: now,
    )

    with pytest.raises(RateLimitError, match="Hourly send quota"):
        reloaded.assert_capacity(
            [("team", "team-token")],
            per_group_cooldown_seconds=0,
            max_sends_per_hour=1,
            max_sends_per_day=100,
        )


def test_group_cooldown_blocks_immediate_second_send(tmp_path: Path) -> None:
    ledger = DeliveryLedger(
        tmp_path / "state.json",
        integrity_key=b"k" * 32,
        duplicate_window_seconds=3600,
        clock=lambda: 1000.0,
    )
    ledger.record_attempt("one", "ops", "ops-token")
    ledger.update_status("one", "sent")

    with pytest.raises(RateLimitError, match="cooldown"):
        ledger.assert_capacity(
            [("renamed-ops", "ops-token")],
            per_group_cooldown_seconds=5,
            max_sends_per_hour=20,
            max_sends_per_day=100,
        )


def test_unknown_attempt_still_blocks_duplicate(tmp_path: Path) -> None:
    ledger = DeliveryLedger(
        tmp_path / "state.json",
        integrity_key=b"k" * 32,
        duplicate_window_seconds=3600,
        clock=lambda: 1000.0,
    )
    ledger.record_attempt("fingerprint", "ops", "ops-token")
    ledger.update_status("fingerprint", "unknown")

    assert ledger.was_sent_recently("fingerprint")


def test_tampered_state_is_rejected(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    ledger = DeliveryLedger(
        state_path,
        integrity_key=b"k" * 32,
        duplicate_window_seconds=3600,
        clock=lambda: 1000.0,
    )
    ledger.record_attempt("fingerprint", "ops", "ops-token")
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    raw["records"][0]["sent_at"] = 1.0
    state_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(StateError, match="integrity"):
        ledger.was_sent_recently("fingerprint")


def test_missing_initialized_state_fails_closed(tmp_path: Path) -> None:
    ledger = DeliveryLedger(
        tmp_path / "state.json",
        integrity_key=b"k" * 32,
        duplicate_window_seconds=3600,
    )

    with pytest.raises(StateError, match="missing after initialization"):
        ledger.initialize(allow_create=False)


def test_get_records_returns_all_entries(tmp_path: Path) -> None:
    ledger = DeliveryLedger(
        tmp_path / "state.json",
        integrity_key=b"k" * 32,
        duplicate_window_seconds=3600,
        clock=lambda: 1000.0,
    )
    ledger.record_attempt("one", "ops", "ops-token")
    ledger.update_status("one", "sent")
    ledger.record_attempt("two", "team", "team-token")

    records = ledger.get_records()
    assert len(records) == 2
    assert records[0].fingerprint == "one"
    assert records[0].status == "sent"
    assert records[1].fingerprint == "two"
    assert records[1].status == "dispatching"
