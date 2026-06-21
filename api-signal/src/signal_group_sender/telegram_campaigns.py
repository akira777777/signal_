from __future__ import annotations

import hmac
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from signal_group_sender.state import StateError

ENGAGEMENT_WINDOW_SECONDS = 86_400


@dataclass(frozen=True, slots=True)
class TelegramCampaignDelivery:
    campaign_id: str
    created_at: float
    alias: str
    target_token: str
    peer_id: str
    variant_id: str
    round_index: int
    status: str
    message_ids: tuple[int, ...]
    attachment_count: int
    reply_count: int = 0
    activity_count: int = 0
    engagement_checked_at: float | None = None


class TelegramCampaignLedger:
    def __init__(
        self,
        path: Path,
        *,
        integrity_key: bytes,
        clock: Any = time.time,
    ) -> None:
        self._path = path
        self._integrity_key = integrity_key
        self._clock = clock

    def initialize(self) -> None:
        if self._path.exists():
            self._load()
            return
        self._write([])

    def record_delivery(
        self,
        *,
        campaign_id: str,
        alias: str,
        target_token_value: str,
        peer_id: str,
        variant_id: str,
        round_index: int,
        status: str,
        message_ids: tuple[int, ...] = (),
        attachment_count: int = 0,
    ) -> None:
        records = self._load()
        now = self._clock()
        records.append(
            TelegramCampaignDelivery(
                campaign_id=campaign_id,
                created_at=now,
                alias=alias,
                target_token=target_token_value,
                peer_id=peer_id,
                variant_id=variant_id,
                round_index=round_index,
                status=status,
                message_ids=message_ids,
                attachment_count=attachment_count,
            )
        )
        self._write(records)

    def get_campaigns(self) -> list[dict[str, Any]]:
        campaigns: dict[str, list[TelegramCampaignDelivery]] = {}
        for record in self._load():
            campaigns.setdefault(record.campaign_id, []).append(record)
        return [
            self._campaign_summary(campaign_id, records)
            for campaign_id, records in sorted(
                campaigns.items(),
                key=lambda item: max(record.created_at for record in item[1]),
                reverse=True,
            )
        ]

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        records = [
            record for record in self._load() if record.campaign_id == campaign_id
        ]
        if not records:
            return None
        return {
            **self._campaign_summary(campaign_id, records),
            "deliveries": [self._record_payload(record) for record in records],
            "variants": self._variant_summaries(records),
            "chat_suggestions": self._chat_suggestions(records),
        }

    def delivery_records(
        self,
        campaign_id: str,
    ) -> list[TelegramCampaignDelivery]:
        return [
            record for record in self._load() if record.campaign_id == campaign_id
        ]

    def update_engagement(
        self,
        campaign_id: str,
        updates: dict[tuple[str, int, str], tuple[int, int]],
    ) -> None:
        checked_at = self._clock()
        changed = False
        records: list[TelegramCampaignDelivery] = []
        for record in self._load():
            key = (record.alias, record.round_index, record.variant_id)
            if record.campaign_id == campaign_id and key in updates:
                reply_count, activity_count = updates[key]
                records.append(
                    replace(
                        record,
                        reply_count=reply_count,
                        activity_count=activity_count,
                        engagement_checked_at=checked_at,
                    )
                )
                changed = True
            else:
                records.append(record)
        if changed:
            self._write(records)

    def _campaign_summary(
        self,
        campaign_id: str,
        records: list[TelegramCampaignDelivery],
    ) -> dict[str, Any]:
        sent = sum(1 for record in records if record.status in {"sent", "already_sent"})
        failed = sum(1 for record in records if record.status == "failed")
        unknown = sum(1 for record in records if record.status == "delivery_unknown")
        replies = sum(1 for record in records if record.reply_count > 0)
        active = sum(1 for record in records if record.activity_count > 0)
        total = len(records)
        return {
            "campaign_id": campaign_id,
            "created_at": min(record.created_at for record in records),
            "last_sent_at": max(record.created_at for record in records),
            "deliveries": total,
            "sent": sent,
            "failed": failed,
            "unknown": unknown,
            "reply_rate": round(replies / total * 100) if total else 0,
            "activity_rate": round(active / total * 100) if total else 0,
            "reply_count": replies,
            "activity_count": active,
            "variants": self._variant_summaries(records),
        }

    def _variant_summaries(
        self,
        records: list[TelegramCampaignDelivery],
    ) -> list[dict[str, Any]]:
        variants: dict[str, list[TelegramCampaignDelivery]] = {}
        for record in records:
            variants.setdefault(record.variant_id, []).append(record)
        return [
            {
                "variant_id": variant_id,
                "deliveries": len(items),
                "sent": sum(1 for item in items if item.status in {"sent", "already_sent"}),
                "reply_rate": round(
                    sum(1 for item in items if item.reply_count > 0) / len(items) * 100
                )
                if items
                else 0,
                "activity_rate": round(
                    sum(1 for item in items if item.activity_count > 0) / len(items) * 100
                )
                if items
                else 0,
            }
            for variant_id, items in sorted(variants.items())
        ]

    def _chat_suggestions(
        self,
        records: list[TelegramCampaignDelivery],
    ) -> dict[str, list[dict[str, Any]]]:
        by_alias: dict[str, list[TelegramCampaignDelivery]] = {}
        for record in records:
            by_alias.setdefault(record.alias, []).append(record)
        scored = [
            {
                "alias": alias,
                "deliveries": len(items),
                "reply_count": sum(item.reply_count for item in items),
                "activity_count": sum(item.activity_count for item in items),
            }
            for alias, items in by_alias.items()
        ]
        scored.sort(
            key=lambda item: (
                int(str(item["reply_count"])),
                int(str(item["activity_count"])),
            ),
            reverse=True,
        )
        return {
            "best": scored[:5],
            "weak": list(reversed(scored[-5:])) if scored else [],
        }

    def _load(self) -> list[TelegramCampaignDelivery]:
        if not self._path.exists():
            return []
        try:
            envelope = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StateError(f"Cannot read campaign state: {self._path}") from exc
        if not isinstance(envelope, dict):
            raise StateError(f"Invalid campaign state: {self._path}")
        raw = envelope.get("records")
        supplied_mac = envelope.get("mac")
        if not isinstance(raw, list) or not isinstance(supplied_mac, str):
            raise StateError(f"Invalid campaign state: {self._path}")
        if not hmac.compare_digest(supplied_mac, self._records_mac(raw)):
            raise StateError(f"Campaign state integrity check failed: {self._path}")
        records: list[TelegramCampaignDelivery] = []
        for item in raw:
            if not isinstance(item, dict):
                raise StateError(f"Invalid campaign state: {self._path}")
            try:
                records.append(
                    TelegramCampaignDelivery(
                        campaign_id=str(item["campaign_id"]),
                        created_at=float(item["created_at"]),
                        alias=str(item["alias"]),
                        target_token=str(item["target_token"]),
                        peer_id=str(item["peer_id"]),
                        variant_id=str(item.get("variant_id", "A")),
                        round_index=int(item.get("round_index", 1)),
                        status=str(item["status"]),
                        message_ids=tuple(int(value) for value in item.get("message_ids", [])),
                        attachment_count=int(item.get("attachment_count", 0)),
                        reply_count=int(item.get("reply_count", 0)),
                        activity_count=int(item.get("activity_count", 0)),
                        engagement_checked_at=(
                            None
                            if item.get("engagement_checked_at") is None
                            else float(item["engagement_checked_at"])
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise StateError(f"Invalid campaign state: {self._path}") from exc
        return records

    def _record_payload(self, record: TelegramCampaignDelivery) -> dict[str, Any]:
        return {
            "campaign_id": record.campaign_id,
            "created_at": record.created_at,
            "alias": record.alias,
            "target_token": record.target_token,
            "variant_id": record.variant_id,
            "round_index": record.round_index,
            "status": record.status,
            "message_ids": list(record.message_ids),
            "attachment_count": record.attachment_count,
            "reply_count": record.reply_count,
            "activity_count": record.activity_count,
            "engagement_checked_at": record.engagement_checked_at,
        }

    def _records_payload(
        self,
        records: list[TelegramCampaignDelivery],
    ) -> list[dict[str, Any]]:
        return [
            {
                **self._record_payload(record),
                "peer_id": record.peer_id,
            }
            for record in records
        ]

    def _records_mac(self, payload: Sequence[object]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hmac.new(self._integrity_key, canonical, "sha256").hexdigest()

    def _write(self, records: list[TelegramCampaignDelivery]) -> None:
        temporary: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_name(f"{self._path.name}.{os.getpid()}.tmp")
            payload = self._records_payload(records)
            envelope = {"records": payload, "mac": self._records_mac(payload)}
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(envelope, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise StateError(f"Cannot persist campaign state: {self._path}") from exc
