import json
import multiprocessing
import os
from html.parser import HTMLParser
from pathlib import Path

import pytest

from asclepius.domain import AppError, ExportArtifact
from asclepius.exports import render_report, safe_terminal, write_export
from asclepius.results import assess_runs
from tests.cli.view_support import HOSTILE, alternate, evidence_view, hostile_view


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def test_json_report_preserves_exact_evidence_and_explicit_denominators():
    view = hostile_view()
    document = json.loads(render_report(view, "json").content)
    assert document["report_schema_version"] == 1
    assert document["runs"][0] == view.model_dump(mode="json")
    assert document["summaries"][0]["attacks"]["generated"] == 6
    assert document["summaries"][0]["controls"]["generated"] == 3
    assert document["summaries"][0]["target_usage"]["output_tokens"] is None


def test_html_keeps_hostile_metadata_evidence_and_family_names_inert():
    content = render_report(hostile_view(), "html").content
    document = Elements()
    document.feed(content)
    allowed = {
        "html",
        "head",
        "meta",
        "title",
        "style",
        "body",
        "h1",
        "h2",
        "h3",
        "p",
        "pre",
        "svg",
        "text",
        "rect",
        "table",
        "thead",
        "tbody",
        "details",
        "summary",
        "tr",
        "th",
        "td",
    }
    assert {tag for tag, _ in document.elements} <= allowed
    assert "<script>" not in content
    assert not any(
        name.lower().startswith("on") or name in {"href", "src"}
        for _, attrs in document.elements
        for name in attrs
    )
    assert any(
        attrs.get("http-equiv") == "Content-Security-Policy" for _, attrs in document.elements
    )
    assert safe_terminal(HOSTILE) in document.text
    assert "Attack outcome counts" in content
    assert 'width="50.0000"' in content
    assert "<td>6</td>" in content and "<td>3</td>" in content
    assert "capture" in content


def test_markdown_untrusted_values_are_indented_including_blank_lines():
    content = render_report(hostile_view(), "markdown").content
    assert "    <script>alert(1)</script>\n    \n    [click](https://evil.invalid)" in content
    assert "    ```\n    # injected\n" in content
    for line in content.splitlines():
        if line and not line.startswith("    "):
            assert not any(
                token in line
                for token in ("script", "evil.invalid", "```", "injected", "\x1b", "\u202e")
            )
    assert "| 1 | 1 | 6 | 1 | 1 | 1 | 3 | 3 | 1 | 1 | 0 | 0 |" in content


@pytest.mark.parametrize("newline", ["\r", "\r\n"])
def test_markdown_family_newlines_remain_literal_and_json_preserves_evidence(newline):
    view = evidence_view()
    family = "Family" + newline + '<script>alert("family")</script>'
    check = view.snapshot.checks[0].model_copy(update={"family": family})
    view = alternate(view, checks=(check, view.snapshot.checks[1]))
    content = render_report(view, "markdown").content
    assert '    Family\n    <script>alert("family")</script>\n' in content
    assert "\r" not in content
    document = json.loads(render_report(view, "json").content)
    assert document["runs"][0]["snapshot"]["checks"][0]["family"] == family


@pytest.mark.parametrize("format", ["markdown", "html"])
def test_family_terminal_and_bidi_controls_are_visible_in_display_only(format):
    view = evidence_view()
    family = "Family\x1b]8;;https://evil.invalid\x07label\x1b]8;;\x07\u202e"
    check = view.snapshot.checks[0].model_copy(update={"family": family})
    view = alternate(view, checks=(check, view.snapshot.checks[1]))
    content = render_report(view, format).content
    assert "\x1b" not in content and "\x07" not in content and "\u202e" not in content
    assert r"Family\u001b]8;;https://evil.invalid\u0007label\u001b]8;;\u0007\u202e" in content
    document = json.loads(render_report(view, "json").content)
    assert document["runs"][0]["snapshot"]["checks"][0]["family"] == family


def test_comparison_shows_not_selected_only_for_absent_pinned_family():
    view = evidence_view()
    other = alternate(view, checks=(view.snapshot.checks[0],))
    html = render_report(assess_runs((view, other)), "html").content
    assert "incompatible" in html
    assert "<h3>unrun</h3>" in html
    assert "<td>not-selected</td>" in html
    assert "<td>1</td><td>1</td><td>0</td>" in html


def test_terminal_controls_are_visible_without_changing_printable_text():
    assert safe_terminal("ok\x1b]8;;url\x07\n\u202eé") == "ok\\u001b]8;;url\\u0007\\u000a\\u202eé"
    assert (
        json.loads(render_report(hostile_view(), "json").content)["runs"][0]["findings"][0][
            "description"
        ]
        == HOSTILE
    )


def artifact(text="new bytes"):
    return ExportArtifact(format="json", content=text)


def test_export_no_clobber_overwrite_and_private_temporary_cleanup(tmp_path):
    destination = tmp_path / "report.json"
    assert write_export(artifact(), destination) == destination
    assert destination.read_bytes() == b"new bytes"
    with pytest.raises(AppError) as error:
        write_export(artifact("replacement"), destination)
    assert error.value.code == "export_exists"
    assert destination.read_bytes() == b"new bytes"
    write_export(artifact("replacement"), destination, overwrite=True)
    assert destination.read_bytes() == b"replacement"
    assert list(tmp_path.glob("*.tmp")) == []
    locks = list(tmp_path.glob("*.lock"))
    assert len(locks) == 1
    if os.name != "nt":
        assert destination.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["flush", "replace", "interrupt"])
def test_prepublication_failure_preserves_previous_bytes(tmp_path, monkeypatch, failure):
    destination = tmp_path / "report.json"
    destination.write_bytes(b"previous")

    def fail(*args):
        if failure == "interrupt":
            raise KeyboardInterrupt
        raise OSError("fixture failure")

    monkeypatch.setattr(os, "fsync" if failure != "replace" else "replace", fail)
    expected = KeyboardInterrupt if failure == "interrupt" else AppError
    with pytest.raises(expected):
        write_export(artifact(), destination, overwrite=True)
    assert destination.read_bytes() == b"previous"
    assert list(tmp_path.glob("*.tmp")) == []


def test_external_creator_cannot_be_clobbered_between_check_and_publication(tmp_path, monkeypatch):
    destination = tmp_path / "report.json"
    original = os.link

    def race(source, target):
        Path(target).write_bytes(b"external creator")
        original(source, target)

    monkeypatch.setattr(os, "link", race)
    with pytest.raises(AppError) as error:
        write_export(artifact(), destination)
    assert error.value.code == "export_exists"
    assert destination.read_bytes() == b"external creator"
    assert list(tmp_path.glob("*.tmp")) == []


def test_unsupported_hardlink_has_no_clobber_fallback(tmp_path, monkeypatch):
    def unsupported(*args):
        raise OSError("filesystem has no hardlink support")

    monkeypatch.setattr(os, "link", unsupported)
    destination = tmp_path / "report.json"
    with pytest.raises(AppError) as error:
        write_export(artifact(), destination)
    assert error.value.code == "export_error"
    assert not destination.exists()
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.skipif(os.name == "nt", reason="Directory fsync is a POSIX durability operation.")
def test_postpublication_durability_failure_identifies_committed_output(tmp_path, monkeypatch):
    original = os.fsync
    calls = 0

    def fail_directory(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory durability unavailable")
        original(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory)
    destination = tmp_path / "report.json"
    with pytest.raises(AppError) as error:
        write_export(artifact(), destination)
    assert error.value.code == "export_committed"
    assert destination.read_bytes() == b"new bytes"


@pytest.mark.parametrize("kind", ["directory", "hardlink", "symlink"])
def test_unsafe_existing_leaf_is_not_followed_or_replaced(tmp_path, kind):
    original = tmp_path / "original"
    original.write_bytes(b"protected")
    destination = tmp_path / "report.json"
    if kind == "directory":
        destination.mkdir()
    elif kind == "hardlink":
        os.link(original, destination)
    else:
        try:
            destination.symlink_to(original)
        except OSError as error:
            if os.name == "nt" and error.winerror == 1314:
                pytest.skip("Windows account cannot create symlinks.")
            raise
    with pytest.raises(AppError) as error:
        write_export(artifact(), destination, overwrite=True)
    assert error.value.code == "export_unsafe"
    assert original.read_bytes() == b"protected"


def publication_worker(destination, text, ready, start, outcomes):
    ready.put(True)
    if not start.wait(10):
        outcomes.put("timeout")
        return
    try:
        write_export(artifact(text), Path(destination))
        outcomes.put("written")
    except AppError as error:
        outcomes.put(error.code)


def test_independent_processes_publish_exactly_one_complete_artifact(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready, outcomes = context.Queue(), context.Queue()
    start = context.Event()
    destination = tmp_path / "report.json"
    values = [letter * 100000 for letter in "ABC"]
    children = [
        context.Process(
            target=publication_worker, args=(str(destination), value, ready, start, outcomes)
        )
        for value in values
    ]
    try:
        for child in children:
            child.start()
        for _ in children:
            assert ready.get(timeout=15) is True
        start.set()
        assert sorted(outcomes.get(timeout=15) for _ in children) == [
            "export_exists",
            "export_exists",
            "written",
        ]
        for child in children:
            child.join(15)
            assert child.exitcode == 0
        assert destination.read_text(encoding="utf-8") in values
        assert list(tmp_path.glob("*.tmp")) == []
    finally:
        start.set()
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(5)
        ready.close()
        outcomes.close()


def test_destination_aliases_share_persistent_lock_and_refuse_clobber(tmp_path):
    subdirectory = tmp_path / "subdirectory"
    subdirectory.mkdir()
    destination = tmp_path / "report.json"
    write_export(artifact("first"), destination)
    with pytest.raises(AppError) as error:
        write_export(artifact("second"), subdirectory / ".." / "report.json")
    assert error.value.code == "export_exists"
    assert destination.read_bytes() == b"first"
    assert len(list(tmp_path.glob("*.lock"))) == 1


def test_export_refuses_multilink_lock_without_touching_destination(tmp_path):
    destination = tmp_path / "report.json"
    write_export(artifact("first"), destination)
    lock = next(tmp_path.glob("*.lock"))
    os.link(lock, tmp_path / "lock-alias")
    with pytest.raises(AppError) as error:
        write_export(artifact("second"), destination, overwrite=True)
    assert error.value.code == "export_unsafe"
    assert destination.read_bytes() == b"first"


def test_human_cli_errors_escape_terminal_controls(monkeypatch, capsys):
    from asclepius.cli import main

    async def fail(*args):
        raise AppError("fixture", "bad \x1b]8;;url\x07\u202e path")

    monkeypatch.setattr("asclepius.cli.dispatch", fail)
    assert main(["init"]) == 5
    assert capsys.readouterr().err == "bad \\u001b]8;;url\\u0007\\u202e path\n"
    assert main(["init", "--json"]) == 5
    assert (
        json.loads(capsys.readouterr().out)["error"]["message"] == "bad \x1b]8;;url\x07\u202e path"
    )


def test_published_output_remains_visible_when_own_temp_cleanup_fails(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("cleanup unavailable")

    monkeypatch.setattr(os, "unlink", fail)
    destination = tmp_path / "report.json"
    with pytest.raises(AppError) as error:
        write_export(artifact("published"), destination)
    assert error.value.code == "export_committed"
    assert destination.read_bytes() == b"published"
    assert len(list(tmp_path.glob("*.tmp"))) == 1
