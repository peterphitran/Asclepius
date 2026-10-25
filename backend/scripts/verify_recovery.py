import argparse
import json
import sys
import tempfile
from pathlib import Path

from recovery_fixture import (
    cancel_scenario,
    crash_scenario,
    drain_scenario,
    queued_cancel_scenario,
    rate_cancel_scenario,
    watch_scenario,
)

import asclepius


def proof(root, certificates):
    return {
        "queued_cancel": queued_cancel_scenario(root / "queued", certificates),
        "active_cancel": [
            cancel_scenario(root / ("cancel-" + actor), certificates, actor)
            for actor in ("selector", "target")
        ],
        "rate_wait_cancel": rate_cancel_scenario(root / "rate", certificates),
        "drain": drain_scenario(root / "drain", certificates),
        "watch": watch_scenario(root / "watch", certificates),
        "crashes": [
            crash_scenario(root / point, certificates, point)
            for point in ("before_send", "target_received", "after_reporter")
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificates", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    module = Path(asclepius.__file__).resolve()
    assert "site-packages" in module.parts, module
    assert module.is_relative_to(Path(sys.prefix).resolve()), (module, sys.prefix)
    with tempfile.TemporaryDirectory(prefix="asclepius-recovery-") as directory:
        result = proof(Path(directory), args.certificates.resolve())
    payload = {
        "status": "PASS",
        "python": sys.version,
        "executable": sys.executable,
        "module": str(module),
        "proof": result,
        "temporary_store_cleanup": True,
    }
    encoded = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
