# Documentation

| Document | Owns |
| --- | --- |
| [Product](product.md) | Purpose, agreed scope, terminology, intended workflow, and open design decisions. |
| [Backend design](specs/backend-design.md) | Component ownership, SQLite queue/storage, daemon lifecycle, and runtime transition. |
| [Evaluation pipeline](specs/evaluation-pipeline.md) | Four agent contracts, their handoffs, and evidence provenance. |
| [RAG testing](specs/rag-testing.md) | Document fixtures, ingestion/readiness, retrieval evidence, mutation isolation, and cleanup. |
| [Design review](specs/design-review.md) | Cross-feature concerns, proposed defaults, and decisions needing discussion. |
| [Implementation plan](plans/2026-10-21-cli-evaluator.md) | Reviewable defaults, file ownership, task order, and hosted/Ollama acceptance gates. Task 1 verified; runtime execution still pending. |
| [Status](status.md) | Current implementation, reusable pieces, and transition gaps. |
| [Feature map](features/README.md) | User actions and their feature-specific verification paths. |
| [Development](development.md) | Environment setup, CLI and daemon commands, migrations, and test commands. |
| [Verification](verification.md) | Shared proof standards and map provenance. |

Read the product and status pages first, then only the feature area relevant to your task.

## Documentation rules

- Define each fact in its owning document; link to it elsewhere.
- Use the product vocabulary for planned features.
- Mark design candidates as proposed and commands as illustrative until implemented.
- Record code changes in status; record observed behavior in verification evidence.
- Put technical specs under `docs/specs/` and implementation plans under `docs/plans/`.
  Plan checkboxes track execution, not design approval or proof by themselves.
- Keep superseded proposals and task logs out of the current documentation tree.
