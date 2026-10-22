# Product

Status: agreed scope; technical design pending.

## Purpose

Asclepius is a personal terminal tool for evaluating the security of models, chatbots,
RAG applications, and other LLM systems the user owns or has permission to test.
It should support repeated evaluations of several applications and make their results
easy to inspect and compare.

## Agreed scope

| Area | Decision |
| --- | --- |
| Interface | Local CLI. |
| Applications | Save multiple named profiles with connection details and execution limits. |
| Execution | Manually start a detached background daemon; submit runs with bounded concurrency. |
| Storage | Local SQLite history and local report files. |
| Inspection | Run details, logs, findings, repeated-run comparisons, and charts. |
| Output | Generated local reports; JSON, Markdown, and HTML are candidate formats. |
| Accounts | No Asclepius sign-in or hosted account required. |
| Startup | Explicit manual control; no automatic operating-system startup. |

The personal-tool design does not require a persistent web frontend, hosted API,
Postgres, Redis, organization tenancy, or a team disclosure workflow. Credentials for
target applications and model providers may still be needed.

## Vocabulary

- **Target:** the model or application being evaluated.
- **Application profile:** saved connection settings and limits for a named target.
- **Check:** a security test with an objective, input strategy, and evaluation criteria.
- **Run:** one execution of selected checks against a profile, with its own ID and results.
- **Daemon:** the local background process that accepts and executes queued runs.
- **Finding:** evidence of a potential weakness, linked to its run and check.
- **Report:** an exported view of run results or comparisons.

Use these terms consistently in new documentation and commands. A profile name does
not identify a source folder or automatically start its target application.

## Intended workflow

The following commands illustrate the agreed interaction; they do not exist yet.
Exact subcommands, arguments, and flags remain to be designed.

```text
asclepius targets add my-rag-app ...connection details...
asclepius daemon start
asclepius run my-rag-app
asclepius runs list
asclepius runs watch <run-id>
asclepius report <run-id> --html
asclepius daemon stop
```

A target must be reachable before a run can use it. Closing the submitting terminal
should leave the daemon working. Computer sleep, shutdown, process crashes, and
restart recovery require explicit handling; detachment alone does not solve them.

## Design decisions still open

- Initial connection protocol, request mapping, response extraction, and credential storage.
- First checks, versioned case format, judging criteria, and evidence schema.
- Whether separate selector/generator/judge/reporter stages are useful; no provider
  or orchestration library has been selected.
- SQLite schema, configuration snapshots, data paths, and data migration policy.
- Daemon readiness, single-instance behavior, submission while stopped, stop/drain
  semantics, cancellation, retries, and interrupted-run recovery.
- Concurrency, timeout, request, and cost limits.
- Comparison metrics, compatibility rules, report formats, and chart types.
- Which existing implementation to adapt or retire.

Detailed user behaviors belong in the [feature map](features/README.md).
