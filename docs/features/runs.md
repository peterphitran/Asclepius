# Runs

Status: planned. Give each evaluation an identity and expose its persisted progress and outcome.

## Sub-features

- `run-submit`: create a run using a profile and selected checks.
- `run-state`: expose waiting, executing, and final outcomes.
- `run-progress`: show completed work and execution errors.
- `run-cancel`, `run-retry` (proposed): control work while retaining evidence.
- `run-ownership` (design pending): prevent duplicate claims and results.

## How to get to it (user POV)

Submit against a saved profile, keep the returned run ID, and inspect it from another
process. Status vocabulary, cancel/retry commands, and retry identity remain undecided.

## Driving it with the terminal

Drive a controllable target from submission to a final outcome. Match configuration,
request logs, counts, and results to one run ID. Cover bad profiles/checks, concurrent
submissions, target failure, and user interruption. Exercise cancellation/retry through
their user commands when available.

## Gotchas

- Saving a queued record does not establish dispatch.
- Progress must account for errors and incomplete checks.
- Internal state-service tests cannot prove a complete user run.
