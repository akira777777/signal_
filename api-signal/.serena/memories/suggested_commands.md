# Suggested commands (PowerShell)

- Setup: `python -m venv .venv`; `.\\.venv\\Scripts\\Activate.ps1`; `python -m pip install -e ".[dev]"`.
- Configure: `Copy-Item .env.example .env`; `Copy-Item groups.example.json groups.json`.
- Bridge: `docker compose up -d`.
- List Signal groups: `signal-groups groups`.
- Dry-run: `signal-groups send --group <alias> --message-file .\\message.txt`.
- Live: `signal-groups send --group <alias> --message-file .\\message.txt --execute --confirm-count 1`.
- Tests: `pytest`; lint: `ruff check .`; types: `mypy src tests`.
