# Document ingestion and retrieval testing

Status: planned design extension requested during feature review. Nothing here is
implemented. Defaults below are proposed, not additional user-approved product choices.

## Scope and access

Asclepius evaluates an existing application; it does not become that application's
document store, embedding service, or retrieval engine. Fixtures provide small,
versioned corpora and query sets. Ordinary ingestion/retrieval correctness checks
support security evaluation; this is not a general-purpose benchmarking platform.

| Available interface | What a run can establish | What it cannot establish alone |
| --- | --- | --- |
| Chat only | Observed answers, refusal behavior, exposed citations, and groundedness against supplied evidence. | Actual indexed contents, retrieved ranking, or ingestion completion. |
| Retrieval | Returned document/chunk IDs, ranks, scores if supplied, and access-boundary behavior. | Whether an unobserved ingestion operation worked or how the final answer used results. |
| Ingestion and readiness | Acceptance, indexed visibility, update/deletion behavior when supported. | Retrieval relevance or answer grounding without their corresponding observations. |

Capabilities are explicit: chat, retrieval, ingest, readiness, update, delete, and
isolated corpus management. A check declares its required subset. Reject an explicitly
requested unsupported check before submission; never silently convert it to chat-only
testing. User-selected narrower coverage is allowed and must appear in the run summary.

The agreed integration order is hosted model API, Ollama, then RAGbot. Chat is the
first transport milestone, not the definition of complete RAG support. Direct retrieval
and ingestion remain planned capabilities with their own acceptance milestone.
RAGbot is the selected RAG integration. Its actual API capabilities, version, and
isolation mechanisms still need inspection; choosing it does not establish those facts.
RAG-specific payloads extend the [general schema boundary](backend-design.md#logical-records)
instead of making document/corpus fields mandatory for other applications.

## Fixture and evidence contracts

A fixture manifest pins document IDs, content hashes, metadata, queries, expected
relevant document IDs, and rubric versions. Pin chunk expectations only when the
target's chunk identity contract is stable. Record corpus version, target/index revision
when observable, retrieval depth, filters, and execution identity labels without secrets.
Unobservable revisions are marked unknown, not inferred from a profile name.

The coordinator uses a bounded operation plan: prepare an isolated corpus, ingest,
wait for observable readiness, query/retrieve/chat as required, evaluate, and clean up.
Adapters normalize operation-specific observations, including receipts, returned IDs,
ordered retrieval results, citations, errors, and request uncertainty. Agents cannot
invent endpoints, execute arbitrary scripts, or select unrelated documents to delete.

Selector chooses applicable checks. Generator produces bounded documents/queries or
uses fixed fixtures; it cannot change an expected answer after seeing the result.
Judge uses deterministic assertions for known IDs, ranks, and lifecycle expectations.
Save assertion outcomes (met, not met, or inconclusive) and metric values separately
from the security verdict (weakness, pass, or inconclusive). A diagnostic-only check
has no security verdict; its failed assertion does not create a weakness finding.
Model-based semantic judgments are separately labeled with their rubric/model versions.
Reporter produces evidence-backed weaknesses; ordinary correctness failures and
inconclusive outcomes remain visible even when they are not security findings.
The four [role boundaries](evaluation-pipeline.md) do not change.

## Mutation, isolation, and cleanup

Read-only chat/retrieval checks do not imply permission to upload or delete documents.
Here, read-only means target behavior is verified not to trigger actions or durable
session writes. HTTP method or a chat-shaped API does not establish that property.
Proposed first-adapter constraint: stateless requests or fresh run-owned sessions with
target-side tools/actions disabled. Otherwise require explicit side-effect opt-in and
an adapter-specific isolation/cleanup contract before running checks. Never reuse session
IDs across runs; pin any session ownership and actor associations in operation records.

For access-boundary checks, declare named setup and query actors with separate credential
references. Pin non-secret actor labels on requests and observations. Validate required
actors before acceptance and resolve each at execution; never fall back to an admin or
setup credential when a query credential is missing. The fixture specifies which actor
should see which documents. Target identities do not introduce an Asclepius login.

Proposed default: mutation checks require explicit opt-in and a disposable namespace
or collection that the adapter can isolate and identify as owned by this run. Reject
mutation checks against shared live corpora when ownership cannot be established.
Do not ingest private local documents implicitly.

Persist intended operations and ownership metadata before external mutation, then save
receipts and exact created resource IDs. A naming prefix alone is not ownership proof.
Cleanup touches only proven run-owned resources, never a whole existing collection.
Do not share mutable fixture corpora between concurrent runs. Scheduling uses a shared
resource key so two profiles for one collection cannot bypass the same mutation lock.

Readiness is a bounded poll of adapter-defined observable visibility, not a fixed sleep
or an upload-success response. A readiness timeout is an execution failure, not evidence
that retrieval passed or that the system is vulnerable. Verify updates/deletions through
the required read interface; distinguish an acknowledged delete from observed absence.

Cancellation stops new evaluation operations. Known-owned cleanup is a separate,
bounded maintenance action, not continuation of the evaluation. Record cleanup state
separately from the run's evaluation state: not required, pending, succeeded, failed,
or uncertain. Failed cleanup must remain prominent without overwriting a cancellation,
failure, or valid evaluation result. A report cannot claim the environment was restored
unless cleanup was verified.
Reserve a separate bounded cleanup request/time budget before evaluation begins, so
exhausting the evaluation budget cannot consume that reserve. Graceful drain includes bounded
known-owned cleanup. If cleanup cannot finish before shutdown, save pending/uncertain
resources and show an actionable warning, rather than claiming restoration or retrying
unknown operations automatically. Control operations remain responsive during cleanup.

After a crash, show unresolved resources and instructions; do not automatically repeat
uploads, updates, or deletes. Explicit cleanup may be attempted with ownership checks.
A linked retry uses a new isolated corpus, not a possibly polluted abandoned one.
Unknown external outcomes require reconciliation; deleting by guessed ID is forbidden.
If the target offers expiry, record it as a fallback, not as verified cleanup.

## Metrics and comparison

Use deterministic relevance labels where available. At a pinned retrieval depth k,
report recall@k and reciprocal rank only when the fixture defines relevant identities.
Name the identity level (document or chunk) and deduplicate at that level before scoring.
Queries without relevance labels are unscored, not zero-scored. Empty result sets,
transport failures, access denials, and inconclusive judgments are separate outcomes.

Grounding requires answer plus supporting source evidence. Citations alone are not proof
of support. A correctness miss is not automatically a security vulnerability. Record
the security objective, violated boundary, and observed evidence for security findings.

Compare matching corpus/query/rubric versions and compatible target settings. Show
unknown target revisions and nondeterminism. Report coverage and metric denominators;
do not combine incompatible scores into an unlabeled overall quality percentage.

## Acceptance evidence and remaining choices

Use a controlled application with real ingestion/retrieval endpoints and deterministic
labels. Prove upload versus readiness, expected and irrelevant retrieval, update/delete
visibility, restricted-document queries under distinct authorized identities, grounding,
and a malicious-document instruction attempt. Include delayed indexing, partial upload,
malformed retrieval, cancellation, crash uncertainty, concurrent profiles sharing a
resource, and cleanup failure. Preserve operation logs and saved evidence after cleanup.

Before implementing this milestone, select the first target API, document formats,
namespace/ownership/readiness contracts, and fixture/check definitions. Exact adapter
schemas and metric edge cases require fixture tests before being treated as stable.
The [design review](design-review.md) tracks the decisions that still need discussion.
