import html
import json
import unicodedata
from collections.abc import Iterator
from typing import Literal, NamedTuple

from asclepius.domain import AppError, Comparison, ExportArtifact, RunResults, RunView
from asclepius.results import summarize_run

NOTICE = (
    "Counts describe saved evidence as of capture. Generated cases are actual; planned cases "
    "are unknown. Missing judgment is not a pass. Delivery and judgments are independent. "
    "Remote revision is unknown. Generated input matching is not established. "
    "No paired deltas, ranking or causal inference is asserted."
)
FAMILY_HEADERS = (
    "Run",
    "Requested checks",
    "Generated attacks",
    "Weakness",
    "Pass",
    "Inconclusive",
    "Missing attack judgment",
    "Generated controls",
    "Answered",
    "Over refusal",
    "Inconclusive controls",
    "Missing control judgment",
)
HTML_HEAD = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
    "style-src &#39;unsafe-inline&#39;; base-uri &#39;none&#39;; "
    'form-action &#39;none&#39;">'
    "<title>Asclepius results</title><style>"
    "body{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;"
    "color:#172338;background:#fff}pre{white-space:pre-wrap;overflow-wrap:anywhere;"
    "padding:1rem;background:#f2f5f9}table{border-collapse:collapse;width:100%}"
    "td,th{border:1px solid #bcc9da;padding:.5rem;text-align:left}"
    "svg{width:100%;max-width:650px}h2{margin-top:2rem}</style></head><body>"
    "<h1>Asclepius results</h1>"
)


class Section(NamedTuple):
    title: str
    data: object
    headline: bool = False


def safe_terminal(text: str) -> str:
    return "".join(
        f"\\u{ord(char):04x}" if unicodedata.category(char) in {"Cc", "Cf", "Cs"} else char
        for char in text
    )


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2)


def _literal(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join("    " + safe_terminal(line) for line in text.split("\n")) + "\n\n"


def _sections(view: RunView, summary: RunResults) -> Iterator[Section]:
    yield Section(
        "Run identity and capture",
        {
            "run_id": str(summary.run_id),
            "state": view.state.value,
            "partial": summary.partial,
            "captured_at": (view.captured_at.isoformat() if view.captured_at else "unavailable"),
            "reason": view.reason,
            "cancel_requested": view.cancel_requested,
            "requested_checks": summary.requested_checks,
            "generated_checks": summary.generated_checks,
            "planned_cases": None,
            "remote_revision": "unknown",
            "generated_input_matching": "not_established",
        },
        headline=True,
    )
    yield Section(
        "Target, evaluator, budgets and pinned checks", view.snapshot.model_dump(mode="json")
    )
    yield Section(
        "Delivery and judgment denominators",
        {
            "attacks": summary.attacks.model_dump(mode="json"),
            "controls": summary.controls.model_dump(mode="json"),
        },
        headline=True,
    )
    yield Section(
        "Usage coverage and evaluator actors",
        {
            "target": summary.target_usage.model_dump(mode="json"),
            "evaluator": summary.evaluator_usage.model_dump(mode="json"),
            "actors": [actor.model_dump(mode="json") for actor in summary.evaluators],
            "meaning": (
                "Token totals cover measured observations only. Missing counters are unknown."
            ),
        },
        headline=True,
    )
    yield Section("Stage diagnostics", [item.model_dump(mode="json") for item in view.attempts])
    yield Section("Generated cases", [item.model_dump(mode="json") for item in view.variants])
    yield Section(
        "Observations and raw byte metadata",
        [item.model_dump(mode="json") for item in view.observations],
    )
    yield Section(
        "Judgments, assertions and metric denominators",
        [item.model_dump(mode="json") for item in view.judgments],
    )
    yield Section("Findings and evidence", [item.model_dump(mode="json") for item in view.findings])


def _family_rows(summaries: tuple[RunResults, ...]) -> Iterator[tuple[str, list[tuple]]]:
    for family in dict.fromkeys(f.family for summary in summaries for f in summary.families):
        rows = []
        for index, summary in enumerate(summaries, 1):
            row = next((item for item in summary.families if item.family == family), None)
            if row is None:
                rows.append((index,) + ("not-selected",) * (len(FAMILY_HEADERS) - 1))
            else:
                rows.append(
                    (
                        index,
                        row.requested_checks,
                        row.attacks.generated,
                        row.attacks.weakness,
                        row.attacks.passed,
                        row.attacks.inconclusive,
                        row.attacks.missing_judgment,
                        row.controls.generated,
                        row.controls.answered,
                        row.controls.over_refusal,
                        row.controls.inconclusive,
                        row.controls.missing_judgment,
                    )
                )
        yield family, rows


def _chart(summary: RunResults) -> str:
    counts = summary.attacks
    rows = (
        ("Weakness", counts.weakness),
        ("Pass", counts.passed),
        ("Inconclusive", counts.inconclusive),
        ("Verdict unknown", counts.verdict_unknown),
        ("Missing judgment", counts.missing_judgment),
    )
    elements = ['<svg viewBox="0 0 600 180" role="img" aria-label="Attack outcome counts">']
    for index, (label, count) in enumerate(rows):
        width = 300 * count / counts.generated if counts.generated else 0
        y = 10 + index * 32
        elements.append(
            f'<text x="0" y="{y + 16}">{label}</text>'
            f'<rect x="180" y="{y}" width="{width:.4f}" height="22" fill="#3563a6"/>'
            f'<text x="500" y="{y + 16}">{count}</text>'
        )
    return "".join(elements) + "</svg>"


def _markdown(runs, summaries, assessment) -> str:
    parts = ["# Asclepius results\n\n", NOTICE + "\n\n"]
    if assessment:
        body = _json(assessment.model_dump(mode="json"))
        parts.append("## Comparison assessment\n\n" + _literal(body))
    for index, (run, summary) in enumerate(zip(runs, summaries, strict=True), 1):
        parts.append(f"## Run {index}\n\n")
        for section in _sections(run, summary):
            parts.append(f"### {section.title}\n\n" + _literal(_json(section.data)))
    parts.append("## Per-family comparison\n\n")
    for family, rows in _family_rows(summaries):
        parts.append(_literal(family))
        parts.append(
            "| "
            + " | ".join(FAMILY_HEADERS)
            + " |\n| "
            + " | ".join("---" for _ in FAMILY_HEADERS)
            + " |\n"
        )
        parts.extend("| " + " | ".join(map(str, values)) + " |\n" for values in rows)
        parts.append("\n")
    return "".join(parts)


def _html(runs, summaries, assessment) -> str:
    parts = [HTML_HEAD, f"<p>{NOTICE}</p>"]
    if assessment:
        body = _json(assessment.model_dump(mode="json"))
        parts.append("<h2>Comparison assessment</h2><pre>" + html.escape(body) + "</pre>")
    for index, (run, summary) in enumerate(zip(runs, summaries, strict=True), 1):
        parts.append(f"<h2>Run {index}</h2>")
        parts.append(_chart(summary))
        for section in _sections(run, summary):
            pre = f"<pre>{html.escape(_json(section.data))}</pre>"
            if section.headline:
                parts.append(f"<h3>{section.title}</h3>{pre}")
            else:
                parts.append(f"<details><summary>{section.title}</summary>{pre}</details>")
    parts.append("<h2>Per-family comparison</h2>")
    for family, rows in _family_rows(summaries):
        parts.append(f"<h3>{html.escape(safe_terminal(family))}</h3>")
        parts.append(
            "<table><thead><tr>"
            + "".join(f"<th>{h}</th>" for h in FAMILY_HEADERS)
            + "</tr></thead><tbody>"
        )
        parts.extend(
            "<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>" for values in rows
        )
        parts.append("</tbody></table>")
    parts.append("</body></html>\n")
    return "".join(parts)


def render_report(
    view: RunView | Comparison, format: Literal["json", "markdown", "html"]
) -> ExportArtifact:
    if isinstance(view, Comparison):
        runs, summaries, assessment = view.runs, view.summaries, view.assessment
    else:
        runs, summaries, assessment = (view,), (summarize_run(view),), None
    if format == "json":
        content = (
            _json(
                {
                    "report_schema_version": 1,
                    "runs": [run.model_dump(mode="json") for run in runs],
                    "summaries": [summary.model_dump(mode="json") for summary in summaries],
                    "assessment": assessment.model_dump(mode="json") if assessment else None,
                }
            )
            + "\n"
        )
    elif format == "markdown":
        content = _markdown(runs, summaries, assessment)
    elif format == "html":
        content = _html(runs, summaries, assessment)
    else:
        raise AppError("arguments", "Unsupported report format.", 2)
    return ExportArtifact(format=format, content=content)
