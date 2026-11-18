import json
import sqlite3
import ssl
from contextlib import closing
from pathlib import Path

import pytest

from scripts import recovery_fixture

CERTIFICATES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("damage", ["transport_error", "response_id", "content"])
def test_cancel_proof_rejects_lost_or_replaced_issued_reply(tmp_path, monkeypatch, damage):
    original = recovery_fixture.wait_run

    def damaged_view(*args, **kwargs):
        view = original(*args, **kwargs)
        observation = view["observations"][-1]
        if damage == "transport_error":
            observation.update(status="transport_error", payload=None, error_code="timeout")
        else:
            observation["payload"][damage] = "replacement"
        return view

    monkeypatch.setattr(recovery_fixture, "wait_run", damaged_view)
    with pytest.raises(AssertionError, match="Issued reply"):
        recovery_fixture.cancel_scenario(tmp_path, CERTIFICATES, "target")


@pytest.mark.parametrize("damage", ["intent", "unknown_request"])
def test_crash_proof_rejects_rewritten_original_intent(tmp_path, monkeypatch, damage):
    original = recovery_fixture.Fixture.restart

    def restart_with_damage(fixture):
        status = original(fixture)
        with closing(sqlite3.connect(fixture.directory / "asclepius.sqlite3")) as db:
            if damage == "intent":
                db.execute(
                    "UPDATE operations SET started_at='2000-01-01T00:00:00Z' WHERE status='unknown'"
                )
            else:
                operation, raw = db.execute(
                    "SELECT operation_id,document_json FROM observations "
                    "WHERE json_extract(document_json,'$.status')='unknown'"
                ).fetchone()
                document = json.loads(raw)
                document["request_payload"]["messages"][-1]["content"] = "replacement"
                db.execute(
                    "UPDATE observations SET document_json=? WHERE operation_id=?",
                    (json.dumps(document), operation),
                )
            db.commit()
        return status

    monkeypatch.setattr(recovery_fixture.Fixture, "restart", restart_with_damage)
    with pytest.raises(AssertionError, match="Original intent|Unknown request"):
        recovery_fixture.crash_scenario(tmp_path, CERTIFICATES, "before_send")


@pytest.mark.parametrize("peer_error", [BrokenPipeError, ConnectionResetError, ssl.SSLEOFError])
def test_killed_request_disconnect_permission_does_not_cover_retry(peer_error):
    import io
    import threading
    from types import SimpleNamespace

    from scripts.pipeline_fixture import KEY, Handler

    server = SimpleNamespace(
        lock=threading.Lock(),
        active=0,
        max_active=0,
        permitted_disconnects={"killed-operation"},
        failures=[],
    )

    def request(operation, error):
        handler = object.__new__(Handler)
        handler.server = server
        body = b"{}"
        handler.headers = {"Authorization": "Bearer " + KEY, "Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.send_response = lambda _: None
        handler.send_header = lambda *_: None
        handler.end_headers = lambda: None

        def respond(body, *, on_receipt):
            on_receipt(operation)
            return 200, {"id": "fixture-" + operation}

        def write(data):
            raise error("peer closed")

        server.respond = respond
        handler.wfile = SimpleNamespace(write=write)
        handler.do_POST()

    request("killed-operation", peer_error)
    assert server.failures == []
    request("retry-operation", peer_error)
    expected = "('peer closed',)" if peer_error is ssl.SSLEOFError else "peer closed"
    assert server.failures == ["Unexpected peer disconnect for retry-operation: " + expected]
    with pytest.raises(ValueError, match="peer closed"):
        request("killed-operation", ValueError)
    assert server.active == 0
