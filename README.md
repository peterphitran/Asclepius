# Asclepius

A personal security lab for evaluating models and RAG applications you own or control.

The agreed direction is a local CLI: save named application profiles, start a background
daemon manually, launch bounded evaluation runs, and inspect history and generated
reports from the terminal. Run data will live in SQLite, with reports and charts as
local files. No product account or sign-in is required.

## Current state

The project is transitioning from a web dashboard to that CLI. The frontend was removed
on 2026-10-21. The published backend contains the initial FastAPI health endpoint,
configuration, tests, and Postgres/Redis development infrastructure.

The original development checkout is further ahead: it has 43 additional local
commits for database/API work, plus uncommitted CRUD and lifecycle changes. That
backend work is outside the frontend-removal and documentation PRs. The
[implementation inventory](docs/current-state.md) distinguishes both checkpoints.

The CLI, SQLite storage, daemon, target execution, evaluation pipeline, and report
generation have not been implemented. Even in the more advanced local checkout,
campaign creation only persists queued records; it does not launch an evaluation.

## Documentation

- [Documentation index](docs/README.md): current guidance and historical material.
- [Product direction](docs/specs/2026-10-21-personal-cli-direction.md): agreed decisions,
  proposed command examples, and remaining design questions.
- [Implementation status](docs/current-state.md): what exists and what is unverified.
- [Existing backend setup](backend/README.md): running and checking the legacy API.
- [Archived web-platform material](docs/archive/web-platform/README.md): previous
  clinical proposal, specs, implementation plans, and task reports.

The old Redis/Postgres worker plans are archived. They are reference material for
future design work, not an active implementation checklist.
