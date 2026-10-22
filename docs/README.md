# Documentation

| Document | Owns |
| --- | --- |
| [Product](product.md) | Purpose, agreed scope, terminology, intended workflow, and open design decisions. |
| [Status](status.md) | Current implementation, reusable pieces, and transition gaps. |
| [Feature map](features/README.md) | User actions and their feature-specific verification paths. |
| [Development](development.md) | Environment setup, API startup, migrations, and test commands. |
| [API reference](reference/existing-api.md) | Existing HTTP operations and their limitations. |
| [Verification](verification.md) | Shared proof standards, recorded checks, and map provenance. |

Read the product and status pages first, then only the feature area relevant to your task.

## Documentation rules

- Define each fact in its owning document; link to it elsewhere.
- Use the product vocabulary for planned features. Keep old code identifiers only in
  status and API reference where they help locate implementation.
- Mark design candidates as proposed and commands as illustrative until implemented.
- Record code changes in status; record observed behavior in verification evidence.
- Put future technical specs under `docs/specs/` when needed. There is no active
  implementation plan yet.
- Keep superseded proposals and task logs out of the current documentation tree.
