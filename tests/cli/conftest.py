import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from asclepius.transport import JsonTransport
from scripts.localhost_tls import ensure as ensure_localhost_tls
from tests.cli.groq_support import reply
from tests.cli.storage_fixtures import release_leases


def pytest_configure(config):
    ensure_localhost_tls(Path(__file__).parent / "fixtures")


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


@pytest.fixture
def groq(provider):
    fixtures = Path(__file__).parent / "fixtures"
    cert = fixtures / "localhost-cert.pem"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, fixtures / "localhost-key.pem")
    provider.socket = context.wrap_socket(provider.socket, server_side=True)
    provider.origin = f"https://127.0.0.1:{provider.server_port}"
    provider.body = json.dumps(reply()).encode()
    return provider, JsonTransport(verify=ssl.create_default_context(cafile=str(cert)))


@pytest.fixture(autouse=True)
def close_test_leases():
    yield
    release_leases()
