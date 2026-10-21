# Asclepius Project Context

Updated: 2026-10-21.

## Direction

Personal CLI security lab for models and RAG applications the user owns or controls.
Agreed behavior: named application profiles, a manually started detached daemon,
bounded concurrency, SQLite run history, and local reports/charts. No product login,
web frontend, or operating-system auto-start is required. These CLI capabilities
are planned, not implemented.

Read the [product direction](docs/specs/2026-10-21-personal-cli-direction.md) and
[current source inventory](docs/current-state.md) before planning changes.

## Published baseline

The GitHub baseline inspected on 2026-10-21 is `4485f06`. It contains FastAPI health
scaffolding, configuration, one health test, and Postgres/Redis Compose services.
The frontend-removal and documentation PRs build on that baseline.

## Additional local code

The original development checkout's `main` is 43 commits ahead of that published
baseline at `dc0f4a2`, and also contains uncommitted backend changes. The following
inventory describes that local checkout, not code included in these two PRs:

- `backend/`: FastAPI, async SQLAlchemy, Alembic, Postgres, JWT auth, organization-scoped APIs.
- `backend/app/services/sweep_state.py`: partial lifecycle service with leases and transitions.
- `backend/alembic/versions/9c4a1d2e7f80_add_sweep_lifecycle_metadata.py`: migration artifact.
- `backend/tests/`: health, security, and fake-session lifecycle tests.
- `backend/docker-compose.yml`: legacy Postgres and Redis services; no worker.
- `frontend/`: removed. Local backup details are in the source inventory.

Campaign creation only saves queued records. No CLI, SQLite store, daemon, target
execution, agents, or reports exist yet. Do not describe the system as operational E2E.
Local auth and database configuration describe legacy code, not the chosen CLI architecture.

## Documentation and history

- [Docs index](docs/README.md) is the entry point.
- [Backend guide](backend/README.md) describes the existing API only.
- [Archive](docs/archive/web-platform/README.md) preserves the clinical proposal,
  old specs/plans, and task reports. They are superseded, not an active checklist.
- Earlier production-target and Langfuse discussions were proposals, not implementations
  or required dependencies. Connection contracts, credentials, initial checks, evaluation
  stages, daemon recovery, and reporting still need design.

## Working constraints

Preserve the checkout's uncommitted backend work. Inspect source and diffs before
reusing historical plans. Separate artifacts and historical test reports from current
verified behavior. The Linux virtual environment belongs under WSL; native Windows
interpreter failures do not establish a product test failure.

## Latest changes

- 2026-10-21: Removed the independent frontend, preserving its local files externally.
- 2026-10-21: Reconciled documentation with the CLI direction and archived the former
  web/clinical specs, plans, proposal, and implementation notes.
