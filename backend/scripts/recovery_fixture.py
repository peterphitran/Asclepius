import ctypes
import json
import os
import select
import signal
import site
import sqlite3
import subprocess
import sys
import time
from contextlib import closing, contextmanager
from pathlib import Path

from asclepius.checks import load_pack_plan

if __package__:
    from .pipeline_fixture import KEY, Provider, cli, cli_result, configure, provider, wait_run
else:
    from pipeline_fixture import KEY, Provider, cli, cli_result, configure, provider, wait_run


def until(read, accept, *, timeout=15):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if accept(value):
            return value
        assert time.monotonic() < deadline, value
        time.sleep(0.05)


def rows(directory, query, arguments=()):
    with closing(sqlite3.connect(directory / "asclepius.sqlite3")) as db:
        return db.execute(query, arguments).fetchall()


def pending(directory, run, actor):
    return rows(
        directory,
        "SELECT id FROM operations WHERE run_id=? AND status='pending' "
        "AND json_extract(request_json,'$.actor')=?",
        (run, actor),
    )


def preserved(directory, run):
    result = {"snapshot": rows(directory, "SELECT * FROM runs WHERE id=?", (run,))}
    for table in (
        "work_items",
        "stages",
        "stage_attempts",
        "operations",
        "observations",
        "judgments",
        "findings",
        "events",
        "budget_reservations",
    ):
        result[table] = rows(
            directory, f"SELECT * FROM {table} WHERE run_id=? ORDER BY rowid", (run,)
        )
    return result


class OwnedDaemon:
    def __init__(self, directory, status):
        self.directory = directory
        self.pid = status["pid"]
        self.generation = status["instance_id"]

    def kill(self):
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x100001, False, self.pid)
            assert handle, ctypes.get_last_error()
        else:
            handle = os.pidfd_open(self.pid)
        try:
            status = cli(self.directory, "daemon", "status")
            assert status["pid"] == self.pid and status["instance_id"] == self.generation
            assert (
                status["owned"]
                and status["responsive"]
                and status["state"] in {"ready", "draining"}
            )
            if os.name == "nt":
                assert kernel.TerminateProcess(handle, 91), ctypes.get_last_error()
                assert kernel.WaitForSingleObject(handle, 10000) == 0
            else:
                signal.pidfd_send_signal(handle, signal.SIGKILL)
                assert select.select([handle], [], [], 10)[0]
        finally:
            if os.name == "nt":
                assert kernel.CloseHandle(handle)
            else:
                os.close(handle)
        until(lambda: cli(self.directory, "daemon", "status"), lambda s: not s["owned"])


class Fixture:
    def __init__(self, root, server, directory, evaluator, targets, status):
        self.root, self.server, self.directory = root, server, directory
        self.evaluator, self.targets = evaluator, targets
        self.owner = OwnedDaemon(directory, status)
        plan = load_pack_plan("broad-chat-v1")
        self.plan = root / "plan.json"
        self.plan.write_text(
            plan.model_copy(update={"checks": plan.checks[:1]}).model_dump_json(), encoding="utf-8"
        )

    def submit(self):
        return cli(
            self.directory, "run", "fixture", "--plan", self.plan, "--evaluator", self.evaluator
        )["id"]

    def show(self, run):
        return cli(self.directory, "runs", "show", run)

    def restart(self):
        status = cli(self.directory, "daemon", "start", "--config", self.root / "daemon.toml")
        assert status["instance_id"] != self.owner.generation
        self.owner = OwnedDaemon(self.directory, status)
        return status


@contextmanager
def owned_fixture(root, certificates, **limits):
    with provider(root / "store", certificates) as server:
        directory, evaluator, targets, status = configure(
            root, server, certificates, limits=dict(active_runs=1, **limits)
        )
        fixture = Fixture(root, server, directory, evaluator, targets, status)
        try:
            yield fixture
        finally:
            server.release.set()
            for gate in server.gates:
                gate.release.set()
            status = cli(directory, "daemon", "status")
            if status["owned"]:
                assert status["instance_id"] == fixture.owner.generation
                for (run,) in rows(
                    directory, "SELECT id FROM runs WHERE state IN ('queued','running')"
                ):
                    cancelled = cli_result(directory, "runs", "cancel", run)
                    if cancelled.returncode != 0:
                        assert cancelled.payload["error"]["code"] == "invalid_transition"
                        assert fixture.show(run)["state"] in {
                            "completed",
                            "cancelled",
                            "failed",
                            "interrupted",
                        }
                assert cli(directory, "daemon", "stop")["owned"] is False
        assert server.failures == [], server.failures


CONSOLE_CONTROLLER = """
import ctypes
import os
import sys
pid = int(sys.argv[1])
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.FreeConsole()
assert kernel.AttachConsole(pid), ctypes.get_last_error()
members = (ctypes.c_ulong * 16)()
count = kernel.GetConsoleProcessList(members, 16)
assert set(members[:count]) == {pid, os.getpid()}, list(members[:count])
assert kernel.SetConsoleCtrlHandler(None, True)
assert kernel.GenerateConsoleCtrlEvent(0, 0), ctypes.get_last_error()
"""


def interrupt_watch(directory, run, root):
    output = root / "watch.log"
    command = [
        sys.executable,
        "-u",
        "-m",
        "asclepius",
        "--data-dir",
        str(directory),
        "--json",
        "runs",
        "watch",
        run,
    ]
    options = {}
    if os.name == "nt":
        import asclepius

        expected_module = str(Path(asclepius.__file__).resolve())
        code = (
            "import site,runpy; "
            + "; ".join(f"site.addsitedir({p!r})" for p in site.getsitepackages())
            + "; import asclepius; from pathlib import Path; "
            + f"assert str(Path(asclepius.__file__).resolve()) == {expected_module!r}; "
            + "print('WATCH_IMPORT ' + asclepius.__file__,flush=True); "
            + "runpy.run_module('asclepius',run_name='__main__')"
        )
        command = [sys._base_executable, "-S", "-u", "-c", code, *command[4:]]
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        options = {"creationflags": subprocess.CREATE_NEW_CONSOLE, "startupinfo": startup}
    with output.open("w") as log:
        child = subprocess.Popen(
            command, stdout=log, stderr=log, env=dict(os.environ, PIPELINE_KEY=KEY), **options
        )
        try:
            until(
                lambda: output.read_text(),
                lambda text: any(line.startswith("{") for line in text.splitlines()),
            )
            if os.name == "nt":
                controller = subprocess.run(
                    [
                        sys._base_executable,
                        "-S",
                        "-c",
                        CONSOLE_CONTROLLER,
                        str(child.pid),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                assert controller.returncode == 0, controller.stdout + controller.stderr
            else:
                child.send_signal(signal.SIGINT)
            assert child.wait(10) == 130, (child.returncode, output.read_text())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(10)
    assert KEY not in output.read_text()
    return {
        "exit_code": child.returncode,
        "events": len(output.read_text().splitlines()),
        "signal": "CTRL_C_EVENT" if os.name == "nt" else "SIGINT",
        "module": expected_module if os.name == "nt" else None,
    }


def watch_scenario(root, certificates):
    with owned_fixture(root, certificates) as fixture:
        with fixture.server.gate("selector") as gate:
            run = fixture.submit()
            assert gate.received.wait(15)
            result = interrupt_watch(fixture.directory, run, root)
            active = fixture.show(run)
            assert active["state"] == "running" and not active["cancel_requested"]
        assert wait_run(fixture.directory, run)["state"] == "completed"
        result["run_id"] = run
        result["completed_without_cancel"] = True
        return result


def cancel_scenario(root, certificates, actor):
    with owned_fixture(root, certificates) as fixture:
        with fixture.server.gate(actor) as gate:
            run = fixture.submit()
            assert gate.received.wait(15)
            issued = tuple(item["operation_id"] for item in fixture.server.calls)
            cli(fixture.directory, "runs", "cancel", run)
            assert fixture.show(run)["cancel_requested"]
        view = wait_run(fixture.directory, run)
        assert view["state"] == "cancelled"
        assert tuple(item["operation_id"] for item in fixture.server.calls) == issued
        assert {item["operation_id"] for item in view["observations"]} == set(issued)
        observations = {item["operation_id"]: item for item in view["observations"]}
        for call in fixture.server.calls:
            observation = observations[call["operation_id"]]
            assert observation["status"] == "success", "Issued reply was not successful"
            assert observation["error_code"] is None, "Issued reply retained an error"
            reply = observation["payload"]
            assert reply is not None, "Issued reply was lost"
            assert reply["response_id"] == "fixture-" + call["operation_id"], (
                "Issued reply response ID changed"
            )
            content, finish = Provider.proposal(call["actor"], call["body"], call["variant"])
            assert reply["content"] == content, "Issued reply content changed"
            assert reply["finish_reason"] == finish, "Issued reply finish reason changed"
        assert {
            row[0]
            for row in rows(fixture.directory, "SELECT id FROM operations WHERE run_id=?", (run,))
        } == set(issued)
        assert all(item["state"] != "pending" for item in view["attempts"])
        assert rows(fixture.directory, "SELECT id FROM operations WHERE status='pending'") == []
        return {
            "run_id": run,
            "actor": actor,
            "issued": len(issued),
            "retained_observations": len(view["observations"]),
        }


def queued_cancel_scenario(root, certificates):
    with owned_fixture(root, certificates) as fixture:
        with fixture.server.gate("selector") as gate:
            active = fixture.submit()
            assert gate.received.wait(15)
            queued = fixture.submit()
            assert fixture.show(queued)["state"] == "queued"
            cli(fixture.directory, "runs", "cancel", queued)
            view = fixture.show(queued)
            assert view["state"] == "cancelled"
            assert view["observations"] == [] and view["attempts"] == []
            assert (
                rows(fixture.directory, "SELECT id FROM operations WHERE run_id=?", (queued,)) == []
            )
            assert not any(item["run_id"] == queued for item in fixture.server.calls)
        assert wait_run(fixture.directory, active)["state"] == "completed"
        return {"run_id": queued, "operations": 0, "receipts": 0}


def rate_cancel_scenario(root, certificates):
    with owned_fixture(root, certificates, requests_per_minute=1) as fixture:
        run = fixture.submit()
        until(lambda: pending(fixture.directory, run, "generator"), bool)
        assert [item["actor"] for item in fixture.server.calls] == ["selector"]
        cli(fixture.directory, "runs", "cancel", run)
        view = wait_run(fixture.directory, run)
        assert view["state"] == "cancelled"
        assert [item["actor"] for item in fixture.server.calls] == ["selector"]
        states = rows(
            fixture.directory,
            "SELECT state FROM budget_reservations WHERE run_id=? ORDER BY rowid",
            (run,),
        )
        assert states == [("settled",), ("released",)], states
        assert all(item["state"] != "pending" for item in view["attempts"])
        return {
            "run_id": run,
            "generator_receipts": 0,
            "reservation_states": [state[0] for state in states],
        }


def drain_scenario(root, certificates):
    from concurrent.futures import ThreadPoolExecutor

    with owned_fixture(root, certificates) as fixture:
        with fixture.server.gate("selector") as gate:
            active = fixture.submit()
            assert gate.received.wait(15)
            queued = fixture.submit()
            with ThreadPoolExecutor(max_workers=2) as executor:
                stopping = executor.submit(
                    cli_result, fixture.directory, "daemon", "stop", "--timeout", "0.2"
                )
                racing = executor.submit(
                    cli_result,
                    fixture.directory,
                    "run",
                    "fixture",
                    "--plan",
                    fixture.plan,
                    "--evaluator",
                    fixture.evaluator,
                )
                stopped = stopping.result()
                raced = racing.result()
            assert (
                stopped.returncode == 4 and stopped.payload["error"]["code"] == "daemon_draining"
            ), stopped
            status = cli(fixture.directory, "daemon", "status")
            assert status["owned"] and status["responsive"] and status["state"] == "draining"
            assert (
                status["pid"] == fixture.owner.pid
                and status["instance_id"] == fixture.owner.generation
            )
            if raced.returncode == 0:
                raced_id = raced.payload["data"]["id"]
                assert fixture.show(raced_id)["state"] == "queued"
            else:
                assert raced.payload["error"]["code"] == "daemon_unavailable", raced
                raced_id = None
            rejected = cli_result(
                fixture.directory,
                "run",
                "fixture",
                "--plan",
                fixture.plan,
                "--evaluator",
                fixture.evaluator,
            )
            assert rejected.returncode == 4
            assert rejected.payload["error"]["code"] == "daemon_unavailable"
            expected = {active, queued} | ({raced_id} if raced_id else set())
            assert {row[0] for row in rows(fixture.directory, "SELECT id FROM runs")} == expected
        assert wait_run(fixture.directory, active)["state"] == "completed"
        until(lambda: cli(fixture.directory, "daemon", "status"), lambda value: not value["owned"])
        assert fixture.show(queued)["state"] == "queued"
        assert not any(item["run_id"] != active for item in fixture.server.calls)
        fixture.restart()
        assert wait_run(fixture.directory, queued)["state"] == "completed"
        if raced_id:
            assert wait_run(fixture.directory, raced_id)["state"] == "completed"
        return {
            "active": active,
            "queued": queued,
            "racing_run": raced_id,
            "race_accepted": raced.returncode == 0,
            "timeout_pid": status["pid"],
            "queued_completed_after_restart": True,
        }


def crash_scenario(root, certificates, point):
    from contextlib import nullcontext

    cap = {"before_send": 1, "target_received": 10000, "after_reporter": 5}[point]
    with owned_fixture(root, certificates, requests_per_minute=cap) as fixture:
        target = fixture.targets["fixture"]
        target.write_text(
            target.read_text().replace(
                f"requests_per_minute = {cap}", "requests_per_minute = 10000"
            ),
            encoding="utf-8",
        )
        cli(fixture.directory, "targets", "edit", "fixture", "--config", target)
        with fixture.server.gate("target") if point == "target_received" else nullcontext() as gate:
            run = fixture.submit()
            if point == "target_received":
                assert gate.received.wait(15)
                waiting = pending(fixture.directory, run, "target")
                assert waiting
                assert (
                    rows(
                        fixture.directory,
                        "SELECT 1 FROM observations WHERE operation_id=?",
                        (waiting[0][0],),
                    )
                    == []
                )
            else:
                actor = "generator" if point == "before_send" else "target"
                waiting = until(
                    lambda: (
                        pending(fixture.directory, run, actor)
                        if point != "after_reporter"
                        or rows(
                            fixture.directory,
                            "SELECT count(*) FROM findings WHERE run_id=?",
                            (run,),
                        )
                        == [(1,)]
                        else []
                    ),
                    bool,
                )
                if point == "after_reporter":
                    assert rows(
                        fixture.directory, "SELECT count(*) FROM findings WHERE run_id=?", (run,)
                    ) == [(1,)]
                    assert [item["actor"] for item in fixture.server.calls] == [
                        "selector",
                        "generator",
                        "target",
                        "judge",
                        "reporter",
                    ]
                else:
                    assert [item["actor"] for item in fixture.server.calls] == ["selector"]
            known = {
                table: rows(
                    fixture.directory,
                    f"SELECT * FROM {table} WHERE run_id=? ORDER BY rowid",
                    (run,),
                )
                for table in ("observations", "judgments", "findings", "stages")
            }
            intents = rows(
                fixture.directory,
                "SELECT id,run_id,work_item_id,request_json,started_at FROM operations "
                "WHERE run_id=? AND status='pending' ORDER BY rowid",
                (run,),
            )
            assert {row[0] for row in intents} == {row[0] for row in waiting}
            queued = fixture.submit()
            assert fixture.show(queued)["state"] == "queued"
            with fixture.server.lock:
                fixture.server.permitted_disconnects.update(row[0] for row in intents)
            fixture.owner.kill()
        until(lambda: fixture.server.active, lambda count: count == 0)
        receipts = tuple(item["operation_id"] for item in fixture.server.calls)
        config = root / "daemon.toml"
        config.write_text(
            config.read_text().replace(
                f"requests_per_minute = {cap}", "requests_per_minute = 10000"
            ),
            encoding="utf-8",
        )
        fixture.restart()
        view = fixture.show(run)
        assert view["state"] == "interrupted" and view["reason"] == "owner_lost"
        unknown = rows(
            fixture.directory,
            "SELECT id FROM operations WHERE run_id=? AND status='unknown'",
            (run,),
        )
        assert set(unknown) == set(waiting), (unknown, waiting)
        recovered_intents = rows(
            fixture.directory,
            "SELECT id,run_id,work_item_id,request_json,started_at FROM operations "
            "WHERE run_id=? AND status='unknown' ORDER BY rowid",
            (run,),
        )
        assert recovered_intents == intents, "Original intent changed during recovery"
        observations = {item["operation_id"]: item for item in view["observations"]}
        for operation, _, _, raw, _ in intents:
            observation = observations[operation]
            assert observation["status"] == "unknown", "Unknown request outcome changed"
            assert observation["error_code"] == "owner_lost", "Unknown request reason changed"
            assert observation["dispatch_status"] == "unknown", "Unknown request dispatch changed"
            assert observation["payload"] is None, "Unknown request claimed a reply"
            assert observation["request_payload"] == json.loads(raw)["payload"], (
                "Unknown request payload changed"
            )
        assert all(item["state"] != "pending" for item in view["attempts"])
        for table, original in known.items():
            after = rows(
                fixture.directory, f"SELECT * FROM {table} WHERE run_id=? ORDER BY rowid", (run,)
            )
            assert all(row in after for row in original), table
        assert wait_run(fixture.directory, queued)["state"] == "completed"
        assert (
            tuple(item["operation_id"] for item in fixture.server.calls if item["run_id"] == run)
            == receipts
        )
        before_retry = preserved(fixture.directory, run)
        snapshot = view["snapshot"]
        target.write_text(
            target.read_text().replace("Frozen profile policy", "Current edited profile"),
            encoding="utf-8",
        )
        cli(fixture.directory, "targets", "edit", "fixture", "--config", target)
        fixture.plan.write_text('{"current_plan":"changed"}', encoding="utf-8")
        fixture.evaluator.write_text('current_evaluator = "changed"', encoding="utf-8")
        retry = cli(fixture.directory, "runs", "retry", run)["id"]
        assert retry != run
        retried = wait_run(fixture.directory, retry)
        assert retried["state"] == "completed", retried["reason"]
        saved = retried["snapshot"]
        assert saved["source_run_id"] == run
        for field in ("profile", "evaluator", "checks", "prompts"):
            assert saved[field] == snapshot[field], field
        assert preserved(fixture.directory, run) == before_retry
        old_variants = {variant["id"] for variant in view["variants"]}
        assert not old_variants.intersection(variant["id"] for variant in retried["variants"])
        old_operations = {
            row[0]
            for row in rows(fixture.directory, "SELECT id FROM operations WHERE run_id=?", (run,))
        }
        new_operations = {
            row[0]
            for row in rows(fixture.directory, "SELECT id FROM operations WHERE run_id=?", (retry,))
        }
        assert old_operations.isdisjoint(new_operations)
        assert fixture.show(run)["state"] == "interrupted"
        return {
            "point": point,
            "source_run_id": run,
            "retry_run_id": retry,
            "unknown_operations": [row[0] for row in unknown],
            "retained_observations": len(known["observations"]),
            "retained_findings": len(known["findings"]),
            "queued_completed_after_restart": queued,
            "source_unchanged_after_retry": True,
            "retry_variants": len(retried["variants"]),
        }
