# Background Daemon

Status: planned. Manually control detached execution with bounded parallel work.

## Sub-features

- `daemon-start`: start an instance that survives terminal closure.
- `daemon-status` (proposed): report instance readiness and identity.
- `daemon-stop`: stop the service deliberately.
- `daemon-bounds`: enforce configured concurrency.
- `daemon-recovery` (design pending): handle interrupted work and stale ownership.

## How to get to it (user POV)

Start the daemon before submitting runs and stop it when finished.
Behavior for a submission while stopped, repeated starts, and active work during stop
must be specified.

## Driving it with the terminal

Submit a delayed fixture run, close the submitting terminal, then inspect progress from
another terminal. Measure peak active fixture requests against the concurrency limit.
Check duplicate start and stop under the chosen drain/cancel policy; retain saved results.

## Gotchas

- Computer sleep and shutdown interrupt computation.
- A startup message alone does not prove a usable worker.
- Retry, cancellation, and recovery need distinct, explicit semantics.
