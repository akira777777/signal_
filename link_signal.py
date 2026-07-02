#!/usr/bin/env python3
"""
Signal Device Linker
====================
Связывает signal-cli-rest-api контейнер с вашим аккаунтом Signal через QR-код.

QR-коды привязки короткоживущие (около минуты). Этот скрипт:
  1. логинится в Dashboard;
  2. запрашивает свежий QR-код;
  3. открывает его в просмотрщике;
  4. ждёт, пока вы отсканируете его в Signal на телефоне;
  5. при истечении срока действия QR автоматически перевыпускает его.

Использование:
    python link_signal.py
"""

import base64
import sys
import time
import webbrowser
from pathlib import Path

import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except AttributeError:
        pass

# ── Конфигурация ──────────────────────────────────────────────────────────
BASE_URL = "http://127.0.0.1:8787"
PASSWORD = "1111"
QR_FILE = Path(__file__).resolve().parent / "api-signal" / "outputs" / "signal-link.png"

# Срок жизни QR ~ 60 сек; перевыпускаем чуть раньше.
QR_REFRESH_SECONDS = 50
# Сколько всего ждать сканирования.
WAIT_TIMEOUT_SECONDS = 600
# Как часто опрашивать статус привязки.
POLL_INTERVAL = 5


def open_qr_image(path: Path) -> None:
    if sys.platform == "win32":
        import os
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        import subprocess
        subprocess.run(["open", str(path)], check=False)
    else:
        webbrowser.open(path.as_uri())


def main() -> int:
    s = requests.Session()
    s.headers.update({"Origin": BASE_URL, "Content-Type": "application/json"})

    # Логин
    try:
        r = s.post(f"{BASE_URL}/api/login", json={"password": PASSWORD}, timeout=10)
    except requests.ConnectionError:
        print("ОШИБКА: Dashboard не запущен на http://127.0.0.1:8787")
        print("        Запустите: docker compose -f api-signal/docker-compose.yml up -d signal-api dashboard")
        return 1
    if r.status_code != 200:
        print(f"ОШИБКА: логин не удался (HTTP {r.status_code}): {r.text}")
        return 1
    print("✓ Авторизация в Dashboard успешна")

    deadline = time.time() + WAIT_TIMEOUT_SECONDS
    last_refresh = 0.0

    print()
    print("=" * 60)
    print("Привязка устройства Signal")
    print("=" * 60)
    print("1. Откройте Signal на телефоне")
    print("2. Настройки → Связанные устройства → Добавить новое устройство")
    print("3. Наведите камеру на QR-код")
    print()

    while time.time() < deadline:
        # Перевыпуск QR при необходимости
        if time.time() - last_refresh >= QR_REFRESH_SECONDS or last_refresh == 0.0:
            try:
                qr_resp = s.post(f"{BASE_URL}/api/accounts/link-qr", timeout=30)
            except requests.RequestException as exc:
                print(f"⚠ Не удалось получить QR: {exc}")
                time.sleep(3)
                continue
            if qr_resp.status_code != 200:
                print(f"⚠ /api/accounts/link-qr вернул HTTP {qr_resp.status_code}: {qr_resp.text}")
                time.sleep(3)
                continue
            data = qr_resp.json()
            image_url = data.get("image", "")
            if not image_url.startswith("data:image/"):
                print("⚠ Некорректный ответ QR, повтор...")
                time.sleep(3)
                continue
            header, b64 = image_url.split(",", 1)
            QR_FILE.parent.mkdir(parents=True, exist_ok=True)
            QR_FILE.write_bytes(base64.b64decode(b64))
            print(f"✓ Свежий QR сохранён: {QR_FILE}")
            open_qr_image(QR_FILE)
            last_refresh = time.time()
            print("  QR открыт. Отсканируйте его в Signal на телефоне.")
            print("  (если QR исчезнет — он обновится автоматически)")

        # Проверка статуса привязки
        try:
            st = s.get(f"{BASE_URL}/api/status", timeout=15)
            if st.status_code == 200:
                j = st.json()
                accounts = j.get("accounts", [])
                if accounts:
                    print()
                    print("=" * 60)
                    print(f"✓ УСТРОЙСТВО ПРИВЯЗАНО: {accounts}")
                    print(f"  Подключено: {j.get('connected')}")
                    print(f"  Групп доступно: {len(j.get('groups', []))}")
                    print("=" * 60)
                    print()
                    print("Теперь можно запускать рассылку:")
                    print("  python reminder_scheduler.py --signal-only --once --dry-run")
                    return 0
        except requests.RequestException:
            pass

        time.sleep(POLL_INTERVAL)

    print()
    print("Таймаут ожидания истёк. Запустите скрипт снова и быстрее отсканируйте QR.")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nОстановлено.")
        raise SystemExit(130)
