# Existing API Reference

This records the HTTP implementation available in the current working checkout. Its
routes and terminology are migration references, not the planned product's interface.
Use [development setup](../development.md) to launch it and [status](../status.md) for
code locations and reuse gaps.

## Operations

| Action | Route | Current behavior |
| --- | --- | --- |
| Process health | `GET /health` | Status, service, environment, and version. |
| Route schema | `GET /openapi.json` | Registered operations and payload schemas. |
| Login | `POST /auth/login` | Form username/password produces a bearer token. |
| Current user | `GET /auth/me` | User and organization for the token. |
| Targets | `GET /targets`, `GET /targets/{target_id}` | Stored connection labels and finding counts. |
| Create target | `POST /targets` | Persists a record without probing the endpoint. |
| Campaigns | `GET /campaigns`, `GET /campaigns/{campaign_id}` | Stored campaign configuration. |
| Create campaign | `POST /campaigns` | Persists a queued campaign/sweep and returns `sweepId`; no execution. |
| Sweeps | `GET /sweeps`, `GET /sweeps/{sweep_id}` | Stored lifecycle metadata and steps. |
| Findings | `GET /findings`, `GET /findings/{finding_id}` | Stored evidence and target association. |
| Review list | `GET /review` | Pending-review findings. |
| Review outcome | `PATCH /findings/{finding_id}` | Writes approved/rejected status. |
| Summary | `GET /dashboard` | Target, running-sweep, open-finding, and review counts. |

Data operations require a bearer token and are scoped to the user's organization.
There are no cancel/retry HTTP routes; the similarly named lifecycle functions are internal.

## Verification boundaries

The [recorded smoke](../verification.md) covers health, route discovery, and missing-token
rejection. To exercise data paths, use a disposable schema and fixture account, submit
through HTTP, then re-read results in a fresh session. For review, check persistence,
pending-list changes, and summary counts using separate approve/reject fixtures.

Exercise invalid payloads, missing/foreign IDs, empty lists, and expired credentials.
Review authorization, malformed token subjects, and target probing are known gaps;
do not assume they satisfy the intended behavior.

Existing clinical result fields, seeded activity, and organization scoping need deliberate
redesign before becoming general CLI features.
