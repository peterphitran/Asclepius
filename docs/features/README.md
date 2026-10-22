# Feature Map

Behavior coverage for the project defined in [product scope](../product.md).
The feature pages describe intended CLI actions and the evidence needed to verify them.
All CLI features are planned; use [implementation status](../status.md) for existing code.

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
follow this order and finish with journeys. Shared preconditions, proof conventions,
and existing smoke evidence live in [verification](../verification.md).

Exact CLI syntax is undecided; the only command sketch is in [product workflow](../product.md).
Status labels used in feature pages are **planned** and **design pending**. Neither means
implemented or verified. Update a page's entry points and proof when its code becomes usable.

Existing HTTP operations are documented separately in the [API reference](../reference/existing-api.md).
