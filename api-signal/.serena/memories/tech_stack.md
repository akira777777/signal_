# Tech stack

- Python >=3.11, setuptools src-layout package.
- Runtime: requests, python-dotenv.
- Quality: pytest + pytest-cov, Ruff, strict mypy + types-requests.
- Signal bridge: `bbernhard/signal-cli-rest-api:0.100-rootless`, mode `json-rpc-native`, wrapping unofficial signal-cli.
- Docker Compose binds bridge only to `127.0.0.1:8080`; signal identity/session data persists in named volume.
