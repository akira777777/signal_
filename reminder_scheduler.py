"""
Unified Reminder Scheduler — Telegram + Signal
================================================
Sends promotional messages (text + video) to Telegram and Signal groups
at random intervals (30-60 min by default). Runs continuously until Ctrl+C.

Usage:
    python reminder_scheduler.py
    python reminder_scheduler.py --config path/to/config.json
    python reminder_scheduler.py --dry-run          # показать группы, не отправлять
    python reminder_scheduler.py --once             # один цикл и выход
    python reminder_scheduler.py --telegram-only    # только Telegram
    python reminder_scheduler.py --signal-only      # только Signal
"""

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import re
import signal
import sys
import time
from pathlib import Path

# Reconfigure stdout/stderr to use UTF-8 encoding to avoid Windows console encoding issues
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
        sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
    except AttributeError:
        pass

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

# Configure root logger with both StreamHandler (console) and FileHandler (UTF-8)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Clear existing handlers if any
for handler in list(root_logger.handlers):
    root_logger.removeHandler(handler)

formatter = logging.Formatter(LOG_FORMAT)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

# File handler
log_file_path = Path(__file__).resolve().parent / "reminder_scheduler.log"
file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

logger = logging.getLogger("ReminderScheduler")

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
SHUTDOWN_EVENT: asyncio.Event | None = None
SCRIPT_DIR = Path(__file__).resolve().parent


# ═══════════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════════

def load_config(config_path: str) -> dict:
    """Load and validate reminder_config.json."""
    path = Path(config_path)
    if not path.exists():
        logger.error(f"Конфиг не найден: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Resolve message text
    msg_file = cfg.get("message_text_file")
    if msg_file:
        msg_path = (SCRIPT_DIR / msg_file) if not Path(msg_file).is_absolute() else Path(msg_file)
        if msg_path.exists():
            cfg["message_text"] = msg_path.read_text(encoding="utf-8").strip()
        else:
            logger.warning(f"Файл сообщения не найден: {msg_path}")

    if not cfg.get("message_text"):
        logger.error("Текст сообщения пуст — укажите message_text или message_text_file в конфиге")
        sys.exit(1)

    # Validate video path
    video = cfg.get("video_path")
    if video and not Path(video).exists():
        logger.warning(f"Видеофайл не найден: {video} — будет отправляться только текст")
        cfg["video_path"] = None

    return cfg


def parse_spintax(text: str) -> str:
    """Replace {opt1|opt2} constructs with a random choice."""
    pattern = re.compile(r"\{([^{}]+)\}")
    while pattern.search(text):
        text = pattern.sub(lambda m: random.choice(m.group(1).split("|")), text)
    return text


# ═══════════════════════════════════════════════════════════════════════════
# Telegram Sender
# ═══════════════════════════════════════════════════════════════════════════

async def send_telegram(cfg: dict, dry_run: bool = False) -> dict:
    """Send reminders to all Telegram chats in the configured folder."""
    tg_cfg = cfg.get("telegram", {})
    if not tg_cfg.get("enabled", False):
        logger.info("Telegram отключён в конфиге — пропускаем")
        return {"success": 0, "fail": 0, "total": 0, "skipped": True}

    try:
        from telethon import TelegramClient
        from telethon.tl.functions.messages import GetDialogFiltersRequest
        from telethon.tl.types import DialogFilter
        from telethon.errors import (
            FloodWaitError,
            ChatWriteForbiddenError,
            UserBannedInChannelError,
        )
    except ImportError:
        logger.error("Telethon не установлен. Выполните: pip install telethon")
        return {"success": 0, "fail": 0, "total": 0, "skipped": True}

    api_id = tg_cfg["api_id"]
    api_hash = tg_cfg["api_hash"]
    session_name = tg_cfg.get("session_name", "session_reminder")
    folder_name = tg_cfg.get("folder_name", "Без лимитов")
    min_delay = tg_cfg.get("min_delay_between_chats", 15)
    max_delay = tg_cfg.get("max_delay_between_chats", 30)

    message_text = cfg["message_text"]
    if cfg.get("enable_spintax"):
        message_text = parse_spintax(message_text)

    video_path = cfg.get("video_path")

    # Resolve session path — support both absolute paths and names relative to script dir
    if Path(session_name).is_absolute() or os.path.exists(session_name + ".session"):
        session_path = session_name
    else:
        session_path = str(SCRIPT_DIR / session_name)
    client = TelegramClient(session_path, api_id, api_hash)

    try:
        await client.start()
    except Exception as e:
        logger.error(f"Telegram: ошибка авторизации — {e}")
        return {"success": 0, "fail": 0, "total": 0, "skipped": True}

    logger.info("Telegram: авторизация успешна. Получаю папки...")

    # Find target folder
    filters_result = await client(GetDialogFiltersRequest())
    target_filter = None
    for f in filters_result.filters:
        f_title = getattr(f.title, "text", f.title) if hasattr(f, "title") else None
        if isinstance(f, DialogFilter) and f_title == folder_name:
            target_filter = f
            break

    if not target_filter:
        logger.error(f"Telegram: папка '{folder_name}' не найдена")
        await client.disconnect()
        return {"success": 0, "fail": 0, "total": 0, "skipped": True}

    peers = target_filter.include_peers
    logger.info(f"Telegram: найдено {len(peers)} чатов в папке '{folder_name}'")

    if dry_run:
        for i, peer in enumerate(peers, 1):
            try:
                entity = await client.get_entity(peer)
                name = getattr(entity, "title", getattr(entity, "first_name", "?"))
            except Exception:
                name = f"ID {getattr(peer, 'chat_id', getattr(peer, 'channel_id', '?'))}"
            logger.info(f"  [{i}/{len(peers)}] {name}")
        await client.disconnect()
        return {"success": 0, "fail": 0, "total": len(peers), "skipped": False}

    success_count = 0
    fail_count = 0

    for idx, peer in enumerate(peers, 1):
        # Check shutdown
        if SHUTDOWN_EVENT and SHUTDOWN_EVENT.is_set():
            logger.info("Telegram: получен сигнал остановки, прерываю цикл")
            break

        try:
            entity = await client.get_entity(peer)
            chat_name = getattr(entity, "title", getattr(entity, "first_name", "Неизвестный"))
        except Exception:
            chat_name = f"ID {getattr(peer, 'chat_id', getattr(peer, 'channel_id', '?'))}"

        logger.info(f"Telegram: [{idx}/{len(peers)}] Отправка в '{chat_name}'...")

        sent = False
        # Try with video first
        if video_path:
            try:
                await client.send_file(peer, video_path, caption=message_text)
                sent = True
                logger.info(f"Telegram: [{idx}/{len(peers)}] ✅ Видео+текст → '{chat_name}'")
            except FloodWaitError as e:
                logger.warning(f"Telegram: FloodWait {e.seconds}s — ожидаю...")
                await asyncio.sleep(e.seconds)
                try:
                    await client.send_file(peer, video_path, caption=message_text)
                    sent = True
                    logger.info(f"Telegram: [{idx}/{len(peers)}] ✅ Видео+текст (после ожидания) → '{chat_name}'")
                except Exception as e2:
                    logger.warning(f"Telegram: [{idx}/{len(peers)}] ⚠ Видео не прошло после FloodWait: {e2}")
            except (ChatWriteForbiddenError, UserBannedInChannelError) as e:
                logger.error(f"Telegram: [{idx}/{len(peers)}] ❌ Нет прав → '{chat_name}': {e}")
                fail_count += 1
                continue
            except Exception as e:
                logger.warning(f"Telegram: [{idx}/{len(peers)}] ⚠ Видео не прошло → '{chat_name}': {e}")

        # Fallback: text only
        if not sent:
            try:
                await client.send_message(peer, message_text)
                sent = True
                logger.info(f"Telegram: [{idx}/{len(peers)}] ✅ Текст → '{chat_name}'")
            except FloodWaitError as e:
                logger.warning(f"Telegram: FloodWait {e.seconds}s — ожидаю...")
                await asyncio.sleep(e.seconds)
                try:
                    await client.send_message(peer, message_text)
                    sent = True
                    logger.info(f"Telegram: [{idx}/{len(peers)}] ✅ Текст (после ожидания) → '{chat_name}'")
                except Exception as e2:
                    logger.error(f"Telegram: [{idx}/{len(peers)}] ❌ Текст тоже не прошёл → '{chat_name}': {e2}")
            except (ChatWriteForbiddenError, UserBannedInChannelError) as e:
                logger.error(f"Telegram: [{idx}/{len(peers)}] ❌ Нет прав → '{chat_name}': {e}")
            except Exception as e:
                logger.error(f"Telegram: [{idx}/{len(peers)}] ❌ Ошибка → '{chat_name}': {e}")

        if sent:
            success_count += 1
        else:
            fail_count += 1

        # Delay between chats
        if idx < len(peers):
            delay = random.randint(min_delay, max_delay)
            logger.info(f"Telegram: ожидание {delay} сек перед следующим чатом...")
            await asyncio.sleep(delay)

    await client.disconnect()
    logger.info(f"Telegram: завершено. ✅ {success_count} | ❌ {fail_count}")
    return {"success": success_count, "fail": fail_count, "total": len(peers), "skipped": False}


# ═══════════════════════════════════════════════════════════════════════════
# Signal Sender (via Dashboard API)
# ═══════════════════════════════════════════════════════════════════════════

def _signal_login(session, base_url: str, password: str) -> bool:
    """Authenticate with the Signal Dashboard and store the session cookie."""
    try:
        resp = session.post(
            f"{base_url}/api/login",
            json={"password": password},
            headers={
                "Content-Type": "application/json",
                "Origin": base_url,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Signal: авторизация в Dashboard успешна")
            return True
        else:
            logger.error(f"Signal: ошибка авторизации — HTTP {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Signal: не удалось подключиться к Dashboard — {e}")
        return False


def _signal_get_groups(session, base_url: str) -> list[dict]:
    """Get list of available Signal groups from the Dashboard."""
    try:
        resp = session.get(f"{base_url}/api/status", timeout=30)
        if resp.status_code != 200:
            logger.error(f"Signal: ошибка получения статуса — HTTP {resp.status_code}")
            return []
        data = resp.json()
        if not data.get("connected"):
            logger.error(f"Signal: не подключён — {data.get('message', '?')}")
            return []
        groups = data.get("groups", [])
        available = [g for g in groups if g.get("available", True)]
        return available
    except Exception as e:
        logger.error(f"Signal: ошибка получения групп — {e}")
        return []


def _signal_plan_single(session, base_url: str, alias: str, message: str, attachments: list[str]) -> str | None:
    """Call /api/plan for a single group and return confirm_token or None on error."""
    payload = {
        "aliases": [alias],
        "message": message,
        "repeat_count": 1,
        "interval_seconds": 0,
        "attachments": attachments,
    }
    try:
        resp = session.post(
            f"{base_url}/api/plan",
            json=payload,
            headers={"Origin": base_url},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("confirm_token")
        else:
            logger.warning(f"Signal: /api/plan для '{alias}' вернул HTTP {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        logger.warning(f"Signal: ошибка /api/plan для '{alias}' — {e}")
        return None


def _signal_send_single(
    session,
    base_url: str,
    alias: str,
    message: str,
    attachments: list[str],
    confirm_token: str,
) -> bool:
    """Call /api/send for a single group and return True if sent successfully."""
    payload = {
        "aliases": [alias],
        "message": message,
        "repeat_count": 1,
        "interval_seconds": 0,
        "attachments": attachments,
        "confirm_token": confirm_token,
        "retry_unknown": False,
        "round_index": 1,
    }
    try:
        resp = session.post(
            f"{base_url}/api/send",
            json=payload,
            headers={"Origin": base_url},
            timeout=60,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                status = results[0].get("status")
                if status in ("sent", "already_sent"):
                    return True
                else:
                    detail = results[0].get("detail", "")
                    logger.warning(f"Signal: группа '{alias}' вернула статус '{status}': {detail}")
            return False
        else:
            logger.warning(f"Signal: /api/send для '{alias}' вернул HTTP {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.warning(f"Signal: ошибка /api/send для '{alias}' — {e}")
        return False


async def send_signal(cfg: dict, dry_run: bool = False) -> dict:
    """Send reminders to all Signal groups via the Dashboard API."""
    sig_cfg = cfg.get("signal", {})
    if not sig_cfg.get("enabled", False):
        logger.info("Signal отключён в конфиге — пропускаем")
        return {"success": 0, "fail": 0, "total": 0, "skipped": True}

    try:
        import requests
    except ImportError:
        logger.error("requests не установлен. Выполните: pip install requests")
        return {"success": 0, "fail": 0, "total": 0, "skipped": True}

    base_url = sig_cfg["dashboard_url"]
    password = sig_cfg["password"]

    session = requests.Session()

    # Login
    loop = asyncio.get_event_loop()
    login_ok = await loop.run_in_executor(None, _signal_login, session, base_url, password)
    if not login_ok:
        return {"success": 0, "fail": 0, "total": 0, "skipped": True}

    # Get groups
    groups = await loop.run_in_executor(None, _signal_get_groups, session, base_url)
    if not groups:
        logger.warning("Signal: нет доступных групп")
        return {"success": 0, "fail": 0, "total": 0, "skipped": False}

    logger.info(f"Signal: найдено {len(groups)} групп")

    if dry_run:
        for i, g in enumerate(groups, 1):
            logger.info(f"  [{i}/{len(groups)}] {g.get('name', g.get('alias', '?'))}")
        return {"success": 0, "fail": 0, "total": len(groups), "skipped": False}

    message_text = cfg["message_text"]
    video_path = cfg.get("video_path")
    min_delay = sig_cfg.get("min_delay_between_groups", 2)
    max_delay = sig_cfg.get("max_delay_between_groups", 5)

    # Prepare video attachment as base64 data URL
    attachments = []
    if video_path:
        try:
            with open(video_path, "rb") as vf:
                video_bytes = vf.read()
            b64_data = base64.b64encode(video_bytes).decode("ascii")
            data_url = f"data:video/mp4;base64,{b64_data}"
            attachments = [data_url]
            logger.info(f"Signal: видео загружено ({len(video_bytes) / 1024 / 1024:.1f} MB)")
        except Exception as e:
            logger.warning(f"Signal: не удалось загрузить видео — {e}")

    success_count = 0
    fail_count = 0

    for idx, group in enumerate(groups, 1):
        if SHUTDOWN_EVENT and SHUTDOWN_EVENT.is_set():
            logger.info("Signal: получен сигнал остановки, прерываю цикл")
            break

        alias = group["alias"]
        group_name = group.get("name", alias)
        logger.info(f"Signal: [{idx}/{len(groups)}] Отправка в '{group_name}'...")

        # Resolve spintax if enabled
        msg_to_send = message_text
        if cfg.get("enable_spintax"):
            msg_to_send = parse_spintax(msg_to_send)

        # Make message unique to bypass dashboard duplicate prevention (duplicate_window_seconds)
        # We append a random number of zero-width spaces (between 1 and 15) to the end.
        unique_message = msg_to_send + ("\u200b" * random.randint(1, 15))

        sent = False
        # Try sending with video first
        if attachments:
            # 1. Plan with video
            token = await loop.run_in_executor(
                None, _signal_plan_single, session, base_url, alias, unique_message, attachments
            )
            if token:
                # 2. Send with video
                sent = await loop.run_in_executor(
                    None, _signal_send_single, session, base_url, alias, unique_message, attachments, token
                )
                if sent:
                    logger.info(f"Signal: [{idx}/{len(groups)}] ✅ Видео+текст → '{group_name}'")
                else:
                    logger.warning(f"Signal: [{idx}/{len(groups)}] ⚠ Отправка с видео не удалась, пробую фолбэк...")
            else:
                logger.warning(f"Signal: [{idx}/{len(groups)}] ⚠ Планирование с видео не удалось, пробую фолбэк...")

        # Fallback to text only
        if not sent:
            # 1. Plan without video
            token = await loop.run_in_executor(
                None, _signal_plan_single, session, base_url, alias, unique_message, []
            )
            if token:
                # 2. Send without video
                sent = await loop.run_in_executor(
                    None, _signal_send_single, session, base_url, alias, unique_message, [], token
                )
                if sent:
                    logger.info(f"Signal: [{idx}/{len(groups)}] ✅ Текст → '{group_name}'")
                else:
                    logger.error(f"Signal: [{idx}/{len(groups)}] ❌ Текст тоже не прошёл → '{group_name}'")
            else:
                logger.error(f"Signal: [{idx}/{len(groups)}] ❌ Не удалось спланировать текст → '{group_name}'")

        if sent:
            success_count += 1
        else:
            fail_count += 1

        # Delay between groups
        if idx < len(groups):
            delay = random.randint(min_delay, max_delay)
            logger.info(f"Signal: ожидание {delay} сек перед следующей группой...")
            await asyncio.sleep(delay)

    return {"success": success_count, "fail": fail_count, "total": len(groups)}


# ═══════════════════════════════════════════════════════════════════════════
# Main Scheduler Loop
# ═══════════════════════════════════════════════════════════════════════════

async def run_cycle(cfg: dict, args) -> None:
    """Run one send cycle: Telegram + Signal."""
    cycle_start = time.time()
    logger.info("=" * 60)
    logger.info("🔔 НАЧАЛО ЦИКЛА НАПОМИНАНИЙ")
    logger.info("=" * 60)

    tg_result = {"skipped": True}
    signal_result = {"skipped": True}

    # Send to Telegram
    if not args.signal_only:
        try:
            tg_result = await send_telegram(cfg, dry_run=args.dry_run)
        except Exception as e:
            logger.error(f"Telegram: критическая ошибка — {e}", exc_info=True)

    # Send to Signal
    if not args.telegram_only:
        try:
            signal_result = await send_signal(cfg, dry_run=args.dry_run)
        except Exception as e:
            logger.error(f"Signal: критическая ошибка — {e}", exc_info=True)

    elapsed = time.time() - cycle_start
    logger.info("-" * 60)
    logger.info(f"📊 ИТОГИ ЦИКЛА ({elapsed:.0f} сек):")
    if not tg_result.get("skipped"):
        logger.info(
            f"  Telegram: ✅ {tg_result.get('success', 0)} / "
            f"❌ {tg_result.get('fail', 0)} / "
            f"📋 {tg_result.get('total', 0)}"
        )
    if not signal_result.get("skipped"):
        logger.info(
            f"  Signal:   ✅ {signal_result.get('success', 0)} / "
            f"❌ {signal_result.get('fail', 0)} / "
            f"📋 {signal_result.get('total', 0)}"
        )
    logger.info("-" * 60)


async def main_loop(cfg: dict, args) -> None:
    """Main infinite loop with random intervals."""
    global SHUTDOWN_EVENT
    SHUTDOWN_EVENT = asyncio.Event()

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, SHUTDOWN_EVENT.set)

    min_interval = cfg.get("min_interval_minutes", 30) * 60
    max_interval = cfg.get("max_interval_minutes", 60) * 60
    cycle_number = 0

    while True:
        cycle_number += 1
        logger.info(f"\n{'#' * 60}")
        logger.info(f"# ЦИКЛ #{cycle_number}")
        logger.info(f"{'#' * 60}")

        try:
            await run_cycle(cfg, args)
        except Exception as e:
            logger.error(f"Ошибка цикла #{cycle_number}: {e}", exc_info=True)

        if args.once:
            logger.info("Режим --once: завершение после одного цикла")
            break

        if SHUTDOWN_EVENT.is_set():
            logger.info("Получен сигнал остановки — завершаю...")
            break

        # Random delay before next cycle
        delay = random.randint(int(min_interval), int(max_interval))
        delay_min = delay // 60
        delay_sec = delay % 60
        next_time = time.strftime("%H:%M:%S", time.localtime(time.time() + delay))
        logger.info(f"\n⏰ Следующий цикл через {delay_min} мин {delay_sec} сек (в ~{next_time})")
        logger.info(f"   Для остановки нажмите Ctrl+C\n")

        # Sleep in small intervals to allow graceful shutdown
        slept = 0
        while slept < delay:
            if SHUTDOWN_EVENT.is_set():
                logger.info("Получен сигнал остановки во время ожидания — завершаю...")
                return
            chunk = min(5, delay - slept)
            await asyncio.sleep(chunk)
            slept += chunk


def parse_args():
    parser = argparse.ArgumentParser(
        description="Единый планировщик напоминаний: Telegram + Signal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=str(SCRIPT_DIR / "reminder_config.json"),
        help="Путь к конфигу (по умолчанию: reminder_config.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать группы, не отправлять сообщения",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Один цикл и выход (без бесконечного повтора)",
    )
    parser.add_argument(
        "--telegram-only",
        action="store_true",
        help="Отправлять только в Telegram",
    )
    parser.add_argument(
        "--signal-only",
        action="store_true",
        help="Отправлять только в Signal",
    )
    return parser.parse_args()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    args = parse_args()
    cfg = load_config(args.config)

    logger.info("=" * 60)
    logger.info("🚀 UNIFIED REMINDER SCHEDULER")
    logger.info(f"   Telegram: {'✅' if cfg.get('telegram', {}).get('enabled') else '❌'}")
    logger.info(f"   Signal:   {'✅' if cfg.get('signal', {}).get('enabled') else '❌'}")
    logger.info(f"   Видео:    {'✅ ' + cfg.get('video_path', 'нет') if cfg.get('video_path') else '❌ только текст'}")
    logger.info(f"   Интервал: {cfg.get('min_interval_minutes', 30)}-{cfg.get('max_interval_minutes', 60)} мин")
    logger.info(f"   Режим:    {'dry-run' if args.dry_run else 'once' if args.once else 'непрерывный'}")
    logger.info("=" * 60)

    try:
        asyncio.run(main_loop(cfg, args))
    except KeyboardInterrupt:
        logger.info("\n👋 Остановлено пользователем (Ctrl+C)")
    finally:
        logger.info("Планировщик завершён.")
