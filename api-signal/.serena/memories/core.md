# Project core

- Safe local CLI for sending one text message to allowlisted Signal groups through `signal-cli-rest-api`.
- Entry point: `signal-groups` / `python -m signal_group_sender`.
- Safety invariants: dry-run by default; live send requires `--execute --confirm-count N`; only group IDs loaded from `groups.json`; verify current group membership before sending; sequential sends; stop after first failure or unknown delivery; never retry POST `/v2/send`.
- Persistent HMAC-based duplicate detection, quotas, per-group cooldown, and cross-process run lock.
- Bridge is unofficial and must remain loopback-only. Read `mem:tech_stack` for versions, `mem:conventions` for code invariants, and `mem:task_completion` before handoff.
