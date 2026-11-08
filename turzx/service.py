"""Single-owner USB worker, controlled through a private local command queue."""

import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from .config import atomic_write, load_config, runtime_dir, state_dir
from .protocol import Display
from .render import render, test_pattern
from .sensors import Sampler
from . import __version__


def request(message="PING"):
    if message not in ("PING", "STOP", "TEST", "RELOAD"):
        return False
    try:
        directory = runtime_dir()
        with (directory / "worker.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False  # An unlocked file means there is no worker.
            except BlockingIOError:
                if message != "PING":
                    atomic_write(directory / "commands" / (uuid.uuid4().hex + ".cmd"), message.encode("ascii"))
                return True
    except OSError:
        return False


def start():
    replacing = False
    if request():
        if status().get("version") == __version__:
            return
        request("STOP")
        replacing = True
    root = Path(__file__).resolve().parent.parent
    arguments = [sys.executable, "-m", "turzx", "--run"]
    if replacing:
        arguments.append("--wait-for-worker")
    subprocess.Popen(arguments, cwd=root,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def status():
    try:
        data = json.loads((runtime_dir() / "status.json").read_text())
        if time.time() - data["updated"] < 20 and (not data["running"] or request()):
            return data
    except (OSError, ValueError, KeyError):
        pass
    return {"connected": False, "message": "Painel parado", "running": False}


class Worker:
    def __init__(self, simulate=False, wait=False):
        self.simulate = simulate
        self.wait = wait
        self.stopping = False
        self.display = None
        self.applied = None
        self.test_until = 0
        self.message = "Iniciando…"
        self.connected = False

    def report(self, message, connected=False, running=True):
        self.message, self.connected = message, connected
        atomic_write(runtime_dir() / "status.json", json.dumps({
            "message": message, "connected": connected, "running": running,
            "updated": time.time(), "simulation": self.simulate,
            "version": __version__,
        }).encode())

    def close_display(self):
        if self.display:
            self.display.close()
        self.display, self.applied = None, None

    def run(self):
        directory = runtime_dir()
        with (directory / "worker.lock").open("a") as lock:
            deadline = time.monotonic() + 15
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if not self.wait:
                        return 0
                    if time.monotonic() >= deadline:
                        raise RuntimeError("O processo anterior não encerrou. Pare o painel e tente novamente.")
                    time.sleep(.1)
            return self._serve(directory)

    def _serve(self, directory):
        commands = directory / "commands"
        commands.mkdir(exist_ok=True, mode=0o700)
        for path in commands.glob("*.cmd"):
            path.unlink(missing_ok=True)
        try:
            def stop(*_):
                self.stopping = True
            old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
            sampler = Sampler()
            next_frame, next_status = 0, 0
            previous_error = None
            self.report("Iniciando painel…")
            try:
                while not self.stopping:
                    for path in list(commands.glob("*.cmd"))[:32]:
                        try:
                            with path.open("rb") as stream:
                                message = stream.read(32)
                            if message == b"STOP":
                                self.stopping = True
                            elif message == b"TEST":
                                self.test_until = time.monotonic() + 8
                                next_frame = 0
                            elif message == b"RELOAD":
                                next_frame = 0
                        finally:
                            path.unlink(missing_ok=True)
                    if self.stopping:
                        break
                    now = time.monotonic()
                    if now >= next_frame:
                        try:
                            config = load_config()
                            # Render before touching the device; bad images never interrupt a frame.
                            testing = now < self.test_until
                            image = test_pattern(config.size) if testing else render(config, sampler.sample())
                            if not self.simulate:
                                if self.applied and self.applied.port != config.port:
                                    self.close_display()
                                if self.display is None:
                                    self.display = Display.connect(config.port)
                                if config != self.applied:
                                    self.display.configure(config)
                                    self.applied = config
                                if config.screen_on:
                                    self.display.show(image)
                            label = "Teste de cores · 8 segundos" if testing else "Transmitindo para sua TURZX"
                            if not config.screen_on:
                                label = "Tela apagada · comunicação ativa"
                            self.report("Simulação · USB não utilizado" if self.simulate else label, not self.simulate)
                            previous_error = None
                            next_frame = time.monotonic() + config.interval
                        except Exception as exc:
                            self.close_display()
                            message = str(exc) or type(exc).__name__
                            self.report(message)
                            if message != previous_error:
                                logging.exception("Falha no painel")
                                previous_error = message
                            next_frame = time.monotonic() + 3
                    if time.monotonic() >= next_status:
                        self.report(self.message, self.connected)
                        next_status = time.monotonic() + 1
                    time.sleep(.15)
            finally:
                for sig, handler in old_handlers.items():
                    signal.signal(sig, handler)
                if self.display:
                    try:
                        self.display.off()
                    except Exception:
                        pass
                    self.close_display()
                self.report("Painel parado", running=False)
        finally:
            for path in commands.glob("*.cmd"):
                path.unlink(missing_ok=True)
        return 0


def configure_logging():
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = RotatingFileHandler(directory / "turzx.log", maxBytes=512_000, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
