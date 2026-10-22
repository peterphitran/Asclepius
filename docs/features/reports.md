# Reports and Charts

Status: planned. Export results as local files for inspection and comparison.

## Sub-features

- `report-run`: generate a report for one run.
- `report-data`: export structured results.
- `report-charts`: visualize outcomes and compatible repeated runs.
- `report-open`: inspect the generated artifact locally.
- `report-overwrite` (proposed default): refuse existing output unless explicitly overwriting.

## How to get to it (user POV)

Select a run or comparison and generate a local report. JSON, Markdown, and HTML
are candidate formats; chart types, output paths, and export syntax remain open.

## Driving it with the terminal

Generate an artifact from known results and check its run IDs, counts, and evidence
against saved data. For HTML, open it and confirm charts render. Include empty/incomplete
runs, existing output paths, and trend data with incompatible versions.
Export while the daemon is stopped and verify that repeated exports create no target
or agent-provider calls.

## Gotchas

- A file path alone does not establish a readable chart.
- Prompts and replies need safe rendering as data.
- Zero checks, missing data, and errors must not yield invented success rates.
- Show corpus/query/rubric versions, coverage, metric denominators, and cleanup warnings.
  Do not equate retrieval relevance, answer grounding, and security pass rates.
- Reports are sensitive local artifacts, not sanitized public disclosures. Escape HTML
  and Markdown content, avoid active remote resources, and sanitize terminal controls.
- An export of a running run is a labeled point-in-time snapshot, not a final report.
  Chart polish and final formats remain open; saved evidence is the source of truth.
