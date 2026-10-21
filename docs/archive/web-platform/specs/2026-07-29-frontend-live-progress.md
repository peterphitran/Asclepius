> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Frontend Live Sweep Progress Specification

## Goal

Make campaign launch and sweep detail accurately represent real execution state instead of implying that queued work will start without a worker.

## Launch flow

- Submit campaign to `POST /campaigns`.
- Show “Queued” only after the backend confirms persistence and enqueue success.
- Navigate to the returned sweep.
- Display a clear error if enqueueing fails after persistence.

## Sweep detail data flow

Use one of these transport options, in order of preference:

1. Server-sent events endpoint for sweep events;
2. bounded polling of `GET /sweeps/{id}` with backoff;
3. one-time fetch only for terminal historical sweeps.

The first implementation may use polling every 2–5 seconds while status is `queued` or `running`, stopping on terminal status or after a configurable timeout.

## UI states

- queued: waiting for worker, with cancel action;
- running: progress, current agent, current activity, and step feed;
- completed: final counts and findings links;
- failed: error detail, retry action, and preserved partial results;
- cancelled: cancellation reason and restart option.

Do not display “live” badges unless the latest response has a recent heartbeat or the worker state is explicitly running.

## Dashboard behavior

Dashboard cards and active-sweep preview continue to use API data. They should refetch or subscribe after campaign launch and review actions so counts do not remain stale.

## Acceptance criteria

- A newly launched sweep visibly changes from queued to running when the worker claims it.
- Progress and step events update without a full page reload.
- Terminal states stop network activity.
- API errors and expired sessions use existing auth/error patterns.
- Seeded historical sweeps still render without requiring a worker.
