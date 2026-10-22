# Feature design review

Status: documentation review, not an implementation plan or verification result.
The [draft implementation plan](../plans/2026-10-21-cli-evaluator.md) proposes concrete
models, check definitions, budgets, outputs, and an execution order for review.
The existing runtime remains the API prototype described in [status](../status.md).
Proposed defaults are assistant recommendations awaiting review, not user decisions.

## Clarifications from agreed direction

| Concern | Design consequence | Owner |
| --- | --- | --- |
| No frontend or login | Local commands, local history, credentials only for targets/providers. No hosted dashboard needed for charts. | [Product](../product.md) |
| Four agents versus workers | Four role contracts, coordinator-controlled execution, bounded worker capacity. | [Pipeline](evaluation-pipeline.md) |
| Background execution | Manual start, one daemon per data directory; terminal closure is distinct from sleep or a crash. | [Backend](backend-design.md) |
| RAG access | Chat, retrieval, and ingestion are separate capabilities with different proof limits. | [RAG testing](rag-testing.md) |
| Integration order and generality | Hosted API first, Ollama second, then RAGbot; preserve an application-neutral core with capability-specific typed extensions. | [Backend](backend-design.md#logical-records) |
| Initial provider | Groq for target and evaluator roles, with independent configuration and per-role model settings. Exact model choices remain open. | [Backend](backend-design.md#connections-and-model-configuration) |
| Initial coverage | Broad attack pack, not a small smoke-only pack; capability gates and bounded execution still apply. | [Evaluation checks](../features/evaluations.md) |
| Retry versus reproduction | Linked new-run retry preserves the source; it is not exact replay or in-place resume. | [Backend](backend-design.md) |

## Proposed defaults added during this review

| Concern | Recommendation | Acceptance consequence |
| --- | --- | --- |
| Mutation safety | Explicit opt-in; disposable run-owned corpus; no mutations of shared live corpora. | Refuse unsafe configuration before requests; retain unresolved cleanup records. |
| Shared destinations | Apply scheduling limits by canonical resource identity, not profile name alone. | Two aliases for one endpoint/collection cannot evade limits or corpus isolation. |
| Coverage gaps | Reject requested unsupported checks; show narrower user-selected coverage. | No silent skips or invented passes. |
| Corpus readiness | Poll observable adapter-defined readiness within a budget. | Upload acknowledgment is not indexing proof. |
| Judgment | Deterministic assertions for labeled retrieval/lifecycle checks; label semantic model judgments separately. | Distinguish relevance, grounding, technical failures, and security findings. |
| Cleanup | Separate persisted maintenance status; bounded cleanup only for proven owned resources. | Cancellation remains cancellation; reports disclose leftover resources. |
| Cleanup budget | Reserve a separate bounded maintenance budget; drain includes cleanup or records leftovers. | Evaluation exhaustion cannot silently disable cleanup. |
| Access identities | Separate named setup/query credential roles with no privilege fallback. | Access-isolation tests cannot accidentally query as the setup administrator. |
| Chat side effects | Require stateless or isolated run-owned sessions with actions disabled for the first adapter. | Stateful/tool-enabled targets need explicit side-effect opt-in and isolation contracts. |
| Comparison | Pin corpus/query/check/rubric/configuration; show unknown target revisions and denominators. | No unlabeled aggregate success score across incomparable work. |
| Profile edits/removal | Revalidate at execution; preserve submitted snapshots and historical profile identity. | Editing a queued profile does not redirect a queued run. |
| Secrets and local output | Resolve secrets in the daemon; redact configured secrets before persistence; safely render untrusted text. | Test daemon environment differences, terminal control characters, and report injection. |
| Retention and export | No automatic history purge in the first milestone; fail on existing output unless explicitly overwriting. | No silent evidence deletion or report replacement. |

## Decisions needing discussion before implementation

Work through these one at a time, starting with the first. Other defaults can be
reviewed alongside their feature; no need to settle every flag before choosing a target.

The first usable milestone exercises the complete shared CLI workflow against a real
hosted model API. Ollama follows to validate local inference through the same core.
RAGbot follows for ingestion/retrieval-specific evaluation, not as a prerequisite for
validating the CLI. Inspect its intended checkout/version and actual interfaces before
planning its adapter. Fixture tests remain supporting evidence, not substitutes for
real-model evaluations. Pin inputs, rubrics, model/settings, and actual responses;
repeat trials to expose variability rather than promising identical model replies.

1. **Models and data exposure.** Groq is selected for both target and evaluator roles.
   Select exact models independently and decide which test content they may receive.
   Proposed initial restriction: synthetic test content only, no private documents or
   real secrets. Local history does not imply local model execution. Revisit data exposure
   explicitly before testing applications with sensitive replies or document excerpts.
2. **Check definitions and limits.** Broad initial coverage is selected. Review the
   proposed families in [evaluation checks](../features/evaluations.md), specify concrete
   objectives/rubrics and benign controls, and select request/token/time budgets. Breadth
   does not authorize unlimited variants or unsupported RAG/tool/multi-turn checks.
3. **First outputs.** Choose the initial structured export and human-readable report;
   defer chart polish until saved results and comparison semantics are trustworthy.

Schema DDL, locking libraries, command spelling, and adapter mapping syntax are builder
decisions within these constraints. They still need a concrete implementation plan and
tests, but should not be mistaken for unresolved product intent.
