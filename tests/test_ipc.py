import os
from pathlib import Path
import socket
import struct
import tempfile
import unittest

from linclip.ipc import AlreadyRunning, MAX_MESSAGE, Server, receive, request, send


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.left, self.right = socket.socketpair()
        self.left.settimeout(1)
        self.right.settimeout(1)
        self.addCleanup(self.left.close)
        self.addCleanup(self.right.close)

    def test_unicode_roundtrip(self):
        message = {"action": "capture", "text": "中文 😀"}
        send(self.left, message)
        self.assertEqual(receive(self.right), message)

    def test_oversized_header_rejected_before_allocation(self):
        self.left.sendall(struct.pack("!I", MAX_MESSAGE + 1))
        with self.assertRaises(ValueError):
            receive(self.right)

    def test_truncated_frame(self):
        self.left.sendall(struct.pack("!I", 50) + b"{}")
        self.left.shutdown(socket.SHUT_WR)
        with self.assertRaises(ValueError):
            receive(self.right)

    def test_non_object_json(self):
        self.left.sendall(struct.pack("!I", 2) + b"[]")
        with self.assertRaises(ValueError):
            receive(self.right)


@unittest.skipUnless(os.name == "posix", "Unix socket/flock integration requires Linux")
class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "control.sock"
        self.messages = []
        self.server = Server(self.path, self.messages.append)
        self.addCleanup(self.server.close)

    def test_command_and_single_instance(self):
        self.assertTrue(request(self.path, {"action": "show"})["ok"])
        self.assertEqual(self.messages, [{"action": "show"}])
        with self.assertRaises(AlreadyRunning):
            Server(self.path, self.messages.append)
        self.assertTrue(request(self.path, {"action": "ping"})["ok"])
        self.assertEqual(len(self.messages), 1)

    def test_invalid_command_then_valid_command(self):
        self.assertFalse(request(self.path, {"action": "invalid"})["ok"])
        self.assertFalse(request(self.path, {"action": []})["ok"])
        self.assertTrue(request(self.path, {"action": "toggle"})["ok"])

    def test_socket_permission_and_cleanup(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.server.close()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
