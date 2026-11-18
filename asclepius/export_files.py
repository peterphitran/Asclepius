import hashlib
import os
import stat
import tempfile
from pathlib import Path

import portalocker

from asclepius.domain import AppError, ExportArtifact


def _regular_single(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AppError(
            "export_unsafe", "Export destination and lock must be regular single-link files."
        )
    return info


def write_export(artifact: ExportArtifact, destination: Path, overwrite: bool = False) -> Path:
    temporary = None
    committed = False
    try:
        parent = destination.parent.resolve(strict=True)
        name = destination.name
        if (
            not name
            or name in {".", ".."}
            or "\x00" in name
            or (
                os.name == "nt"
                and (
                    name.endswith((" ", "."))
                    or ":" in name
                    or (
                        os.path.isreserved(name)
                        if hasattr(os.path, "isreserved")
                        else destination.is_reserved()
                    )
                )
            )
        ):
            raise AppError("export_unsafe", "Unsafe export filename.")
        target = parent / name
        identity = os.path.normcase(str(target))
        digest = hashlib.sha256(os.fsencode(identity)).hexdigest()
        lock_path = parent / f".asclepius-export-{digest}.lock"
        _regular_single(lock_path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        with os.fdopen(descriptor, "r+b") as lock:
            info = _regular_single(lock_path)
            opened = os.fstat(lock.fileno())
            if info is None or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                raise AppError("export_unsafe", "Export lock identity changed.")
            if os.name != "nt" and opened.st_uid != os.getuid():
                raise AppError("export_unsafe", "Export lock belongs to another user.")
            portalocker.lock(lock, portalocker.LOCK_EX)
            try:
                existing = _regular_single(target)
                if existing is not None and not overwrite:
                    raise AppError("export_exists", "Export destination already exists.", 2)
                descriptor, temporary = tempfile.mkstemp(
                    prefix=".asclepius-export-", suffix=".tmp", dir=parent
                )
                with os.fdopen(descriptor, "wb") as output:
                    output.write(artifact.content.encode("utf-8"))
                    output.flush()
                    os.fsync(output.fileno())
                _regular_single(target)
                if overwrite:
                    os.replace(temporary, target)
                    temporary = None
                else:
                    os.link(temporary, target)
                committed = True
                if temporary is not None:
                    os.unlink(temporary)
                    temporary = None
                if os.name != "nt":
                    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            finally:
                portalocker.unlock(lock)
        return target
    except FileExistsError:
        raise AppError("export_exists", "Export destination already exists.", 2) from None
    except (OSError, portalocker.LockException):
        if committed:
            raise AppError(
                "export_committed", "Export was published; durability confirmation failed."
            ) from None
        raise AppError("export_error", "Cannot publish export on this filesystem.") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                raise AppError(
                    "export_committed" if committed else "export_error",
                    "Export was published; temporary cleanup failed."
                    if committed
                    else "Export was not published; temporary cleanup failed.",
                ) from None
