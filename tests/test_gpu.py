from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from turzx.gpu import drm_gpus, number, parse_nvidia_csv, sample_gpus


class GPUTests(unittest.TestCase):
    def test_amd_sysfs_unit_conversion_missing_fields_and_zero_fan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            device = root / "card0/device"
            hw = device / "hwmon/hwmon0"
            hw.mkdir(parents=True)
            values = {"vendor": "0x1002", "device": "0x9999", "product_name": "Test GPU",
                      "gpu_busy_percent": "42", "mem_info_vram_used": str(2**30), "mem_info_vram_total": str(8 * 2**30)}
            for name, value in values.items():
                (device / name).write_text(value)
            for name, value in {"temp1_input": "56000", "power1_average": "72500000", "freq1_input": "2100000000", "fan1_input": "0"}.items():
                (hw / name).write_text(value)
            # Connector directories must not become extra GPUs.
            (root / "card0-HDMI-A-1").mkdir()
            gpus = drm_gpus(root)
            self.assertEqual(len(gpus), 1)
            gpu = gpus[0]
            self.assertEqual((gpu.usage, gpu.temperature, gpu.memory_used, gpu.memory_total), (42, 56, 1, 8))
            self.assertEqual((gpu.power, gpu.clock, gpu.fan_rpm, gpu.memory_percent), (72.5, 2100, 0, 12.5))
            self.assertIsNone(gpu.fan_percent)
            (hw / "temp1_input").unlink()
            self.assertIsNone(drm_gpus(root)[0].temperature)

    def test_nvidia_multiple_cards_na_and_units(self):
        rows = 'GPU-abc, NVIDIA RTX A, 00000000:01:00.0, 75, 68, 2048, 8192, 110.5, 1800, 40, 0\nGPU-def, NVIDIA RTX B, 00000000:02:00.0, 0, N/A, 0, 16384, [Not Supported], 500, N/A, 1\n'
        data = parse_nvidia_csv(rows)
        self.assertEqual(len(data), 2)
        bus, gpu = data[0]
        self.assertEqual(bus, "0000:01:00.0")
        self.assertEqual(gpu.id, "GPU-abc")
        self.assertEqual((gpu.memory_used, gpu.memory_total, gpu.fan_percent), (2, 8, 40))
        self.assertIsNone(data[1][1].temperature)
        self.assertIsNone(data[1][1].power)
        self.assertEqual(data[1][1].usage, 0)

    def test_nonfinite_and_invalid_values_are_unavailable(self):
        for value in ("N/A", "nan", "inf", -1, None, ""):
            self.assertIsNone(number(value))
        self.assertEqual(number("0"), 0)

    def test_nvidia_timeout_does_not_break_other_sensors(self):
        with patch("turzx.gpu.drm_gpus", return_value=[]), patch("turzx.gpu.shutil.which", return_value="nvidia-smi"), patch("turzx.gpu.subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 1.5)):
            self.assertEqual(sample_gpus(), [])

    def test_nvidia_driver_missing_is_supported(self):
        with patch("turzx.gpu.drm_gpus", return_value=[]), patch("turzx.gpu.shutil.which", return_value=None):
            self.assertEqual(sample_gpus(), [])
