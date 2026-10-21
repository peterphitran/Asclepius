# Archived Web and Clinical Platform

Archived: 2026-10-21. Superseded by the
[personal CLI direction](../../specs/2026-10-21-personal-cli-direction.md).

These documents preserve product history and implementation evidence. They are not
an active backlog, executable instructions, or proof that their acceptance criteria
were met. Original dates, checkboxes, source paths, and report claims are retained.
References to `frontend/`, `docs/superpowers/`, and `.superpowers/sdd/` describe original
locations, some of which no longer exist.

## Earlier proposal and specifications

| Document | Disposition for the personal CLI |
| --- | --- |
| [Clinical proposal](product-proposal.md) | Historical only; includes nonexistent scripts and unimplemented features. |
| [Platform architecture](specs/2026-07-29-agent-platform-architecture.md) | Reassess lifecycle concepts; its web, Postgres, Redis, and review requirements are superseded. |
| [Worker execution](specs/2026-07-29-worker-execution.md) | Bounded work/persistence are reference concepts; Redis/Compose execution is not required. |
| [Agent pipeline](specs/2026-07-29-agent-pipeline.md) | Structured stages may be useful; four agents and provider choices are unsettled. |
| [Attack cases](specs/2026-07-29-attack-cases.md) | Versioned cases may be useful; clinical examples and a fixed nineteen-case target need review. |
| [Target adapter](specs/2026-07-29-reference-target-adapter.md) | HTTP contracts/errors are reference ideas; the initial profile contract needs design. |
| [Frontend progress](specs/2026-07-29-frontend-live-progress.md) | Retired with frontend removal. |
| [Sidebar design](specs/2026-07-29-live-sidebar-data-design.md) | Retired with frontend removal. |
| [E2E and operations](specs/2026-07-29-e2e-verification-and-operations.md) | Replace the browser/login/Postgres/Redis scenario with a CLI scenario. |

## Earlier implementation plans

- [Architecture plan](plans/2026-07-29-agent-platform-architecture.md): partially implemented;
  do not resume its remaining Redis/API tasks as the CLI roadmap.
- [Sidebar plan](plans/2026-07-29-live-sidebar-data.md): historical frontend work.

## Implementation notes

- [Progress ledger](implementation-notes/progress.md)
- [Task 1 brief](implementation-notes/task-1-brief.md)
- [Task 1 report](implementation-notes/task-1-report.md)
- [Task 1 review package](implementation-notes/task-1-review-package.md)
- [Task 1 fix review package](implementation-notes/task-1-fix-review-package.md)
- [Task 2 brief](implementation-notes/task-2-brief.md)
- [Task 2 report](implementation-notes/task-2-report.md)

Reports capture different points in time. A passing test or completed task is not
evidence of current runtime health or a complete evaluation pipeline. See the
[current source inventory](../../current-state.md) before deciding what to reuse.
