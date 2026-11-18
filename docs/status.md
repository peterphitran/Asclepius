# Implementation Status

Implementation checkpoint on 2026-10-29 America/Chicago, branch `codex/cli-evaluator`.

Tasks 1 through 9 implement CLI management, SQLite history, manual detached daemon
control, provider components, the broad pack, and persisted evaluation execution. The
daemon claims bounded queued work and routes it through the coordinator. Prepared request
intent precedes every call; observations precede role acceptance; stage failures preserve
partial findings. Saved findings, labeled comparisons, and local JSON/Markdown/HTML reports
with outcome charts are available without a running daemon. The public runtime proof uses
deterministic providers over loopback HTTPS.
Saved chat observations now retain optional `provider_model` evidence from the response,
separately from the requested model. Older observations keep this value unknown.
The [metadata prerequisite record](verification/evidence/cli-provider-model.json) covers
the offline checks. Task 10 live acceptance (2026-11-16) ran the full pack against hosted
Groq and survived a console window close on native Windows; see
[verification](verification.md#live-groq-and-terminal-close-acceptance).

Task 11 adds local Ollama targets with Groq as the evaluator. Task 12 retired the legacy
web runtime: the FastAPI app, Postgres models and Alembic migrations, Docker Compose file,
web frontend, legacy API tests and API reference are removed, with their dependencies. They
remain in git history. The original checkout's uncommitted sweep-lifecycle work for that
API is preserved on the local branch `wip/legacy-sweep-lifecycle`.

## Existing code

| Area | Location | Current behavior |
| --- | --- | --- |
| CLI | `asclepius/cli.py` | Help, configuration, initialization, profiles, run/history/finding reads, watch, cancellation, and retry commands. |
| Services | `asclepius/services.py` | Complete supplied-plan validation, credential presence checks, pinned snapshots, cancellation, and linked retries. Submission makes no provider calls or implicit daemon launch. |
| Local storage | `asclepius/storage.py` | SQLite snapshots, paginated reads, profile tombstones, claims, fenced writes, atomic stage/evidence commits, and orphan interruption. Coordinator uses these transactions for execution. |
| Daemon control | `asclepius/process.py`, `daemon.py` | Manual detached start, generation-bound readiness, heartbeat, duplicate exclusion, drain/stop. Claims within shared limits, heartbeats independently, and drains active work. |
| Bounds | `asclepius/limits.py` | Shared request gates/rates and durable call/completion reservations, connected to provider components. Cancellation before dispatch releases allowance; uncertain dispatch retains it. |
| Provider components | `asclepius/transport.py`, `adapters/chat.py`, `adapters/ollama.py`, `models.py` | Bounded HTTPS (plain HTTP only on loopback for a local Ollama target), independent credentials, redacted immutable requests, strict evaluator schemas, typed errors and validated retry timing. No automatic retries; coordinator persists their evidence. |
| Saved results and exports | `asclepius/results.py`, `exports.py` | Coherent comparison summaries, separate attack/control/legacy outcomes, inert JSON/Markdown/HTML and atomic local publication. |
| Checks and agents | `asclepius/checks.py`, `agents.py`, `packs/`, `prompts/` | Twenty pinned checks, three generated attacks and one code-owned control per check. Four role contracts require an injected prepared-request dispatch. Coordinator supplies durable dispatch. |
| Local migrations | `asclepius/maintenance.py`, `migrations/` | New schema v4 and explicit stopped v1/v2/v3 upgrade, OS/maintenance locking, rollback, and local-only path policy. |
| Tests | `tests/cli/` | Real HTTP/HTTPS provider fixtures, SQLite persistence and budgets, process checks, and a check that the CLI runs with every legacy web dependency blocked. See the [Task 7 execution results](verification/evidence/cli-pipeline.json) and [Task 8 recovery results](verification/evidence/cli-recovery.json). Native Windows skips the WSL-only mount test. |

## Missing product capabilities

Evaluator accuracy beyond the reviewed live runs, a physical human terminal closure, and
host sleep or shutdown remain unverified. On WSL the daemon stops when WSL shuts its Linux
side down after the last WSL session closes. Saved comparisons and exports use deterministic fixture evidence in
[Task 9 verification](verification/evidence/cli-results.json).
Legacy plans remain readable and can queue, but the role runner requires three strategies
per check. Legacy judgments without check lineage cannot initiate Reporter. JSON-schema
violation findings require the entire reply as evidence within the 4096-byte quote cap.
Startup interrupts prior owned runs without replaying uncertain requests. Task 8 verifies
queued and active cancellation, drain timeout, watcher OS interruption, three process-crash
boundaries, manual recovery, and linked retry through public CLI subprocesses, detached
daemons, HTTPS fixtures, and SQLite on WSL and native Windows. Task 7 proves normal
execution. Deterministic fixture judgments do not establish live model accuracy.
Submission requires a fresh elapsed heartbeat and both live generation locks inside the
enqueue transaction. Released ownership rejects new queue work after a hard crash.
A software-sent console close was survived on native Windows with a completed live run.
One native creator-exit test failed during review, then passed reruns and ten extra probes;
its cause remains unresolved.

For tested observations and limits see [verification](verification.md). Source presence
and old passing-test reports do not establish a complete evaluation system.
