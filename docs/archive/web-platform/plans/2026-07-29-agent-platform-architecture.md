> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Agent Platform Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the durable sweep lifecycle, persistence contracts, queue boundary, and API behavior required for executable agent runs while preserving seeded demo data.

**Architecture:** Add a persistence-backed sweep state service and explicit queue interface beneath the existing FastAPI routes. `POST /campaigns` will remain fast: it validates and commits the campaign/sweep, then enqueues a small Redis job through an adapter. Later worker and agent specs will consume the same interfaces; this plan does not implement model providers or attack execution.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, PostgreSQL, Redis, Pydantic, pytest, httpx.

## Global Constraints

- Every transition must be persisted in Postgres.
- Redis is transport and coordination, not the system of record.
- Existing seeded records must continue to render.
- Historical seeded sweeps may remain `running` or `completed`; the worker must only claim newly enqueued jobs or explicitly recover stale jobs.
- Require explicit authorization and an endpoint URL for every target.
- Default to synthetic seeded records and bounded request counts.
- Critical findings remain `pending_review` until an authorized reviewer approves them.
- The API must not perform long-running agent work inline.
- Do not modify unrelated user changes already present in the worktree.

## File map

- Create `backend/app/services/sweep_state.py`: transactional lifecycle and lease operations.
- Create `backend/app/services/queue.py`: queue protocol and Redis implementation.
- Create `backend/app/services/__init__.py`: service package exports.
- Modify `backend/app/models/sweep.py`: durable lifecycle and idempotency columns.
- Modify `backend/app/schemas.py`: expose lifecycle metadata through sweep responses.
- Modify `backend/app/api/campaigns.py`: enqueue after commit through the queue boundary.
- Modify `backend/app/api/sweeps.py`: add cancellation and retry endpoints using state service.
- Modify `backend/app/config.py`: add queue/lease/retry settings.
- Create `backend/alembic/versions/20260729_add_sweep_lifecycle.py`: migrate new sweep columns.
- Create `backend/tests/test_sweep_state.py`: state transition and lease tests.
- Create `backend/tests/test_queue.py`: queue payload and enqueue tests.
- Modify `backend/tests/test_health.py` or add API-focused tests: lifecycle endpoint behavior.

---

### Task 1: Define the durable sweep lifecycle model

**Files:**
- Modify: `backend/app/models/sweep.py`
- Modify: `backend/app/schemas.py`
- Create: `backend/tests/test_sweep_state.py`

**Interfaces:**
- Produces model fields `finished_at`, `failure_code`, `failure_detail`, `heartbeat_at`, `lease_owner`, `lease_expires_at`, `attempt`, and `idempotency_key`.
- Produces API fields with camelCase aliases for those lifecycle values.

- [ ] **Step 1: Write failing tests for terminal and retry metadata**

Add model-level tests that construct a `Sweep` and assert its default attempt is `1`, its idempotency key is accepted, and terminal metadata can be represented without changing seeded fields:

```python
def test_sweep_defaults_to_first_attempt_without_terminal_state():
    sweep = Sweep(org_id=uuid.uuid4(), campaign_id=uuid.uuid4())
    assert sweep.attempt == 1
    assert sweep.finished_at is None
    assert sweep.failure_code is None
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run from `backend`:

```powershell
.venv\bin\python.exe -m pytest tests/test_sweep_state.py::test_sweep_defaults_to_first_attempt_without_terminal_state -q
```

Expected: FAIL because the new fields/default are not yet defined.

- [ ] **Step 3: Add nullable lifecycle fields and safe defaults**

Add the fields to `Sweep` with database-safe defaults. Keep existing `progress`, `completed_cases`, `total_cases`, `current_agent`, and `current_activity` unchanged. Use a string idempotency key with an index and nullable lease fields.

- [ ] **Step 4: Add the fields to `SweepOut`**

Expose the lifecycle metadata through the existing response schema. Do not make new fields required for old rows at the database level; return `attempt=1` and null terminal/lease values for seeded records.

- [ ] **Step 5: Run the focused test and verify it passes**

Run the same pytest command. Expected: PASS.

- [ ] **Step 6: Commit the isolated model/schema change**

```powershell
git add backend/app/models/sweep.py backend/app/schemas.py backend/tests/test_sweep_state.py
git commit -m "feat: add durable sweep lifecycle metadata"
```

### Task 2: Add the transactional sweep state service

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/sweep_state.py`
- Modify: `backend/tests/test_sweep_state.py`

**Interfaces:**
- `async def claim_sweep(session, sweep_id, worker_id, lease_seconds) -> Sweep`
- `async def heartbeat_sweep(session, sweep_id, worker_id, lease_seconds) -> Sweep`
- `async def complete_sweep(session, sweep_id, worker_id) -> Sweep`
- `async def fail_sweep(session, sweep_id, worker_id, code, detail) -> Sweep`
- `async def cancel_sweep(session, sweep_id, requested_by) -> Sweep`
- `async def retry_sweep(session, sweep_id, requested_by) -> Sweep`

- [ ] **Step 1: Write failing transition tests**

Cover these behaviors with an async database fixture:

```python
async def test_claim_moves_queued_sweep_to_running_and_sets_lease(...):
    claimed = await claim_sweep(session, sweep.id, "worker-a", 60)
    assert claimed.status == CampaignStatus.RUNNING
    assert claimed.lease_owner == "worker-a"
    assert claimed.started_at is not None

async def test_second_worker_cannot_claim_an_active_lease(...):
    await claim_sweep(session, sweep.id, "worker-a", 60)
    with pytest.raises(SweepStateConflict):
        await claim_sweep(session, sweep.id, "worker-b", 60)
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
.venv\bin\python.exe -m pytest tests/test_sweep_state.py -q
```

Expected: FAIL because the service and exception do not exist.

- [ ] **Step 3: Implement guarded state transitions**

Use a single transaction per operation. `claim_sweep` may claim only `queued` sweeps or sweeps whose lease has expired. `heartbeat_sweep`, `complete_sweep`, and `fail_sweep` must verify the lease owner. Terminal sweeps cannot be claimed or completed again. `cancel_sweep` must prevent future work and set a terminal cancellation detail. `retry_sweep` must increment `attempt`, clear transient execution fields, and generate a new idempotency key.

- [ ] **Step 4: Add append-only step helpers**

Add `record_step_started` and `record_step_finished` helpers that create/update one `SweepStep` without deleting prior steps. Duplicate `(sweep_id, idempotency_key)` operations must return the existing step rather than insert a duplicate.

- [ ] **Step 5: Run tests and verify green**

Run:

```powershell
.venv\bin\python.exe -m pytest tests/test_sweep_state.py -q
```

Expected: PASS with no unrelated test failures.

- [ ] **Step 6: Commit the state service**

```powershell
git add backend/app/services backend/tests/test_sweep_state.py
git commit -m "feat: add transactional sweep state service"
```

### Task 3: Add the Redis queue boundary

**Files:**
- Create: `backend/app/services/queue.py`
- Modify: `backend/app/config.py`
- Modify: `backend/tests/test_queue.py`

**Interfaces:**
- `class SweepQueue(Protocol): async def enqueue(self, job: SweepJob) -> None`
- `class SweepJob(TypedDict): sweep_id: str; org_id: str; attempt: int; enqueued_at: str`
- `class RedisSweepQueue`: serializes jobs to `asclepius:sweeps`.

- [ ] **Step 1: Write failing queue contract tests**

Use a fake Redis client implementing `rpush` and assert the exact JSON payload and queue name:

```python
async def test_enqueue_writes_rebuildable_sweep_job():
    redis = FakeRedis()
    await RedisSweepQueue(redis, "asclepius:sweeps").enqueue(job)
    assert json.loads(redis.items[0]) == job
```

- [ ] **Step 2: Run the test and verify it fails**

```powershell
.venv\bin\python.exe -m pytest tests/test_queue.py -q
```

Expected: FAIL because the queue implementation does not exist.

- [ ] **Step 3: Implement serialization and configuration**

Add queue name, lease seconds, retry limit, and enqueue timeout settings with development-safe defaults. The queue adapter must not contain database logic and must raise a typed `QueueUnavailable` error when Redis is unreachable.

- [ ] **Step 4: Run queue tests and verify green**

```powershell
.venv\bin\python.exe -m pytest tests/test_queue.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the queue boundary**

```powershell
git add backend/app/services/queue.py backend/app/config.py backend/tests/test_queue.py
git commit -m "feat: add Redis sweep queue boundary"
```

### Task 4: Enqueue campaigns without blocking the API

**Files:**
- Modify: `backend/app/api/campaigns.py`
- Modify: `backend/app/core/deps.py` or add a service dependency module
- Create: `backend/tests/test_campaign_launch.py`

**Interfaces:**
- `POST /campaigns` continues returning `CampaignCreated` with `sweepId`.
- The handler accepts a `SweepQueue` dependency and enqueues `{sweep_id, org_id, attempt}` only after the database transaction commits.

- [ ] **Step 1: Write failing API tests**

Test that a valid campaign creates a queued sweep and calls the fake queue once, while a queue failure returns a clear server error and does not claim the sweep as running. Test target/org isolation and invalid category/variant validation.

- [ ] **Step 2: Run the tests and verify they fail**

```powershell
.venv\bin\python.exe -m pytest tests/test_campaign_launch.py -q
```

Expected: FAIL because the route does not depend on a queue.

- [ ] **Step 3: Wire queue enqueue after commit**

Preserve the current campaign and sweep transaction. After commit and refresh, enqueue the job. If enqueue fails, return an explicit enqueue error and leave the sweep queued for a recovery/reconciliation command; do not falsely report it as running.

- [ ] **Step 4: Run API tests and verify green**

```powershell
.venv\bin\python.exe -m pytest tests/test_campaign_launch.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit campaign enqueue integration**

```powershell
git add backend/app/api/campaigns.py backend/app/core/deps.py backend/tests/test_campaign_launch.py
git commit -m "feat: enqueue sweep jobs after campaign creation"
```

### Task 5: Expose cancellation, retry, and failure metadata

**Files:**
- Modify: `backend/app/api/sweeps.py`
- Modify: `backend/app/schemas.py`
- Create: `backend/tests/test_sweep_api.py`

**Interfaces:**
- `POST /sweeps/{sweep_id}/cancel` returns `SweepOut`.
- `POST /sweeps/{sweep_id}/retry` returns `SweepOut` and enqueues a new attempt.
- `GET /sweeps/{sweep_id}` includes status, attempt, failure, lease heartbeat, and terminal timestamps.

- [ ] **Step 1: Write failing endpoint tests**

Cover successful cancellation, retry of a failed sweep, rejection of retry on a running sweep, and tenant isolation. Assert that responses contain the new lifecycle fields.

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
.venv\bin\python.exe -m pytest tests/test_sweep_api.py -q
```

Expected: FAIL because the endpoints and response fields are absent.

- [ ] **Step 3: Implement endpoints through the state service**

Do not mutate status directly inside routers. Resolve the sweep within the current organization, call the state service, enqueue retries through `SweepQueue`, and return the refreshed representation.

- [ ] **Step 4: Run focused and existing backend tests**

```powershell
.venv\bin\python.exe -m pytest tests/test_sweep_api.py tests/test_health.py tests/test_security.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit lifecycle endpoints**

```powershell
git add backend/app/api/sweeps.py backend/app/schemas.py backend/tests/test_sweep_api.py
git commit -m "feat: add sweep cancellation and retry APIs"
```

### Task 6: Create and apply the database migration

**Files:**
- Create: `backend/alembic/versions/20260729_add_sweep_lifecycle.py`
- Modify: `backend/tests/test_sweep_state.py`

- [ ] **Step 1: Write a migration compatibility test**

Verify a database containing the current initial schema can upgrade and that existing seeded-style rows receive valid defaults without changing their status or step data.

- [ ] **Step 2: Run the migration test and verify it fails**

```powershell
.venv\bin\python.exe -m pytest tests/test_sweep_state.py -q
```

Expected: FAIL until the revision exists and fields are present in the database.

- [ ] **Step 3: Generate or write the Alembic revision**

Add nullable timestamp/text/lease fields, integer attempt defaulting to `1`, idempotency key, and indexes needed for queued/lease-expiry lookup. The downgrade must remove only these new columns/indexes.

- [ ] **Step 4: Apply and inspect the migration**

Run from `backend` against the development Postgres container:

```powershell
.venv\bin\python.exe -m alembic upgrade head
.venv\bin\python.exe -m alembic current
```

Expected: the new revision is current and existing API health remains 200.

- [ ] **Step 5: Run the full backend test suite**

```powershell
.venv\bin\python.exe -m pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit the migration**

```powershell
git add backend/alembic/versions backend/tests/test_sweep_state.py
git commit -m "feat: migrate sweep execution lifecycle fields"
```

### Task 7: Architecture foundation verification checkpoint

**Files:**
- Modify: `backend/README.md`
- Modify: `README.md`
- Create: `backend/tests/test_architecture_smoke.py`

- [ ] **Step 1: Write the smoke test**

Create a fake queue and fake worker claim flow that proves: campaign launch creates a queued sweep, the queue receives a rebuildable job, a worker can claim it, and the sweep response exposes running metadata without invoking an external model or target.

- [ ] **Step 2: Run the smoke test and verify it fails before the complete integration**

```powershell
.venv\bin\python.exe -m pytest tests/test_architecture_smoke.py -q
```

Expected: FAIL until Tasks 1–5 are integrated.

- [ ] **Step 3: Implement only the test harness wiring needed for the smoke path**

Use fake queue/state dependencies; do not introduce provider calls or agent logic in this architecture plan.

- [ ] **Step 4: Run all backend tests and lint**

```powershell
.venv\bin\python.exe -m pytest -q
.venv\bin\python.exe -m ruff check app tests
```

Expected: both commands exit 0.

- [ ] **Step 5: Update documentation to match the new foundation**

Document the actual commands for migrations, API startup, queue configuration, and the fact that agent execution is supplied by the later target/agent/worker specs. Do not claim full agent execution until those specs are implemented.

- [ ] **Step 6: Commit the checkpoint**

```powershell
git add backend/README.md README.md backend/tests/test_architecture_smoke.py
git commit -m "docs: document executable sweep architecture foundation"
```

## Spec coverage self-review

- Durable lifecycle fields and state transitions: Tasks 1–2 and 6.
- Redis as transport, Postgres as system of record: Task 3 and Task 4.
- Fast non-blocking campaign creation: Task 4.
- Cancellation, retry, and failure visibility: Task 5.
- Seed compatibility and tenant isolation: Tasks 1, 4, 5, and 6.
- Safety constraints and bounded execution: configuration contracts in Tasks 3–5; target/agent limits are implemented by later specs.
- Real worker execution and frontend live progress: intentionally deferred to the worker and frontend specs; Task 7 verifies the shared contract without pretending those components exist.
