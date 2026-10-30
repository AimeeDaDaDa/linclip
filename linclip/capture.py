"""wl-paste --watch child: read a bounded payload from stdin and forward it."""

from __future__ import annotations

import base64
import os
from pathlib import Path
import sys

from .ipc import request
from .store import MAX_ITEM_BYTES


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"text", "image"}:
        return 2
    # wl-clipboard conveys password-manager hints using this environment value.
    if os.environ.get("CLIPBOARD_STATE") in {"nil", "clear", "sensitive"}:
        return 0
    payload = sys.stdin.buffer.read(MAX_ITEM_BYTES + 1)
    if not payload or len(payload) > MAX_ITEM_BYTES:
        return 0
    if sys.argv[1] == "text":
        try:
            payload.decode("utf-8")
        except UnicodeError:
            return 0
    try:
        request(Path(sys.argv[2]), {
            "action": "capture",
            "kind": sys.argv[1],
            "payload": base64.b64encode(payload).decode("ascii"),
        })
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
