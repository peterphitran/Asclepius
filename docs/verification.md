# Verification

The [feature map](features/README.md) defines behavior coverage. This page owns shared
verification conventions; feature files add only their specific actions and observations.

## Before running a check

Identify the checkout and whether it contains local edits. Use an isolated fixture target,
disposable database/data directory, and instances you create for the check. Follow
[development setup](development.md) for the current API.

The CLI entry point now provides help and configuration validation. The mapped evaluation
journeys remain future acceptance paths, not runnable instructions. Do not fabricate
commands to mark them passed.
The [backend design](specs/backend-design.md) defines runtime acceptance requirements;
the [pipeline design](specs/evaluation-pipeline.md) defines the agent-specific checks.
The [RAG design](specs/rag-testing.md) adds capability-specific fixture, indexing,
retrieval, isolation, and cleanup cases. Chat-only proof cannot stand in for them.

## Proof requirements

- Pair the user action with its result: command/exit status, HTTP request/response,
  fixture request log, persisted data, or rendered report.
- Include relevant success, invalid-input, empty, error, interruption, and persistence paths.
- Use a controlled target/provider only at its real external boundary; keep submission,
  execution, persistence, and output generation in the path being checked.
- Report missing prerequisites and unimplemented paths explicitly.
- Record source checkpoint, setup, observations, gaps, and cleanup. Omit credentials.
- Stop only instances you started. Keep evidence after removing scratch state.

A passing unit test does not establish a working daemon. A health response does not
establish database readiness. Seeded results do not establish target execution.

## Recorded API smoke

The [2026-10-21 record](verification/evidence/api-smoke.json) comes from real loopback
HTTP calls against this working checkout, including its uncommitted backend changes.

It observed `GET /health` and `GET /openapi.json` returning 200, and unauthenticated
`GET /targets` returning 401. The verification-owned instance stopped afterward.
An earlier attempt hit its startup deadline; the successful run's setup is recorded.

This covers process metadata, route discovery, and missing-token rejection only.
Authenticated database paths, CLI behavior, target execution, concurrency, recovery,
and reports remain unverified by that smoke check.

## Recorded CLI foundation

The earlier [transport slice](verification/evidence/cli-transport.json) tested real loopback
HTTP/HTTPS. Task 5 now connects target and evaluator components as recorded below.
Neither record establishes hosted Groq responses or queued evaluation execution.

The [Task 1 record](verification/evidence/cli-foundation.json) covers 45 passing tests on
WSL and native Windows, Ruff, hashed dependency installs, and installed-wheel help/config
checks outside the source tree. It includes the initial missing-package failure and
review regressions. The legacy Starlette HTTPX deprecation warning remains.

No network evaluation, daemon ownership, SQLite lifecycle, Groq model response, agent
execution, report, or chart is verified by this checkpoint.

## Recorded SQLite repository

The [Task 2 record](verification/evidence/cli-storage.json) covers 67 passing tests on WSL
and native Windows, including 22 storage tests using real temporary SQLite files and
spawned claimant processes. It records transaction rollback, owner fences, exact repeats,
immutable snapshots, evidence relationships, unknown intent recovery, WAL reads, and locks.
Installed wheels initialize their bundled schema outside the source tree on both platforms.

The control identity used by repository tests is a fixture, not proof of a real daemon.
CLI profile/submission commands, actual network execution, crash timing at the network
boundary, pending/failed stage invocation records, and end-to-end recovery remain unverified.

## Recorded CLI management

The [Task 3 record](verification/evidence/cli-management.json) covers 91 passing tests on
WSL and native Windows. It includes 24 new service/CLI cases, two concurrent profile clients,
controlled-ready submission, immutable retries, stopped reads, cancellation intent, and
watch interruption. Regression tests cover removed-identity lookup, concurrent rename/removal,
incomplete retry plans, consistent cancellation reasons, deeply nested JSON errors, and
initialization that preserves an existing file selected as the data directory.

The rebuilt wheels pass `backend/scripts/verify_cli_management.py` outside the source tree
on both platforms. The script verifies installed imports and real profile commands. It
does not start a daemon or send provider requests. Controlled readiness and injected
KeyboardInterrupt tests do not establish actual daemon ownership or terminal-close survival.

## Recorded daemon control and budgets

The [Task 4 record](verification/evidence/cli-daemon.json) covers 122 passing WSL tests and
121 passing native Windows tests with one WSL-only skip. It verifies real manual daemon
start/duplicate/stop, generation-bound readiness, stopped reads, explicit populated v1
migration, lock exclusion, cancellation-safe worker drain, and separately exercised budgets.
Loopback HTTP handlers record destination concurrency; fixtures do not substitute for model
evaluation. Shared origin/reference rate gates reject alias bypasses.

Both rebuilt wheels pass `backend/scripts/verify_daemon.py` outside the source tree. It
drives the real CLI with synthetic credential references, submits to a real ready control
daemon, verifies that the run stays queued, stops that daemon, and reads/cancels while stopped.
Its temporary stores are removed after its owned child exits.

One native creator-exit test failed during review and then passed its reruns and ten extra
probes. That unexplained failure remains recorded. Physical terminal-close, sleep/shutdown,
real provider calls, and scheduler/recovery integration are not proved by Task 4.
The daemon reports `execution_available: false`; no queued run is dispatched yet.
Submission uses persisted heartbeat freshness, so abrupt owner loss can leave up to ten
seconds of queued acceptance before the record becomes stale. Status/start use the OS
generation lease; enqueue is not an immediate crash detector.

## Recorded Groq provider components

The [Task 5 record](verification/evidence/cli-groq-components.json) covers independent
Groq target and evaluator configuration, strict schema validation, shared budgets,
redacted finalized requests, retained replies and provider failures, and older JSON reads.
Real HTTP/HTTPS fixtures substitute only the provider boundary. Cancellation before
slot acquisition releases unused allowance. Uncertain dispatch retains it. Provider errors
retain validated retry timing without automatic retries. Empty length-limited replies
retain metadata and produce a typed incomplete evaluator result.

Fresh environments installed each platform's hashed lock and rebuilt wheel. The
installed `backend/scripts/verify_groq.py` proof runs outside the checkout and makes two
HTTPS requests, validates an evaluator reply, and persists both observations through
real SQLite budgets. Its temporary store and fixture server are removed afterward.

The record includes exact full-suite results, source hashes, wheel hashes, review findings
and regressions. No live key or hosted model was used. Built-in checks, four-role agents,
coordinator execution, reports, comparisons, and physical terminal-close acceptance remain
later gates. The daemon still reports `execution_available: false`.

## Feature-map convention

Each feature file has four sections: sub-features, user entry point, terminal driving,
and gotchas. Stable feature IDs support focused checks; [user journeys](features/user-journeys.md)
cover behavior spanning several features.

The format is adapted from [poteto's example](https://github.com/poteto/verification-skill-example/blob/main/.cursor/skills/verify-atlas/references/features/README.md)
and [verification guidance](https://github.com/cursor/plugins/blob/main/pstack/skills/create-verification-skill/SKILL.md).
The linked [article](https://x.com/poteto/article/2094457600259842065?lang=en) was reviewed
through its [readable mirror](https://threadnavigator.com/thread/2094457600259842065/).
