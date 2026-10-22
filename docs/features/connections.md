# Target Connections

Status: planned. Send test input and extract a reply using the selected profile.

## Sub-features

- `connection-http` (proposed first adapter): support a single-turn HTTP JSON chat endpoint.
- `connection-mapping`: describe request fields and response extraction.
- `connection-auth`: supply required target credentials.
- `connection-errors`: distinguish network, timeout, protocol, and missing-reply failures.
- `connection-capabilities`: declare chat, retrieval, ingestion, readiness, and optional
  update/delete/isolation support independently.
- Direct-provider, streaming, and multi-turn adapters remain candidates.

## How to get to it (user POV)

Configure the profile before running checks. A model, chatbot, or RAG app may expose
an HTTP chat endpoint; application type alone does not determine the adapter.
The [backend design](../specs/backend-design.md) proposes the first adapter contract.
Template syntax, reply selectors, and secret-reference implementation still need detail.

## Driving it with the terminal

Use a local fixture with a request log. Verify destination, request structure, extracted
reply, limits, and error classification through an actual run. Include valid, malformed,
oversized, and delayed replies. Confirm credential values are absent from shared output.

## Gotchas

- No single JSON shape works for every target.
- Chat access does not provide document ingestion for retrieval tests.
- Supporting UI-only applications would require a separate adapter.
- See [RAG testing](../specs/rag-testing.md) for ingestion, readiness, retrieval, and
  cleanup contracts. Unsupported requested checks fail validation, not silently skip.
- Credentials must resolve in the daemon's environment, which may differ from the CLI's.
  Never persist resolved headers, signed URLs, or credential values in snapshots/logs.
- Redirects must not forward credentials to a different origin automatically. Define
  destination/redirect policy before implementing connection probes or adapters.
- Upload, update, and delete calls are mutations: no automatic transport replay when
  the outcome is unknown. Response limits apply to retrieval/document payloads too.
- Chat is not inherently read-only: sessions and target-side tools can mutate state.
  Require isolated/stateless execution or explicit side-effect opt-in under the RAG contract.
- Access-control checks need distinct named setup/query credentials; never silently
  query as an administrator because a lower-privilege credential is missing.
