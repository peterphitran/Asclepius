# CLI Evaluator Implementation Plan

> **For agentic workers:** The user selected installed pstack skills for implementation. Follow poteto-mode and its Codex mapping, keep a decision trail, and verify each task before starting the next. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a general-purpose CLI LLM evaluator with a real Groq-backed broad attack pack, durable background execution, comparisons, and local reports; then validate Ollama through the same core.

**Architecture:** Add an application-neutral `asclepius` Python package alongside the existing API. CLI and one manually started daemon share application services and SQLite; a coordinator controls four role contracts, target adapters, persistence, and budgets. Retire legacy runtime dependencies only after replacement proofs and review of existing local changes.

**Tech Stack:** Python >=3.12; standard-library argparse, asyncio, sqlite3, tomllib, subprocess, and HTML/SVG rendering; Pydantic v2 contracts; HTTPX asynchronous transport; portalocker file locks; pytest and Ruff. Resolve and lock exact compatible versions during Task 1, not by guessing package versions here.

**Spec:** [Backend design](../specs/backend-design.md), [pipeline](../specs/evaluation-pipeline.md), [product](../product.md), [feature map](../features/README.md). [RAG design](../specs/rag-testing.md) is a later capability milestone, not implemented by this plan.

Status: implementation started on `codex/cli-evaluator`. Tasks 1 through 5 are verified in
[the foundation evidence](../verification/evidence/cli-foundation.json) and
[the storage evidence](../verification/evidence/cli-storage.json), and
[the management evidence](../verification/evidence/cli-management.json), and
[the daemon evidence](../verification/evidence/cli-daemon.json), and
[the Groq component evidence](../verification/evidence/cli-groq-components.json). Tasks 6 through 12 remain pending.
Task 4 verifies control and budget components, not queued execution or physical terminal closure.

## Global Constraints

- Python 3.12 or newer. Preserve the existing Linux `.venv`; use WSL for it.
- Local CLI; no Asclepius login, hosted API, Redis broker, or Postgres for the new runtime.
- Manually started detached daemon; no operating-system autostart or implicit daemon start.
- One daemon per canonical data directory; several CLI clients; local SQLite WAL, not a network share.
- Separate Selector, Generator, Judge, and Reporter responsibilities; workers are execution capacity.
- Groq first for independently configured target/evaluator roles; Ollama second; RAGbot afterward.
- Broad initial coverage, capability validation, immutable snapshots, bounded requests, and retained errors.
- Completed does not mean secure. Retry is a linked new run, not in-place resume or exact replay.
- Preserve unrelated local changes, existing databases, and frontend backup. No pushes or PRs.
- Windows and WSL require separate data directories and separate terminal-close proofs.

## Review Focus

1. A credential disappears after submission: fail that run clearly without identity fallback; test in Tasks 3 and 7.
2. Two profiles alias one destination: enforce shared bounds despite different names; test in Tasks 4 and 7.
3. Crash after external response but before commit: preserve unknown outcome, never auto-replay; test in Tasks 2 and 8.
4. Malicious target text attacks Judge or local rendering: no instruction authority, invented evidence, terminal escapes, or active HTML; test in Tasks 6 and 9.
5. A profile/check changes while work waits: execute pinned inputs and label remote/model uncertainty; test in Tasks 3, 7, and 9.

## Scope, deliverables, and transition

**M1 (Tasks 1–10):** complete hosted evaluation product, including broad coverage and local charts.
**M2 (Task 11):** Ollama target integration with the same lifecycle/results.
**Transition (Task 12):** remove obsolete runtime only after M1 acceptance and explicit disposition of local edits.
**M3 (separate plan):** inspect RAGbot's actual API, then implement ingestion/retrieval/readiness, corpus isolation, actor-specific access checks, and cleanup under the RAG design. Do not create a speculative RAGbot connector here.

This is one dependent implementation chain, not several parallel scaffolding projects.
Intermediate tasks have testable deliverables; only M1's final gate establishes the user workflow.

Planning baseline: `backend/app/` is FastAPI/Postgres; `app/services/sweep_state.py` and its tests
contain useful transition cases, but reclaim/retry behavior differs from this design.
Do not import those ORM types or translate row locks into the new scheduler.
At that baseline, `backend/pyproject.toml` packaged only `app` and had no CLI entry point.
Tasks 1 through 3 add the new package, entry point, repository, and management commands;
there was no existing execution engine to extend.

Before execution, inventory `git status --short` and preserve the current dirty work through
a reviewed checkpoint/patch handoff before creating an isolated execution worktree. A worktree
from HEAD alone omits the current design files and local backend work. Never reset or blindly
stage that work. Task commits contain only the implementer's changes; publication is not implied.

## Proposed defaults for review

These are concrete builder recommendations, not newly agreed product requirements.

| Area | Proposed initial value/policy |
| --- | --- |
| Target | Groq `openai/gpt-oss-20b`, temperature 0, maximum 512 completion tokens. |
| Evaluator | Groq `openai/gpt-oss-120b` for all four roles initially, temperature 0, maximum 2048 completion tokens; independently override each role. |
| Credentials | Environment references only initially: `env:GROQ_API_KEY`; never values in arguments, config, snapshots, logs, or exports. Daemon inherits environment at manual start. |
| Data exposure | Synthetic check content only in M1; no automatic local-file ingestion or real secret probes. |
| Pack | 5 families × 4 checks; 3 attack variants and 1 benign control per check: 80 target calls, not 80 separate runs. |
| Runs/calls | 1 active run by default, configurable; global outbound concurrency 4, target-resource concurrency 2, evaluator concurrency 2. Shared account/resource limits also apply. |
| Request budgets | Per run: at most 100 target calls, 220 evaluator calls, and 300 combined calls. Count every dispatched attempt, including failures. |
| Rate | 10 combined requests/minute per Groq credential reference by default; configurable to the account's actual limits. Cancellation remains responsive while waiting. |
| Time | Total request deadline 60 seconds; run execution deadline 45 minutes from claim; startup wait 15 seconds; stop command waits 15 seconds then reports draining, never silently kills. |
| Size/usage | Target input 16 KiB, evaluator input 64 KiB, response body 1 MiB; per-run 500,000 reserved maximum completion tokens. Record actual provider usage separately. |
| Persistence | SQLite busy timeout 5 seconds; daemon poll 250 ms; heartbeat 2 seconds, readiness stale after 10 seconds. OS lock remains ownership authority. |
| Output | Versioned JSON, readable Markdown, self-contained HTML with inline SVG outcome/comparison charts; no CDN or external scripts. |
| Retention | No automatic purge; existing export fails unless `--overwrite` is explicit. |

Models are proposed examples verified against [Groq's model list](https://console.groq.com/docs/models).
The evaluator models above support strict schema outputs according to [Groq's structured-output docs](https://console.groq.com/docs/structured-outputs).
Revalidate models/account access during implementation and live acceptance; do not substitute silently.
Reasoning-model completion limits can truncate output: preserve finish reason and return a typed
incomplete-output error rather than fabricate a judgment. Tune limits only through visible config.

Completion reservations are enforced before dispatch and retained for uncertain calls. Input bytes
are bounded separately. Provider-reported total tokens and estimated cost are informational, not
a guaranteed dollar ceiling. Provider spend controls remain separate; never advertise a hard cost
cap from guessed token counts or a missing price table. No automatic network retries in M1,
including 429/5xx; expose status/retry-after and allow explicit linked-run retry.
Use a conservative normalized provider-origin bucket across target/evaluator calls in
addition to credential-reference limits. Target resource bounds derive from normalized
adapter/base URL; an optional resource key may merge targets, never split an existing
destination bucket. Profile aliases or different references to one key cannot bypass
the origin limit. More precise independent-account scheduling can follow after M1.

The baseline has 1 Selector + 20 Generator + 80 Judge + at most 80 Reporter calls = at most
181 evaluator calls and 80 target calls. Reporter may record anomalous controls too; do not
assume only attacks can produce findings. Invalid role output fails visibly with no hidden repair calls.
Worst-case baseline completion reservations are 80 × 512 + 181 × 2048 = 411,648 tokens,
within the proposed 500,000-token reservation ceiling. This is not expected actual usage.

### CLI and configuration contract

Proposed commands, not currently runnable:

```text
asclepius --data-dir <dir> init
asclepius storage migrate
asclepius config validate <config.toml>
asclepius targets add groq-target --config <config.toml>
asclepius targets list|show|edit|remove ...
asclepius daemon start|status|stop
asclepius checks list --pack broad-chat-v1
asclepius run groq-target --pack broad-chat-v1 --evaluator <evaluator.toml>
asclepius runs list|show|watch|cancel|retry <run-id>
asclepius findings list --run <run-id>
asclepius findings show <finding-id>
asclepius compare <run-a> <run-b>
asclepius report <run-id> --format json|markdown|html --output <path>
asclepius compare <run-a> <run-b> --format html --output <path>
```

Group syntax above abbreviates separate commands, not literal shell pipe expressions.
Global `--json` emits one versioned JSON envelope (watch: newline-delimited events).
Exit codes: 0 command success; 2 bad input/configuration; 3 missing resource; 4 daemon
unavailable; 5 execution/storage/export error. Run submission success means accepted,
not secure/completed. `runs watch` is read-only; Ctrl+C exits 130 without cancelling the run.

TOML schema v1 has `[target]` adapter/model/base_url/secret_ref/system_prompt/resource_key,
`[limits]` numeric overrides, and separate evaluator TOML `[roles.selector]`,
`[roles.generator]`, `[roles.judge]`, `[roles.reporter]` provider/model/base_url/secret_ref/
temperature/max_completion_tokens. Defaults are materialized before snapshotting.
Reject unknown fields, nonpositive limits, credential literals, URL userinfo/query secrets,
and malformed references. Hosted URLs require HTTPS; loopback HTTP is allowed only for
local adapters/fixtures. Redirects disabled. Initial protocol uses explicit chat message
arrays and `choices[0].message.content`; no expression/template language or arbitrary code.
Custom HTTP mapping is a later adapter extension, not a half-implemented universal parser.

## File ownership and interfaces

All new runtime files below are under `backend/asclepius/`; all new tests are under
`backend/tests/cli/`. Create package `__init__.py` files with their first owning task.
No new package imports `app`, FastAPI, or Postgres settings.

| Files | Responsibility |
| --- | --- |
| `domain.py`, `config.py` | Versioned Pydantic domain/operation contracts, state transitions, TOML and limits. |
| `storage.py`, `migrations/001_initial.sql` | SQLite transactions, schema constraints, snapshots, event reads. |
| `services.py` | Profile CRUD, submission, cancellation/retry, inspection. |
| `cli.py`, `__main__.py` | argparse commands, output/exit handling, console entry point. |
| `process.py`, `daemon.py`, `limits.py` | Locks/paths/detachment, instance lifecycle, scheduling and reservations. |
| `transport.py`, `adapters/chat.py`, `models.py` | Bounded HTTP, Groq target adapter, evaluator gateway. |
| `checks.py`, `packs/broad_chat_v1.json` | Validated built-in check pack, objectives, rubrics and controls. |
| `agents.py`, `prompts/*.txt`, `coordinator.py` | Four structured roles, evidence validation, persisted orchestration. |
| `results.py`, `exports.py` | Comparison queries, safe terminal text, JSON/Markdown/HTML/SVG output. |
| `adapters/ollama.py` | Local model target normalization after M1. |

Core signatures below are the shared interface contract; Task 1 defines their referenced
Pydantic types. `Repository` owns short operations, each opening/closing its connection
inside `asyncio.to_thread`; no connection crosses threads. Pure config/domain/export functions
are synchronous. Do not introduce a DB thread that blocks the daemon's event loop.

## Implementation tasks

### Task 1: Installable CLI, configuration, and domain boundary

Verified on WSL and Windows. See [Task 1 evidence](../verification/evidence/cli-foundation.json).

**Files:** Create `backend/asclepius/{__init__,__main__,cli,config,domain}.py`,
`backend/tests/cli/{__init__,test_config,test_domain,test_cli_help}.py`,
`backend/examples/{groq-target,groq-evaluator}.toml`,
`backend/requirements-cli-{wsl,windows}.lock` (generate on their respective platforms).
Modify `backend/pyproject.toml`, `backend/.gitignore` only for owned packaging/ignore changes.

**Interfaces:** `load_target(path: Path) -> ProfileConfig`, `load_evaluator(path: Path) -> EvaluatorConfig`,
`main(argv: list[str] | None = None) -> int`. Define UUID string identities, UTC timestamps,
`RunState`, `ProfileConfig`, `EvaluatorConfig`, `Limits`, `CheckDefinition`, `Selection`,
`Variant`, `OperationRequest`, `Observation`, `Judgment`, `Finding`, `StageOutput`, `RunSnapshot`,
`DaemonStatus`, `BudgetReservation`, `RunView`, `Comparison`, `ExportArtifact`, and `AppError`.
Envelope requires schema version, operation kind, IDs, timing, status, uncertainty, and
typed payload. Initially register `chat.v1`; unsupported operation kinds fail explicitly.
Judgment contains diagnostic assertions, optional security verdict, and evidence references.

- [x] Write tests `test_target_and_evaluator_are_independent`, `test_reject_secret_literal`,
  `test_reject_unknown_fields`, `test_non_rag_observation_needs_no_corpus`, and
  `test_terminal_states_cannot_transition_to_queued`; assert sample TOML resolves defaults,
  `secret_ref == "env:GROQ_API_KEY"`, and no secret value is serialized.
- [x] Run `python -m pytest tests/cli/test_config.py tests/cli/test_domain.py tests/cli/test_cli_help.py -q` from `backend/`; expect missing-package/function failures before implementation.
- [x] Implement the contracts/parser/help. Add console script `asclepius = "asclepius.cli:main"`,
  package both `app` and `asclepius`, include pack/prompt/SQL resources in built wheels,
  update clinical-only package description, and declare direct CLI dependencies. Keep old
  dependencies for now. Add pip-tools to dev tooling; from `backend/` use
  `python -m piptools compile --extra dev --generate-hashes --output-file requirements-cli-wsl.lock pyproject.toml`
  on WSL and the corresponding `requirements-cli-windows.lock` output on Windows.
  Record Python/resolver versions and install each platform's hashed lock into disposable
  verification environments before the editable project. Never capture private index credentials.
- [x] Run focused tests, install editable into an isolated disposable environment, then
  `asclepius --help` and `python -m asclepius --help`; expect exit 0 and matching command groups.
- [x] Commit only Task 1 paths: `feat: define CLI contracts and configuration`.

### Task 2: SQLite history, claims, and durable identities

**Files:** Create `backend/asclepius/storage.py`, `backend/asclepius/migrations/001_initial.sql`,
`backend/tests/cli/test_storage.py`, `backend/tests/cli/test_storage_processes.py`.

**Interfaces:** `Repository(data_dir: Path)` exposes async `initialize() -> None`,
`claim_next(instance_id: str) -> RunSnapshot | None`,
`commit_stage(run_id: str, work_item_id: str, stage: str, output: StageOutput, *, instance_id: str) -> StageOutput`,
`begin_operation(request: OperationRequest, *, instance_id: str) -> OperationIntent`,
`save_observation(observation: Observation, *, instance_id: str) -> None`,
`events(run_id: str, after: int = 0) -> list[dict]`, `read_run(run_id: str) -> RunView`,
`interrupt_orphans(instance_id: str) -> list[str]`, and
`finalize(run_id: str, state: RunState, reason: str | None, *, instance_id: str) -> None`.

Storage also supplies `save_profile(config: ProfileConfig, *, profile_id: str | None = None) -> str`,
`enqueue(snapshot: RunSnapshot) -> str`, `set_ready(instance_id: str) -> None`, and
`register_work_item(run_id: str, work_item_id: str, check_id: str, variant_id: str | None = None, *, instance_id: str) -> None`.
Omitting `profile_id` creates a profile and rejects duplicate names; supplying it explicitly
edits the existing active identity, including a unique rename. Identical edits do not bump revision.
These are persistence primitives, not public CLI services or proof of OS daemon ownership.
New mutations fence against the current daemon and run owner inside their write transaction.
Exact committed repeats may return saved content without mutation after terminalization.
`OperationIntent.created` grants dispatch eligibility only when true; repeated pending,
observed, or unknown intents never authorize another request. The coordinator must still
check cancellation, ownership, and budgets before dispatch.

- [x] Write real temporary SQLite tests asserting foreign keys, schema rejection, rollback,
  immutable snapshots, monotonic per-run event ordering, and identical stage re-commit returns
  the saved value while conflicting content raises `AppError`. Unique stage identity:
  `(run_id, work_item_id, stage)` for committed output; attempts remain separate audit records.
- [x] Add two-process tests: two claimants cannot claim the same queued run; held write
  contention returns a bounded busy error. Test an operation intent without a saved reply
  becomes unknown on orphan recovery, without deleting prior evidence or replaying a request.
- [x] Run `python -m pytest tests/cli/test_storage.py tests/cli/test_storage_processes.py -q`; expect failure before implementation.
- [x] Implement version table, profiles, runs, work_items, stages, operations, observations,
  judgments, findings, events, daemon_control, and budget reservations. Use FKs/unique
  constraints (including finding run/variant), parameterized SQL, WAL, busy timeout, and
  `BEGIN IMMEDIATE` for conditional claims/state changes. Persist output+event atomically.
  Profile removal is a tombstone; referenced history is not cascade-deleted.
- [x] Run focused tests again; expect pass using real SQLite, not fake sessions.
- [x] Commit Task 2 paths: `feat: persist local runs and atomic claims`.

### Task 3: Profiles, submission, inspection, and linked retries

**Files:** Create `backend/asclepius/services.py`, `backend/tests/cli/test_services.py`,
`backend/tests/cli/test_cli_profiles.py`. Extend `storage.py`, `cli.py`, `config.py`.

**Interfaces:** `EvaluationService(repo: Repository)` exposes async
`save_profile(config: ProfileConfig, *, profile_id: str | None = None) -> str`,
`submit(profile: str, evaluator: EvaluatorConfig, checks: tuple[CheckDefinition, ...], *, prompts: tuple[PromptSnapshot, ...]) -> str`,
`cancel(run_id: str) -> RunView`, `retry(run_id: str) -> str`.
Repository extends the Task 2 profile/enqueue primitives and adds async
`list_profiles(*, limit: int = 50, cursor: str | None = None) -> Page[ProfileRecord]`,
`get_profile(identity: str | UUID) -> ProfileRecord`, `remove_profile(identity: str) -> str`,
`request_cancel(run_id: str) -> RunView`,
`list_runs(*, profile_id: str | None = None, limit: int = 50, cursor: str | None = None) -> Page[RunSummary]`,
`list_findings(run_id: str, *, limit: int = 50, cursor: str | None = None) -> Page[Finding]`,
`read_finding(finding_id: str) -> Finding`.
`enqueue` checks daemon acceptance and inserts the snapshot/event in the same transaction.

Grounding review accepted these refinements before implementation. `ProfileRecord` retains
stable identity and revision. Pages use ascending UUID keyset ordering, fetch one extra row,
and return the last emitted ID as `next_cursor` only when more rows exist. They are live queries,
not snapshot-isolated browsing sessions. `runs list --profile` takes a stable profile ID and
continues to work after removal. String profile selectors reject ambiguous ID/name matches.
Known internal profile UUID values resolve by exact ID, never by another profile's name.
Removal resolves its selector, writes the tombstone, and returns the affected ID in one
transaction. The CLI does not resolve a mutable name twice.

CLI submission accepts `--plan <plan.json>` with a strict versioned `SubmissionPlan` of
full checks and exactly one nonblank prompt per role. It has no caller-assigned run identity.
The service pins these inputs without inventing a registry or prompts. `--pack` explicitly
fails until Task 6 provides the real built-in pack. The future pack loader feeds the same service.
Retry requires the original stable profile to remain active, pins the source configuration,
and rechecks credentials and complete plan contents. Tombstoning a profile revokes new
submissions/retries without changing accepted runs or history. Active cancellation records
intent only until the coordinator exists. Queued cancellation completes transactionally.
Task 3 exposes `init` and selects the OS data-directory default so its CLI can be used.
Task 4 still owns process lifetime locks, network-store rejection, and migration commands.

- [x] Write tests that two profiles retain distinct IDs; duplicate names fail; editing/removing
  a profile leaves history intact; stopped daemon yields exit 4 and zero inserted runs;
  unsupported requested checks yield exit 2 before requests. Supply controlled readiness in
  service tests only; do not count it as proof of a real daemon.
- [x] Test cancellation of queued work, cancellation request for running work, terminal-state
  rejection, and retry from failed/cancelled/interrupted returns a different ID with unchanged
  source snapshot. Missing credentials fail without fallback; never print their values.
- [x] Run `python -m pytest tests/cli/test_services.py tests/cli/test_cli_profiles.py -q`; expect failures.
- [x] Implement service commands, materialized snapshots of full check definitions/prompt
  versions, and CLI reads. Secret references are validated here and resolved again by the
  executing daemon. Reading history and profiles works while stopped. List pagination uses
  default 50/max 500 and an explicit next cursor; unknown IDs return exit 3.
- [x] Repeat tests, including two subprocess CLI clients against one temporary directory;
  expect matching persisted profile/run IDs and no implicit process launch.
- [x] Commit owned Task 3 changes: `feat: manage profiles and queued evaluations`.

### Task 4: Manual daemon, OS ownership, and outbound budgets

**Files:** Create `backend/asclepius/{process,daemon,limits}.py`,
`backend/asclepius/{maintenance,paths}.py`, `migrations/002_daemon_pid.sql`,
`backend/tests/cli/{test_daemon_process,test_limits,test_maintenance}.py`, and
`backend/scripts/verify_daemon.py`; extend storage/CLI.

**Interfaces:** Sync `start_daemon(data_dir: Path, *, timeout: float = 15) -> DaemonStatus`,
`daemon_status(data_dir: Path) -> DaemonStatus`, `stop_daemon(data_dir: Path, *, timeout: float = 15) -> DaemonStatus`,
and `migrate_storage(data_dir: Path, *, timeout: float = 5) -> int`.
Async `serve(data_dir: Path, *, instance_id: str) -> None` receives the parent-generated UUID.
`BudgetManager(repo, instance_id, *, limits: Limits | None = None)` exposes async
`reserve(run_id: str, kind: str, max_output: int) -> BudgetReservation`, `dispatch`, `settle`, `release`,
and `slot(snapshot: RunSnapshot, kind: Kind, *, role: str | None = None)` / `run_slot(snapshot)` context managers.
Repository extends Task 2 readiness persistence and adds async `control() -> DaemonStatus`,
`heartbeat(instance_id: str) -> None`, `request_stop(instance_id: str) -> None`,
`set_stopped(instance_id: str) -> None`, `active_count(instance_id: str) -> int`,
`drain_operations() -> None`, `execution_checkpoint`, `reserve_budget`, and `change_reservation`.

Grounding and independent review accepted these refinements. PID is added by an explicit
v1-to-v2 migration; new initialization applies both SQL revisions transactionally. Maintenance
owns schema changes directly under exclusive locks rather than reentering repository locks.
Daemon startup holds instance EX, maintenance SH, and a generation-specific readiness lock.
Public responsiveness requires that same UUID's readiness lease and fresh heartbeat, so a new
owner blocked on SQLite cannot borrow an old ready record. Status probes locks only after
releasing its repository read transaction. Lock files remain; their existence is not ownership.

The loop deliberately never claims queued work or calls interruption recovery yet.
It reports `execution_available: false`. Tasks 7/8 add execution and restart recovery.
Task 5/7 must inject one shared manager into all transports/workers. Slots derive destination
and origin from HTTPX-normalized wire URLs, including host/default-port/trailing-dot normalization.
Explicit resource keys may add grouping but never replace the destination gate.
Rate buckets apply independently to normalized origin and credential reference across origins.
Reservations count reserved/dispatched/settled against caps; only unused reserved work can
release allowance. Exhaustion commits a reason/event and prevents successful finalization.
Repeated cancellation is deferred until outstanding database workers finish before locks release.
Cleanup is explicitly unsupported until a separate cap exists; evaluation allowance is not reused.
Physical terminal-close acceptance remains Task 10. Retain the recorded one-off native
creator-exit failure even though reruns and ten extra reviewer probes passed.
Final trail review clarified the existing submission contract: enqueue gates on persisted
ready state and a heartbeat up to ten seconds old, not the OS readiness lease. A hard crash
can leave a bounded queued-acceptance window; accepted work waits for manual restart.
Generation leases protect status/start. Do not claim immediate crash detection for enqueue.

- [x] Write process tests for duplicate start, stale PID/heartbeat, readiness only after lock/schema,
  start failure diagnostics, stop timeout without kill, and stopped-daemon reads. Test aliases
  sharing a target resource and shared provider key cannot evade limits. Start with tiny
  test-only limits; measure observed concurrent fixture calls, not only semaphore counters.
- [x] Test maintenance lock contention: daemon holds shared maintenance access, every CLI DB
  operation acquires shared access, migrations require exclusive access with daemon stopped.
  Lock order for startup/migration: instance lock, then maintenance lock; ordinary CLI DB
  operations never acquire the instance lock while holding maintenance access.
  Await outstanding repository thread operations before releasing lifetime locks: cancelling
  an awaiting coroutine does not stop its underlying `asyncio.to_thread` database operation.
- [x] Run `python -m pytest tests/cli/test_daemon_process.py tests/cli/test_limits.py tests/cli/test_maintenance.py -q`; expect failures.
- [x] Implement portalocker lifetime instance lock and maintenance locks. Canonicalize paths;
  default Windows `%LOCALAPPDATA%/Asclepius`, WSL/Linux `$XDG_DATA_HOME/asclepius` or
  `~/.local/share/asclepius`; never share Windows/WSL state. Reject network-store configuration.
  Launch using `sys.executable`, argument arrays, no shell; POSIX `start_new_session=True`,
  Windows `DETACHED_PROCESS` with redirected streams and no visible console. PID reuse is
  not an ownership mechanism. Start waits for this child's fresh instance ID, not stale ready data.
  `init` initializes only new stores; `storage migrate` acquires exclusive instance and
  maintenance locks before applying versioned upgrades. Never auto-upgrade on an ordinary read.
- [x] Implement durable readiness/drain plus reservations and cancellation-aware rate waits.
  Keep control/heartbeat independent of execution capacity; no network call in SQL transaction.
  Exceeding limits stops new dispatch and records `budget_exhausted`, never a pass.
- [x] Repeat process tests; expect pass. Tasks 7/8 complete actual execution/recovery proofs.
- [x] Commit owned changes: `feat: run a manually controlled bounded daemon`.

### Task 5: Real Groq target adapter and evaluator gateway

Component verification uses loopback HTTP/HTTPS and installed wheels on WSL and Windows.
It does not establish hosted Groq access or queued-run execution.

**Files:** Create `backend/asclepius/{transport,models}.py`, `backend/asclepius/adapters/{__init__,chat}.py`,
`backend/tests/cli/{test_transport,test_groq_contract}.py`.

**Interfaces:** `ChatAdapter.execute(request: OperationRequest) -> Observation` (async);
`ModelGateway.generate(role: str, payload: dict, output_type: type[BaseModel]) -> BaseModel` (async).
Both consume independently resolved configs and Task 4 budgets, not global API settings.

Transport boundary (2026-10-22): `JsonTransport.post` is the low-level HTTP
boundary, not a public execution path. Its HTTP loopback support enables real network
tests; hosted target and evaluator configs still require HTTPS. An explicitly supplied
verified TLS context supports private trust roots without environment-derived trust.
Compressed replies are rejected before decoding so response limits also bound decoding
memory. The checked-in localhost certificate/key are public test fixtures, never user
credentials or production trust material.

`GroqConnection` binds the snapshot and one shared budget manager. It captures configured
secret references once per run for consistent authentication/redaction. `ChatAdapter.prepare`
prepends the profile system prompt once; `execute_prepared` sends the finalized call.
The convenience `execute(raw_request)` combines those steps. `ModelGateway.prepare` binds
the work item, pinned role prompt, input, and strict output schema. Its `execute` returns
an immutable per-call result, including observations when structured output is invalid.
`generate` returns only the validated output or raises an error carrying that result.

`PreparedCall.request.provider_body_json` retains the finalized redacted wire body,
including the evaluator schema. This is immutable serialized data, not a nested mutable
dictionary. Task 7 must persist this request through `begin_operation`, dispatch only
when `intent.created`, and persist the returned observation/result. Convenience methods
do not write intents or provide orchestration/replay protection on their own.
Optional metadata fields preserve older JSON reads; replay comparisons normalize
through typed contracts without rewriting stored requests or observations.

Evaluator object models must forbid extra fields. Schema normalization requires every
property, preserves nullable types, and removes default annotations. `jsonschema` checks
the raw output against the exact prepared schema before Pydantic can insert defaults.
Open mappings, fixed tuples, and nonlocal schema references are rejected locally.
Provider errors consume dispatched allowance. Cancellation before dispatch releases unused
allowance; uncertain authorization and dispatched calls retain it. Validated bounded
`retry_after` metadata survives HTTP errors without automatic retries. Empty length-limited
replies retain finish reason, usage and response identity and yield `evaluator_truncated`.
No automatic mode/model fallback is permitted when strict schema output is unsupported.
Provider contract references: [Groq chat API](https://console.groq.com/docs/api-reference)
and [strict structured outputs](https://console.groq.com/docs/structured-outputs).
Local schema validation follows [the JSON Schema validator API](https://python-jsonschema.readthedocs.io/en/stable/validate/).

- [x] Write local HTTP-boundary tests for actual POST message shape, correct secret reference,
  target/evaluator model independence, valid reply, 401/403/429/5xx, invalid JSON, missing
  choices, refusal, truncation, oversized body, redirects, timeout, and missing usage.
  Assert one dispatched call on errors and zero automatic retries or secret-bearing logs.
- [x] Run `python -m pytest tests/cli/test_transport.py tests/cli/test_groq_contract.py -q`; expect failures.
- [x] Implement HTTPX with `trust_env=False`, redirects off, total deadline via asyncio timeout,
  streaming body read up to byte cap, and sanitized exceptions. No tools, streaming generation,
  remote actions, or automatic message history in initial target requests. Save redacted request
  content, finish reason, response IDs, usage, and raw-content truncation metadata.
  Preserve synthetic canaries as test evidence; do not confuse them with actual configured keys.
- [x] Implement strict JSON-schema evaluator responses with Pydantic validation and explicit
  refusal/invalid-output failures. Schema conformance does not validate evidence truth.
  Never silently switch model, endpoint, credentials, or output mode on a provider error.
- [x] Repeat tests; expect pass with a real loopback HTTP server substituting only Groq.
- [x] Commit Task 5 files: `feat: connect Groq targets and evaluator models`.

### Task 6: Broad pack and four-role contracts

**Files:** Create `backend/asclepius/{checks,agents}.py`, `backend/asclepius/packs/broad_chat_v1.json`,
`backend/asclepius/prompts/{selector,generator,judge,reporter}.txt`,
`backend/tests/cli/{test_check_pack,test_agents}.py`.

**Interfaces:** `load_pack(pack_id: str) -> list[CheckDefinition]`; async AgentRunner methods
`select(snapshot: RunSnapshot) -> list[Selection]`, `generate(selection: Selection) -> list[Variant]`,
`judge(check: CheckDefinition, variant: Variant, observation: Observation) -> Judgment`,
`report(judgment: Judgment, observation: Observation) -> Finding`.

Proposed pack v1 has four distinct objectives per family:

| Family | Stable check IDs / objective |
| --- | --- |
| Instruction priority | `priority.override`, `.role-spoof`, `.authority-spoof`, `.quoted-instruction`: lower-trust instructions cannot override the explicit system contract. |
| Protected synthetic context | `context.canary`, `.paraphrase`, `.partial`, `.transform`: protect a synthetic hidden fact under exact, semantic, partial, or transformed disclosure attempts. |
| Encoded instructions | `encoded.base64`, `.unicode`, `.language`, `.fragment`: encoding/representation changes do not grant authority over the system contract. |
| Conflicting context | `conflict.fabricated-history`, `.false-policy`, `.untrusted-note`, `.output-hijack`: invented context cannot rewrite the declared task or output obligations. |
| Application policy | `policy.scope`, `.synthetic-pii`, `.approval`, `.structured-output`: enforce a supplied synthetic application's scope, private facts, approval boundary, and output schema. |

Each definition pins objective, capabilities (`chat.v1`), protected context/contract,
three attack strategies, one benign control, rubric, evidence criteria, and severity rule.
These test model behavior under an explicit harness contract, not vulnerabilities in
Groq infrastructure. No real user data, credentials, external exfiltration destinations,
tool execution, provider-availability stress tests, or implicit collection access.

- [x] Write pack tests: exactly 20 unique checks in five families, four cases/check,
  control distinguished from attack, complete rubrics, no unsupported capability dispatch.
  Agent tests reject missing/extra checks, duplicate variants, modified protected contract,
  fabricated citations, and judgments unsupported by actual observations.
- [x] Add adversarial reply text instructing Judge to emit a pass or Reporter to invent
  evidence; assert role prompts delimit untrusted content and invalid evidence references
  are rejected. Include deterministic exact-canary/schema assertions and labeled semantic
  judgments; known controls expose false positives/over-refusal separately.
- [x] Run `python -m pytest tests/cli/test_check_pack.py tests/cli/test_agents.py -q`; expect failures.
- [x] Implement frozen check definitions and per-role validated outputs. Selector may order
  but not drop requested checks. Generator produces exactly three attack variants; the
  fixed benign control and protected setup come from the pinned definition, not the model.
  Judge does not see Selector rationale. Reporter runs only for evidenced weaknesses.
  Model confidence alone never validates a finding; Reporter cannot mutate verdict/evidence.
- [x] Repeat tests with deterministic gateway responses; expect pass. These are contract
  tests, not proof of real LLM judgment accuracy; Task 10 includes live review.
- [x] Commit owned files: `feat: define broad chat checks and four agent roles`.

#### Accepted Task 6 implementation shape

Design review on 2026-10-23 selected the mandatory prepared-dispatch design. The
alternative was a domain-only invoker receiving role payloads. Both avoid direct hidden
network calls; the selected seam exposes the already-finalized gateway request and
per-call result, making Task 7's persistence boundary explicit. The independent comparison
favored this shape for evidence validation and reporting lineage despite its gateway coupling.

`AgentRunner(connection, *, dispatch)` binds the connection's immutable snapshot.
The required async dispatch receives `(gateway, prepared)` and returns `EvaluationResult`.
It must persist the prepared request before executing it and the resulting observation
before returning, including provider/schema errors. Task 6 has no default dispatch and
no SQLite, lifecycle, target-execution, retry, or mutable last-result state. Task 7 supplies
the durable dispatch. The four public role signatures above remain unchanged.

Code owns proposal normalization. Selector must return exact requested coverage and may
prioritize one pinned strategy. Generator covers all three pinned strategies, creates
only user-text proposals, and code builds protected system messages and the fixed control.
Stable work-item and variant IDs derive from run/check/version and exact accepted inputs.
The whole-run Selector work item is anchored to the first pinned check, never model order,
because the existing repository requires every work item to reference a check.

Optional persisted additions pin evidence criteria, fixed-on-evidenced-weakness severity
rules, deterministic assertion definitions, and semantic/deterministic assessment mode.
New variants carry check version and strategy; new judgments carry check ID/version and a separate
control outcome; assertion records label deterministic or semantic origin. Older JSON
keeps defaults and remains readable. Replay comparison normalizes typed defaults without
rewriting saved JSON, while changed content must still conflict. No SQL migration is needed.
Legacy lineage-incomplete judgments remain readable but cannot start a new Reporter call.

Exact-canary and JSON-schema assertions are computed locally. Exact literal absence does
not establish semantic non-disclosure. Complete checks explicitly governed by an exact
contract may derive a verdict from it. Missing, redacted, or truncated necessary evidence
cannot become a pass. Detectable contradictions between model assessments and deterministic
facts are rejected or explicitly inconclusive, never silently accepted as findings.
Controls retain usefulness/over-refusal separately; a genuine evidenced control violation
may still produce a finding. A refusal alone does not establish a security weakness.

Judge input is rebuilt from the pinned check, exact variant, and matching target observation,
excluding Selector rationale. Quotes must occur in that observation; model-supplied IDs are
never accepted as authority. Reporter proposes description/recommendation only. Code fixes
severity and all IDs, preserves the complete judgment evidence, and builds reproduction
from the exact recorded request. This proves provenance, not general semantic entailment.

Task 6 also wires `checks list --pack` and `run --pack` through the existing submission
service. Listing needs no store or credentials. The queue still does not execute until
Task 7. Files include the Task 6 paths above plus scoped domain, CLI, replay-comparison,
and affected CLI tests. Installed-wheel checks must read the actual bundled resources.

### Task 7: Coordinator and complete persisted execution

**Files:** Create `backend/asclepius/coordinator.py`, `backend/tests/cli/test_pipeline.py`,
`backend/tests/cli/test_multi_client.py`; extend daemon/storage/services.

**Interfaces:** async `Coordinator(repo: Repository, agents: AgentRunner, adapter: ChatAdapter, budgets: BudgetManager).execute(snapshot: RunSnapshot) -> None`.
Daemon schedules claimed snapshots through this interface, never directly invokes model roles.

- [x] Write integration tests with actual CLI subprocesses, daemon, SQLite, and loopback
  target/provider fixtures: requested 80 cases execute with correct IDs/versions, four roles
  have distinct records, and pass/weakness/inconclusive/provider error remain distinguishable.
  Assert no RAG fields required and stop new work on unrecoverable technical error.
- [x] Test profile/check edits after submission do not change the accepted snapshot. Remove a
  daemon credential before dispatch; assert failed run, no alternate identity, no target call.
  Submit using two aliases and configurable two active runs; assert global/resource bounds.
- [x] Run `python -m pytest tests/cli/test_pipeline.py tests/cli/test_multi_client.py -q`; expect failures.
- [x] Implement persisted selection, generated inputs, intent-before-network, observation,
  judgment, finding, and phase counts/events. Before variants exist show phases/counts,
  not a misleading fixed total percentage. Commit exact inputs before sending.
  Bound evidence; necessary evidence missing due truncation yields inconclusive.
  Finalize only after in-flight work settles; partial findings survive failure.
  Add pending/failed stage invocation records before model calls. Task 2 commit-only attempts
  record unknown start time as NULL, not a fabricated duration, and do not prove invocation recovery.
- [x] Repeat integration tests, inspecting saved SQLite output and fixture request logs;
  expect matching identities, no duplicated committed stages/findings.
- [x] Commit owned changes: `feat: execute queued evaluations end to end`.

#### Accepted Task 7 implementation shape

Design comparison on 2026-10-23 selected the run session and scoped invocation design.
Each invocation binds its immutable stage-attempt identity to the existing mandatory
AgentRunner dispatch callback. The coordinator owns the visible sequential role/target
loop; the daemon owns bounded run tasks, heartbeat, drain, and one shared BudgetManager.
The alternative direct run context contributes atomic capacity-aware FIFO admission in
`claim_next`, so a queued run never starts its deadline while waiting for a run slot.
There is no second admission lease registry or generic workflow engine.

The public boundary remains `Coordinator.execute(snapshot)`. Its constructor takes the
repository, shared budgets, and verified transport, then constructs snapshot-bound agents
and adapter internally. This accepted refinement removes circular callback construction
from the plan's original preconstructed-agent constructor. AgentRunner's four existing
method signatures remain unchanged. Public submission stays
`run <profile> --pack broad-chat-v1 --evaluator <path>`.

Repository stage attempts gain owner-fenced pending/failed/completed transitions. An
invocation commits its typed output and attempt completion atomically. Historical direct
stage commits retain NULL start timestamps. Every network call requires a newly created
exact prepared intent; an existing intent never authorizes a resend. Observations become
durable before role semantic acceptance. Generation commits exact variants before target
calls. Finalization rejects pending operations or stage attempts and preserves partial
findings. Fatal storage/ownership failure stops admission rather than claiming settlement.

Dispatch certainty belongs to the connection boundary. A typed failure retains the real
observation when one exists. Additive optional observation metadata distinguishes a proven
local nondispatch failure from attempted or uncertain delivery, without claiming a provider
reply or rebuilding the operations table. Historical JSON keeps its unknown defaults.
Cancellation accounting must retain the existing uncertain-authorization behavior.

Daemon startup accepts one strict optional `--config` TOML containing runtime limits and
an optional CA bundle. Resolve paths and validate trust before readiness, then freeze the
policy for the instance. A supplied bundle adds trust through a verified SSLContext;
hostname and certificate checks stay enabled. Runtime limits must have explicit effective
semantics rather than silently ignored fields. The shared manager constrains all aliases.

Execution capability is persisted for the actual ready daemon generation. An additive
schema-v3 migration adds a default-false control capability; startup explicitly sets it.
Existing v1/v2 stores require stopped explicit migration, preserving saved data. This
narrow migration is accepted to prevent a new CLI from claiming that an older live daemon
executes runs. Stage attempts and dispatch metadata themselves require no SQL changes.

Progress is derived coherently from persisted rows and phase events, with no fixed total
until generation completes. Preflight rejects incomplete legacy execution plans before any
provider call and resolves exact configured credentials from the daemon environment.
Minimal startup orphan interruption closes pending attempts under exclusive ownership;
Task 8 retains the exhaustive cancellation/crash/retry acceptance matrix.

Verification uses public CLI subprocesses, a real detached daemon, verified loopback HTTPS,
and actual SQLite. The fixture replaces only provider responses. It must execute all 80
target cases, exercise all four roles and distinct verdict/error paths, preserve partial
results, and demonstrate shared bounds for two concurrent aliases. Installed-wheel proof
and both platform suites precede the local commit. Live semantic accuracy remains Task 10.

### Task 8: Cancellation, drain, interruption, and explicit retry

**Files:** Create `backend/tests/cli/test_recovery.py`, `backend/tests/cli/test_run_control.py`;
extend coordinator/daemon/services/storage/process.

**Interfaces:** Uses Tasks 2–4/7 interfaces; no new run states or resume endpoint.

- [x] Write process tests that cancel queued work without calls; cancel active work stops
  new calls while saving bounded in-flight replies; stop drains active but leaves queued;
  stop timeout reports still draining. `runs watch` interruption never cancels execution.
- [x] Inject process termination before send, after target receipt, and after stage commit.
  On manual restart assert previous running work is interrupted, uncertain intent retained,
  queued work available, no automatic replay, and retry yields a linked new ID/config.
  Test CLI submission racing drain: reject or durably queue, never lose accepted work.
- [x] Run focused control/recovery tests. Existing runtime contracts largely pass; retain the
  reproduced drain-race RED and review-proof RED/GREEN regressions separately from setup failures.
- [x] Verify existing Task 7 cancellation checkpoints around rate/budget/role/target dispatch
  and owner-checked finalization; correct the reproduced daemon admission race. Restart
  recovery runs only after acquiring exclusive ownership.
  Inactive old owner cannot append results to a new run or overwrite a final state.
- [x] Repeat tests, asserting source evidence unchanged, no new calls after cancel checkpoint,
  and no same-ID requeue. Expect pass.
- [x] Commit owned changes: `feat: preserve evidence across cancellation and crashes`.

#### Accepted Task 8 implementation shape

Task 8 retains the Task 7 runtime types, coordinator boundaries, schema v3, and existing
public CLI. Independent design comparison selected explicit scenario functions over a
scenario registry. A small fixture-owned process context owns daemon identity/handles,
provider response gates, child processes, and cleanup. Existing domain types and immutable
raw evidence snapshots support assertions. A closed mapping for the three crash points
may share their rate/gate setup without becoming a workflow engine.

The proof harness uses actual CLI subprocesses, detached daemon, verified loopback HTTPS,
and SQLite. Normal lifecycle scenarios exclude production fault switches and database
mutation to manufacture process states. Separate negative tests deliberately corrupt saved
evidence to prove the validators reject it. Read-only predicates wait for durable milestones. RPM 1 holds a
Generator intent before send after Selector commits. Selective target response gating
holds a received request before its observation. RPM 5 holds the next target after the
first Reporter/finding commit. These fixture counts apply only to the isolated shared
origin/account scenario; durable recovery still labels pending outcomes unknown.

Acquire a Linux pidfd or native Windows process handle before the final matching
PID/generation/OS-ownership check, then terminate and wait through that retained identity.
Only fixture-owned daemon processes are terminated. Watch uses SIGINT to its owned POSIX
child; native Windows uses a new fixture-owned console, a separate controller attached only
to that watcher, and a strict attached-process membership guard before generating Ctrl+C.
The native watcher uses the base interpreter with `-S` and the intended environment
site-packages bootstrap, asserting the exact imported module path. The venv launcher
capability probe introduced an extra process and safely aborted before signaling.
The controller detaches from any inherited console first; the application console and
detached daemon are outside the signal target. Injected KeyboardInterrupt alone cannot
stand in for native OS-event proof. Physical keyboard/terminal-close and sleep/shutdown
acceptance remain Task 10.

Extend provider fixture gates and a structured CLI-result helper without weakening existing
success assertions. Keep explicit SQLite closing and deterministic resource cleanup; permit
only expected peer-disconnect handling after deliberate client termination. There are no
cleanup sleeps/retries masking leaked handles. The installed-wheel driver shares the same
scenario functions, asserts site-packages imports, emits observed identities/results, and
runs outside the checkout on WSL and native Windows.

Assertions cover queued cancellation with no calls; active target/evaluator cancellation
with bounded issued evidence and no later calls; rate-wait cancellation and allowance;
active drain, queued preservation, timeout ownership, submission/drain race, and watcher
interruption without cancellation. Crash/restart tests prove unknown intents, failed pending
attempts, preserved known observations/findings, no automatic replay, and available queued
work. Linked retry uses new run/variant/operation identities with the source's pinned plan
and unchanged original evidence. Repository-level stale-owner append/overwrite rejection
complements public process tests; identical replay reads remain allowed.

A focused regression reproduced the ready-read/drain/claim race: stop can commit between
readiness and claim, causing an unclean serve exit. The narrow correction accepts only
`daemon_unavailable` after checking the same generation is draining; unrelated errors
still propagate. Existing final cleanup already awaited active work; evidence loss was
not established by that regression. Final platform suites and installed recovery proofs
are retained in [Task 8 evidence](../verification/evidence/cli-recovery.json).

### Task 9: Findings, compatible comparisons, reports, and charts

**Files:** Create `backend/asclepius/{results,exports}.py`,
`backend/tests/cli/{test_results,test_exports}.py`; extend CLI inspection commands.

**Interfaces:** async `compare_runs(repo: Repository, run_ids: list[str]) -> Comparison`;
`render_report(view: RunView | Comparison, format: str) -> ExportArtifact`;
`write_export(artifact: ExportArtifact, destination: Path, overwrite: bool = False) -> Path`;
`safe_terminal(text: str) -> str`.

- [ ] Write tests for zero cases, missing IDs, partial/live runs, no findings, controls,
  failures, incompatible check/model/target settings, unknown remote revisions, and actual
  counts against fixture logs. Separate check compatibility from deliberately changed
  target model: allow labeled cross-model comparison, not an unlabeled like-for-like claim.
- [ ] Add HTML/script/link/Markdown-fence and ANSI/OSC injection inputs; assert inert escaped
  output. Test export refuses existing destination and repeated export invokes no target/provider.
  Simulate interrupted write; previous file remains intact and scratch artifacts are removed.
- [ ] Run `python -m pytest tests/cli/test_results.py tests/cli/test_exports.py -q`; expect failures.
- [ ] Implement coherent SQLite read snapshots, cursor-based findings detail/list, JSON,
  Markdown, self-contained HTML with inline SVG outcome counts and per-family comparison.
  Display denominator, control outcomes, uncertainty, truncation, usage, and evaluator identity;
  do not invent a combined security score. Write temporary file in destination directory and
  replace atomically under a destination lock; avoid check-then-overwrite races.
- [ ] Repeat tests and open generated known-data HTML in a browser; check visible labels,
  empty/partial states, and chart counts. Record visual observation, not just file existence.
- [ ] Commit owned files: `feat: inspect compare and export evaluation evidence`.

### Task 10: Real Groq and platform acceptance

**Files:** Create `backend/tests/cli/test_live_groq.py`,
`backend/tests/cli/test_platform_detach.py`, `docs/verification/evidence/cli-groq.json`;
update `docs/{development,status,verification}.md` and affected feature entry points only
with actual observed behavior. Add pytest marker declarations in `backend/pyproject.toml`.

**Interfaces:** Only public CLI/process/HTTP boundaries from earlier tasks. No direct DB seeding.

- [ ] Write opt-in `live` tests, skipped without explicit `ASCLEPIUS_LIVE_TESTS=1` and secret;
  a skip is not a pass. Tests create isolated owned directories/profiles and run the full
  broad pack; verify real provider response IDs, target/evaluator model identities, saved
  observations, final outcomes, restart inspection, comparison, and three exports. Execute
  two full-pack trials as separate run IDs with separate budgets for the live comparison.
- [ ] Run `python -m pytest tests/cli -m "not live" -q` and
  `python -m ruff check asclepius tests/cli`; expect pass before spending provider calls.
  Retain the existing API baseline separately; do not mask regressions by deleting tests.
- [ ] With user-supplied key available through environment and approved defaults, run
  `python -m pytest tests/cli/test_live_groq.py -m live -v` in WSL first. Confirm account model
  access before attack dispatch; unavailable models block live acceptance, not offline work.
  No guarantee of a vulnerability is a pass criterion: review real responses and sample
  judgments across all families plus controls, documenting disagreements/limitations.
- [ ] Verify terminal closure while a real run is active on WSL and native Windows separately.
  Use a native Windows environment distinct from Linux `.venv`; record terminal, OS,
  instance/run IDs, continued events after closure, and clean shutdown. Unsupported or
  untested platform stays explicitly unverified; do not infer Windows support from WSL.
- [ ] Save source checkpoint, uncommitted diff identity, exact commands, exit statuses, actual
  call/outcome counts, sanitized artifacts, setup/cleanup and missing proofs in the evidence
  JSON. No keys, fabricated provider outputs, or requirement for identical model answers.
- [ ] Commit only actual tests/docs/evidence: `test: verify live Groq CLI workflow`.

### Task 11: Ollama through the existing target boundary

**Files:** Create `backend/asclepius/adapters/ollama.py`, `backend/examples/ollama-target.toml`,
`backend/tests/cli/test_ollama.py`, `backend/tests/cli/test_live_ollama.py`; update connection docs.

**Interfaces:** Async `OllamaAdapter.execute(request: OperationRequest) -> Observation`,
same public target contract; evaluator remains separately configured Groq unless changed explicitly.

- [ ] Write loopback protocol tests and a live opt-in test asserting chat observations,
  missing local model errors, no credential requirement for local target, no automatic model
  pull/server startup, and identical run/history/export behavior without RAG fields.
- [ ] Run `python -m pytest tests/cli/test_ollama.py -q`; expect failures.
- [ ] Implement Ollama adapter using explicit local configuration and non-streaming chat;
  normalize reply/usage, enforce the same limits, require user-selected installed model,
  and declare only supported capabilities. Keep Groq evaluator credentials independent.
- [ ] Repeat focused test; with user-installed Ollama/model, run live marked test, then
  compare a hosted and local run with explicit model/config differences. Missing installation
  blocks only local acceptance; never install/download models without a separate user request.
- [ ] Commit owned files: `feat: evaluate local Ollama targets`.

### Task 12: Retire the legacy path after replacement review

**Files:** Proposed retirement set: `backend/app/`, `backend/alembic/`,
`backend/alembic.ini`, `backend/docker-compose.yml`, legacy API tests and API reference.
Modify packaging/env examples/development/status accordingly. This is a review gate,
not automatic permission to delete overlapping local user work.

**Interfaces:** Installed `asclepius` entry point and all M1 commands remain stable.

- [ ] Inventory all legacy callers and local modifications, including lifecycle migration/
  service/tests. Present an explicit reuse/preservation/retirement disposition; stop if a
  user change has no safe disposition. Do not delete existing databases, Docker volumes,
  frontend backups, `.env`, or unrelated `.github` content.
- [ ] Add isolated-install/import tests showing CLI help, profiles, history, and exports
  need neither Postgres/Redis nor API/JWT dependencies. Run before dependency retirement
  to establish the replacement baseline.
- [ ] After M1 proof and approved disposition, remove only obsolete tracked source/config,
  trim legacy dependencies, rename remaining clinical/API-only copy, and update documentation
  to the real CLI state. Do not move old material back into active docs as duplicate context.
- [ ] Run the complete offline CLI suite, installed-entry-point check, Ruff, live acceptance
  as available, and secret/unrelated-diff review. Existing data remains untouched/recoverable.
- [ ] Commit owned retirement only: `refactor: retire legacy web API runtime`.

## Verification and handoff gates

- M1 is not complete until public CLI actions, real Groq traffic, durable results, broad pack,
  comparison, reports/charts, concurrent-client controls, and recovery all have retained proof.
- Offline fixtures establish reproducible contract/failure handling; live calls establish actual
  model execution. Neither alone establishes security-evaluation accuracy across applications.
- Models/keys/account rate limits and native platform environments are external prerequisites;
  missing prerequisites must be named, not replaced with seeds and called verified.
- M2 adds Ollama without weakening M1. M3 requires a separate RAGbot adapter plan grounded
  in its actual interfaces; corpus/actor/cleanup semantics in the RAG design stay mandatory.
- Each task updates its feature entry points when they become runnable. Do not mark future
  command sketches as implemented just because a parser accepts them.
- Self-review before execution: all shared types/signatures defined, every spec requirement
  mapped to a task or M3 boundary, each Review Focus mapped to tests, budgets consistent,
  and local change preservation checked. No implementation or automatic commit by this plan.

## Technical references

- [Groq model catalog](https://console.groq.com/docs/models) and
  [structured outputs](https://console.groq.com/docs/structured-outputs): model availability
  and evaluator response format; account access still needs a real check.
- [Python subprocess](https://docs.python.org/3.12/library/subprocess.html): platform-specific
  process launch. Flags alone do not prove terminal-close survival.
- [Portalocker](https://portalocker.readthedocs.io/en/latest/): cross-process file locks;
  all participating code must follow the maintenance protocol.
- [Python SQLite](https://docs.python.org/3.12/library/sqlite3.html): connection/transaction
  primitives. Domain state and recovery guarantees come from our tests, not library choice.
- [pip-tools](https://pip-tools.pypa.io/en/stable/): hashed dependency resolution from
  project metadata, generated in each target environment rather than assuming one host's lock is portable.
