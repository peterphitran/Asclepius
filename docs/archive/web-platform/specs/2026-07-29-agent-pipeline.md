> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Agent Pipeline Specification

## Goal

Implement the four-agent pipeline described by the README as independently testable, structured components.

## Agent contracts

### Selector

Input: target profile, attack history, available case definitions, and campaign constraints.

Output: case ID, strategy ID, rationale, and selection metadata.

The selector must avoid selecting completed work unless the campaign explicitly requests retries.

### Generator

Input: selected case and strategy.

Output: bounded list of distinct prompt variants, each with a stable variant ID.

The generator must preserve the case objective and obey safety constraints. It must not receive secrets or unrelated tenant data.

### Judge

Input: case objective, prompt variant, target response, and rubric.

Output: success boolean, confidence, evidence summary, violated signals, and error classification.

Judging must be blind to selector rationale where practical to reduce confirmation bias.

### Reporter

Input: confirmed successful judge results and target metadata.

Output: title, severity, description, patient-safety impact, reproduction steps, recommendation, attack prompt, and target response.

## Model gateway

All LLM calls go through one provider-neutral gateway with:

- provider/model configuration;
- request timeout and retry policy;
- token and cost limits;
- structured-output validation;
- redacted request/response logging;
- deterministic fake provider for tests.

The first production provider may be Anthropic, with OpenAI cross-validation optional. Provider-specific code must not leak into pipeline orchestration.

## Persistence

The coordinator persists an agent step before and after execution. A failed agent step records error detail and can be retried without duplicating its successful output.

## Acceptance criteria

- Each agent has unit tests against a fake model gateway.
- Structured outputs reject malformed model responses.
- A full synthetic case can pass through all four agents without external provider access.
- Provider credentials are loaded only from environment/configuration and never from database case content.
