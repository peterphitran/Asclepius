> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Task 2 brief — transactional sweep state service

Read this first — it is the task requirements, with exact values to use verbatim.

## Scope

Create `backend/app/services/__init__.py` and `backend/app/services/sweep_state.py`. Add or modify `backend/tests/test_sweep_state.py`. Build on the Task 1 Sweep lifecycle fields already present.

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

## Required interfaces

Implement transaction-scoped async operations:

- `async def claim_sweep(session, sweep_id, worker_id, lease_seconds) -> Sweep`
- `async def heartbeat_sweep(session, sweep_id, worker_id, lease_seconds) -> Sweep`
- `async def complete_sweep(session, sweep_id, worker_id) -> Sweep`
- `async def fail_sweep(session, sweep_id, worker_id, code, detail) -> Sweep`
- `async def cancel_sweep(session, sweep_id, requested_by) -> Sweep`
- `async def retry_sweep(session, sweep_id, requested_by) -> Sweep`

Also provide append-only step helpers for starting/finishing a SweepStep with idempotent duplicate handling.

## Behavior

- `claim_sweep` may claim only queued sweeps or sweeps with expired leases.
- A second worker cannot claim an active lease.
- Heartbeat, complete, and fail require the current lease owner.
- Terminal sweeps cannot be claimed or completed again.
- Cancel sets a terminal cancellation detail and prevents future work.
- Retry increments `attempt`, clears transient execution fields, and creates a new idempotency key while preserving historical steps/findings.
- Use one transaction per operation and row locking or an equivalent conditional update.

## TDD

1. Add failing async tests for claim, lease conflict, heartbeat ownership, terminal completion/failure, cancellation, retry, progress bounds, and idempotent step recording.
2. Run `.venv/bin/python -m pytest tests/test_sweep_state.py -q` through WSL and verify the expected failure before implementation.
3. Implement the minimal service and typed domain exceptions.
4. Rerun the focused test and report exact output.

Do not implement Redis, API routes, migrations, target calls, agents, or workers in this task.

## Report

Update `.superpowers/sdd/2026-07-29-agent-platform-architecture/task-1-report.md` only if needed for cross-task notes; otherwise write `.superpowers/sdd/2026-07-29-agent-platform-architecture/task-2-report.md`. Return status, changed files, tests, commit hash if any, and concerns.
