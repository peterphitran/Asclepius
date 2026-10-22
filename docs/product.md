# Product

Status: agreed scope. The backend design records proposed implementation defaults.

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
| Integration order | Hosted model API first, Ollama second, then RAGbot for ingestion/retrieval coverage. Keep the core schema application-neutral. |
| Initial provider | Groq for the target and evaluator roles, configured independently. Exact models remain to be selected. |
| Execution | Manually start a detached background daemon; submit runs with bounded concurrency. |
| Evaluation | Retain Selector, Generator, Judge, and Reporter as four separate agent roles. |
| Initial coverage | Broad attack pack for the target's supported capabilities, not a minimal smoke-only pack. Execution remains bounded. |
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
- **Agent:** one evaluation role in the four-agent pipeline.
- **Worker:** execution capacity within the daemon, distinct from an agent's responsibility.
- **Finding:** evidence of a potential weakness, linked to its run and check.
- **Report:** an exported view of run results or comparisons.

Use these terms consistently in new documentation and commands. A profile name does
not identify a source folder or automatically start its target application.

## Intended workflow

The following commands illustrate the agreed full interaction. Profile management and
persisted inspection exist; daemon startup, built-in packs, evaluation execution, and
reports do not. See [development](development.md) for implemented syntax and limitations.

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

## Backend design

The [backend design](specs/backend-design.md) owns component boundaries, local queue and
storage, lifecycle states, control policy, and the transition from the existing API.
The [evaluation pipeline](specs/evaluation-pipeline.md) owns agent contracts and evidence
handoffs. These designs do not describe implemented capabilities.
The [RAG testing design](specs/rag-testing.md) extends checks to ingestion, direct retrieval,
and grounding where the target exposes those capabilities, without adding a frontend.

## Design decisions still open

- Exact check/rubric definitions, stage schemas, prompts, and initial Groq model selections.
- Target request-template and response-selector syntax, and credential-reference implementation.
- SQLite DDL and migrations, operating-system paths and locks, and numeric execution limits.
- Comparison metrics, report formats, chart types, and optional data import.

Detailed user behaviors belong in the [feature map](features/README.md).
The [design review](specs/design-review.md) prioritizes the remaining product choices
and distinguishes proposed implementation defaults from agreed scope.
