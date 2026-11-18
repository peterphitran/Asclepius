import asyncio
import json
import os
import urllib.request

import pytest

from tests.cli.groq_support import execute_target
from tests.cli.ollama_support import setup


def _live_settings():
    if os.environ.get("ASCLEPIUS_LIVE_OLLAMA") != "1":
        pytest.skip("explicit_opt_in_missing")
    model = os.environ.get("ASCLEPIUS_OLLAMA_MODEL")
    if not model:
        pytest.skip("ollama_model_not_named")
    base = os.environ.get("ASCLEPIUS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=5) as response:
            installed = {item["name"] for item in json.load(response).get("models", [])}
    except OSError:
        pytest.skip("ollama_server_unreachable")
    if model not in installed:
        pytest.skip("ollama_model_not_installed")
    return base, model


def _with_model(snapshot, model):
    target = snapshot.profile.target.model_copy(update={"model": model})
    return snapshot.model_copy(
        update={"profile": snapshot.profile.model_copy(update={"target": target})}
    )


@pytest.mark.live
def test_live_local_chat_observation(tmp_path, monkeypatch):
    base, model = _live_settings()

    async def scenario():
        _, snapshot, work, connection = await setup(None, tmp_path, monkeypatch, base_url=base)
        connection.snapshot = _with_model(snapshot, model)
        observation = await execute_target(connection, work, "Reply with OK.")
        assert observation.status == "success", observation.error_code
        assert observation.payload.content.strip()
        assert observation.payload.provider_model
        assert observation.payload.usage.output_tokens is not None

    asyncio.run(scenario())


@pytest.mark.live
def test_live_missing_model_is_reported_not_pulled(tmp_path, monkeypatch):
    base, _ = _live_settings()

    async def scenario():
        _, snapshot, work, connection = await setup(None, tmp_path, monkeypatch, base_url=base)
        connection.snapshot = _with_model(snapshot, "asclepius-not-installed:0")
        observation = await execute_target(connection, work)
        assert observation.error_code == "local_model_missing"

    asyncio.run(scenario())
