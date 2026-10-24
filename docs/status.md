# Implementation Status

Implementation checkpoint on 2026-10-23 America/Chicago, branch `codex/cli-evaluator`.

Tasks 1 through 4 implement CLI management, SQLite history, and manual detached daemon
control. Real ready-daemon submission accepts supplied plans into the queue. The daemon
does not claim or execute them and reports `execution_available: false`. Budget components
now connect to the Groq target adapter and evaluator gateway. Task 5 implements these
provider components, with independent credentials, strict output validation, and retained
request/reply evidence. Task 6 adds the bundled `broad-chat-v1` pack, four typed agent
roles, offline check listing, and pack submission. The coordinator remains unimplemented.

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
| Daemon control | `backend/asclepius/process.py`, `daemon.py` | Manual detached start, generation-bound readiness, heartbeat, duplicate exclusion, drain/stop. Leaves queued runs untouched. |
| Bounds | `backend/asclepius/limits.py` | Shared request gates/rates and durable call/completion reservations, connected to provider components. Cancellation before dispatch releases allowance; uncertain dispatch retains it. |
| Provider components | `backend/asclepius/transport.py`, `adapters/chat.py`, `models.py` | Bounded HTTPS, independent credentials, redacted immutable requests, strict evaluator schemas, typed errors and validated retry timing. No automatic retries or queued execution. |
| Checks and agents | `backend/asclepius/checks.py`, `agents.py`, `packs/`, `prompts/` | Twenty pinned checks, three generated attacks and one code-owned control per check. Four role contracts require an injected prepared-request dispatch. No queued execution. |
| Local migrations | `backend/asclepius/maintenance.py`, `migrations/` | New schema v2 and explicit stopped v1 upgrade, OS/maintenance locking, rollback, and local-only path policy. |
| API | `backend/app/api/` | Auth, target, campaign, sweep, finding, review, summary, and health routes. |
| Data | `backend/app/models/`, `backend/app/db.py` | Organization-scoped Postgres records through async SQLAlchemy. |
| Migrations | `backend/alembic/` | Inherited Postgres revisions; current database revision is not verified. |
| Fixtures | `backend/app/seed.py` | Resets domain data and inserts simulated records. |
| Infrastructure | `backend/docker-compose.yml` | Postgres and Redis containers; Redis is unused by execution. |
| Tests | `backend/tests/` | Real HTTP/HTTPS provider fixtures, SQLite persistence and budgets, process checks, and legacy API cases. See the [Task 6 results](verification/evidence/cli-agents.json). Native Windows skips the WSL-only mount test. |

Campaign creation stores queued records and returns an identifier. Nothing dispatches
them to a worker or sends evaluation requests to a target.

The existing API calls runs `sweeps` and stores `campaigns`; those identifiers describe
current code. The [backend design](specs/backend-design.md) defines their replacement
with profile/run domain records and a separate execution coordinator.
API authentication is also current code, not a requirement for the personal CLI.

## Missing product capabilities

There is no execution coordinator, comparison engine, or report/chart generator.
Hosted Groq responses and semantic judgment accuracy remain unverified.
Legacy plans remain readable and can queue, but the role runner requires three strategies
per check. Legacy judgments without check lineage cannot initiate Reporter. JSON-schema
violation findings require the entire reply as evidence within the 4096-byte quote cap.
Execution recovery remains a later task; the current control loop does not interrupt old
owned runs or dispatch queued work. Task 5 verifies component behavior against loopback
providers, including installed wheels. It does not establish a working evaluation pipeline.
Submission's fresh-heartbeat gate permits up to ten seconds of queued acceptance after a
hard crash; OS-liveness probes protect status/start, not the enqueue transaction.
Physical terminal-close acceptance remains pending. One native creator-exit test failed
during review, then passed reruns and ten extra probes; its cause remains unresolved.

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
