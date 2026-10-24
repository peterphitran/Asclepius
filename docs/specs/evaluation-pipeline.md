# Four-agent evaluation pipeline

Status: partial implementation. Task 6 implements the four role contracts, pinned pack
and prompts, and deterministic evidence assertions. The coordinator and complete persisted
execution pipeline remain pending.

## Roles and handoffs

| Agent | Input contract | Output contract |
| --- | --- | --- |
| Selector | Profile capabilities, pinned check definitions, requested coverage, run limits, and completed items. | Selection with check ID/version, strategy, and rationale. |
| Generator | Selection, check objective, and variant limits. | Bounded variants with stable IDs, exact inputs, and required target capabilities. |
| Judge | Check objective/rubric, variant input, and normalized target observation. | Judgment with weakness/pass/inconclusive outcome, evidence references, and confidence where meaningful. |
| Reporter | Weakness judgment, observed evidence, and generic target context. | Finding with severity, description, reproduction context, and recommendation. |

The coordinator calls the target adapter between Generator and Judge. Target transport
is execution, not a fifth agent. A transport failure is recorded as an execution error
and must not be converted into a passing judgment.
For [document/retrieval checks](rag-testing.md), the coordinator instead executes the
declared bounded ingestion/readiness/query/cleanup plan and supplies operation-specific
observations. This changes adapter capabilities, not the four-role boundary.

Selector chooses ordering and strategies within the requested check coverage. It cannot
silently omit checks. Generator commits exact variant inputs before target execution.
Judge sees the rubric and observations without Selector's rationale. Reporter cannot
alter the observation or invent evidence.

Save passes, inconclusive judgments, and errors even when no Reporter finding is needed.
Diagnostic ingestion/retrieval assertions retain met/not-met/inconclusive outcomes and
metrics independently of security verdicts. Diagnostic-only checks have no security
verdict and do not trigger Reporter findings merely because a correctness assertion fails.
The first finding identity is per judged variant within a run. Grouping several variants
into one vulnerability is a later design choice.

## Agent and worker boundaries

Four agents are four evaluation responsibilities, not four long-lived processes.
The same model can serve multiple roles with separate prompts and inputs.
Initially use Groq for evaluator roles and the target, with independent configuration
as defined in the [backend design](backend-design.md#connections-and-model-configuration).
Record role/model identity; same-provider evaluation is not proof of an independent judge.
All four roles use validated model proposals. Code owns IDs, protected setup, controls,
coverage, provenance checks, severity, and deterministic exact-canary/schema assertions.

The coordinator owns ordering, limits, persistence, and lifecycle changes.
Workers provide capacity in the daemon. Agents return structured values.
The model gateway validates provider outputs before the coordinator accepts them.
The [backend design](backend-design.md) owns queue, storage, shutdown, and retry policy.

Prompt construction and interpretation of validated judgments should be testable
without importing the CLI, daemon process, database session, or FastAPI.

## Persisted contracts

Selection records pin the check version and strategy. Variant records retain the exact
input. Observations retain request identity, reply or transport error, latency, and
whether the external outcome is known. Judgments cite observations and rubric versions.
Findings cite the judgment and evidence that support them.

Stage records use stable work-item identities even for check-level stages before
variants exist. A completed stage, its output, and its event commit together.
Repeated persistence of that identity cannot insert a duplicate finding or output.

Preserve interrupted-run results. The initial recovery policy creates an explicit
linked retry with a new run ID, as defined in the backend design. It does not replay
uncertain external requests automatically or claim in-place resume.

Typed field definitions and strict proposal schemas now live in `asclepius.domain` and
`asclepius.agents`. Optional lineage/assertion fields preserve older JSON reads. Legacy
judgments without lineage cannot initiate a new report. Raw provider strings are not
internal handoff contracts.

`AgentRunner(connection, *, dispatch)` requires a callback receiving the gateway and
finalized prepared request. The coordinator must save intent before network dispatch and
save the returned observation before role interpretation. There is no default dispatch
or agent-owned database/lifecycle state. This seam is implemented; its durable integration
remains Task 7.

## Reporter and report export

Reporter creates structured findings during evaluation. Exporters turn saved runs,
judgments, and findings into local reports and charts. Exporting again does not call
Reporter, other agents, providers, or targets.

## Pipeline verification

Use the real submission, daemon, coordinator, adapters, and SQLite store.
A controlled target and deterministic provider fixture replace only external calls.
Verify a weakness, a pass, an inconclusive judgment, and a transport/provider failure.

Match check/variant/stage identities to requests and saved results. Verify requested
coverage, variant bounds, evidence provenance, and duplicate persistence handling.
Interrupt a stage, inspect the preserved run, and exercise an explicit linked retry.
Export twice and confirm no new target/provider calls.

These are implementation acceptance criteria, not tests that currently pass.

## Design guidance

[Boundary Discipline](https://github.com/cursor/plugins/blob/main/pstack/skills/principle-boundary-discipline/SKILL.md)
informed component ownership.
[Model the Domain](https://github.com/cursor/plugins/blob/main/pstack/skills/principle-model-the-domain/SKILL.md)
informed typed stage contracts.
[Make Operations Idempotent](https://github.com/cursor/plugins/blob/main/pstack/skills/principle-make-operations-idempotent/SKILL.md)
informed committed identities and explicit uncertainty after interruption.
