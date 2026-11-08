import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from turzx import __version__
from turzx.config import Config, runtime_dir, save_config
from turzx.service import request, status


class ServiceTests(unittest.TestCase):
    def wait_for(self, predicate, seconds=7):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(.05)
        self.fail("O serviço não alcançou o estado esperado dentro do prazo.")

    def test_daemon_control_reload_single_instance_and_stop(self):
        with tempfile.TemporaryDirectory(prefix="turzx-test-") as tmp:
            env = {"XDG_CONFIG_HOME": tmp + "/config", "XDG_STATE_HOME": tmp + "/state", "XDG_RUNTIME_DIR": tmp}
            with patch.dict(os.environ, env):
                save_config(Config(interval=1))
                process = subprocess.Popen([sys.executable, "-m", "turzx", "--run", "--simulate"],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.wait_for(request)
                    self.wait_for(lambda: status().get("simulation") is True and "Simulação" in status()["message"])
                    self.assertFalse(status()["connected"])
                    second = subprocess.run([sys.executable, "-m", "turzx", "--run", "--simulate"],
                                            capture_output=True, timeout=3)
                    self.assertEqual(second.returncode, 0)
                    self.assertTrue(request())
                    self.assertTrue(request("TEST"))
                    self.assertFalse(request("UNKNOWN"))
                    # A bad config keeps the worker alive and reports the actual error.
                    from turzx.config import config_dir
                    (config_dir() / "config.json").write_text('{"brightness":999}')
                    self.assertTrue(request("RELOAD"))
                    self.wait_for(lambda: "brilho" in status()["message"])
                    save_config(Config(interval=1, rotation=180))
                    self.assertTrue(request("RELOAD"))
                    self.wait_for(lambda: "Simulação" in status()["message"])
                    self.assertTrue(request("STOP"))
                    out, err = process.communicate(timeout=4)
                    self.assertEqual(process.returncode, 0, err.decode())
                    self.assertFalse(request())
                    self.assertFalse(status()["running"])
                    self.assertEqual(list((runtime_dir() / "commands").glob("*.cmd")), [])
                finally:
                    if process.poll() is None:
                        process.terminate()
                    process.communicate(timeout=4)

    def test_real_worker_reports_device_error_without_crashing(self):
        # This machine's USB is visible in sysfs but not mapped into /dev.
        # Use a nonexistent manual port to make this test independent of hardware.
        with tempfile.TemporaryDirectory(prefix="turzx-test-") as tmp:
            env = {"XDG_CONFIG_HOME": tmp + "/config", "XDG_STATE_HOME": tmp + "/state", "XDG_RUNTIME_DIR": tmp}
            with patch.dict(os.environ, env):
                save_config(Config(port="/dev/turzx-nonexistent"))
                process = subprocess.Popen([sys.executable, "-m", "turzx", "--run"],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.wait_for(request)
                    self.wait_for(lambda: "não encontrada" in status()["message"])
                    self.assertFalse(status()["connected"])
                    self.assertTrue(request("STOP"))
                    _, err = process.communicate(timeout=4)
                    self.assertEqual(process.returncode, 0, err.decode())
                finally:
                    if process.poll() is None:
                        process.terminate()
                    process.communicate(timeout=4)

    def test_custom_theme_snapshot_runs_in_worker(self):
        from dataclasses import asdict
        from turzx.themes import EditorModel, starter
        with tempfile.TemporaryDirectory(prefix="turzx-custom-") as tmp:
            env = {"XDG_CONFIG_HOME": tmp + "/config", "XDG_STATE_HOME": tmp + "/state", "XDG_RUNTIME_DIR": tmp}
            with patch.dict(os.environ, env):
                model = EditorModel(starter())
                model.add_text()
                model.add_chart(key="memory.usage")
                model.add_chart("chart_bars", key="network.download")
                theme = model.theme
                save_config(Config(mode="custom", custom_theme=theme.id, custom_theme_data=asdict(theme)))
                process = subprocess.Popen([sys.executable, "-m", "turzx", "--run", "--simulate"],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.wait_for(lambda: status().get("simulation") is True and "Simulação" in status()["message"])
                    self.assertIn("Simulação", status()["message"])
                    self.assertEqual(status()["version"], __version__)
                    self.assertTrue(request("STOP"))
                    _, err = process.communicate(timeout=4)
                    self.assertEqual(process.returncode, 0, err.decode())
                finally:
                    if process.poll() is None:
                        process.terminate()
                    process.communicate(timeout=4)

    def test_replacement_waits_for_previous_worker_to_release_usb_owner(self):
        with tempfile.TemporaryDirectory(prefix="turzx-replace-") as tmp:
            env = {"XDG_CONFIG_HOME": tmp + "/config", "XDG_STATE_HOME": tmp + "/state", "XDG_RUNTIME_DIR": tmp}
            with patch.dict(os.environ, env):
                save_config(Config())
                previous = subprocess.Popen([sys.executable, "-m", "turzx", "--run", "--simulate"],
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                next_process = None
                try:
                    self.wait_for(request)
                    next_process = subprocess.Popen([sys.executable, "-m", "turzx", "--run", "--simulate", "--wait-for-worker"],
                                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertTrue(request("STOP"))
                    previous.communicate(timeout=4)
                    self.wait_for(lambda: request() and status().get("running"))
                    self.assertIsNone(next_process.poll())
                    self.assertTrue(request("STOP"))
                    next_process.communicate(timeout=4)
                    self.assertEqual(next_process.returncode, 0)
                finally:
                    for process in (previous, next_process):
                        if process:
                            if process.poll() is None:
                                process.terminate()
                            process.communicate(timeout=4)
