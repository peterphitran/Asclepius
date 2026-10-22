# Application Profiles

Status: profile CRUD and SQLite history preservation are implemented. Supplied-plan
submission is tested with controlled readiness, not an actual daemon. See
[development](../development.md#manage-local-profiles-and-inspect-history).

## Sub-features

- `profile-save`: store a profile's name, connection details, and limits.
- `profile-list`: find saved applications.
- `profile-select`: choose the target for a run.
- `profile-reuse`: associate repeated runs with the same application.
- `profile-edit-policy`: preserve immutable configuration snapshots on existing runs.

## How to get to it (user POV)

Register an application once, then select its profile by name when submitting a run.
Use `targets add <name> --config <target.toml>`, `targets list`, `targets show <name-or-id>`,
`targets edit <name-or-id> --config <target.toml>`, and `targets remove <name-or-id>`.
Names are unique and IDs survive edits. Removal retains the identity as a tombstone.

## Driving it with the terminal

Create profiles for two controlled targets, list them from a new process, and submit a
run using one name. Match received fixture requests and the resulting run to that profile.
Cover empty storage, invalid settings, and ambiguous names.

## Gotchas

- A profile name does not start the target or discover a source folder.
- Stable identities are needed even when names or endpoints change.
- Credentials belong to the connection design, not to a product login.
- Renaming/removing a profile never deletes its historical identity or changes accepted
  run snapshots. Queued work uses saved configuration. Removal blocks new submissions
  and retries; removed names remain reserved. Ambiguous name/ID selectors fail explicitly.
- Resolve secrets and revalidate execution permission when work begins; missing or
  revoked credentials fail clearly rather than falling back to another identity.
- Two profiles may reference one target. Share scheduling/resource limits using an
  explicit canonical resource key; names alone do not provide isolation.
- Hosted API, Ollama, and RAGbot integrations share the profile schema. Non-RAG targets must not
  require corpus settings or fabricated retrieval capabilities; see the
  [general schema boundary](../specs/backend-design.md#logical-records).
