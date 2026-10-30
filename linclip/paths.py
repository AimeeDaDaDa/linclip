"""XDG paths. Importing this module does not require Qt."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile


def private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Not a private directory: {path}")
    if hasattr(os, "getuid") and path.stat().st_uid != os.getuid():
        raise RuntimeError(f"Directory is owned by another user: {path}")
    if os.name == "posix":
        path.chmod(stat.S_IRWXU)
    return path


def data_directory() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return private_directory(base / "linclip")


def runtime_directory() -> Path:
    configured = os.environ.get("XDG_RUNTIME_DIR")
    if configured:
        return private_directory(Path(configured) / "linclip")
    uid = os.getuid() if hasattr(os, "getuid") else "local"
    return private_directory(Path(tempfile.gettempdir()) / f"linclip-{uid}")


def socket_path() -> Path:
    return runtime_directory() / "control.sock"
