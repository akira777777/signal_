# Task completion

Run from project root:

1. `.\\.venv\\Scripts\\ruff.exe check .`
2. `.\\.venv\\Scripts\\mypy.exe src tests`
3. `.\\.venv\\Scripts\\pytest.exe` (coverage target >=80%).
4. Parse `docker-compose.yml` and confirm port remains exactly `127.0.0.1:8080:8080`.
5. If Docker is available, run `docker compose config` and a real linked-device smoke test using a consented test group.
6. Verify `.env`, `groups.json`, state, secret, lock, and signal-cli data remain ignored/uncommitted.
