# Personal CLI Direction

Status: agreed product direction; technical design pending.
Recorded: 2026-10-21.

## Purpose

Asclepius is intended to help the user evaluate the security of models and RAG applications
they own or control. The focus has broadened beyond medical assistants. The immediate
product is a personal local tool, operated through a terminal.

## Agreed decisions

| Area | Decision |
| --- | --- |
| Interface | CLI; the web frontend has been removed. |
| Application profiles | Save multiple named targets and their connection details. |
| Execution | Submit runs to a detached background daemon with bounded concurrency. |
| Startup | Start and stop the daemon manually; no automatic startup integration. |
| Accounts | No Asclepius account, product login, or multi-user workflow required. |
| Storage | Local SQLite run history and local report files. |
| Inspection | Terminal history, run details, logs, and comparisons across runs. |
| Charts | Generated local reports/charts; no persistent web application required. |
| Infrastructure | Redis, a hosted API, and Postgres are not required by this direction. |

Target applications or model providers may still require their own API credentials.
That is separate from signing into Asclepius.

## Terms

- **Application profile / target:** a saved name, endpoint, request format, response
  extraction rules, and execution limits. The name identifies a connection profile;
  it does not make the tool discover or execute a source-code folder automatically.
- **Run:** one evaluation using a profile and selected checks, with its own ID,
  configuration, timestamps, results, and status. A profile can have many runs.
- **Daemon:** the local process that stays alive after the submitting terminal closes.
  It takes queued runs, executes checks, and persists progress.
- **Bounded concurrency:** a limit on simultaneous checks or requests. Background
  execution does not mean unlimited parallel requests.
- **Finding:** evidence of a potential weakness from a run, available for inspection.

The existing backend calls runs `sweeps` and stores `campaigns`. How those entities map
to the CLI remains a design question; this document does not rename code.

## Intended workflow

These commands illustrate the intended interface. They do not exist yet, and exact
flags and syntax remain to be designed.

```text
asclepius targets add my-rag-app ...connection details...
asclepius daemon start
asclepius run my-rag-app
asclepius runs list
asclepius runs watch <run-id>
asclepius report <run-id> --html
asclepius daemon stop
```

The target application must already be reachable. A run uses saved connection details
to send test requests and save results. Closing a terminal should not stop the daemon.
Detachment alone does not make work continue through computer sleep, shutdown, or a
process crash; restart and recovery behavior needs a separate design.

## History and charts

Each run needs its own persisted record so several applications and repeated runs
remain distinguishable. Discussed outputs include run lists, findings, logs, run
comparisons, and JSON/Markdown/HTML reports with charts.

Comparison design should account for target/configuration changes, check versions,
and completed versus failed checks so a different test selection is not mistaken
for a security improvement. Exact metrics, chart types, and report formats remain
to be specified.

## Remaining design work

- First supported target connection format and credential handling.
- Initial evaluation checks, judging behavior, and evidence format.
- Whether the historical four-agent design is useful for the initial CLI; provider
  choices and orchestration libraries have not been selected for it.
- SQLite schema, profile/run configuration snapshots, and local data paths.
- Daemon startup, single-instance handling, submission, stop/cancel behavior, failure
  reporting, interrupted-run recovery, and retry semantics.
- Run/target concurrency limits, timeouts, and request/cost budgets.
- Which existing API, Postgres, migration, and lifecycle code to reuse, adapt, retain
  for reference, or retire. Do not assume Postgres row locks translate to SQLite.
- First reproducible CLI-to-target-to-report verification scenario.

## Scope boundary

The direction does not require a browser dashboard, hosted service, team accounts,
organization tenancy, Windows auto-start, Redis queue, or clinical-only case suite.
Those existed as earlier proposals or legacy infrastructure, not requirements for
the personal tool. Optional observability and broader adapters can be considered
after the local evaluation flow is designed.

## Implementation status

Only frontend removal and documentation reconciliation have been performed for this
direction. See [current state](../current-state.md) for the remaining implementation.
