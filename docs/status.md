# Implementation Status

Implementation checkpoint on 2026-10-22 UTC, branch `codex/cli-evaluator`.

Task 1 implements CLI help, TOML validation, independent target/evaluator settings, and
typed immutable domain contracts. Evaluation execution remains planned.

This worktree starts from `d13e794` and carries the current documentation. The original
checkout's frontend deletion and uncommitted backend lifecycle changes remain there,
untouched. They are not included in this branch. This worktree still contains the inherited
frontend files, which the new CLI does not use. Do not mistake this for restoring or
discarding the original removal work.

## Existing code

| Area | Location | Current behavior |
| --- | --- | --- |
| CLI foundation | `backend/asclepius/` | Help, version, target/evaluator TOML validation, structured errors, and domain contracts. No execution services. |
| API | `backend/app/api/` | Auth, target, campaign, sweep, finding, review, summary, and health routes. |
| Data | `backend/app/models/`, `backend/app/db.py` | Organization-scoped Postgres records through async SQLAlchemy. |
| Migrations | `backend/alembic/` | Inherited Postgres revisions; current database revision is not verified. |
| Fixtures | `backend/app/seed.py` | Resets domain data and inserts simulated records. |
| Infrastructure | `backend/docker-compose.yml` | Postgres and Redis containers; Redis is unused by execution. |
| Tests | `backend/tests/` | Three inherited health/security tests and 42 CLI configuration/domain/help tests. |

Campaign creation stores queued records and returns an identifier. Nothing dispatches
them to a worker or sends evaluation requests to a target.

The existing API calls runs `sweeps` and stores `campaigns`; those identifiers describe
current code. The [backend design](specs/backend-design.md) defines their replacement
with profile/run domain records and a separate execution coordinator.
API authentication is also current code, not a requirement for the personal CLI.

## Missing product capabilities

The installed CLI entry point exists. There is no local daemon, SQLite store, executable
check registry, target adapter, evaluation pipeline, comparison engine, or report/chart
generator. Future command groups fail explicitly rather than claiming success.

## Reuse and migration considerations

The backend design contains the runtime transition decisions. The following constraints
describe source behavior that implementation must account for.

- The original checkout's uncommitted lifecycle operations are a possible starting point, but their Postgres row
  locks do not provide a SQLite scheduler automatically.
- Fake-session tests do not prove concurrent claims, restart recovery, or duplicate prevention.
  Those original-checkout step helpers lack persisted per-variant uniqueness.
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
