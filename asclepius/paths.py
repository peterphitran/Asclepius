import os
import re
from pathlib import Path

from asclepius.domain import AppError


def local_directory(path: Path) -> Path:
    if str(path).startswith(("//", "\\\\")):
        raise AppError(
            "storage_location", "Use a local data directory, not a network or WSL share.", 2
        )
    try:
        resolved = path.resolve()
        remote = False
        if os.name == "nt":
            import ctypes

            remote = ctypes.windll.kernel32.GetDriveTypeW(resolved.anchor) == 4
        elif Path("/proc/self/mountinfo").exists():
            mount_type, depth = "", -1
            for line in Path("/proc/self/mountinfo").read_text().splitlines():
                location, filesystem = line.split(" - ", 1)
                mounted = re.sub(
                    r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), location.split()[4]
                )
                mount = Path(mounted)
                if resolved.is_relative_to(mount) and len(mount.parts) > depth:
                    mount_type, depth = filesystem.split()[0], len(mount.parts)
            remote = mount_type in {
                "nfs",
                "nfs4",
                "cifs",
                "smb3",
                "9p",
                "drvfs",
                "ceph",
                "glusterfs",
            } or mount_type.startswith("fuse.")
        if remote:
            raise AppError(
                "storage_location",
                "Use native local storage. Windows and WSL require separate data directories.",
                2,
            )
        return resolved
    except OSError:
        raise AppError("storage_location", "Cannot resolve the local data directory.", 2) from None
