from __future__ import annotations

import json
from pathlib import Path

import pytest

from signal_group_sender.state import StateError
from signal_group_sender.telegram_campaigns import TelegramCampaignLedger


def test_campaign_ledger_records_without_message_text(tmp_path: Path) -> None:
    path = tmp_path / "campaigns.json"
    ledger = TelegramCampaignLedger(
        path,
        integrity_key=b"k" * 32,
        clock=lambda: 1000.0,
    )
    ledger.initialize()

    ledger.record_delivery(
        campaign_id="tg-1",
        alias="chat-a",
        target_token_value="token-a",
        peer_id="1001",
        variant_id="A",
        round_index=1,
        status="sent",
        message_ids=(42,),
        attachment_count=1,
    )

    raw_text = path.read_text(encoding="utf-8")
    assert "hello" not in raw_text
    campaign = ledger.get_campaign("tg-1")
    assert campaign is not None
    assert campaign["sent"] == 1
    assert campaign["deliveries"][0]["message_ids"] == [42]


def test_campaign_ledger_rejects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "campaigns.json"
    ledger = TelegramCampaignLedger(path, integrity_key=b"k" * 32)
    ledger.initialize()
    ledger.record_delivery(
        campaign_id="tg-1",
        alias="chat-a",
        target_token_value="token-a",
        peer_id="1001",
        variant_id="A",
        round_index=1,
        status="sent",
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["records"][0]["status"] = "failed"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(StateError, match="integrity"):
        ledger.get_campaigns()
