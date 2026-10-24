# Evaluation Checks

Status: partial. The built-in pack and four role contracts exist. Queued execution
and live model assessment remain pending.

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

List definitions with `asclepius checks list --pack broad-chat-v1 --json`. Submit the
pack with `asclepius run <target> --pack broad-chat-v1 --evaluator <evaluator.toml>`
after starting the daemon and configuring credentials. Submission accepts queued work;
the daemon still reports `execution_available: false`.

The pack has four objectives in each of five families, instruction priority, protected
synthetic context, encoded instructions, conflicting context, and application policy.
The [implementation plan](../plans/2026-10-21-cli-evaluator.md#task-6-broad-pack-and-four-role-contracts)
lists the 20 stable IDs. Each check pins three attack strategies, a fixed benign control,
a protected system contract, a rubric, evidence criteria, and a severity rule. The four
cases per check give 80 cases. These probe a supplied synthetic contract and do not
establish vulnerabilities in Groq infrastructure.

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
- The role runner uses immutable pinned prompts and typed proposals with a required
  dispatch callback. The coordinator must persist intent before dispatch and observations
  before interpreting outputs. That integration remains Task 7.
- Local canary/schema assertions remain separate from semantic judgments. Quotes must
  occur in the actual reply. Reporter cannot change IDs, severity, or evidence and builds
  reproduction from the recorded request. Control over-refusal is a separate diagnostic.
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
