# Target Connections

Status: planned. Send test input and extract a reply using the selected profile.

## Sub-features

- `connection-http` (proposed first adapter): support a configured chat endpoint.
- `connection-mapping`: describe request fields and response extraction.
- `connection-auth`: supply required target credentials.
- `connection-errors`: distinguish network, timeout, protocol, and missing-reply failures.
- Direct-provider, streaming, multi-turn, and document-ingestion adapters remain candidates.

## How to get to it (user POV)

Configure the profile before running checks. A model, chatbot, or RAG app may expose
an HTTP chat endpoint; application type alone does not determine the adapter.
The first protocol and mapping syntax are design pending.

## Driving it with the terminal

Use a local fixture with a request log. Verify destination, request structure, extracted
reply, limits, and error classification through an actual run. Include valid, malformed,
oversized, and delayed replies. Confirm credential values are absent from shared output.

## Gotchas

- No single JSON shape works for every target.
- Chat access does not provide document ingestion for retrieval tests.
- Supporting UI-only applications would require a separate adapter.
