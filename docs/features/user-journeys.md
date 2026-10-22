# User Journeys

Status: planned. Verify complete workflows after their constituent features are implemented.

## Sub-features

- `journey-first-run`: profile to background run to finding/report.
- `journey-multiple-apps`: separate applications and histories.
- `journey-repeat-run`: repeated evaluation and meaningful comparison.
- `journey-interruption`: failure, interruption, and recovery under a defined policy.

## How to get to it (user POV)

Follow the intended [product workflow](../product.md). Read the relevant feature pages
before driving a journey.

## Driving it with the terminal

| Journey | Actions and required observations |
| --- | --- |
| First run | Save a [profile](profiles.md), start the [daemon](daemon.md), submit a [run](runs.md), close the terminal, inspect [findings](findings.md), and open a [report](reports.md). One run ID ties the observations together. |
| Multiple applications | Use two [connections](connections.md) with distinct fixture logs. Requests and results stay attached to their selected profiles; aggregate concurrency obeys the declared limit. |
| Repeat evaluation | Run the same [checks](evaluations.md) before/after a known change. Restart the tool and check [history/comparison](history.md) against persisted outcomes. |
| Failure/recovery | Force a target failure or delay, apply the designed stop/cancel/retry behavior, and inspect preserved results. Confirm recovery does not duplicate completed work. |

These journeys currently have no runnable CLI path. Record the missing segment rather
than substituting direct database writes or seeded results.

## Gotchas

- Recovery semantics must be designed before asserting expected restart behavior.
- A fixture can replace the external target/provider, not the workflow being tested.
- Keep evidence after cleanup as described in [verification](../verification.md).
