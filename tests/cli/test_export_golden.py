import re
from pathlib import Path

import pytest

from asclepius.exports import render_report
from asclepius.results import assess_runs
from tests.cli.view_support import alternate, evidence_view, hostile_view

GOLDEN = Path(__file__).parent / "fixtures" / "exports"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:\+00:00|Z)?")


def normalize(content: str) -> str:
    seen: dict[str, str] = {}
    content = UUID.sub(lambda m: seen.setdefault(m.group(), f"<uuid-{len(seen)}>"), content)
    return STAMP.sub("<time>", content)


def subjects():
    view = evidence_view()
    other = alternate(view, checks=(view.snapshot.checks[0],))
    return {"hostile": hostile_view(), "comparison": assess_runs((view, other))}


@pytest.mark.parametrize("name", ["hostile", "comparison"])
@pytest.mark.parametrize("format", ["json", "markdown", "html"])
def test_rendered_reports_match_golden_bytes(name, format):
    content = normalize(render_report(subjects()[name], format).content)
    golden = GOLDEN / f"{name}.{format}"
    assert content == golden.read_bytes().decode("utf-8")
