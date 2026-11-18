# Verification

The [feature map](features/README.md) defines behavior coverage. This page owns shared
verification conventions; feature files add only their specific actions and observations.

## Before running a check

Identify the checkout and whether it contains local edits. Use an isolated fixture target,
disposable database/data directory, and instances you create for the check. Follow
[development setup](development.md) for the current API.

The CLI supports configuration, management, execution, cancellation, and manual recovery.
Recorded checkpoints below distinguish verified journeys from remaining acceptance paths.
Distinguish saved-data comparison/export proof from live model or physical terminal acceptance.
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

The rebuilt wheels pass `scripts/verify_cli_management.py` outside the source tree
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

The Task 4 rebuilt wheels passed the then-current `scripts/verify_daemon.py`
outside the source tree. That version drove the real CLI with synthetic credentials,
submitted to a real ready control daemon, verified queued state, stopped it, and read/cancelled
while stopped. Task 7 updates the executable driver for current execution behavior.
That version removed its temporary stores after its owned child exited.

One native creator-exit test failed during review and then passed its reruns and ten extra
probes. That unexplained failure remains recorded. Physical terminal-close, sleep/shutdown,
real provider calls, and scheduler/recovery integration are not proved by Task 4.
At the Task 4 checkpoint the daemon reported `execution_available: false` and did not
dispatch queued runs.
Submission checks the persisted elapsed heartbeat and the live generation locks inside its
transaction. Abrupt owner loss rejects new queue work once the locks release. Previously
queued work remains for normal recovery.

## Recorded Groq provider components

The [Task 5 record](verification/evidence/cli-groq-components.json) covers independent
Groq target and evaluator configuration, strict schema validation, shared budgets,
redacted finalized requests, retained replies and provider failures, and older JSON reads.
Real HTTP/HTTPS fixtures substitute only the provider boundary. Cancellation before
slot acquisition releases unused allowance. Uncertain dispatch retains it. Provider errors
retain validated retry timing without automatic retries. Empty length-limited replies
retain metadata and produce a typed incomplete evaluator result.

Fresh environments installed each platform's hashed lock and rebuilt wheel. The
installed `scripts/verify_groq.py` proof runs outside the checkout and makes two
HTTPS requests, validates an evaluator reply, and persists both observations through
real SQLite budgets. The script removes its temporary store and fixture server afterward.

The record includes exact full-suite results, source hashes, wheel hashes, review findings
and regressions. No live key or hosted model was used. At the Task 5 checkpoint, built-in
checks and four-role agents remained future work; Task 6 implements those components below.
Coordinator execution, reports, comparisons, and physical terminal-close acceptance remain
later gates at that checkpoint, whose daemon reported `execution_available: false`.

## Recorded broad pack and role contracts

The [Task 6 record](verification/evidence/cli-agents.json) covers the 20-check pack,
80-case generation, four typed role contracts, fixed controls, evidence provenance,
local canary/schema assertions, offline listing, and queued pack submission. It retains
review findings and regressions, final reviewer responses, source hashes, and wheel hashes.
The final suites passed 305 WSL tests and 304 native Windows tests with one existing
WSL-only skip. Ruff lint and formatting checks passed.

`scripts/verify_agents.py` runs against each final installed wheel outside the
checkout. It reads bundled resources and drives the public CLI. It uses a controlled
ready record and deterministic callbacks through real gateway preparation. It does not
start a daemon, send provider requests, or persist role observations through a coordinator.
Its synthetic target observation does not establish real model behavior. No live key is used.

At the Task 6 checkpoint, coordinator execution, semantic accuracy, comparisons, and report
export remained later gates. Its daemon reported `execution_available: false`.

## Recorded coordinator execution

The [Task 7 record](verification/evidence/cli-pipeline.json) covers persisted execution
through public CLI subprocesses, real detached daemons, verified loopback HTTPS, and
SQLite. Provider replies are deterministic fixtures. Completed broad-pack runs execute
80 target cases and all four roles, retaining pass, weakness, and incomplete inconclusive
judgments. Technical failures preserve prior findings and provider evidence.

The full suites passed 331 WSL tests and 330 native Windows tests with one existing
WSL-only skip. Those runs preceded a fixture-only SQLite cleanup fix; two focused
regressions per platform and the final installed-wheel proofs cover that fix. Runtime
package code was unchanged. Ruff passed. The legacy Starlette HTTPX warning remains.

The installed driver is `scripts/verify_pipeline.py`. It checks prepared intents
and generated inputs at provider receipt, two concurrent aliases under shared bounds,
and HTTP/invalid-proposal failures. It asserts an installed import, stops owned daemons,
and removes temporary stores. Exact final platform results, hashes, reviewer responses,
and proof output are retained in the record. Live Groq behavior, semantic accuracy, full
crash/cancellation acceptance, comparisons, and exports remain later gates.

## Recorded cancellation and crash recovery

The [Task 8 record](verification/evidence/cli-recovery.json) covers queued cancellation
without calls, issued reply preservation, cancellation while rate-limited, active drain,
stop timeout ownership, durable submission racing drain, and OS watcher interruption
without cancellation. Process termination is checked before dispatch, after validated target
receipt, and after a committed Reporter finding. Manual restart interrupts old work,
retains original uncertain request payloads and known evidence, and executes queued work.
Explicit retry uses the saved snapshot under new run/variant/operation IDs and leaves
all original source rows unchanged. Stale-owner append/overwrite checks supplement the
public process scenarios. Each lifecycle scenario pins one broad-pack check with three
attacks and one fixed control; Task 7 remains the full 80-case execution proof.

Final full suites passed 354 WSL tests and 353 native Windows tests with
one existing WSL-only skip. Ruff passed. The legacy Starlette HTTPX warning remains.
A reproduced ready-read/drain/claim race now exits cleanly after confirming same-generation
drain; unrelated admission/storage errors still propagate. Review strengthened reply-content
and uncertain-intent preservation checks; raw RED/GREEN results and full review reports
are retained in the record.

`scripts/verify_recovery.py` passed against both final installed wheels outside
the checkout. It shares the real scenario functions, asserts intended installed imports,
and records run identities, unknown operations, reply counts, watcher OS-event results,
and cleanup. Windows uses a dedicated watcher console guarded by exact process membership;
WSL sends SIGINT to its watcher. Loopback HTTPS responses remain deterministic. Hosted Groq,
semantic accuracy, physical keyboard/terminal close, sleep/shutdown, comparisons and exports
remain later gates.

## Recorded findings, comparisons, and exports

The [Task 9 record](verification/evidence/cli-results.json) covers coherent multi-run
SQLite reads, direct comparison counts, joined finding detail and cursor pagination,
and JSON/Markdown/HTML reports. Attack and control judgments, delivery outcomes, missing
judgments, and legacy unknown-kind cases have separate denominators. Selected but unrun
families remain visible. Planned historical case counts and remote revisions are unknown.
Check-order differences are execution mismatches; model-only changes are labeled cross-model.
No combined score, paired-input claim, or numerical delta is produced.

Final full suites passed 400 WSL tests and 397 native Windows tests with
3 platform skips. Ruff passed. The existing Starlette HTTPX deprecation warning remains.
The record retains the initial public CLI
RED, focused legacy/publication regressions, actual review reports and corrections. Review
reproduced and fixed carriage-return Markdown injection and isolated child CLI imports;
CR/CRLF, terminal/bidi controls and shadow-package regressions cover those changes.

Both installed `scripts/verify_results.py` proofs run outside the checkout and use
public CLI, real daemon, verified fixture HTTPS and SQLite. Full known-data evidence has
60 attacks (1 weakness, 58 passes, 1 inconclusive), 20 answered controls, 80 target cases,
and 182 observations. Smaller comparison/empty/partial scenarios are recorded separately.
Stopped repeated findings/comparison/exports make no provider calls or logical database
changes. Both final wheels' runtime/resource members match the frozen source.

An independent markdown-it-py renderer with raw HTML enabled checks final Markdown under
CommonMark and its default preset. Actual hostile scripts, links, and fences remain literal
code, with no active markup. A real browser opens final complete/comparison/empty/partial
HTML; visible text and SVG/table counts, DOM safety and network observations are retained
with screenshots. This establishes fixture report behavior, not hosted semantic accuracy.
Open the retained [complete](verification/evidence/cli-results-assets/completed-wsl.html),
[empty](verification/evidence/cli-results-assets/empty-wsl.html),
[partial](verification/evidence/cli-results-assets/partial-wsl.html), and
[cross-model](verification/evidence/cli-results-assets/cross-model-wsl.html) reports.
The [outcome screenshot](verification/evidence/cli-results-assets/completed-wsl.png) and
[hostile-family screenshot](verification/evidence/cli-results-assets/hostile-family-wsl.png)
record the visually inspected presentation.

Publication checks exercise independent writers, an external creator, interrupted writes,
unsafe leaves and cleanup. Atomic visibility is bounded to the tested local filesystems;
Windows power-loss durability and hostile ancestor-directory replacement are not claimed.
Native Windows skips the WSL-only mount case, POSIX directory fsync, and privileged symlink
creation when unavailable.
Live hosted-provider and terminal-close acceptance are recorded under Task 10 below.

## Provider-reported model prerequisite

The [metadata evidence record](verification/evidence/cli-provider-model.json) covers the
Task 10 prerequisite. Optional `ChatOutput.provider_model` records only the response's
`model`, after credential redaction. Missing, null, and empty metadata stay unknown.
Malformed types and invalid Unicode fail safely. Saved requests retain the requested model
separately. The reported value does not establish the serving deployment or remote revision.
Old observation documents remain readable and replay without byte rewrites.

Verified HTTPS regressions exercise target and strict evaluator replies, literal and escaped
credential reflection, raw and post-redaction Unicode, persistence, and three export formats.
The installed component proof checks the same identity distinction on Linux and native
Windows. It uses deterministic replies and two HTTPS requests per platform. It does not prove
queued CLI execution, hosted Groq behavior, semantic accuracy, or terminal-close survival.
Task 10 remains incomplete. Opt-in live tests and owned terminal scenarios are still pending.

## Clock correction prerequisite

The [clock evidence record](verification/evidence/cli-clock-correction.json) retains the
received-reply UTC reversal failure and the correction. Actual UTC labels can reverse;
private elapsed samples govern readiness and run deadlines. A precisely classified expired
heartbeat lets the same live owner renew and resume its control loop. Other ownership,
clock and storage failures remain errors. Existing stores require explicit stopped migration
to schema 4.

The final suites pass 487 CLI tests on WSL and 484 on native Windows, with three platform
skips. Three API compatibility tests also pass. Installed proof on both platforms preserves
reversed target and evaluator samples through verified HTTPS, storage and all three exports.
All 31 package members match source and wheel bytes. Explicit migration preserves all old
stored values in a stopped fixture containing two completed runs and 364 observations.

Earlier failed runs and the review-discovered pause window remain in the record. One native
reply fixture timed out across a one-hour interval; its physical cause is unproven. Physical
host sleep, real Groq execution and terminal application closure remain unverified. This
runtime prerequisite does not complete Task 10.

## Live Groq and terminal-close acceptance

The [Task 10 record](verification/evidence/cli-groq.json) covers hosted Groq traffic on a
free-tier account. The target was `openai/gpt-oss-20b`; all four evaluator roles used
`openai/gpt-oss-120b` at low reasoning effort, with a 6000 tokens-per-minute budget.

- Two full-pack trials (2026-11-13) each completed 80 of 80 cases with no missing
  judgments, no transport errors and matching provider-reported models. Each used about
  115k tokens.
- On native Windows (2026-11-16, commit `6f37995`), a run started inside its own console
  window. Closing that window about a minute in did not stop it: the same daemon finished
  80 of 80 judgments and then stopped cleanly through the public command. The close was
  sent by software (`WM_CLOSE`, the X-button request), not by a person.
- On WSL, the same window close was survived. WSL then stopped the whole distro, daemon
  included, about 15 seconds after the last WSL session ended. `daemon start` now warns
  about this on WSL; keep a WSL terminal open while runs are active.
- Manual review of every finding from three runs found each one real under the synthetic
  contract. Several repeat a forbidden marker while summarizing or refusing, which is a
  literal violation with lower practical severity.

Live runs exposed and fixed: Reporter text that contradicted settled findings (now
product-written for failed deterministic assertions), unquoted judge passes recorded as
inconclusive (judge prompt `broad-chat-v1.3`), and a single misquoted pass failing a whole
run (now downgraded). One run failed on a provider connection error and was correctly not
retried. Evaluator accuracy beyond the reviewed runs, a physical human terminal closure,
and host sleep or shutdown remain unverified.

## Feature-map convention

Each feature file has four sections: sub-features, user entry point, terminal driving,
and gotchas. Stable feature IDs support focused checks; [user journeys](features/user-journeys.md)
cover behavior spanning several features.

The format is adapted from [poteto's example](https://github.com/poteto/verification-skill-example/blob/main/.cursor/skills/verify-atlas/references/features/README.md)
and [verification guidance](https://github.com/cursor/plugins/blob/main/pstack/skills/create-verification-skill/SKILL.md).
The linked [article](https://x.com/poteto/article/2094457600259842065?lang=en) was reviewed
through its [readable mirror](https://threadnavigator.com/thread/2094457600259842065/).
