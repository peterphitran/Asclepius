# Reports and charts

Status: JSON, Markdown, and self-contained HTML exports with inline SVG outcome/family
counts are implemented. Task 9 records both
installed-platform proofs, CommonMark rendering, and browser observations.

## Sub-features

- `report-run`: generate a report for one run.
- `report-data`: export structured results.
- `report-charts`: visualize outcomes and compatible repeated runs.
- `report-open`: inspect the generated artifact locally.
- `report-overwrite`: refuse existing output unless explicitly overwriting.

## How to get to it (user POV)

Select one or more saved runs and an existing output directory:

```text
asclepius report <run-id> --format html --output reports/run.html
asclepius report <run-a> <run-b> --format markdown --output reports/comparison.md
asclepius report <run-id> --format json --output reports/run.json
```

Add `--overwrite` deliberately to replace an existing regular destination. Reports contain
actual generated/judged counts, separate controls and delivery outcomes, usage coverage,
configuration identities, uncertainty, and saved evidence. Historical planned case totals
remain unknown. A comparison shows its settings relation and per-family counts without
claiming matched inputs or immutable remote model revisions. HTML has inline SVG charts;
Markdown keeps untrusted content in literal code blocks. See [commands](../development.md).

## Driving it with the terminal

Generate an artifact from known results and check its run IDs, counts, and evidence
against saved data. For HTML, open it and confirm charts render. Include empty/incomplete
runs, existing output paths, and trend data with incompatible versions.
Export while the daemon is stopped and verify that repeated exports create no target
or agent-provider calls.

## Gotchas

- A file path alone does not establish a readable chart. Task 9 includes actual browser
  observations of complete, comparison, empty, and partial reports.
- Output requires a user-controlled existing local directory supporting atomic link/replace.
  Default publication cannot clobber a concurrent creator; explicit overwrite replaces the
  directory entry atomically. Precommit failure leaves previous bytes intact.
- Persistent destination lock files are intentional. Cleanup removes only the writer's own
  temporary file. A reported postcommit durability error can leave the new artifact present.
  Atomic visibility does not establish Windows power-loss durability.
- Prompts and replies need safe rendering as data.
- Zero checks, missing data, and errors must not yield invented success rates.
- Show corpus/query/rubric versions, coverage, metric denominators, and cleanup warnings.
  Do not equate retrieval relevance, answer grounding, and security pass rates.
- Reports are sensitive local artifacts, not sanitized public disclosures. Escape HTML
  and Markdown content, avoid active remote resources, and sanitize terminal controls.
- An export of a running run is a labeled point-in-time snapshot, not a final report.
  Chart polish and final formats remain open; saved evidence is the source of truth.
