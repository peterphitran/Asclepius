# Asclepius

A personal CLI security lab for models, chatbots, RAG applications, and other LLM
systems you own or have permission to test.

Save application profiles, start background evaluations manually, inspect run history,
and generate local reports and charts.

The `asclepius` package is the whole runtime: run `asclepius` or `python -m asclepius` for
help, profiles, evaluation runs, history, findings, comparisons and reports. It stores
everything in a local SQLite directory and needs no database server, web API or Docker.
Examples live in `examples/`. Use [implementation status](docs/status.md) and
[development setup](docs/development.md) for current behavior and commands.

Start with the [documentation index](docs/README.md).
The [backend design](docs/specs/backend-design.md) describes the CLI runtime
and four-agent execution architecture.
