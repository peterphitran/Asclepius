# Application Profiles

Status: planned. Save named connection settings for applications you want to evaluate.
The CLI foundation can validate target/evaluator TOML files as described in
[development](../development.md#cli-foundation). Saving profiles and submitting runs
are not implemented yet.

## Sub-features

- `profile-save`: store a profile's name, connection details, and limits.
- `profile-list`: find saved applications.
- `profile-select`: choose the target for a run.
- `profile-reuse`: associate repeated runs with the same application.
- `profile-edit-policy`: preserve immutable configuration snapshots on existing runs.

## How to get to it (user POV)

Register an application once, then select its profile by name when submitting a run.
Add/list/edit syntax remains open. The backend design requires unique profile names
and stable profile IDs.

## Driving it with the terminal

Create profiles for two controlled targets, list them from a new process, and submit a
run using one name. Match received fixture requests and the resulting run to that profile.
Cover empty storage, invalid settings, and ambiguous names.

## Gotchas

- A profile name does not start the target or discover a source folder.
- Stable identities are needed even when names or endpoints change.
- Credentials belong to the connection design, not to a product login.
- Proposed default: renaming/removing a profile never deletes its historical identity
  or changes accepted run snapshots. Queued work uses its saved configuration.
- Resolve secrets and revalidate execution permission when work begins; missing or
  revoked credentials fail clearly rather than falling back to another identity.
- Two profiles may reference one target. Share scheduling/resource limits using an
  explicit canonical resource key; names alone do not provide isolation.
- Hosted API, Ollama, and RAGbot integrations share the profile schema. Non-RAG targets must not
  require corpus settings or fabricated retrieval capabilities; see the
  [general schema boundary](../specs/backend-design.md#logical-records).
