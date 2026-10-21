# Current Implementation State

Reviewed: 2026-10-21. The published repository and the original development checkout
are at different checkpoints. This document records both; it does not claim current
end-to-end verification.

## Published baseline

GitHub `main` was `4485f06` when the frontend-removal and documentation PRs were
prepared. Those PRs contain only frontend deletion and documentation changes.

| Area | Published baseline |
| --- | --- |
| API | [main.py](../backend/app/main.py) mounts the health router. Auth, campaign, sweep, and finding routes are not included. |
| Configuration | [config.py](../backend/app/config.py) defines development settings, including database/Redis URLs and legacy browser CORS origins. |
| Infrastructure | [Compose](../backend/docker-compose.yml) defines Postgres 17 and Redis 7. Neither is used by the health endpoint. |
| Dependencies | [pyproject.toml](../backend/pyproject.toml) declares Python 3.12+, FastAPI, Uvicorn, settings, and development tools. No CLI entry point or database layer is present in this baseline. |
| Tests | [Health test](../backend/tests/test_health.py) checks process metadata. |
| Frontend | Removed by the frontend-removal PR. |

## More advanced local checkout

The original development checkout's `main` is `dc0f4a2`: 43 commits ahead of the
published baseline, with additional uncommitted changes. That existing backend work
is excluded from these two PRs.

The paths below identify local artifacts and may not exist in a checkout of the
published PR branches:

| Local artifact | Evidence and limits |
| --- | --- |
| `backend/app/api/` | Auth, dashboard, target, campaign, sweep, finding, and review routes. Local CRUD changes are also uncommitted. |
| `backend/app/models/`, `backend/app/db.py` | Async SQLAlchemy/Postgres models and database access; not the planned SQLite store. |
| `backend/app/api/campaigns.py` | Campaign creation commits campaign and queued sweep records and returns an ID without execution dispatch. |
| `backend/app/services/sweep_state.py` | Uncommitted transactional claim, heartbeat, complete, fail, cancel, retry, progress, and step helpers. |
| `backend/alembic/versions/9c4a1d2e7f80_add_sweep_lifecycle_metadata.py` | Uncommitted migration adding eight lifecycle columns. Its presence does not verify the current database revision. |
| `backend/app/api/sweeps.py` | Read endpoints with uncommitted lifecycle metadata changes; cancel/retry service functions are not HTTP endpoints. |
| `backend/app/seed.py` | Resets domain tables and inserts clinical demo records, including simulated steps/findings. |
| `backend/tests/test_sweep_state.py` | Uncommitted lifecycle tests using a fake async session. Security tests also exist locally. |

The local API still requires JWT authentication and organization scoping. Those
legacy implementation details are separate from the CLI's no-sign-in direction.

## Capabilities that do not exist yet

Neither checkpoint has the planned CLI, local daemon, SQLite history, target HTTP
adapter, executable evaluation pipeline, attack-case registry, or report/chart generator.
There is no application Redis queue consumer. The named-profile/background-run
workflow is a product direction, not a usable feature.

## Historical validation

The [Task 2 report](archive/web-platform/implementation-notes/task-2-report.md) records
eight focused tests, eleven full-suite tests, focused Ruff checks, and a local Postgres
migration upgrade passing in a prior environment. Those results describe earlier local
backend work; they do not establish current health of either checkpoint.

Local lifecycle helpers request Postgres row locks, but fake-session tests do not prove
concurrent-worker correctness. Step helpers look up rows by sweep, agent, category, and
strategy; they do not provide the old plan's persisted per-step idempotency key or
database uniqueness guarantee. Restart-safe execution remains unproven.

The original checkout's virtual environment is Linux/WSL-based. Its interpreter cannot
be invoked directly as a native Windows executable. Follow the [backend guide](../backend/README.md)
for an appropriate environment. No current database revision or full evaluation result
is established by this inventory.

## Preservation

Keep the original checkout's unpublished commits and uncommitted backend work while
designing the CLI transition. They are not silently included in the two cleanup PRs.

The complete local frontend was moved to this machine-specific backup:
`C:/Users/ptran/Downloads/Projects/Asclepius-backups/frontend-20261021-170713`.
Source/config/asset hashes were verified when it was moved. This backup is not part
of the repository or a portable installation dependency.

Use the [personal CLI direction](specs/2026-10-21-personal-cli-direction.md) for product decisions.
