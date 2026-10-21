> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Attack Case Definitions Specification

## Goal

Replace prose-only attack coverage with versioned, validated case definitions that the selector and generator can consume safely.

## Case schema

Each case has:

```yaml
id: rag-hidden-instruction
version: 1
category: rag_poisoning
name: Hidden instruction in discharge summary
description: Synthetic description of the security objective
objective: What behavior demonstrates success
severity_hint: critical
strategies:
  - id: embedded-directive
    name: Embedded directive
    constraints:
      - Do not request real patient data
variants:
  min: 1
  max: 12
judge_rubric:
  success_signals: []
  failure_signals: []
```

## Coverage

Initial release must include the five README categories:

- prompt injection;
- data exfiltration using synthetic records;
- identity and role exploits;
- RAG poisoning;
- denial of service with bounded payloads.

The first release should preserve the existing 19-case intent, but cases may be migrated incrementally from the README into validated files.

## Loading and validation

- Load definitions at worker startup or through a versioned registry.
- Validate category, IDs, bounds, and rubric shape before accepting a campaign.
- Reject unknown case IDs and invalid variant counts before creating a sweep.
- Store selected case ID and version on each sweep step for reproducibility.

## Safety constraints

- No real PHI or production patient identifiers in case files.
- DoS cases must have explicit size, time, and request-count ceilings.
- Data exfiltration cases must target synthetic fixtures and redact captured output in normal logs.
- Case prompts must be treated as untrusted content by the pipeline.

## Acceptance criteria

- All initial case files validate in CI.
- A campaign can select categories and resolve them to deterministic case versions.
- A failed or retried sweep can identify the exact case and strategy version used.
- Adding a new case does not require changing agent orchestration code.
