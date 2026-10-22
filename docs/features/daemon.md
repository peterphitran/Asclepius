# Background Daemon

Status: planned. Manually control detached execution with bounded parallel work.

## Sub-features

- `daemon-start`: start an instance that survives terminal closure.
- `daemon-status`: report instance readiness and identity.
- `daemon-stop`: stop the service deliberately.
- `daemon-bounds`: enforce configured concurrency.
- `daemon-recovery`: preserve lost-owner work as interrupted and retain queued work.

## How to get to it (user POV)

Start the daemon before submitting runs and stop it when finished. The
[backend design](../specs/backend-design.md) defines one instance per data directory,
readiness before acceptance, and graceful stop by draining active work. Submission
while stopped fails without creating a run; repeated start identifies the existing instance.

## Driving it with the terminal

Submit a delayed fixture run, close the submitting terminal, then inspect progress from
another terminal. Measure peak active fixture requests against the concurrency limit.
Check duplicate start and graceful drain. Restart after a forced interruption and verify
that incomplete runs are marked interrupted, while queued runs remain available.

## Gotchas

- Computer sleep and shutdown interrupt computation.
- A startup message alone does not prove a usable worker.
- A stale heartbeat alone cannot prove that instance ownership has been released.
- Per-run bounds are insufficient: enforce global, model-provider, target, and mutable
  corpus limits across all profiles. Keep control operations responsive under saturation.
- Cancellation and drain must not strand invisible uploaded fixtures; surface the
  independent cleanup status described in [RAG testing](../specs/rag-testing.md).
- Sleep can expire request deadlines or target credentials. On wake, classify uncertain
  calls explicitly; detachment is not a promise of uninterrupted execution.
- Reserve cleanup capacity/budget separately from evaluation limits. Graceful shutdown
  waits for bounded cleanup or records unresolved resources with a visible warning.
