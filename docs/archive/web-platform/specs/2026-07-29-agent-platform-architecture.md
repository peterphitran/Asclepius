> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Asclepius Agent Platform Architecture Specification

## Status

Draft approved for decomposition into implementation plans.

## Goal

Turn the current dashboard prototype into an executable, auditable red-team pipeline while preserving the seeded Postgres data and existing review UI.

## Current baseline

- FastAPI backend in `backend/app`.
- Postgres and Redis provisioned by `backend/docker-compose.yml`.
- Next.js frontend in `frontend`.
- Campaign creation currently persists a `queued` campaign and sweep only.
- Seed data contains simulated sweep steps and findings.

## Target lifecycle

```text
campaign request
  -> validate target and attack cases
  -> persist campaign + queued sweep
  -> enqueue sweep job in Redis
  -> worker claims job
  -> selector chooses case/strategy
  -> generator creates variants
  -> target adapter executes variants
  -> judge scores responses
  -> reporter writes confirmed findings
  -> severity router publishes or gates critical findings
  -> sweep completes and frontend reflects state
```

Every transition must be persisted in Postgres. Redis is transport and coordination, not the system of record.

## State model

Campaign and sweep statuses remain `queued`, `running`, `completed`, `failed`, or `cancelled`. A sweep must record:

- `started_at` and `finished_at`.
- `progress`, `completed_cases`, and `total_cases`.
- `current_agent` and `current_activity`.
- failure code and human-readable failure detail.
- an idempotency key for retries.

Agent steps are append-only execution events linked to a sweep. Findings are linked to the sweep when possible and must include evidence sufficient for review.

## Boundaries

- Target adapter: only component allowed to call an external clinical AI endpoint.
- Agent layer: produces structured decisions and content; it does not write arbitrary database rows.
- Pipeline coordinator: owns ordering, retries, cancellation, and persistence.
- Worker: claims and runs jobs; it must be safe to restart.
- API: validates requests and exposes state; it must not perform long-running agent work inline.
- Frontend: displays persisted state and sends user actions; it does not infer execution state.

## Safety requirements

- Require explicit authorization and an endpoint URL for every target.
- Default to synthetic seeded records and bounded request counts.
- Never log API keys, bearer tokens, or full target responses unless configured for local development.
- Redact likely PHI from logs and traces.
- Critical findings remain `pending_review` until an authorized reviewer approves them.
- Every outbound target request must include a correlation ID and timeout.

## Compatibility

Existing seeded records must continue to render. Historical seeded sweeps may remain `running` or `completed`; the worker must only claim newly enqueued jobs or explicitly recover stale jobs.

## Acceptance criteria

- A campaign can be created without blocking the API request.
- A worker can execute a sweep and survive restart without duplicate findings.
- All agent transitions and failures are visible through the existing sweep API.
- The dashboard can show real progress while seeded data remains valid.
- A critical finding cannot become published without review.
