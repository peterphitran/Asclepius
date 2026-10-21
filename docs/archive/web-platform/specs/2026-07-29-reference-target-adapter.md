> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Reference Target Adapter Specification

## Goal

Provide a safe, deterministic HTTP target contract so the pipeline can test the bundled reference assistant or an explicitly configured external target.

## HTTP contract

The adapter sends:

```http
POST {target.endpoint}
Content-Type: application/json
X-Asclepius-Run-Id: {sweep_id}
X-Asclepius-Request-Id: {request_id}

{"message":"..."}
```

It accepts a JSON response containing a string `response`. Non-2xx responses, malformed JSON, missing `response`, and timeouts become structured target errors.

## Adapter interface

```python
class TargetAdapter(Protocol):
    async def send(
        self,
        target: TargetConfig,
        message: str,
        *,
        request_id: str,
        timeout_seconds: float,
    ) -> TargetResponse: ...
```

`TargetResponse` contains status code, response text, latency, request ID, and optional error metadata.

## Reference target

Add a local FastAPI service under a clearly separated target package or service. It must:

- expose `POST /chat` with the contract above;
- use synthetic patient records only;
- support deterministic fixtures for prompt injection, data exfiltration, role, RAG, and denial-of-service cases;
- expose `GET /health`;
- never be required for the dashboard API to start.

## Configuration

- `TARGET_URL` selects the default reference or external target.
- Per-target database endpoints remain authoritative for multi-tenant use.
- `TARGET_TIMEOUT_SECONDS`, `TARGET_MAX_RESPONSE_BYTES`, and retry count are bounded settings.

## Acceptance criteria

- The adapter can call the bundled target and parse a valid response.
- Timeout, network, malformed-response, and oversized-response cases produce typed errors.
- The pipeline can use an external target matching the same contract.
- Tests use a local HTTP fixture and do not require internet access.
