# Backend design

Status: implementation design for the personal CLI. Manual control and local management
exist; evaluation runtime integration remains incomplete. See [current status](../status.md).
Product choices come from [product scope](../product.md). Technical defaults below are
proposed implementation choices, not claims about the current API.

## Runtime boundary

Keep Python as the implementation language. The CLI and a manually started daemon use
the same core services and SQLite repository. CLI commands submit work directly to the
repository. The daemon polls persisted queued runs. No HTTP API or Redis broker sits
between them.

One daemon owns execution for one canonical data directory. Several CLI processes can
inspect history or submit work. Workers provide bounded execution capacity inside that
daemon. They execute the [four-agent pipeline](evaluation-pipeline.md).

## Component ownership

| Component | Owns |
| --- | --- |
| CLI | Arguments, configuration selection, user output, and calls to application services. |
| Application services | Profile management, run submission, cancellation, retry creation, history, and export requests. |
| Domain | Typed profiles, check plans, run states, observations, judgments, findings, and legal transitions. |
| Daemon | Instance ownership, readiness, polling, shutdown, and worker scheduling. |
| Coordinator | Agent ordering, execution limits, cancellation checkpoints, and persisted stage transitions. |
| Agent roles | Selector, Generator, Judge, and Reporter contracts. |
| Target adapters | Requests to evaluated applications and normalized observations. |
| Model gateway | Provider calls used by agents, response parsing, and provider errors. |
| SQLite repository | Transactions, durable queue records, constraints, and read queries. |
| Exporters | Local report files and charts derived from saved results. |

CLI and daemon entry points call core services without constructing FastAPI requests.
Agents return domain values to the coordinator. They do not own database transactions,
run status, or arbitrary tool access. Target and provider traffic use separate adapters.

The module names above describe ownership, not a required directory for every row.
Concrete package layout and libraries belong in the implementation plan.

## Submission and inspection

A profile can be created without starting the daemon. Submission requires the selected
data directory's persisted ready record with a heartbeat no more than ten seconds old.
Stopped, draining, or stale readiness returns an actionable error and creates no run.
After abrupt owner loss, a fresh record may still accept queued work within that window.
This is durable acceptance, not synchronous OS liveness; that work waits for manual restart.
Do not start the daemon automatically. Status and execution ownership use OS locks.

The submission service validates the profile, selected checks, required capabilities,
credentials references, and limits. It stores one queued run with immutable configuration
snapshots in a transaction. Its returned run ID means durable acceptance, not execution.

A shutdown can race with submission. Accepted work remains queued until a daemon starts
again. The CLI must show the persisted state rather than promise immediate execution.
Profile inspection, history, finding reads, and exports work while the daemon is stopped.
Watching a run reads persisted events and stops on a final state or user interruption.

## Local storage

A shared data-directory option selects the same database and instance for every command.
Choose an operating-system application-data default during implementation. Keep the
database, instance metadata, logs, and report output under that directory unless the
user chooses an export path. Distinct data directories provide distinct tool instances.

Use a local SQLite database with foreign keys, schema versioning, and WAL journaling.
Readers can proceed while another connection writes, but SQLite still has one writer.
Keep transactions short, use a bounded busy timeout, and return a clear contention error.
Never await a target or provider call inside a database transaction.

WAL requires local same-host storage. Concurrent Windows and WSL instances must use
separate data directories. Do not treat a network share as a supported runtime store.
See SQLite's [WAL](https://sqlite.org/wal.html) and
[transaction](https://sqlite.org/lang_transaction.html) documentation.

### Logical records

Use a hosted model API as the first real target, Ollama second, and RAGbot afterward
for ingestion/retrieval coverage. None defines the core domain model. Keep profiles, runs,
checks, work items, observations, judgments, findings, and events application-neutral.
Select checks by adapter capabilities, not a hardcoded application-type branch.

Proposed schema boundary: every operation/observation has a common envelope with its
identity, operation kind, schema version, provenance, timing, execution status, and
evidence references. Operation-specific inputs and outputs use typed, versioned payloads
validated at the adapter boundary; this is not an unrestricted metadata dictionary.
Document/chunk IDs, corpus manifests, retrieval ranks, and ingestion receipts belong
to optional RAG contracts, not required columns on every profile, run, or finding.
Absence of retrieval support means unsupported, not failed or zero-scored.

RAGbot endpoint names, request fields, and response selectors belong to its adapter
configuration. They must not become assumptions in the scheduler, agent contracts,
or generic history/report queries. A future non-RAG target can use the same run lifecycle
without dummy corpus records or RAG-specific metrics.

| Record | Purpose and constraints |
| --- | --- |
| Profile | Stable ID, unique display name, connection configuration, credential references, limits, and revision. |
| Run | ID, profile identity, immutable profile/check/model/limit snapshots, status, cancellation request, timestamps, failure detail, and optional source run ID. |
| Work item | Stable check identity/version and variant identity, with execution state and completed outputs. |
| Stage record | Work-item ID, stage, invocation attempt, validated input/output references, timestamps, and error details. |
| Observation | Request identity, normalized reply or transport error, bounded evidence, latency, and outcome certainty. |
| Judgment | Variant reference, rubric version, diagnostic assertions/metrics, optional security verdict, and supporting evidence. |
| Finding | Run/variant/judgment references, severity, description, reproduction context, and recommendation. |
| Run event | Ordered persisted lifecycle/progress event for terminal inspection. |
| Daemon control | Instance identity, readiness, heartbeat, and stop request. |

Use non-null work-item identities for stage uniqueness, including check-level stages
that run before variants exist. A completed stage output has one committed identity.
A judgment-backed finding has a unique run/variant identity in the initial design.
A rerun under a new run ID is intentional new work, not a duplicate write.

Store stage completion, its validated output, and the corresponding event together.
Snapshot configuration before evaluation so editing a profile cannot rewrite an old
run's meaning. Exact DDL, retention, and artifact-size limits remain implementation work.
Pin full check definitions and prompt/model configuration, not only mutable file paths.

Initialize a new database transactionally under an exclusive maintenance lock. Existing
commands reject unsupported schema versions instead of modifying a database silently.
Repository operations must also respect the maintenance lock so initialization cannot
race with another CLI process opening a write transaction.

## Daemon ownership and scheduling

Start acquires an operating-system lock for the data directory and holds it for the
daemon lifetime. A second start reports the existing instance rather than starting a
second scheduler. A PID file or heartbeat alone is not the ownership guarantee.

Start returns success only after the child has its lock, has opened the compatible
schema, and has written a ready record with a fresh instance ID. Redirect standard
streams so the child does not depend on its launching terminal. Verify terminal-close
survival on each supported operating system before declaring detachment working.

Each claim uses a brief SQLite write transaction and conditional queued-to-running
update. Save the owner instance ID and a run-start event in the same transaction.
Do not translate the existing Postgres row-lock code mechanically.

Bound active runs and outbound requests separately. Apply per-target limits as well as
global limits. Agent model calls also have concurrency, timeout, request, and token limits.
Select numeric defaults after fixture verification rather than inheriting demo counts.
Cancellation and daemon control remain responsive when the execution slots are full.

## Run states and control policy

| State | Meaning | Allowed next states |
| --- | --- | --- |
| queued | Accepted, awaiting execution. | running, cancelled |
| running | Claimed by the current daemon. | completed, failed, cancelled, interrupted |
| completed | Planned work reached valid final evaluation outcomes. | None |
| failed | A technical failure prevented complete evaluation. | None |
| cancelled | The user deliberately stopped this run. | None |
| interrupted | Execution lost its owner before a final outcome. | None |

A completed run can contain weaknesses or inconclusive judgments. Completion does not
mean the target passed. Failed, cancelled, and interrupted runs retain partial evidence.
An unrecoverable execution error stops new work for that run. Bound and settle its
in-flight requests before finalizing failed, preserving the observations already received.

Cancellation records a request. For queued work, change it to cancelled without dispatch.
For active work, stop scheduling new outbound calls, let already-issued calls finish
within their timeout, save any replies, and finalize cancelled. A forced process exit is
an interruption, not a graceful cancellation.

The default daemon stop drains active runs, rejects new submissions once draining is
recorded, and leaves waiting runs queued. No new queued runs are claimed during drain.
A bounded stop timeout reports that work is still active. It does not silently kill it.

Retry creates a new run ID linked to a failed, cancelled, or interrupted source run.
Use its saved evaluation configuration rather than the profile's latest edits.
Resolve credential references again and validate current execution permissions and
limits before acceptance. Keep the previous run and evidence unchanged.
A retry may generate new variants. Exact-input replay is a separate feature; do not
describe a linked rerun as an exact reproduction unless it actually uses saved inputs.

## Crash recovery and request uncertainty

After acquiring exclusive instance ownership, a restarted daemon marks runs still
owned by the lost instance as interrupted. Preserve their outputs and identify unfinished
stage records. Continue ordinary queued runs only after the daemon is manually started.

Do not automatically replay interrupted target requests. A crash can occur after the
target receives a request but before the observation is committed. Mark that observation
unknown rather than reporting success or promising exactly-once execution.

The initial recovery path is an explicit retry as a linked new run. In-place resume
and reuse of outputs across runs are deferred. Within one run, duplicate writes or
repeated persistence operations return the already committed stage/result.

This distinguishes durable history from resuming computation. The initial tool preserves
work across restarts without pretending every interrupted operation is safe to replay.

## Connections and model configuration

Proposed first target adapter: a single-turn HTTP JSON chat endpoint. A profile contains
a URL, a structured request template, a reply-field selector, timeouts, response limits,
and header credential references. Define the template/selector syntax before coding.
No arbitrary expression evaluator is required.

Resolve credentials from the execution environment or a configured secret reference.
Do not store credential values in run snapshots or report artifacts.
A target capability declaration identifies checks the adapter can support. A chat-only
connection cannot run document-ingestion checks merely because the app uses RAG.
The [RAG design](rag-testing.md) defines additional ingestion, readiness, retrieval,
update/delete, and isolation contracts. Chat is an initial transport slice, not complete
RAG coverage. The coordinator executes bounded typed operation plans; no new agent role
or embedded vector database is required.

Proposed defaults from the [feature review](design-review.md): resolve credentials and
revalidate execution permission when claiming work, without changing saved configuration.
Share concurrency/resource limits across profile aliases for the same destination.
Redact configured secret values before storing evidence and sanitize untrusted output.
Do not forward credentials across origins on redirects automatically.
Mutating tests require explicit opt-in and isolated, proven run-owned resources.
Chat/session side effects and distinct setup/query actors follow the RAG contract too.
Persist cleanup status/resource ownership separately from run evaluation state, including
after cancellation or uncertain external outcomes. Never replay uncertain mutations.
Reserve a separate bounded cleanup budget; graceful drain includes cleanup or explicitly
records unresolved resources. Evaluation exhaustion must not silently disable cleanup.

The four roles use a shared provider-neutral model gateway with separately versioned
prompts and validated outputs. The same provider/model can serve several roles.
Groq is selected for the first hosted target and evaluator roles. Keep target connection
configuration separate from evaluator configuration, with independently selected models,
generation settings, secret references, and budgets. Evaluator configuration supports
per-role settings; do not inherit the target model or credentials implicitly. A user
may explicitly reference the same secret for both without copying its value.
Pin both configurations in each run snapshot so changing one does not silently change
the other. Sharing a provider/model does not establish independent judging quality;
retain evidence and label the evaluator identity for later cross-model comparisons.
Exact Groq models and any role that uses deterministic logic remain open choices.
Future providers belong behind the target/model-gateway boundaries, not provider-specific
run states or finding schemas. Do not assume every provider supports identical protocols.
A deterministic gateway fixture is needed for repeatable pipeline verification.

## Results, comparisons, and export

Persist all judgment outcomes and errors, including those that are not findings. Report planned/completed
work, weaknesses, inconclusive judgments, and execution failures separately.

Comparisons check profile snapshots, check/rubric versions, and evaluation configuration
before presenting differences. Label incompatible or incomplete runs explicitly.

Exporters read saved results while the daemon is stopped. They do not invoke the agents,
model gateway, or target adapter. Write generated files through a temporary file and
atomic replacement, with a defined overwrite policy.
Proposed first-milestone defaults: no automatic history purge, refuse an existing export
path unless overwrite is explicit, and label live-run exports as point-in-time snapshots.
Preserve profile identity/history when a profile is renamed or removed.

## Transition from the current API

| Current area | Treatment |
| --- | --- |
| FastAPI routers, JWT login, users/organizations, CORS, dashboard routes | Retire from the CLI execution path after replacements are usable. |
| Postgres ORM, engine, Alembic revisions | Replace for new CLI state with the SQLite repository and its migrations. Preserve existing databases. |
| Campaign/sweep API schemas | Reassess as profile/run domain records. Do not expose old API payloads as CLI core types. |
| Lifecycle service | Reuse transition ideas and error cases; implement SQLite ownership/transactions explicitly. |
| Findings | Reuse evidence concepts; replace clinical-only fields and define generic provenance. |
| Redis Compose service | Remove when retiring the old runtime; it is not used by the new queue. |
| Seed data | Keep only as disposable historical fixtures until generic test fixtures exist. |
| Four-agent enums | Keep the role names; add actual contracts and implementations. |

Do not delete the old implementation or migrate user data as part of this design update.
The implementation plan must identify replacement proofs and retire old callers when
their replacements work. Import of existing Postgres records is a separate future feature.

## Implementation acceptance

Use the [verification guide](../verification.md) and [user journeys](../features/user-journeys.md).
Required proofs include two CLI processes submitting/reading against one daemon,
exclusive instance ownership, atomic claims, bounded concurrent requests, graceful
drain/cancel behavior, crash marking, linked retry, and immutable snapshots.

Also prove the real four-role path with fixture target/provider boundaries, durable
findings, compatible comparisons, and report export without new network/model calls.
Verify terminal-close survival on Windows and WSL separately.
Prove submission, execution, judgments, history, and export against a real hosted model
API first, then Ollama, without corpus or retrieval fields. Fixtures supplement these
paths with controlled failures and repeatable assertions; scripted responses do not
establish real-model evaluation. Add RAGbot's capability-specific acceptance afterward.

Before coding, resolve exact schema/constraints, locking implementation, check format,
template/selector syntax, first provider/checks, and numeric limits. This document does not scaffold a package,
add dependencies, change databases, or remove the runtime.
