from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from turzx.config import Config, THEMES, load_config, save_config
from turzx.desktop import autostart_path, quote_exec, set_autostart
from turzx.device import discover, select_device
from turzx.render import render, test_pattern
from turzx.sensors import Metrics

METRICS = Metrics(42, 60, 18.5, 32, 80, 64, 10240, 1536, 12500, datetime(2026, 11, 8, 15, 30))


class ConfigTests(unittest.TestCase):
    def test_atomic_roundtrip_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings/config.json"
            config = Config(title="Meu Linux • ação", brightness=0, rotation=270)
            save_config(config, path)
            self.assertEqual(load_config(path), config)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(path.parent.glob(".turzx-*")), [])

    def test_invalid_values_never_saved(self):
        cases = ({"brightness": 101}, {"brightness": True}, {"rotation": 45},
                 {"interval": float("nan")}, {"interval": 0}, {"interval": "a"},
                 {"screen_on": "false"}, {"port": "/etc/passwd"}, {"title": "bad\nname"},
                 {"theme": {}}, {"title": "a" * 29}, {"mode": "video"})
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(Config(), **changes).validate()

    def test_malformed_json_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{broken")
            with self.assertRaises(ValueError):
                load_config(path)
            self.assertEqual(path.read_text(), "{broken")

    def test_missing_config_returns_defaults(self):
        self.assertEqual(load_config(Path("/nonexistent/turzx-config.json")), Config())

    def test_autostart_enable_disable(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            set_autostart(True)
            content = autostart_path().read_text()
            self.assertIn("--run", content)
            self.assertIn("Terminal=false", content)
            set_autostart(False)
            self.assertFalse(autostart_path().exists())

    def test_desktop_quotes_spaces_percent_and_shell_metacharacters(self):
        self.assertEqual(quote_exec("/tmp/a b%f"), '"/tmp/a b%%f"')
        self.assertEqual(quote_exec("$x"), '"\\\\$x"')


class DeviceTests(unittest.TestCase):
    def port(self, serial="USB35INCHIPSV2", vid=0x1a86, pid=0x5722):
        return SimpleNamespace(device="/dev/ttyACM0", vid=vid, pid=pid, serial_number=serial)

    def test_only_confirmed_revision_is_eligible(self):
        ports = [self.port(), self.port(serial="other"), self.port(vid=0x1234)]
        devices = discover(sysfs=Path("/nonexistent/sysfs"), ports=ports)
        self.assertEqual(len(devices), 1)

    def test_unknown_manual_port_is_not_opened(self):
        with patch("turzx.device.discover", return_value=[]):
            with self.assertRaisesRegex(OSError, "não encontrada"):
                select_device("/dev/ttyS0")

    def test_missing_device_node_is_explained(self):
        devices = discover(sysfs=Path("/nonexistent/sysfs"), ports=[self.port()])
        devices[0].present = False
        with patch("turzx.device.discover", return_value=devices):
            with self.assertRaisesRegex(OSError, "não está disponível"):
                select_device()

    def test_multiple_devices_require_selection(self):
        devices = discover(sysfs=Path("/nonexistent/sysfs"), ports=[self.port()])
        with patch("turzx.device.discover", return_value=devices * 2):
            with self.assertRaisesRegex(OSError, "mais de uma"):
                select_device()

    def test_sysfs_identification_without_device_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            usb = Path(tmp) / "1-1"
            tty = usb / "1-1:1.0/tty/ttyACM99"
            tty.mkdir(parents=True)
            for name, value in (("idVendor", "1a86"), ("idProduct", "5722"), ("serial", "USB35INCHIPSV2")):
                (usb / name).write_text(value)
            devices = discover(sysfs=Path(tmp), ports=[])
            self.assertEqual(devices[0].port, "/dev/ttyACM99")
            self.assertFalse(devices[0].present)


class RenderingTests(unittest.TestCase):
    def test_every_theme_orientation_and_mode(self):
        for theme in THEMES:
            for rotation in (0, 90, 180, 270):
                for mode in ("dashboard", "clock"):
                    config = Config(theme=theme, rotation=rotation, mode=mode)
                    image = render(config, METRICS)
                    self.assertEqual(image.size, config.size)
                    self.assertEqual(image.mode, "RGB")
                    self.assertGreater(len(image.getcolors(1_000_000)), 50)

    def test_unavailable_sensor_and_long_title(self):
        image = render(Config(title="M" * 28, rotation=0), replace(METRICS, temperature=None))
        self.assertEqual(image.size, (320, 480))

    def test_image_fit_and_color(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            Image.new("RGB", (100, 100), (200, 10, 20)).save(path)
            image = render(Config(mode="image", image_path=str(path)), METRICS)
            self.assertEqual(image.size, (480, 320))
            self.assertEqual(image.getpixel((10, 10)), (200, 10, 20))

    def test_missing_image_is_actionable(self):
        with self.assertRaisesRegex(ValueError, "Escolha uma imagem"):
            render(Config(mode="image"), METRICS)

    def test_pattern_contains_rgb_primaries(self):
        image = test_pattern((480, 320))
        self.assertEqual(image.getpixel((400, 0)), (255, 0, 0))
        self.assertEqual(image.getpixel((479, 0)), (0, 0, 255))
