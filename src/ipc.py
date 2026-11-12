"""Unix domain socket IPC integrated with GLib's event loop."""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path
from typing import Any, Callable


def start_server(socket_path: str, on_toggle: Callable[[], None]) -> socket.socket:
    """Create a private nonblocking socket and dispatch commands through GLib."""
    from gi.repository import GLib

    path = Path(socket_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError(f"Refusing to replace unsafe socket path: {path}")
        path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.setblocking(False)
    server.bind(str(path))
    os.chmod(path, 0o600)
    server.listen(8)

    def accept_ready(_fd: int, _condition: Any) -> bool:
        """Accept one local command without blocking GTK's event loop."""
        try:
            connection, _ = server.accept()
        except BlockingIOError:
            return GLib.SOURCE_CONTINUE
        try:
            connection.settimeout(0.2)
            command = connection.recv(128).decode("utf-8", "replace").strip()
            if command == "toggle":
                on_toggle()
                connection.sendall(b"ok\n")
            else:
                connection.sendall(b"error: unsupported command\n")
        except (OSError, UnicodeError):
            pass
        finally:
            connection.close()
        return GLib.SOURCE_CONTINUE

    channel = GLib.IOChannel.unix_new(server.fileno())
    channel.set_close_on_unref(False)
    channel.set_encoding(None)
    channel.set_buffered(False)
    GLib.io_add_watch(channel, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, accept_ready)
    return server


def send_command(socket_path: str | os.PathLike[str], command: str = "toggle") -> None:
    """Send a command and raise when the daemon is unavailable or rejects it."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(1.5)
        client.connect(socket_path)
        client.sendall((command + "\n").encode("utf-8"))
        response = client.recv(128).decode("utf-8", "replace").strip()
        if response != "ok":
            raise RuntimeError(response or "daemon did not acknowledge command")
