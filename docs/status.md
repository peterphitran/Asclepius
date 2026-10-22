# Implementation Status

Implementation checkpoint on 2026-10-22 UTC, branch `codex/cli-evaluator`.

Tasks 1 and 2 implement CLI help, TOML validation, independent target/evaluator settings,
typed immutable domain contracts, and a tested SQLite repository. Evaluation execution
and public profile/run commands remain planned.

This worktree starts from `d13e794` and carries the current documentation. The original
checkout's frontend deletion and uncommitted backend lifecycle changes remain there,
untouched. They are not included in this branch. This worktree still contains the inherited
frontend files, which the new CLI does not use. Do not mistake this for restoring or
discarding the original removal work.

## Existing code

| Area | Location | Current behavior |
| --- | --- | --- |
| CLI foundation | `backend/asclepius/` | Help, version, target/evaluator TOML validation, structured errors, and domain contracts. No execution services. |
| Local storage | `backend/asclepius/storage.py` | SQLite snapshots, conditional claims, fenced writes, atomic stage/evidence commits, and orphan interruption. Repository API only, not daemon execution. |
| API | `backend/app/api/` | Auth, target, campaign, sweep, finding, review, summary, and health routes. |
| Data | `backend/app/models/`, `backend/app/db.py` | Organization-scoped Postgres records through async SQLAlchemy. |
| Migrations | `backend/alembic/` | Inherited Postgres revisions; current database revision is not verified. |
| Fixtures | `backend/app/seed.py` | Resets domain data and inserts simulated records. |
| Infrastructure | `backend/docker-compose.yml` | Postgres and Redis containers; Redis is unused by execution. |
| Tests | `backend/tests/` | Three inherited health/security tests, 42 CLI foundation tests, and 22 real SQLite/storage process tests. |

Campaign creation stores queued records and returns an identifier. Nothing dispatches
them to a worker or sends evaluation requests to a target.

The existing API calls runs `sweeps` and stores `campaigns`; those identifiers describe
current code. The [backend design](specs/backend-design.md) defines their replacement
with profile/run domain records and a separate execution coordinator.
API authentication is also current code, not a requirement for the personal CLI.

## Missing product capabilities

The installed CLI entry point and SQLite repository exist. There is no public storage/profile/run
command workflow, local daemon, executable check registry, target adapter, evaluation pipeline,
comparison engine, or report/chart generator. Future command groups fail explicitly rather
than claiming success. The next task connects profiles, submission, and inspection to storage.

## Reuse and migration considerations

The backend design contains the runtime transition decisions. The following constraints
describe source behavior that implementation must account for.

- The original checkout's uncommitted lifecycle operations are a possible starting point, but their Postgres row
  locks do not provide a SQLite scheduler automatically.
- Fake-session tests do not prove concurrent claims, restart recovery, or duplicate prevention.
  Those original-checkout step helpers lack persisted per-variant uniqueness.
- Target records currently store endpoint/model/environment labels without request
  mapping, credentials, or a real connection probe.
- Legacy findings contain clinical-specific fields and simulated evidence. Generic result
  contracts and SQLite relationships now exist; legacy finding migration or retirement remains pending.
- Review mutations lack role checks, pending-state enforcement, and reviewer audit history.
  Retaining that workflow is undecided.
- Postgres-specific types, existing tenancy, and authentication need explicit reuse/retirement decisions.

For endpoint details see the [API reference](reference/existing-api.md).
For tested observations and limits see [verification](verification.md). Source presence
and old passing-test reports do not establish a complete evaluation system.
