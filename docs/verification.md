# Verification

The [feature map](features/README.md) defines behavior coverage. This page owns shared
verification conventions; feature files add only their specific actions and observations.

## Before running a check

Identify the checkout and whether it contains local edits. Use an isolated fixture target,
disposable database/data directory, and instances you create for the check. Follow
[development setup](development.md) for the current API.

The CLI has no entry point or verification driver yet. Its mapped journeys are future
acceptance paths, not runnable instructions. Do not fabricate commands to mark them passed.

## Proof requirements

- Pair the user action with its result: command/exit status, HTTP request/response,
  fixture request log, persisted data, or rendered report.
- Include relevant success, invalid-input, empty, error, interruption, and persistence paths.
- Use a controlled target/provider only at its real external boundary; keep submission,
  execution, persistence, and output generation in the path being checked.
- Report missing prerequisites and unimplemented paths explicitly.
- Record source checkpoint, setup, observations, gaps, and cleanup. Omit credentials.
- Stop only instances you started. Keep evidence after removing scratch state.

A passing unit test does not establish a working daemon. A health response does not
establish database readiness. Seeded results do not establish target execution.

## Recorded API smoke

The [2026-10-21 record](verification/evidence/api-smoke.json) comes from real loopback
HTTP calls against this working checkout, including its uncommitted backend changes.

It observed `GET /health` and `GET /openapi.json` returning 200, and unauthenticated
`GET /targets` returning 401. The verification-owned instance stopped afterward.
An earlier attempt hit its startup deadline; the successful run's setup is recorded.

This covers process metadata, route discovery, and missing-token rejection only.
Authenticated database paths, CLI behavior, target execution, concurrency, recovery,
and reports remain unverified by that smoke check.

## Feature-map convention

Each feature file has four sections: sub-features, user entry point, terminal driving,
and gotchas. Stable feature IDs support focused checks; [user journeys](features/user-journeys.md)
cover behavior spanning several features.

The format is adapted from [poteto's example](https://github.com/poteto/verification-skill-example/blob/main/.cursor/skills/verify-atlas/references/features/README.md)
and [verification guidance](https://github.com/cursor/plugins/blob/main/pstack/skills/create-verification-skill/SKILL.md).
The linked [article](https://x.com/poteto/article/2094457600259842065?lang=en) was reviewed
through its [readable mirror](https://threadnavigator.com/thread/2094457600259842065/).
