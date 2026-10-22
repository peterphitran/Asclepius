# Reports and Charts

Status: planned. Export results as local files for inspection and comparison.

## Sub-features

- `report-run`: generate a report for one run.
- `report-data`: export structured results.
- `report-charts`: visualize outcomes and compatible repeated runs.
- `report-open`: inspect the generated artifact locally.
- `report-overwrite` (design pending): handle an existing output path predictably.

## How to get to it (user POV)

Select a run or comparison and generate a local report. JSON, Markdown, and HTML
are candidate formats; chart types, output paths, and export syntax remain open.

## Driving it with the terminal

Generate an artifact from known results and check its run IDs, counts, and evidence
against saved data. For HTML, open it and confirm charts render. Include empty/incomplete
runs, existing output paths, and trend data with incompatible versions.

## Gotchas

- A file path alone does not establish a readable chart.
- Prompts and replies need safe rendering as data.
- Zero checks, missing data, and errors must not yield invented success rates.
