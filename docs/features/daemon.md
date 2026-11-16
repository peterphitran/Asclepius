# Background Daemon

Status: manual detached control, readiness, heartbeat, and graceful stop are implemented.
Scheduling and controlled model execution are verified by [Task 7](../verification/evidence/cli-pipeline.json).
[Task 8](../verification/evidence/cli-recovery.json) verifies active drain, timeout ownership,
submission racing drain, and manual restart after process loss. Physical terminal-close,
sleep/shutdown, and hosted-provider acceptance remain Task 10.

## Sub-features

- `daemon-start`: start a detached instance.
- `daemon-status`: report instance readiness and identity.
- `daemon-stop`: stop the service deliberately.
- `daemon-bounds`: enforce configured concurrency.
- `daemon-recovery`: preserve lost-owner work as interrupted and retain queued work.

## How to get to it (user POV)

Start the daemon before submitting runs and stop it when finished. The
[backend design](../specs/backend-design.md) defines one instance per data directory,
readiness before acceptance, and graceful stop by draining active work. Submission
with stopped/draining/stale control fails without creating a run; repeated start identifies
the existing instance. After abrupt loss releases the ownership locks, submission refuses
new work. Runs already queued remain available for manual restart.
Use `daemon start`, `daemon status`, and `daemon stop --timeout <seconds>` with the shared
`--data-dir`. Ready status includes `execution_available: true`; the coordinator claims
queued runs within configured limits. A timed-out stop reports draining under the same
PID and generation and lets active work finish. Queued work waits for manual restart.
See [daemon commands and migration](../development.md#control-the-local-daemon).

## Driving it with the terminal

Submit a delayed fixture run, close the submitting terminal, then inspect progress from
another terminal. Measure peak active fixture requests against the concurrency limit.
Check duplicate start and graceful drain. Restart after a forced interruption and verify
that incomplete runs are marked interrupted, while queued runs remain available.

## Gotchas

- Computer sleep and shutdown interrupt computation.
- On WSL, keep a WSL terminal open while runs are active. WSL stops its Linux side,
  including the detached daemon, shortly after its last terminal or session closes. A live
  check on 2026-11-14 saw the daemon killed about 15 seconds after that, mid-run, leaving the
  run marked running. `daemon start` prints a warning to stderr on WSL; the JSON output is
  unchanged. Closing the creating terminal alone is survived while another WSL session is open.
- A startup message alone does not prove a usable worker.
- A stale heartbeat alone cannot prove that instance ownership has been released.
- Enqueue and claim require the current generation's held locks and an elapsed heartbeat
  no more than ten seconds old. A released owner cannot admit new work after a crash.
  If a pause expires its own ready heartbeat, the daemon renews under its generation
  fence and rereads control before retrying refused startup recovery or claiming work.
  Clients remain refused during the stall; accepted work and provider calls are not replayed.
- Readiness requires both lifetime instance ownership and the current UUID's readiness
  lock. PID and a fresh old row cannot establish a new child's readiness.
- A timed-out stop never kills the process. A startup timeout may leave a child starting;
  inspect status. Do not delete lock files to force ownership.
- Storage failures can include bounded native error codes and trusted stack locations in
  the daemon log, without exception messages, queries or credentials. Preserve that record
  and the store when investigating the [open storage issue](../verification/issues/2026-11-06-storage-busy.md).
- Per-run bounds are insufficient: enforce global, model-provider, target, and mutable
  corpus limits across all profiles. Keep control operations responsive under saturation.
- Cancellation and drain must not strand invisible uploaded fixtures; surface the
  independent cleanup status described in [RAG testing](../specs/rag-testing.md).
- Sleep can expire request deadlines or target credentials. On wake, classify uncertain
  calls explicitly; detachment is not a promise of uninterrupted execution.
- Reserve cleanup capacity/budget separately from evaluation limits. Graceful shutdown
  waits for bounded cleanup or records unresolved resources with a visible warning.
- Cleanup reservations currently return unsupported; evaluation allowance is not a substitute.
- One native creator-exit check failed during review and then passed repeated probes.
  Physical terminal-close behavior remains an explicit acceptance item.
