# Implementation Status

Reviewed against this working checkout on 2026-10-21.

The frontend has been removed. The executable code that remains is a FastAPI/Postgres
prototype, not the CLI described in [product scope](product.md). The checkout contains
uncommitted backend work; preserve it during the transition.

## Existing code

| Area | Location | Current behavior |
| --- | --- | --- |
| API | `backend/app/api/` | Auth, target, campaign, sweep, finding, review, summary, and health routes. |
| Data | `backend/app/models/`, `backend/app/db.py` | Organization-scoped Postgres records through async SQLAlchemy. |
| Lifecycle | `backend/app/services/sweep_state.py` | Claim, heartbeat, complete, fail, cancel, retry, progress, and step helpers. |
| Migrations | `backend/alembic/` | Postgres revisions, including lifecycle metadata; current database revision is not verified. |
| Fixtures | `backend/app/seed.py` | Resets domain data and inserts simulated records. |
| Infrastructure | `backend/docker-compose.yml` | Postgres and Redis containers; Redis is unused by execution. |
| Tests | `backend/tests/` | Health/security tests and fake-session lifecycle tests. |

Campaign creation stores queued records and returns an identifier. Nothing dispatches
them to a worker or sends evaluation requests to a target.

The existing API calls runs `sweeps` and stores `campaigns`; those identifiers describe
current code. Their mapping to the new product vocabulary is still a design task.
API authentication is also current code, not a requirement for the personal CLI.

## Missing product capabilities

There is no CLI entry point, local daemon, SQLite store, executable check registry,
target adapter, evaluation pipeline, comparison engine, or report/chart generator.

## Reuse and migration considerations

- Guarded lifecycle operations are a possible starting point, but their Postgres row
  locks do not provide a SQLite scheduler automatically.
- Fake-session tests do not prove concurrent claims, restart recovery, or duplicate prevention.
  Step helpers lack persisted per-variant uniqueness.
- Target records currently store endpoint/model/environment labels without request
  mapping, credentials, or a real connection probe.
- Existing findings contain clinical-specific fields and simulated evidence; the
  generic result schema needs design.
- Review mutations lack role checks, pending-state enforcement, and reviewer audit history.
  Retaining that workflow is undecided.
- Postgres-specific types, existing tenancy, and authentication need explicit reuse/retirement decisions.

For endpoint details see the [API reference](reference/existing-api.md).
For tested observations and limits see [verification](verification.md). Source presence
and old passing-test reports do not establish a complete evaluation system.
