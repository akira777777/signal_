# Signal Group Sender — результат

Готовый проект находится в родительском каталоге `api-signal`.

Основные файлы:

- `README.md` — установка, привязка Signal, настройка allowlist и отправка;
- `docker-compose.yml` — закрытый Signal bridge, CLI и QR-linker;
- `src/signal_group_sender/` — Python CLI;
- `tests/` — тесты защитных механизмов.

Проверено:

- Ruff: без ошибок;
- strict mypy: без ошибок;
- pytest: 38 тестов, покрытие 85%;
- финальный независимый review: blocker/high отсутствуют;
- Docker/Compose проверены статически. Docker runtime в текущей среде недоступен,
  поэтому привязку реального Signal-аккаунта и отправку в тестовую группу нужно
  выполнить по инструкции из основного `README.md`.
