"""Desktop integration; executed as the logged-in user, never root."""

import os
from pathlib import Path
import sys

from .config import atomic_write


def autostart_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart/turzx-linux.desktop"


def quote_exec(value):
    # Desktop Entry Exec has its own escaping rules, distinct from shell quoting.
    value = str(value).replace("%", "%%")
    for old, new in (("\\", "\\\\"), ('"', '\\"'), ("`", "\\`"), ("$", "\\$")):
        value = value.replace(old, new)
    return '"' + value.replace("\\", "\\\\") + '"'


def set_autostart(enabled):
    path = autostart_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    installed = Path("/usr/bin/turzx-linux")
    if installed.exists():
        command = "/usr/bin/turzx-linux --run"
    else:
        launcher = Path(__file__).resolve().parent.parent / "launch.py"
        command = f"{quote_exec(sys.executable)} {quote_exec(launcher)} --run"
    content = ("[Desktop Entry]\nType=Application\nName=Turzx Linux\n"
               "Comment=Inicia o painel USB ao entrar no Linux\n"
               f"Exec={command}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")
    atomic_write(path, content.encode())
