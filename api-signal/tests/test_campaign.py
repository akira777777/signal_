from __future__ import annotations

import time
from typing import Any

from signal_group_sender.campaign import PersistentCampaignManager


def test_campaign_stops_repeats_after_incomplete_round(tmp_path) -> None:
    calls: list[int] = []

    def sender(snapshot: dict[str, Any], round_index: int) -> list[dict[str, Any]]:
        del snapshot
        calls.append(round_index)
        return [{"alias": "ops", "status": "failed"}]

    manager = PersistentCampaignManager(
        tmp_path / "campaign.json",
        sender,
        wait_slice_seconds=0.01,
    )

    manager.start(
        {
            "transport": "signal",
            "repeat_count": 50,
            "interval_seconds": 0,
            "targets": [{"alias": "ops"}],
            "attachment_digests": [],
        }
    )
    status = manager.status()
    for _ in range(50):
        status = manager.status()
        if status["status"] == "failed":
            break
        time.sleep(0.02)
    manager.shutdown()

    assert status["status"] == "failed"
    assert status["current_round"] == 1
    assert calls == [1]
    assert "Round 1 did not complete" in status["error"]


def test_campaign_cancel_during_wait(tmp_path) -> None:
    calls: list[int] = []

    def sender(snapshot: dict[str, Any], round_index: int) -> list[dict[str, Any]]:
        del snapshot
        calls.append(round_index)
        return [{"alias": "ops", "status": "sent"}]

    manager = PersistentCampaignManager(
        tmp_path / "campaign.json",
        sender,
        wait_slice_seconds=0.01,
    )

    manager.start(
        {
            "transport": "signal",
            "repeat_count": 5,
            "interval_seconds": 100,
            "targets": [{"alias": "ops"}],
            "attachment_digests": [],
        }
    )

    for _ in range(50):
        status = manager.status()
        if status["status"] == "waiting":
            break
        time.sleep(0.01)

    assert manager.status()["status"] == "waiting"

    start_time = time.time()
    manager.cancel()

    for _ in range(50):
        status = manager.status()
        if status["status"] == "cancelled":
            break
        time.sleep(0.01)

    elapsed = time.time() - start_time
    manager.shutdown()

    assert status["status"] == "cancelled"
    assert elapsed < 2.0
    assert calls == [1]
