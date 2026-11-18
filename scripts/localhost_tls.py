import os
import shutil
import subprocess
import tempfile
from pathlib import Path

CERT = "localhost-cert.pem"
KEY = "localhost-key.pem"


def ensure(directory):
    """Create the self-signed loopback certificate and key in directory if missing."""
    directory = Path(directory)
    if (directory / CERT).is_file() and (directory / KEY).is_file():
        return directory
    openssl = shutil.which("openssl")
    if openssl is None:
        raise RuntimeError("openssl is required to generate the loopback test certificate")
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as scratch:
        scratch = Path(scratch)
        subprocess.run(
            [
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "3650",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
                "-keyout",
                str(scratch / KEY),
                "-out",
                str(scratch / CERT),
            ],
            check=True,
            capture_output=True,
        )
        os.replace(scratch / KEY, directory / KEY)
        os.replace(scratch / CERT, directory / CERT)
    return directory
