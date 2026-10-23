import asyncio
import json
import logging
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from asclepius.domain import AppError
from asclepius.transport import JsonTransport


@pytest.fixture
def provider():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            with self.server.lock:
                self.server.active += 1
                self.server.peak = max(self.server.peak, self.server.active)
            try:
                self.respond()
            finally:
                with self.server.lock:
                    self.server.active -= 1

        def respond(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            self.server.calls.append((self.path, dict(self.headers), json.loads(body)))
            self.server.received.set()
            time.sleep(self.server.delay)
            self.send_response(self.server.status, self.server.reason)
            self.send_header("Location", self.server.origin + "/redirected")
            for value in self.server.retry_after:
                self.send_header("Retry-After", value)
            if self.server.echo_secret:
                self.send_header("X-Provider-Diagnostic", self.headers["Authorization"])
            if self.server.encoding:
                self.send_header("Content-Encoding", self.server.encoding)
            self.end_headers()
            try:
                if self.server.drip_interval:
                    for byte in self.server.body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if self.server.release.wait(self.server.drip_interval):
                            break
                else:
                    self.wfile.write(self.server.body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.calls = []
    server.lock = threading.Lock()
    server.active = 0
    server.peak = 0
    server.delay = 0
    server.encoding = None
    server.retry_after = []
    server.echo_secret = False
    server.reason = None
    server.drip_interval = 0
    server.release = threading.Event()
    server.received = threading.Event()
    server.status = 200
    server.body = b'{"ok": true}'
    server.origin = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def post(provider, *, timeout=10, cap=1024, transport=None):
    return asyncio.run(
        (transport or JsonTransport()).post(
            provider.origin + "/openai/v1/chat/completions",
            {"model": "target-model", "messages": [{"role": "user", "content": "canary"}]},
            secret="synthetic-key",
            deadline_seconds=timeout,
            response_bytes=cap,
        )
    )


def test_real_post_and_no_environment_proxy(provider, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/asclepius-test-cert")
    assert post(provider) == {"ok": True}
    path, headers, body = provider.calls[0]
    assert path == "/openai/v1/chat/completions"
    assert headers["Authorization"] == "Bearer synthetic-key"
    assert headers["Accept-Encoding"] == "identity"
    assert body["messages"] == [{"role": "user", "content": "canary"}]
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "headers,expected",
    [
        (["0"], "0"),
        (["120"], "120"),
        (["Wed, 21 Oct 2015 07:28:00 GMT"], "Wed, 21 Oct 2015 07:28:00 GMT"),
        (["Sunday, 06-Nov-94 08:49:37 GMT"], "Sunday, 06-Nov-94 08:49:37 GMT"),
        (["Sun Nov  6 08:49:37 1994"], "Sun Nov  6 08:49:37 1994"),
        ([], None),
        (["-1"], None),
        (["1.5"], None),
        (["NaN"], None),
        (["1" * 129], None),
        (["Wed, 32 Oct 2015 07:28:00 GMT"], None),
        (["Wed, 21 Oct 2015 07:28:00 +0000"], None),
        (["Wed, 21 Oct 2015 07:28:00 GMT junk"], None),
        (["Wed, 21 Oct 2015 25:28:00 GMT"], None),
        (["secret diagnostic"], None),
        (["120", "240"], None),
    ],
)
def test_http_error_retains_only_valid_bounded_retry_after(provider, headers, expected):
    provider.status = 429
    provider.retry_after = headers
    with pytest.raises(AppError) as caught:
        post(provider)
    assert caught.value.code == "provider_http_429"
    assert caught.value.status_code == 429
    assert getattr(caught.value, "retry_after", None) == expected
    assert len(provider.calls) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 429, 500, 503])
def test_errors_never_retry_follow_or_expose_body(provider, status, caplog):
    caplog.set_level("DEBUG")
    provider.status = status
    provider.body = b"synthetic-key private-provider-error"
    with pytest.raises(AppError) as caught:
        post(provider)
    assert caught.value.code == f"provider_http_{status}"
    assert len(provider.calls) == 1
    assert "synthetic-key" not in str(caught.value)
    assert "synthetic-key" not in caplog.text
    assert "private-provider-error" not in caplog.text


@pytest.mark.parametrize("body", [b"not json", b"[]", b"null", b'"text"', b"\xff"])
def test_invalid_response(provider, body):
    provider.body = body
    with pytest.raises(AppError, match="Invalid provider response") as caught:
        post(provider)
    assert caught.value.code == "provider_response"
    assert len(provider.calls) == 1


def test_body_cap(provider):
    provider.body = b"x" * 10000
    with pytest.raises(AppError) as caught:
        post(provider, cap=10)
    assert caught.value.code == "response_too_large"
    assert len(provider.calls) == 1


def test_total_deadline(provider):
    provider.delay = 0.2
    with pytest.raises(AppError) as caught:
        post(provider, timeout=0.05)
    assert caught.value.code == "provider_timeout"
    assert len(provider.calls) <= 1


@pytest.mark.parametrize("secret", ["", "bad\nheader", "bad\rheader", "non-ascii-\u2603"])
def test_invalid_secrets_never_dispatch(provider, secret):
    with pytest.raises(AppError) as caught:
        asyncio.run(
            JsonTransport().post(
                provider.origin, {}, secret=secret, deadline_seconds=1, response_bytes=100
            )
        )
    assert caught.value.code == "secret_invalid"
    assert provider.calls == []


def test_compressed_responses_cannot_bypass_memory_bound(provider):
    provider.encoding = "gzip"
    with pytest.raises(AppError) as caught:
        post(provider)
    assert caught.value.code == "provider_encoding"
    assert len(provider.calls) == 1


def test_tls_verification_cannot_be_disabled():
    with pytest.raises(AppError) as caught:
        JsonTransport(verify=False)
    assert caught.value.code == "transport_config"


@pytest.mark.parametrize("disable_certificates", [True, False])
def test_insecure_tls_contexts_are_rejected(disable_certificates):
    context = ssl.create_default_context()
    context.check_hostname = False
    if disable_certificates:
        context.verify_mode = ssl.CERT_NONE
    with pytest.raises(AppError) as caught:
        JsonTransport(verify=context)
    assert caught.value.code == "transport_config"


def test_https_verifies_certificate_and_ignores_environment_trust(provider, monkeypatch):
    fixtures = Path(__file__).parent / "fixtures"
    cert = fixtures / "localhost-cert.pem"
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, fixtures / "localhost-key.pem")
    provider.socket = server_context.wrap_socket(provider.socket, server_side=True)
    provider.origin = f"https://127.0.0.1:{provider.server_port}"
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    with pytest.raises(AppError) as caught:
        post(provider)
    assert caught.value.code == "provider_connection"
    assert provider.calls == []
    context = ssl.create_default_context(cafile=str(cert))
    assert post(provider, transport=JsonTransport(verify=context)) == {"ok": True}
    assert len(provider.calls) == 1


def test_provider_reflected_secrets_never_reach_debug_logs(provider, caplog):
    caplog.set_level("DEBUG")
    provider.echo_secret = True
    provider.reason = "synthetic-key"
    assert post(provider) == {"ok": True}
    assert "synthetic-key" not in caplog.text
    logging.getLogger("httpx").warning("unrelated caller diagnostic")
    assert "unrelated caller diagnostic" in caplog.text


def test_invalid_wire_url_is_sanitized():
    with pytest.raises(AppError) as caught:
        asyncio.run(
            JsonTransport().post(
                "https://[v1.foo]/",
                {},
                secret="synthetic-key",
                deadline_seconds=1,
                response_bytes=100,
            )
        )
    assert caught.value.code == "transport_config"


def test_suppression_does_not_hide_concurrent_caller_logs(provider, caplog):
    caplog.set_level("DEBUG")
    provider.delay = 0.2
    provider.echo_secret = True

    async def scenario():
        pending = asyncio.create_task(
            JsonTransport().post(
                provider.origin, {}, secret="synthetic-key", deadline_seconds=10, response_bytes=100
            )
        )
        assert await asyncio.to_thread(provider.received.wait, 12)
        logging.getLogger("httpcore.http11").warning("concurrent caller diagnostic")
        assert await pending == {"ok": True}

    asyncio.run(scenario())
    assert "concurrent caller diagnostic" in caplog.text
    assert "synthetic-key" not in caplog.text


@pytest.mark.parametrize("status", [200, 500])
def test_suppression_restores_same_task_logging(provider, caplog, status):
    provider.status = status
    caplog.set_level("DEBUG")

    async def scenario():
        try:
            await JsonTransport().post(
                provider.origin, {}, secret="synthetic-key", deadline_seconds=10, response_bytes=100
            )
        except AppError:
            if status == 200:
                raise
        logging.getLogger("httpx").warning("same task diagnostic")

    asyncio.run(scenario())
    assert "same task diagnostic" in caplog.text


def test_total_deadline_stops_continuously_arriving_body(provider):
    provider.body = b'{"ok": true, "padding": "........................................"}'
    provider.drip_interval = 0.075
    context = ssl.create_default_context()
    with pytest.raises(AppError) as caught:
        post(provider, timeout=2, transport=JsonTransport(verify=context))
    assert caught.value.code == "provider_timeout"
    assert len(provider.calls) == 1
