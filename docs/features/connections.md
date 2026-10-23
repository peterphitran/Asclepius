# Target Connections

Status: partial. Groq chat target and evaluator boundaries have component implementations.
CLI queued-run execution and hosted-model acceptance remain unimplemented/unverified.
See the [Task 5 component evidence](../verification/evidence/cli-groq-components.json).

## Sub-features

- `connection-http` (component implementation): one Groq-compatible HTTPS chat POST.
- `connection-mapping` (component implementation): fixed Groq message/reply format, not arbitrary field mapping.
- `connection-auth` (component implementation): independent target/evaluator environment references.
- `connection-errors` (component implementation): network uncertainty, deadline, provider HTTP,
  protocol, explicit refusal, unsupported tools, truncation, and missing-reply outcomes.
- `connection-capabilities`: declare chat, retrieval, ingestion, readiness, and optional
  update/delete/isolation support independently.
- Non-Groq, streaming, multi-turn, ingestion, and retrieval adapters remain planned.

## How to get to it (user POV)

Configure the profile before running checks. A model, chatbot, or RAG app may expose
an HTTP chat endpoint; application type alone does not determine the adapter.
The [backend design](../specs/backend-design.md) proposes the first adapter contract.
Generic request templates and reply selectors are not implemented. Current provider
boundaries live in `backend/asclepius/adapters/chat.py` and `models.py`.

## Driving it with the terminal

Use a local fixture with a request log. Verify destination, request structure, extracted
reply, limits, and error classification through an actual run. Include valid, malformed,
oversized, and delayed replies. Confirm credential values are absent from shared output.
The current installed-wheel proof runs `backend/scripts/verify_groq.py` against loopback
HTTPS and real local SQLite budgets. It does not run a CLI evaluation or contact Groq.

## Gotchas

- No single JSON shape works for every target.
- Chat access does not provide document ingestion for retrieval tests.
- Supporting UI-only applications would require a separate adapter.
- See [RAG testing](../specs/rag-testing.md) for ingestion, readiness, retrieval, and
  cleanup contracts. Unsupported requested checks fail validation, not silently skip.
- Credentials must resolve in the daemon's environment, which may differ from the CLI's.
  Never persist resolved headers, signed URLs, or credential values in snapshots/logs.
- A run-bound connection captures credentials once. Changes to the environment require a
  new connection/run. Only configured credential values are redacted, not synthetic canaries.
- Evaluator output is checked against the exact sent schema before typed construction.
  Schema compliance does not prove evidence truth or an independent judge.
- Provider errors retain validated `retry_after` timing as decimal seconds or an HTTP date.
  Invalid, duplicate, oversized, or credential-bearing values are discarded. Timing is
  evidence for an explicit retry, never authorization for an automatic request.
- Prepared request bodies include the evaluator schema. The coordinator must persist them
  before dispatch and retain observations for validation failures; convenience calls alone
  do not establish durable execution or prevent duplicate dispatch.
- Redirects must not forward credentials to a different origin automatically. Define
  destination/redirect policy before implementing connection probes or adapters.
- Upload, update, and delete calls are mutations: no automatic transport replay when
  the outcome is unknown. Response limits apply to retrieval/document payloads too.
- Chat is not inherently read-only: sessions and target-side tools can mutate state.
  Require isolated/stateless execution or explicit side-effect opt-in under the RAG contract.
- Access-control checks need distinct named setup/query credentials; never silently
  query as an administrator because a lower-privilege credential is missing.
