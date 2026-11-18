# User journeys

Status: planned. Verify complete workflows after their constituent features are implemented.

## Sub-features

- `journey-first-run`: profile to background run to finding/report.
- `journey-multiple-apps`: separate applications and histories.
- `journey-repeat-run`: repeated evaluation and meaningful comparison.
- `journey-interruption`: failure, interruption, and recovery under a defined policy.
- `journey-rag`: isolated corpus preparation through ingestion/retrieval evaluation and cleanup.

## How to get to it (user POV)

Follow the intended [product workflow](../product.md). Read the relevant feature pages
before driving a journey.

## Driving it with the terminal

| Journey | Actions and required observations |
| --- | --- |
| First run | Save a [profile](profiles.md), start the [daemon](daemon.md), submit a [run](runs.md), close the terminal, inspect [findings](findings.md), and open a [report](reports.md). One run ID ties the observations together. |
| Multiple applications | Use two [connections](connections.md) with distinct fixture logs. Requests and results stay attached to their selected profiles; aggregate concurrency obeys the declared limit. |
| Repeat evaluation | Run the same [checks](evaluations.md) before/after a known change. Restart the tool and check [history/comparison](history.md) against persisted outcomes. |
| Failure/recovery | Force a target failure or interruption, inspect preserved results, and explicitly retry as a linked new run. Confirm the source stays unchanged and persistence does not duplicate records within either run. |
| Ingestion/retrieval | Use a versioned fixture in a disposable run-owned corpus. Observe readiness, query expected documents, inspect ranked evidence/grounding, and verify cleanup. Repeat with delayed indexing, partial failure, cancellation, and a cleanup failure. |

These journeys currently have no runnable CLI path. Record the missing segment rather
than substituting direct database writes or seeded results.

## Gotchas

- Follow the [backend design](../specs/backend-design.md) for drain, cancellation,
  interruption, and linked-retry expectations. In-place resume is deferred.
- A fixture can replace the external target/provider, not the workflow being tested.
- Keep evidence after cleanup as described in [verification](../verification.md).
- Chat-only journeys do not cover ingestion/retrieval. Run the capability-specific
  [RAG acceptance cases](../specs/rag-testing.md) before claiming that support.
- Include two profile aliases for the same collection and prove that concurrent runs
  cannot modify each other's corpus or bypass aggregate execution limits.
