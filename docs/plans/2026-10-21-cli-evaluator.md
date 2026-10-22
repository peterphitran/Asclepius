# CLI Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execution method requires user selection; this document does not authorize starting implementation.

**Goal:** Deliver a general-purpose CLI LLM evaluator with a real Groq-backed broad attack pack, durable background execution, comparisons, and local reports; then validate Ollama through the same core.

**Architecture:** Add an application-neutral `asclepius` Python package alongside the existing API. CLI and one manually started daemon share application services and SQLite; a coordinator controls four role contracts, target adapters, persistence, and budgets. Retire legacy runtime dependencies only after replacement proofs and review of existing local changes.

**Tech Stack:** Python >=3.12; standard-library argparse, asyncio, sqlite3, tomllib, subprocess, and HTML/SVG rendering; Pydantic v2 contracts; HTTPX asynchronous transport; portalocker file locks; pytest and Ruff. Resolve and lock exact compatible versions during Task 1, not by guessing package versions here.

**Spec:** [Backend design](../specs/backend-design.md), [pipeline](../specs/evaluation-pipeline.md), [product](../product.md), [feature map](../features/README.md). [RAG design](../specs/rag-testing.md) is a later capability milestone, not implemented by this plan.

Status: draft for user review. No task is implemented or verified by this document.

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

Current source: `backend/app/` is FastAPI/Postgres; `app/services/sweep_state.py` and its tests
contain useful transition cases, but reclaim/retry behavior differs from this design.
Do not import those ORM types or translate row locks into the new scheduler.
`backend/pyproject.toml` packages only `app` and has no CLI entry point. No existing engine to extend.

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

- [ ] Write tests `test_target_and_evaluator_are_independent`, `test_reject_secret_literal`,
  `test_reject_unknown_fields`, `test_non_rag_observation_needs_no_corpus`, and
  `test_terminal_states_cannot_transition_to_queued`; assert sample TOML resolves defaults,
  `secret_ref == "env:GROQ_API_KEY"`, and no secret value is serialized.
- [ ] Run `python -m pytest tests/cli/test_config.py tests/cli/test_domain.py tests/cli/test_cli_help.py -q` from `backend/`; expect missing-package/function failures before implementation.
- [ ] Implement the contracts/parser/help. Add console script `asclepius = "asclepius.cli:main"`,
  package both `app` and `asclepius`, include pack/prompt/SQL resources in built wheels,
  update clinical-only package description, and declare direct CLI dependencies. Keep old
  dependencies for now. Add pip-tools to dev tooling; from `backend/` use
  `python -m piptools compile --extra dev --generate-hashes --output-file requirements-cli-wsl.lock pyproject.toml`
  on WSL and the corresponding `requirements-cli-windows.lock` output on Windows.
  Record Python/resolver versions and install each platform's hashed lock into disposable
  verification environments before the editable project. Never capture private index credentials.
- [ ] Run focused tests, install editable into an isolated disposable environment, then
  `asclepius --help` and `python -m asclepius --help`; expect exit 0 and matching command groups.
- [ ] Commit only Task 1 paths: `feat: define CLI contracts and configuration`.

### Task 2: SQLite history, claims, and durable identities

**Files:** Create `backend/asclepius/storage.py`, `backend/asclepius/migrations/001_initial.sql`,
`backend/tests/cli/test_storage.py`, `backend/tests/cli/test_storage_processes.py`.

**Interfaces:** `Repository(data_dir: Path)` exposes async `initialize() -> None`,
`claim_next(instance_id: str) -> RunSnapshot | None`,
`commit_stage(run_id: str, work_item_id: str, stage: str, output: StageOutput) -> StageOutput`,
`begin_operation(request: OperationRequest) -> str`, `save_observation(observation: Observation) -> None`,
`events(run_id: str, after: int = 0) -> list[dict]`, `read_run(run_id: str) -> RunView`,
`interrupt_orphans(instance_id: str) -> list[str]`, and `finalize(run_id: str, state: RunState, reason: str | None) -> None`.

- [ ] Write real temporary SQLite tests asserting foreign keys, schema rejection, rollback,
  immutable snapshots, monotonic per-run event ordering, and identical stage re-commit returns
  the saved value while conflicting content raises `AppError`. Unique stage identity:
  `(run_id, work_item_id, stage)` for committed output; attempts remain separate audit records.
- [ ] Add two-process tests: two claimants cannot claim the same queued run; held write
  contention returns a bounded busy error. Test an operation intent without a saved reply
  becomes unknown on orphan recovery, without deleting prior evidence or replaying a request.
- [ ] Run `python -m pytest tests/cli/test_storage.py tests/cli/test_storage_processes.py -q`; expect failure before implementation.
- [ ] Implement version table, profiles, runs, work_items, stages, operations, observations,
  judgments, findings, events, daemon_control, and budget reservations. Use FKs/unique
  constraints (including finding run/variant), parameterized SQL, WAL, busy timeout, and
  `BEGIN IMMEDIATE` for conditional claims/state changes. Persist output+event atomically.
  Profile removal is a tombstone; referenced history is not cascade-deleted.
- [ ] Run focused tests again; expect pass using real SQLite, not fake sessions.
- [ ] Commit Task 2 paths: `feat: persist local runs and atomic claims`.

### Task 3: Profiles, submission, inspection, and linked retries

**Files:** Create `backend/asclepius/services.py`, `backend/tests/cli/test_services.py`,
`backend/tests/cli/test_cli_profiles.py`. Extend `storage.py`, `cli.py`, `config.py`.

**Interfaces:** `EvaluationService(repo: Repository)` exposes async
`save_profile(config: ProfileConfig) -> str`, `submit(profile: str, evaluator: EvaluatorConfig, checks: list[CheckDefinition]) -> str`,
`cancel(run_id: str) -> RunView`, `retry(run_id: str) -> str`.
Repository adds async `save_profile(config: ProfileConfig) -> str`, `list_profiles() -> list[ProfileConfig]`,
`get_profile(identity: str) -> ProfileConfig`, `remove_profile(identity: str) -> None`,
`enqueue(snapshot: RunSnapshot) -> str`, `request_cancel(run_id: str) -> RunView`,
`list_runs(profile_id: str | None = None) -> list[RunView]`,
`list_findings(run_id: str) -> list[Finding]`, `read_finding(finding_id: str) -> Finding`.
`enqueue` checks daemon acceptance and inserts the snapshot/event in the same transaction.

- [ ] Write tests that two profiles retain distinct IDs; duplicate names fail; editing/removing
  a profile leaves history intact; stopped daemon yields exit 4 and zero inserted runs;
  unsupported requested checks yield exit 2 before requests. Supply controlled readiness in
  service tests only; do not count it as proof of a real daemon.
- [ ] Test cancellation of queued work, cancellation request for running work, terminal-state
  rejection, and retry from failed/cancelled/interrupted returns a different ID with unchanged
  source snapshot. Missing credentials fail without fallback; never print their values.
- [ ] Run `python -m pytest tests/cli/test_services.py tests/cli/test_cli_profiles.py -q`; expect failures.
- [ ] Implement service commands, materialized snapshots of full check definitions/prompt
  versions, and CLI reads. Secret references are validated here and resolved again by the
  executing daemon. Reading history and profiles works while stopped. List pagination uses
  default 50/max 500 and an explicit next cursor; unknown IDs return exit 3.
- [ ] Repeat tests, including two subprocess CLI clients against one temporary directory;
  expect matching persisted profile/run IDs and no implicit process launch.
- [ ] Commit owned Task 3 changes: `feat: manage profiles and queued evaluations`.

### Task 4: Manual daemon, OS ownership, and outbound budgets

**Files:** Create `backend/asclepius/{process,daemon,limits}.py`,
`backend/tests/cli/{test_daemon_process,test_limits,test_maintenance}.py`; extend storage/CLI.

**Interfaces:** `start_daemon(data_dir: Path) -> DaemonStatus`, async
`serve(data_dir: Path) -> None`, async `BudgetManager.reserve(run_id: str, kind: str, max_output: int) -> BudgetReservation`,
async `BudgetManager.slot(resource_key: str, kind: str)` context manager.
Repository adds async `control() -> DaemonStatus`, `set_ready(instance_id: str) -> None`,
`heartbeat(instance_id: str) -> None`, `request_stop() -> None` and persisted reservation operations.

- [ ] Write process tests for duplicate start, stale PID/heartbeat, readiness only after lock/schema,
  start failure diagnostics, stop timeout without kill, and stopped-daemon reads. Test aliases
  sharing a target resource and shared provider key cannot evade limits. Start with tiny
  test-only limits; measure observed concurrent fixture calls, not only semaphore counters.
- [ ] Test maintenance lock contention: daemon holds shared maintenance access, every CLI DB
  operation acquires shared access, migrations require exclusive access with daemon stopped.
  Lock order for startup/migration: instance lock, then maintenance lock; ordinary CLI DB
  operations never acquire the instance lock while holding maintenance access.
- [ ] Run `python -m pytest tests/cli/test_daemon_process.py tests/cli/test_limits.py tests/cli/test_maintenance.py -q`; expect failures.
- [ ] Implement portalocker lifetime instance lock and maintenance locks. Canonicalize paths;
  default Windows `%LOCALAPPDATA%/Asclepius`, WSL/Linux `$XDG_DATA_HOME/asclepius` or
  `~/.local/share/asclepius`; never share Windows/WSL state. Reject network-store configuration.
  Launch using `sys.executable`, argument arrays, no shell; POSIX `start_new_session=True`,
  Windows `DETACHED_PROCESS` with redirected streams and no visible console. PID reuse is
  not an ownership mechanism. Start waits for this child's fresh instance ID, not stale ready data.
  `init` initializes only new stores; `storage migrate` acquires exclusive instance and
  maintenance locks before applying versioned upgrades. Never auto-upgrade on an ordinary read.
- [ ] Implement durable readiness/drain plus reservations and cancellation-aware rate waits.
  Keep control/heartbeat independent of execution capacity; no network call in SQL transaction.
  Exceeding limits stops new dispatch and records `budget_exhausted`, never a pass.
- [ ] Repeat process tests; expect pass. Tasks 7/8 complete actual execution/recovery proofs.
- [ ] Commit owned changes: `feat: run a manually controlled bounded daemon`.

### Task 5: Real Groq target adapter and evaluator gateway

**Files:** Create `backend/asclepius/{transport,models}.py`, `backend/asclepius/adapters/{__init__,chat}.py`,
`backend/tests/cli/{test_transport,test_groq_contract}.py`.

**Interfaces:** `ChatAdapter.execute(request: OperationRequest) -> Observation` (async);
`ModelGateway.generate(role: str, payload: dict, output_type: type[BaseModel]) -> BaseModel` (async).
Both consume independently resolved configs and Task 4 budgets, not global API settings.

- [ ] Write local HTTP-boundary tests for actual POST message shape, correct secret reference,
  target/evaluator model independence, valid reply, 401/403/429/5xx, invalid JSON, missing
  choices, refusal, truncation, oversized body, redirects, timeout, and missing usage.
  Assert one dispatched call on errors and zero automatic retries or secret-bearing logs.
- [ ] Run `python -m pytest tests/cli/test_transport.py tests/cli/test_groq_contract.py -q`; expect failures.
- [ ] Implement HTTPX with `trust_env=False`, redirects off, total deadline via asyncio timeout,
  streaming body read up to byte cap, and sanitized exceptions. No tools, streaming generation,
  remote actions, or automatic message history in initial target requests. Save redacted request
  content, finish reason, response IDs, usage, and raw-content truncation metadata.
  Preserve synthetic canaries as test evidence; do not confuse them with actual configured keys.
- [ ] Implement strict JSON-schema evaluator responses with Pydantic validation and explicit
  refusal/invalid-output failures. Schema conformance does not validate evidence truth.
  Never silently switch model, endpoint, credentials, or output mode on a provider error.
- [ ] Repeat tests; expect pass with a real loopback HTTP server substituting only Groq.
- [ ] Commit Task 5 files: `feat: connect Groq targets and evaluator models`.

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

- [ ] Write pack tests: exactly 20 unique checks in five families, four cases/check,
  control distinguished from attack, complete rubrics, no unsupported capability dispatch.
  Agent tests reject missing/extra checks, duplicate variants, modified protected contract,
  fabricated citations, and judgments unsupported by actual observations.
- [ ] Add adversarial reply text instructing Judge to emit a pass or Reporter to invent
  evidence; assert role prompts delimit untrusted content and invalid evidence references
  are rejected. Include deterministic exact-canary/schema assertions and labeled semantic
  judgments; known controls expose false positives/over-refusal separately.
- [ ] Run `python -m pytest tests/cli/test_check_pack.py tests/cli/test_agents.py -q`; expect failures.
- [ ] Implement frozen check definitions and per-role validated outputs. Selector may order
  but not drop requested checks. Generator produces exactly three attack variants; the
  fixed benign control and protected setup come from the pinned definition, not the model.
  Judge does not see Selector rationale. Reporter runs only for evidenced weaknesses.
  Model confidence alone never validates a finding; Reporter cannot mutate verdict/evidence.
- [ ] Repeat tests with deterministic gateway responses; expect pass. These are contract
  tests, not proof of real LLM judgment accuracy; Task 10 includes live review.
- [ ] Commit owned files: `feat: define broad chat checks and four agent roles`.

### Task 7: Coordinator and complete persisted execution

**Files:** Create `backend/asclepius/coordinator.py`, `backend/tests/cli/test_pipeline.py`,
`backend/tests/cli/test_multi_client.py`; extend daemon/storage/services.

**Interfaces:** async `Coordinator(repo: Repository, agents: AgentRunner, adapter: ChatAdapter, budgets: BudgetManager).execute(snapshot: RunSnapshot) -> None`.
Daemon schedules claimed snapshots through this interface, never directly invokes model roles.

- [ ] Write integration tests with actual CLI subprocesses, daemon, SQLite, and loopback
  target/provider fixtures: requested 80 cases execute with correct IDs/versions, four roles
  have distinct records, and pass/weakness/inconclusive/provider error remain distinguishable.
  Assert no RAG fields required and stop new work on unrecoverable technical error.
- [ ] Test profile/check edits after submission do not change the accepted snapshot. Remove a
  daemon credential before dispatch; assert failed run, no alternate identity, no target call.
  Submit using two aliases and configurable two active runs; assert global/resource bounds.
- [ ] Run `python -m pytest tests/cli/test_pipeline.py tests/cli/test_multi_client.py -q`; expect failures.
- [ ] Implement persisted selection, generated inputs, intent-before-network, observation,
  judgment, finding, and phase counts/events. Before variants exist show phases/counts,
  not a misleading fixed total percentage. Commit exact inputs before sending.
  Bound evidence; necessary evidence missing due truncation yields inconclusive.
  Finalize only after in-flight work settles; partial findings survive failure.
- [ ] Repeat integration tests, inspecting saved SQLite output and fixture request logs;
  expect matching identities, no duplicated committed stages/findings.
- [ ] Commit owned changes: `feat: execute queued evaluations end to end`.

### Task 8: Cancellation, drain, interruption, and explicit retry

**Files:** Create `backend/tests/cli/test_recovery.py`, `backend/tests/cli/test_run_control.py`;
extend coordinator/daemon/services/storage/process.

**Interfaces:** Uses Tasks 2–4/7 interfaces; no new run states or resume endpoint.

- [ ] Write process tests that cancel queued work without calls; cancel active work stops
  new calls while saving bounded in-flight replies; stop drains active but leaves queued;
  stop timeout reports still draining. `runs watch` interruption never cancels execution.
- [ ] Inject process termination before send, after target receipt, and after stage commit.
  On manual restart assert previous running work is interrupted, uncertain intent retained,
  queued work available, no automatic replay, and retry yields a linked new ID/config.
  Test CLI submission racing drain: reject or durably queue, never lose accepted work.
- [ ] Run `python -m pytest tests/cli/test_recovery.py tests/cli/test_run_control.py -q`; expect failures.
- [ ] Implement cancellation checkpoints around rate/budget/role/target dispatch and durable
  owner-checked finalization. Restart recovery runs only after acquiring exclusive ownership.
  Inactive old owner cannot append results to a new run or overwrite a final state.
- [ ] Repeat tests, asserting source evidence unchanged, no new calls after cancel checkpoint,
  and no same-ID requeue. Expect pass.
- [ ] Commit owned changes: `feat: preserve evidence across cancellation and crashes`.

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
