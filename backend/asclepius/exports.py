import hashlib
import html
import json
import os
import stat
import tempfile
import unicodedata
from pathlib import Path
from typing import Literal

import portalocker

from asclepius.domain import AppError, Comparison, ExportArtifact, RunResults, RunView
from asclepius.results import summarize_run


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


def _sections(view: RunView, summary: RunResults):
    yield (
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
    )
    yield "Target, evaluator, budgets and pinned checks", view.snapshot.model_dump(mode="json")
    yield (
        "Delivery and judgment denominators",
        {
            "attacks": summary.attacks.model_dump(mode="json"),
            "controls": summary.controls.model_dump(mode="json"),
            "legacy_unclassified": summary.legacy_unclassified.model_dump(mode="json"),
        },
    )
    yield (
        "Usage coverage and evaluator actors",
        {
            "target": summary.target_usage.model_dump(mode="json"),
            "evaluator": summary.evaluator_usage.model_dump(mode="json"),
            "actors": [actor.model_dump(mode="json") for actor in summary.evaluators],
            "meaning": (
                "Token totals cover measured observations only. Missing counters are unknown."
            ),
        },
    )
    yield "Stage diagnostics", [item.model_dump(mode="json") for item in view.attempts]
    yield "Generated cases", [item.model_dump(mode="json") for item in view.variants]
    yield (
        "Legacy cases with unknown kind and saved requests",
        [item.model_dump(mode="json") for item in view.legacy_cases],
    )
    yield (
        "Observations and raw byte metadata",
        [item.model_dump(mode="json") for item in view.observations],
    )
    yield (
        "Judgments, assertions and metric denominators",
        [item.model_dump(mode="json") for item in view.judgments],
    )
    yield "Findings and evidence", [item.model_dump(mode="json") for item in view.findings]


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


def render_report(
    view: RunView | Comparison, format: Literal["json", "markdown", "html"]
) -> ExportArtifact:
    if isinstance(view, Comparison):
        runs, summaries, assessment = view.runs, view.summaries, view.assessment
    else:
        runs, summaries, assessment = (view,), (summarize_run(view),), None
    if format == "json":
        return ExportArtifact(
            format=format,
            content=_json(
                {
                    "report_schema_version": 1,
                    "runs": [run.model_dump(mode="json") for run in runs],
                    "summaries": [summary.model_dump(mode="json") for summary in summaries],
                    "assessment": assessment.model_dump(mode="json") if assessment else None,
                }
            )
            + "\n",
        )
    if format not in {"markdown", "html"}:
        raise AppError("arguments", "Unsupported report format.", 2)
    markdown = format == "markdown"
    parts = (
        ["# Asclepius results\n\n"]
        if markdown
        else [
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
        ]
    )
    notice = (
        "Counts describe saved evidence as of capture. Generated cases are actual; planned cases "
        "are unknown. Missing judgment is not a pass. Delivery and judgments are independent. "
        "Remote revision is unknown. Generated input matching is not established. "
        "No paired deltas, ranking or causal inference is asserted."
    )
    parts.append(notice + "\n\n" if markdown else f"<p>{notice}</p>")
    if assessment:
        body = _json(assessment.model_dump(mode="json"))
        parts.append(
            "## Comparison assessment\n\n" + _literal(body)
            if markdown
            else "<h2>Comparison assessment</h2><pre>" + html.escape(body) + "</pre>"
        )
    for index, (run, summary) in enumerate(zip(runs, summaries, strict=True), 1):
        heading = f"Run {index}"
        parts.append(f"## {heading}\n\n" if markdown else f"<h2>{heading}</h2>")
        if not markdown:
            parts.append(_chart(summary))
        for title, value in _sections(run, summary):
            body = _json(value)
            if markdown:
                parts.append(f"### {title}\n\n" + _literal(body))
            elif title in {
                "Run identity and capture",
                "Delivery and judgment denominators",
                "Usage coverage and evaluator actors",
            }:
                parts.append(f"<h3>{title}</h3><pre>{html.escape(body)}</pre>")
            else:
                parts.append(
                    f"<details><summary>{title}</summary><pre>{html.escape(body)}</pre></details>"
                )

    parts.append("## Per-family comparison\n\n" if markdown else "<h2>Per-family comparison</h2>")
    families = dict.fromkeys(family.family for summary in summaries for family in summary.families)
    for family in families:
        parts.append(
            _literal(family) if markdown else f"<h3>{html.escape(safe_terminal(family))}</h3>"
        )
        headers = (
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
        if markdown:
            parts.append(
                "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n"
            )
        else:
            parts.append(
                "<table><thead><tr>"
                + "".join(f"<th>{h}</th>" for h in headers)
                + "</tr></thead><tbody>"
            )
        for index, summary in enumerate(summaries, 1):
            row = next((item for item in summary.families if item.family == family), None)
            values = (index,) + (
                ("not-selected",) * (len(headers) - 1)
                if row is None
                else (
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
            parts.append(
                "| " + " | ".join(map(str, values)) + " |\n"
                if markdown
                else "<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>"
            )
        parts.append("\n" if markdown else "</tbody></table>")
    if not markdown:
        parts.append("</body></html>\n")
    return ExportArtifact(format=format, content="".join(parts))


def _regular_single(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AppError(
            "export_unsafe", "Export destination and lock must be regular single-link files."
        )
    return info


def write_export(artifact: ExportArtifact, destination: Path, overwrite: bool = False) -> Path:
    temporary = None
    committed = False
    try:
        parent = destination.parent.resolve(strict=True)
        name = destination.name
        if (
            not name
            or name in {".", ".."}
            or "\x00" in name
            or (
                os.name == "nt"
                and (
                    name.endswith((" ", "."))
                    or ":" in name
                    or (
                        os.path.isreserved(name)
                        if hasattr(os.path, "isreserved")
                        else destination.is_reserved()
                    )
                )
            )
        ):
            raise AppError("export_unsafe", "Unsafe export filename.")
        target = parent / name
        identity = os.path.normcase(str(target))
        digest = hashlib.sha256(os.fsencode(identity)).hexdigest()
        lock_path = parent / f".asclepius-export-{digest}.lock"
        _regular_single(lock_path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        with os.fdopen(descriptor, "r+b") as lock:
            info = _regular_single(lock_path)
            opened = os.fstat(lock.fileno())
            if info is None or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                raise AppError("export_unsafe", "Export lock identity changed.")
            if os.name != "nt" and opened.st_uid != os.getuid():
                raise AppError("export_unsafe", "Export lock belongs to another user.")
            portalocker.lock(lock, portalocker.LOCK_EX)
            try:
                existing = _regular_single(target)
                if existing is not None and not overwrite:
                    raise AppError("export_exists", "Export destination already exists.", 2)
                descriptor, temporary = tempfile.mkstemp(
                    prefix=".asclepius-export-", suffix=".tmp", dir=parent
                )
                with os.fdopen(descriptor, "wb") as output:
                    output.write(artifact.content.encode("utf-8"))
                    output.flush()
                    os.fsync(output.fileno())
                _regular_single(target)
                if overwrite:
                    os.replace(temporary, target)
                    temporary = None
                else:
                    os.link(temporary, target)
                committed = True
                if temporary is not None:
                    os.unlink(temporary)
                    temporary = None
                if os.name != "nt":
                    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            finally:
                portalocker.unlock(lock)
        return target
    except FileExistsError:
        raise AppError("export_exists", "Export destination already exists.", 2) from None
    except (OSError, portalocker.LockException):
        if committed:
            raise AppError(
                "export_committed", "Export was published; durability confirmation failed."
            ) from None
        raise AppError("export_error", "Cannot publish export on this filesystem.") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                raise AppError(
                    "export_committed" if committed else "export_error",
                    "Export was published; temporary cleanup failed."
                    if committed
                    else "Export was not published; temporary cleanup failed.",
                ) from None
