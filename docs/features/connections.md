# Target connections

Status: partial. Groq chat boundaries and queued CLI execution are implemented and verified
with deterministic HTTPS providers. Hosted-model acceptance remains unverified.

## Sub-features

- `connection-http` (component implementation): one Groq-compatible HTTPS chat POST.
- `connection-mapping` (component implementation): fixed Groq message/reply format, not arbitrary field mapping.
- `connection-auth` (component implementation): independent target/evaluator environment references.
- `connection-errors` (component implementation): network uncertainty, deadline, provider HTTP,
  protocol, explicit refusal, unsupported tools, truncation, and missing-reply outcomes.
- `connection-capabilities`: declare chat, retrieval, ingestion, readiness, and optional
  update/delete/isolation support independently.
- `connection-ollama` (offline verified; live pending a local install): a local Ollama target
  through its native, non-streaming `/api/chat`. See below.
- Streaming, multi-turn, ingestion, and retrieval adapters remain planned.

## Local Ollama targets

Set `adapter = "ollama-chat"` in the target file (see `examples/ollama-target.toml`).
The target is your own Ollama server; the evaluator stays on Groq with its own credential.

- No credential: an Ollama target refuses `secret_ref`, and no `Authorization` header is sent.
- Plain `http` is allowed only for `localhost`, `127.0.0.1` and `::1`; other hosts need `https`.
- `max_completion_tokens` is sent as Ollama's `num_predict`, and the same request, response,
  rate and token limits apply as for a hosted target.
- Asclepius never pulls a model or starts the server. A model that is not installed fails
  with `local_model_missing`; a stopped server fails with `provider_connection`.
- Ollama replies have no response ID, so `response_id` is empty; `provider_model` is the
  model name Ollama reports.
- A hosted run and a local run of the same pack compare as checks-compatible, with the one
  named difference `target_config`.

Opt-in live checks: start Ollama, install a model yourself, then run
`ASCLEPIUS_LIVE_OLLAMA=1 ASCLEPIUS_OLLAMA_MODEL=<model> python -m pytest tests/cli/test_live_ollama.py -m live`.

## How to get to it (user POV)

Configure the profile before running checks. A model, chatbot, or RAG app may expose
an HTTP chat endpoint; application type alone does not determine the adapter.
The [backend design](../specs/backend-design.md) proposes the first adapter contract.
Generic request templates and reply selectors are not implemented. Current provider
boundaries live in `asclepius/adapters/chat.py` and `models.py`.

## Driving it with the terminal

Use a local fixture with a request log. Verify destination, request structure, extracted
reply, limits, and error classification through an actual run. Include valid, malformed,
oversized, and delayed replies. Confirm credential values are absent from shared output.
The current installed-wheel proof runs `scripts/verify_groq.py` against loopback
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
  new connection/run. Redaction covers only configured credential values, not synthetic canaries.
- Evaluator output is checked against the exact sent schema before typed construction.
  Schema compliance does not prove evidence truth or an independent judge.
- Provider errors retain validated `retry_after` timing as decimal seconds or an HTTP date.
  Asclepius discards invalid, duplicate, oversized, or credential-bearing values. Timing is
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

Saved chat replies expose optional `provider_model` in observation payloads and exports.
This value comes from the provider response after redaction. Requested model names remain
in pinned configuration. Missing reported metadata is unknown, and the value is a provider
self-report rather than proof of a deployment.
