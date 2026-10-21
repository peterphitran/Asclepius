# Documentation

Updated: 2026-10-21.

## Current guidance

| Document | Purpose |
| --- | --- |
| [Product direction](specs/2026-10-21-personal-cli-direction.md) | Agreed CLI behavior, terminology, and unresolved choices. |
| [Current state](current-state.md) | Source-backed inventory and validation limits. |
| [Backend setup](../backend/README.md) | Commands for the existing FastAPI/Postgres API. |
| [Project context](../CONTEXT.md) | Short handoff for future work. |

The direction document records decisions from the conversation. It is not a finished
technical design or an implementation plan. There is currently no active CLI implementation
plan; the former web-platform plans have been superseded.

## Historical material

The [web-platform archive](archive/web-platform/README.md) preserves the earlier clinical
proposal, eight specs, two plans, and seven implementation notes. Each archived file
identifies itself as historical. Its commands, acceptance criteria, test results, and
completion statements must be read in that context.

## Keeping documentation current

- Put current product decisions in `docs/specs/` and link them from this index.
- Describe implemented behavior in `current-state.md`, with source references.
- Label proposed command examples and planned capabilities explicitly.
- Create an implementation plan after the technical design is settled.
- Preserve superseded material in `docs/archive/` with its date and replacement.
- Treat earlier test reports as historical evidence until verification is repeated.
