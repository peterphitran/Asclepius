# Evaluation Checks

Status: planned. Select security checks, execute them, and explain their outcomes.

## Sub-features

- `evaluation-select`: choose identifiable, versioned checks.
- `evaluation-pack`: provide broad initial attack coverage, with explicit capability
  requirements and bounded variants per check rather than a smoke-only pack.
- `evaluation-execute`: send bounded inputs through the connection adapter.
- `evaluation-judge`: distinguish weaknesses, passes, and inconclusive/error results.
- `evaluation-evidence`: associate input, reply, rationale, and errors with the check.
- `evaluation-stages`: use the [four-agent pipeline](../specs/evaluation-pipeline.md),
  with explicit contracts between selection, generation, judgment, and finding creation.
- `evaluation-rag`: use versioned document/query fixtures to check ingestion lifecycle,
  retrieval relevance, grounding, and document-based attacks where capabilities allow.

## How to get to it (user POV)

Select checks when submitting a run and inspect their results afterward.
Broad initial coverage is agreed. Proposed first model/chat families: instruction
override and role spoofing, protected synthetic-context disclosure, encoded/obfuscated
instruction attempts, conflicting-context manipulation, and application-defined policy
boundary checks. These are a proposed taxonomy, not an implemented or approved check list.
Exact checks, rubrics, variant counts, and selection flags still need design.

Indirect document injection, retrieval/access isolation, multi-turn attacks, and tool
misuse require their respective capabilities and acceptance milestones. A hosted chat
model alone does not establish support for those application-level tests.

## Driving it with the terminal

Use known-response fixtures to produce a weakness, a pass, and a controlled execution
failure. Verify distinct outcomes and recorded check versions. Keep real submission,
transport, persistence, and result handling in the path.

## Gotchas

- Model confidence alone does not establish a valid judgment.
- A timeout or malformed reply is not a passing check.
- The pipeline design defines role ownership and contract content. Exact schemas,
  prompts, budgets, and model configuration remain implementation choices.
- Chat-only observations cannot establish retrieved ranks or indexing success. Require
  the explicit interfaces and evidence defined by [RAG testing](../specs/rag-testing.md).
- Freeze expected results before execution; do not let generated fixtures or a Judge
  redefine success after seeing target output. Label deterministic versus model judgments.
- Ingestion/retrieval correctness failures are not automatically security weaknesses.
  Security findings need a stated boundary and observed violation.
- Treat retrieved content and target replies as untrusted input to Judge/Reporter;
  instruction-like content must not become authority or trigger arbitrary tool calls.
- Broad coverage does not mean unlimited generation or requests. Pin the selected
  check versions, variant bounds, and request/token/time limits before dispatch.
- A policy violation requires an explicit target contract and rubric. Provider refusal,
  unusual text, or revealing a synthetic canary is not automatically evidence of a real
  application's vulnerability; record the controlled setup and limit the claim accordingly.
- Keep benign controls for each relevant objective so the pack can expose over-refusal
  and judge false positives, not only produce apparent attack successes.
