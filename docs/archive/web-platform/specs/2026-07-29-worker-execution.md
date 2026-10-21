> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Worker and Redis Execution Specification

## Goal

Connect queued campaigns to durable background execution without running long agent jobs inside FastAPI request handlers.

## Queue contract

Queue name: `asclepius:sweeps`.

Job payload:

```json
{
  "sweep_id": "uuid",
  "org_id": "uuid",
  "attempt": 1,
  "enqueued_at": "ISO-8601"
}
```

The database remains authoritative. Redis jobs are rebuildable from queued sweeps.

## Worker behavior

1. Claim a queued sweep with a transactional database update.
2. Mark it `running` and set `started_at`.
3. Execute the coordinator with bounded concurrency.
4. Persist progress after each case and step.
5. Mark `completed` with final counts, or `failed` with a typed error.
6. Release/expire the lease on success, failure, or cancellation.

Use a lease/heartbeat so a crashed worker leaves recoverable work. A retry must use an idempotency key derived from sweep, case, strategy, and variant IDs.

## API changes

- `POST /campaigns` persists and enqueues a sweep.
- `POST /sweeps/{id}/cancel` requests cancellation.
- `POST /sweeps/{id}/retry` creates a controlled retry or requeues the failed sweep.
- `GET /sweeps/{id}` exposes failure and heartbeat metadata.

## Docker/runtime

Add a worker service to Compose with the same backend image and environment as the API. The worker must wait for Postgres and Redis health before consuming jobs.

Required settings include Redis URL, worker concurrency, lease duration, retry limits, provider credentials, and target limits.

## Acceptance criteria

- Creating a campaign results in a Redis job and eventually a running sweep.
- Restarting the worker does not duplicate completed findings.
- Failed jobs are visible and retryable.
- Cancellation stops new target requests and results in a terminal cancelled state.
- API requests remain responsive while a sweep runs.
