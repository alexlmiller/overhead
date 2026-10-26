# Overhead development

- This repository owns the reusable app, HA integration, example packages and tests.
  Keep installation settings and secrets outside the public repository.
- Use a worktree for substantive changes and `codex/` for agent branches.
- Run `make test` (set `PYTHON=.venv/bin/python` when using the local venv).
  Preview with `make serve`, `?demo=1`, and a 960×540 viewport.
- Preserve HA entity IDs, storage paths, provider separation and same-origin
  authentication. Never copy a live token, key, database or home coordinates into
  Git or static assets. Synthetic fixtures only.
- FlightAware is private-aircraft-only, bounded by the durable 25/24h and
  800/31d request ledger. Commercial misses stay on free providers. Do not reset
  the ledger to clear route caches or make provider calls from offline tests.
- Existing TV actions, house mode and manual control take priority over automatic
  aircraft sessions. Demo mode must never authenticate or invoke HA services.
- Local edits, tests, commits, pushes and PRs are allowed. Dependency changes,
  live deploys/restarts, access changes and secret operations require approval.
- Keep docs concise; use [docs/architecture.md](docs/architecture.md) for runtime
  contracts and docs/setup.md for installation procedures.
