# Application Profiles

Status: planned. Save named connection settings for applications you want to evaluate.

## Sub-features

- `profile-save`: store a profile's name, connection details, and limits.
- `profile-list`: find saved applications.
- `profile-select`: choose the target for a run.
- `profile-reuse`: associate repeated runs with the same application.
- `profile-edit-policy` (design pending): decide how edits affect historical context.

## How to get to it (user POV)

Register an application once, then select its profile by name when submitting a run.
Add/list/edit syntax and duplicate-name rules are still open.

## Driving it with the terminal

Create profiles for two controlled targets, list them from a new process, and submit a
run using one name. Match received fixture requests and the resulting run to that profile.
Cover empty storage, invalid settings, and ambiguous names.

## Gotchas

- A profile name does not start the target or discover a source folder.
- Stable identities are needed even when names or endpoints change.
- Credentials belong to the connection design, not to a product login.
