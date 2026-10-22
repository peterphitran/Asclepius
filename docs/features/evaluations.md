# Evaluation Checks

Status: planned. Select security checks, execute them, and explain their outcomes.

## Sub-features

- `evaluation-select`: choose identifiable, versioned checks.
- `evaluation-execute`: send bounded inputs through the connection adapter.
- `evaluation-judge`: distinguish weaknesses, passes, and inconclusive/error results.
- `evaluation-evidence`: associate input, reply, rationale, and errors with the check.
- `evaluation-stages` (design pending): choose the evaluation stages and providers.

## How to get to it (user POV)

Select checks when submitting a run and inspect their results afterward.
Initial categories, rubrics, provider configuration, and selection flags need design.

## Driving it with the terminal

Use known-response fixtures to produce a weakness, a pass, and a controlled execution
failure. Verify distinct outcomes and recorded check versions. Keep real submission,
transport, persistence, and result handling in the path.

## Gotchas

- Model confidence alone does not establish a valid judgment.
- A timeout or malformed reply is not a passing check.
- Check generation, judging, budgets, and stage separation are still open choices.
