import argparse
import asyncio
import json
import os
from pathlib import Path

import portalocker

from asclepius.domain import AppError
from asclepius.maintenance import instance_lock, maintenance_lock, readiness_lock
from asclepius.storage import Repository


async def serve(data_dir: Path, *, instance_id: str) -> None:
    repo = Repository(data_dir)
    try:
        with (
            instance_lock(repo.data_dir),
            maintenance_lock(repo.data_dir, timeout=0),
            readiness_lock(repo.data_dir, instance_id),
        ):
            try:
                await repo.control()
                await repo.set_ready(instance_id, pid=os.getpid())
                last_heartbeat = 0.0
                while True:
                    control = await repo.control()
                    if str(control.instance_id) != instance_id:
                        raise AppError("ownership", "Daemon ownership changed.")
                    if control.state == "draining" and await repo.active_count(instance_id) == 0:
                        break
                    now = asyncio.get_running_loop().time()
                    if now - last_heartbeat >= 2:
                        await repo.heartbeat(instance_id)
                        last_heartbeat = now
                    await asyncio.sleep(0.25)
            finally:
                await repo.drain_operations()
                await repo.set_stopped(instance_id)
                await repo.drain_operations()
    except portalocker.LockException:
        raise AppError(
            "daemon_owned", "Another instance or migration owns this data directory.", 4
        ) from None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--instance-id", required=True)
    args = parser.parse_args()
    try:
        asyncio.run(serve(args.data_dir, instance_id=args.instance_id))
        return 0
    except AppError as error:
        print(json.dumps({"error": error.code}), flush=True)
        return error.exit_code
    except Exception:
        print(json.dumps({"error": "daemon_failed"}), flush=True)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
