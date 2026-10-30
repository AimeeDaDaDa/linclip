"""Private, bounded local IPC. Clipboard payloads never enter command arguments."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import struct
import threading
from typing import Callable

MAX_MESSAGE = 12 * 1024 * 1024


class AlreadyRunning(RuntimeError):
    pass


def _read_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(min(size - len(chunks), 65536))
        if not chunk:
            raise ValueError("Incomplete IPC message")
        chunks.extend(chunk)
    return bytes(chunks)


def receive(connection: socket.socket) -> dict:
    size = struct.unpack("!I", _read_exact(connection, 4))[0]
    if size < 2 or size > MAX_MESSAGE:
        raise ValueError("IPC message exceeds limit")
    message = json.loads(_read_exact(connection, size).decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("IPC message must be an object")
    return message


def send(connection: socket.socket, message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=True).encode("utf-8")
    if len(payload) > MAX_MESSAGE:
        raise ValueError("IPC message exceeds limit")
    connection.sendall(struct.pack("!I", len(payload)) + payload)


def request(path: Path, message: dict, *, timeout: float = 3) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        send(connection, message)
        return receive(connection)


class Server:
    """Keep a flock for the lifetime of the socket, including socket cleanup."""

    def __init__(self, path: Path, callback: Callable[[dict], None]) -> None:
        import fcntl

        self.path = path
        self.callback = callback
        self.closed = threading.Event()
        self.lock = (path.parent / "instance.lock").open("a+b")
        self.socket = None
        try:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AlreadyRunning("LinClip is already running") from exc
            path.unlink(missing_ok=True)
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.bind(str(path))
            os.chmod(path, 0o600)
            self.socket.listen(8)
            self.socket.settimeout(0.25)
        except Exception:
            if self.socket:
                self.socket.close()
            self.lock.close()
            raise
        self.thread = threading.Thread(target=self._serve, name="linclip-ipc", daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while not self.closed.is_set():
            try:
                connection, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(3)
                try:
                    message = receive(connection)
                    action = message.get("action")
                    if not isinstance(action, str) or action not in {"toggle", "show", "hide", "capture", "quit", "ping"}:
                        raise ValueError("Unknown action")
                    if message["action"] != "ping":
                        self.callback(message)
                    send(connection, {"ok": True})
                except (ValueError, OSError, UnicodeError, RecursionError):
                    try:
                        send(connection, {"ok": False})
                    except OSError:
                        pass

    def close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        self.socket.close()
        self.thread.join(timeout=4)
        self.path.unlink(missing_ok=True)
        self.lock.close()
