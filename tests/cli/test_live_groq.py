import os
import sys
from pathlib import Path

import pytest

from scripts.live_groq_fixture import prerequisites, read_config, run_workflow


@pytest.mark.live
def test_real_groq_two_full_broad_trials(tmp_path):
    if os.environ.get("ASCLEPIUS_LIVE_TESTS") != "1":
        pytest.skip("explicit_opt_in_missing")
    examples = Path(__file__).parents[2] / "examples"
    target = Path(os.environ.get("ASCLEPIUS_LIVE_TARGET", examples / "groq-target.toml"))
    evaluator = Path(os.environ.get("ASCLEPIUS_LIVE_EVALUATOR", examples / "groq-evaluator.toml"))
    reason = prerequisites(read_config(target), read_config(evaluator), os.environ)
    if reason:
        pytest.skip(reason)
    artifacts = Path(os.environ.get("ASCLEPIUS_LIVE_ARTIFACTS", tmp_path / "live-groq"))
    result = run_workflow(
        target,
        evaluator,
        artifacts,
        interpreter=os.environ.get("ASCLEPIUS_LIVE_PYTHON", sys.executable),
    )
    if result["status"] != "succeeded":
        pytest.fail("Live Groq workflow failed; inspect sanitized evidence.json", pytrace=False)
