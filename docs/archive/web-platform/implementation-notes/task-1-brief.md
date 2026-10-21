> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Task 1 brief — durable sweep lifecycle model

Read this first — it is the task requirements, with the exact values to use verbatim.

## Scope

Modify `backend/app/models/sweep.py` and `backend/app/schemas.py`. Add `backend/tests/test_sweep_state.py`.

## Global constraints

- Every transition must be persisted in Postgres.
- Redis is transport and coordination, not the system of record.
- Existing seeded records must continue to render.
- Historical seeded sweeps may remain `running` or `completed`; the worker must only claim newly enqueued jobs or explicitly recover stale jobs.
- Require explicit authorization and an endpoint URL for every target.
- Default to synthetic seeded records and bounded request counts.
- Critical findings remain `pending_review` until an authorized reviewer approves them.
- The API must not perform long-running agent work inline.
- Do not modify unrelated user changes already present in the worktree.

## Required outputs

Produce model fields `finished_at`, `failure_code`, `failure_detail`, `heartbeat_at`, `lease_owner`, `lease_expires_at`, `attempt`, and `idempotency_key`.

Expose the same lifecycle metadata through `SweepOut` using the project’s camelCase aliases. Existing rows must be compatible: `attempt=1`, null terminal/lease values, and unchanged existing sweep fields.

## TDD steps

1. Add a failing test named `test_sweep_defaults_to_first_attempt_without_terminal_state` constructing a `Sweep` and asserting `attempt == 1`, `finished_at is None`, and `failure_code is None`.
2. Run `.venv/bin/python -m pytest tests/test_sweep_state.py::test_sweep_defaults_to_first_attempt_without_terminal_state -q` and confirm it fails for the missing fields.
3. Implement minimal model/schema changes.
4. Run the focused test and report the result.

Do not implement state services, Redis, workers, migrations, API endpoints, target calls, or agent logic in this task.

## Report

Write your report to `.superpowers/sdd/2026-07-29-agent-platform-architecture/task-1-report.md`. Return only status, changed files, commit hash if any, one-line test summary, and concerns.
