from pathlib import Path

import asclepius
from scripts.pipeline_fixture import cli, isolated_python


def test_cli_ignores_shadow_package_in_cwd_and_pythonpath(tmp_path, monkeypatch):
    shadow = tmp_path / "shadow"
    package = shadow / "asclepius"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "__main__.py").write_text('print(\'{"ok": true, "data": {"shadow": true}}\')')
    monkeypatch.chdir(shadow)
    monkeypatch.setenv("PYTHONPATH", str(shadow))
    child = isolated_python("-c", "import asclepius; print(asclepius.__file__)")
    assert child.returncode == 0, child.stderr
    assert Path(child.stdout.strip()).resolve() == Path(asclepius.__file__).resolve()
    directory = tmp_path / "store"
    result = cli(directory, "init")
    assert result.get("shadow") is None
    assert (directory / "asclepius.sqlite3").is_file()
    try:
        started = cli(directory, "daemon", "start")
        assert started["state"] == "ready"
        assert started["owned"] is True
        assert started["responsive"] is True
    finally:
        stopped = cli(directory, "daemon", "stop")
    assert stopped["state"] == "stopped"
    assert stopped["owned"] is False
