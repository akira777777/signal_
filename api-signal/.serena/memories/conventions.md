# Conventions and invariants

- Python: full type hints, strict mypy, dataclasses with `frozen=True, slots=True`, custom domain exceptions.
- No message text in logs/state; no number or group ID in normal send output. State uses keyed HMAC secret stored outside Git.
- CLI message input is file/stdin only, never process arguments.
- API bridge URL rejects credentials/path/query and remote hosts unless explicitly opted in.
- Allowlist aliases match conservative ASCII; IDs must start `group.`; arbitrary recipients are impossible through CLI.
- Read-only GET may retry bounded transient errors. POST send is at-most-once: timeout/connection error becomes `delivery_unknown`, no automatic retry.
- Live operations are serialized by file lock; state is atomically replaced.
