# Implementation Status

Implementation checkpoint on 2026-10-22 UTC, branch `codex/cli-evaluator`.

Tasks 1 through 3 implement CLI configuration, local initialization, profile management,
persisted history/findings, watch, cancellation intent, and linked retries over SQLite.
Supplied-plan submission is tested with controlled readiness. Evaluation execution and
real daemon startup remain planned.

This worktree starts from `d13e794` and carries the current documentation. The original
checkout's frontend deletion and uncommitted backend lifecycle changes remain there,
untouched. They are not included in this branch. This worktree still contains the inherited
frontend files, which the new CLI does not use. Do not mistake this for restoring or
discarding the original removal work.

## Existing code

| Area | Location | Current behavior |
| --- | --- | --- |
| CLI | `backend/asclepius/cli.py` | Help, configuration, initialization, profiles, run/history/finding reads, watch, cancellation, and retry commands. |
| Services | `backend/asclepius/services.py` | Complete supplied-plan validation, credential presence checks, pinned snapshots, cancellation, and linked retries. No provider calls or implicit daemon launch. |
| Local storage | `backend/asclepius/storage.py` | SQLite snapshots, paginated reads, profile tombstones, claims, fenced writes, atomic stage/evidence commits, and orphan interruption. Not daemon execution. |
| API | `backend/app/api/` | Auth, target, campaign, sweep, finding, review, summary, and health routes. |
| Data | `backend/app/models/`, `backend/app/db.py` | Organization-scoped Postgres records through async SQLAlchemy. |
| Migrations | `backend/alembic/` | Inherited Postgres revisions; current database revision is not verified. |
| Fixtures | `backend/app/seed.py` | Resets domain data and inserts simulated records. |
| Infrastructure | `backend/docker-compose.yml` | Postgres and Redis containers; Redis is unused by execution. |
| Tests | `backend/tests/` | Three inherited tests, 42 CLI foundation tests, 22 SQLite/storage cases, and 24 service/CLI management cases. |

Campaign creation stores queued records and returns an identifier. Nothing dispatches
them to a worker or sends evaluation requests to a target.

The existing API calls runs `sweeps` and stores `campaigns`; those identifiers describe
current code. The [backend design](specs/backend-design.md) defines their replacement
with profile/run domain records and a separate execution coordinator.
API authentication is also current code, not a requirement for the personal CLI.

## Missing product capabilities

There is no real daemon, built-in check registry, target adapter, evaluation pipeline,
comparison engine, report/chart generator, or storage migration command. These commands fail
explicitly. Normal submission remains unavailable until a real daemon starts. The next task
adds manual process ownership, readiness, and outbound budgets, not model execution yet.

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
