> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# End-to-End Verification and Operations Specification

## Goal

Make the executable pipeline reproducible locally and prove the full lifecycle with synthetic data.

## Configuration

Provide `.env.example` entries for:

- `DATABASE_URL`;
- `REDIS_URL`;
- `JWT_SECRET`;
- `CORS_ORIGINS`;
- provider/model settings and API keys;
- `TARGET_URL` and target limits;
- worker concurrency, lease, timeout, and retry settings.

Never commit actual secrets. Development defaults must be clearly marked insecure.

## Migrations and seed

- Compose/API startup must document, and optionally automate, `alembic upgrade head`.
- `python -m app.seed` remains an explicit destructive reset command.
- Add a non-destructive fixture path for tests.
- Health checks must distinguish API health from Postgres, Redis, and worker readiness.

## Test layers

1. Unit tests for case validation, model gateway parsing, agent contracts, and target adapter errors.
2. Backend integration tests with Postgres/Redis test services.
3. Worker tests for claim, retry, lease recovery, cancellation, and idempotency.
4. API tests for campaign launch, sweep status, review actions, and tenant isolation.
5. Frontend tests for launch, polling, terminal states, and review updates.
6. One end-to-end synthetic run using a fake model gateway and reference target.

## Required end-to-end scenario

1. Start Postgres, Redis, API, worker, and frontend.
2. Apply migrations and seed demo data.
3. Log in as the seeded demo user.
4. Create a campaign with one category and bounded variants.
5. Verify campaign and sweep are persisted as queued.
6. Verify the worker transitions the sweep to running and records steps.
7. Verify a completed run creates findings with the expected severity route.
8. Verify critical findings appear in review and approval changes their status.
9. Verify dashboard and sweep detail reflect final counts.

## Operational checks

- `GET /health` reports API process health only.
- Add readiness checks for database connectivity, Redis reachability, and worker heartbeat.
- Log correlation IDs, sweep IDs, attempt numbers, and terminal outcomes.
- Expose enough metrics to see queue depth, active sweeps, failures, latency, and provider usage.

## Acceptance criteria

- A clean checkout can follow one documented quickstart to run the synthetic pipeline.
- CI runs unit and API tests without real provider keys.
- The end-to-end scenario is repeatable and does not require real patient data.
- README commands match the actual repository layout and services.
