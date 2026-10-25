# Runs

Status: supplied-plan submission, saved-state inspection, watch, cancellation intent, and
linked retry commands are implemented. A manually started daemon accepts pinned plans
into the queue and executes them through the coordinator. Phases, generated cases, stage attempts, observations and partial findings
remain inspectable. [Task 8](../verification/evidence/cli-recovery.json) verifies cancellation,
manual crash recovery, and linked retry on WSL and native Windows.

## Sub-features

- `run-submit`: create a run using a profile and selected checks.
- `run-state`: expose queued, running, completed, failed, cancelled, and interrupted states.
- `run-progress`: show completed work and execution errors.
- `run-cancel`: stop new requests and preserve in-flight observations under bounded timeouts.
- `run-retry`: create a linked new run from the source run's saved configuration.
- `run-ownership`: prevent duplicate claims and results within one run.

## How to get to it (user POV)

Submit against a saved profile, keep the returned run ID, and inspect it from another
process. The [backend design](../specs/backend-design.md) defines states and retry identity;
use `run <profile> --plan <plan.json> --evaluator <evaluator.toml>` and
`runs list|show|watch|cancel|retry`. See [command details](../development.md#submit-a-complete-plan).

## Driving it with the terminal

Drive a controllable target from submission to a final outcome. Match configuration,
request logs, counts, and results to one run ID. Cover bad profiles/checks, concurrent
submissions, target failure, and user interruption. Exercise cancellation/retry through
their user commands when available. Confirm cancellation retains observations, a retry
returns a distinct linked run ID, and the source run remains unchanged.

## Gotchas

- Saving a queued record does not establish dispatch.
- Submission gates on persisted ready state and a heartbeat up to ten seconds old. Abrupt
  owner loss can leave a bounded queued-acceptance window, not a promise of execution.
- Progress must account for errors and incomplete checks.
- Internal state-service tests cannot prove a complete user run.
- A completed run can contain findings; completion does not mean the target passed.
- Freeze bounded check/variant counts before dispatch and report phase progress; late
  discovery of generated variants must not masquerade as a stable overall percentage.
- A queued run can lose credentials/capabilities before execution. Revalidate without
  substituting a changed profile, new target, or different user identity.
- Cancelling ingestion tests does not undo remote mutations. Show cleanup status and
  any unresolved run-owned resources separately from the evaluation state.
- A retry can incur new model costs and remote mutations; it is not exact replay.
