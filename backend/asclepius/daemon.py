import argparse
import asyncio
import json
import os
import ssl
from pathlib import Path

import portalocker

from asclepius.config import DaemonConfig
from asclepius.coordinator import Coordinator
from asclepius.domain import AppError
from asclepius.limits import BudgetManager
from asclepius.maintenance import instance_lock, maintenance_lock, readiness_lock
from asclepius.storage import Repository
from asclepius.transport import JsonTransport


async def serve(data_dir: Path, *, instance_id: str, policy: DaemonConfig | None = None) -> None:
    repo = Repository(data_dir)
    policy = policy or DaemonConfig()
    tls = ssl.create_default_context()
    if policy.ca_bundle:
        tls.load_verify_locations(cafile=policy.ca_bundle)
    budgets = BudgetManager(repo, instance_id, limits=policy.limits)
    coordinator = Coordinator(repo, budgets, transport=JsonTransport(verify=tls))
    tasks: dict[str, asyncio.Task] = {}
    failure = None
    try:
        with (
            instance_lock(repo.data_dir),
            maintenance_lock(repo.data_dir, timeout=0),
            readiness_lock(repo.data_dir, instance_id),
        ):
            try:
                await repo.control()
                await repo.set_ready(instance_id, pid=os.getpid(), execution_available=True)
                await repo.interrupt_orphans(instance_id)
                last_heartbeat = 0.0
                while True:
                    control = await repo.control()
                    if str(control.instance_id) != instance_id:
                        raise AppError("ownership", "Daemon ownership changed.")
                    for identity, task in tuple(tasks.items()):
                        if task.done():
                            del tasks[identity]
                            try:
                                task.result()
                            except BaseException as error:
                                failure = error
                                await repo.request_stop(instance_id)
                    if failure is None and control.state == "ready":
                        while len(tasks) < policy.limits.active_runs:
                            try:
                                snapshot = await repo.claim_next(instance_id, limits=policy.limits)
                            except AppError as error:
                                if error.code != "daemon_unavailable":
                                    raise
                                current = await repo.control()
                                if (
                                    str(current.instance_id) == instance_id
                                    and current.state == "draining"
                                ):
                                    control = current
                                    break
                                raise
                            if snapshot is None:
                                break
                            tasks[str(snapshot.id)] = asyncio.create_task(
                                coordinator.execute(snapshot)
                            )
                    if (control.state == "draining" or failure is not None) and not tasks:
                        if failure is not None:
                            raise failure
                        if await repo.active_count(instance_id) == 0:
                            break
                    now = asyncio.get_running_loop().time()
                    if now - last_heartbeat >= 2:
                        await repo.heartbeat(instance_id)
                        last_heartbeat = now
                    await asyncio.sleep(0.25)
            finally:
                if tasks:
                    await asyncio.gather(*tasks.values(), return_exceptions=True)
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
    parser.add_argument("--policy-json", default="{}")
    args = parser.parse_args()
    try:
        asyncio.run(
            serve(
                args.data_dir,
                instance_id=args.instance_id,
                policy=DaemonConfig.model_validate_json(args.policy_json),
            )
        )
        return 0
    except AppError as error:
        print(json.dumps({"error": error.code}), flush=True)
        return error.exit_code
    except Exception:
        print(json.dumps({"error": "daemon_failed"}), flush=True)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
