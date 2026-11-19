# Feature map

Behavior coverage for the project defined in [product scope](../product.md).
The feature pages describe intended CLI actions and the evidence needed to verify them.
Profiles, manual daemon control, and persisted run/finding inspection have implementations. Evaluation execution
remains planned; use [implementation status](../status.md) for the tested boundaries.

| Feature | User outcome |
| --- | --- |
| [Application profiles](profiles.md) | Save and select several applications. |
| [Target connections](connections.md) | Communicate with the chosen model or application. |
| [Evaluation checks](evaluations.md) | Select checks and obtain evidenced outcomes. |
| [Background daemon](daemon.md) | Start/stop detached execution and limit parallel work. |
| [Runs](runs.md) | Submit and inspect one evaluation. |
| [History and comparisons](history.md) | Review repeated evaluations across applications. |
| [Findings](findings.md) | Understand evidence behind a potential weakness. |
| [Reports and charts](reports.md) | Generate local summaries and comparisons. |
| [User journeys](user-journeys.md) | Check complete workflows across these features. |

For a focused change, open the affected feature and relevant journey. For a broad sweep,
follow this order and finish with journeys. Shared preconditions and proof conventions
live in [verification](../verification.md).

Implemented command syntax is in [development](../development.md); the intended full
workflow is in [product scope](../product.md).
The [backend design](../specs/backend-design.md) defines proposed lifecycle and control defaults.
The [RAG design](../specs/rag-testing.md) separates chat, retrieval, and ingestion coverage.
The [design review](../specs/design-review.md) tracks proposed defaults and open decisions.
Each feature page states which parts are implemented and which remain planned. A partial
implementation does not establish the full user journey. Update entry points and evidence
when behavior becomes usable.
