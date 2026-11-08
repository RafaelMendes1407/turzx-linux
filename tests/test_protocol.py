import os
import pty
import select
import threading
import unittest

from PIL import Image
import serial

from turzx.config import Config
from turzx.protocol import Display, command, rgb565


class RecordingTransport:
    def __init__(self, limit=None):
        self.data = bytearray()
        self.limit = limit

    def write(self, data):
        count = len(data) if self.limit is None else min(len(data), self.limit)
        self.data.extend(data[:count])
        return count

    def close(self):
        pass


class ProtocolTests(unittest.TestCase):
    def test_command_golden_landscape(self):
        self.assertEqual(command(197, 0, 0, 479, 319), bytes.fromhex("0000077d3fc5"))

    def test_command_golden_portrait(self):
        self.assertEqual(command(197, 0, 0, 319, 479), bytes.fromhex("000004fddfc5"))

    def test_reject_coordinates_outside_wire_format(self):
        for value in (-1, 1024, 1.5):
            with self.assertRaises(ValueError):
                command(197, value)

    def test_rgb565_primary_colors_and_endianness(self):
        image = Image.new("RGB", (5, 1))
        image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)])
        self.assertEqual(rgb565(image), bytes.fromhex("00f8e0071f00ffff0000"))

    def test_orientation_packets_all_four_rotations(self):
        vectors = {
            0: "00000000007964014001e00000000000",
            90: "0000000000796601e001400000000000",
            180: "00000000007965014001e00000000000",
            270: "0000000000796701e001400000000000",
        }
        for rotation, expected in vectors.items():
            with self.subTest(rotation=rotation):
                wire = RecordingTransport()
                Display(wire).configure(Config(rotation=rotation))
                self.assertEqual(wire.data[:16], bytes.fromhex(expected))

    def test_brightness_inverted_and_power(self):
        for brightness, expected in [(0, "3fc00000006e"), (100, "00000000006e")]:
            wire = RecordingTransport()
            Display(wire).configure(Config(brightness=brightness, screen_on=False))
            self.assertEqual(wire.data[16:22], bytes.fromhex(expected))
            self.assertEqual(wire.data[22:], bytes.fromhex("00000000006c"))

    def test_full_frame_is_exact_size_and_contiguous(self):
        wire = RecordingTransport()
        display = Display(wire)
        display.show(Image.new("RGB", (320, 480), "red"))
        self.assertEqual(len(wire.data), 6 + 320 * 480 * 2)
        self.assertEqual(wire.data[6:], b"\x00\xf8" * (320 * 480))

    def test_partial_writes_are_completed(self):
        wire = RecordingTransport(limit=2)
        Display(wire).write(b"1234567")
        self.assertEqual(wire.data, b"1234567")

    def test_zero_write_aborts(self):
        with self.assertRaises(serial.SerialTimeoutException):
            Display(RecordingTransport(limit=0)).write(b"1234")

    def test_wrong_size_never_writes_to_usb(self):
        wire = RecordingTransport()
        with self.assertRaises(ValueError):
            Display(wire).show(Image.new("RGB", (10, 10)))
        self.assertEqual(wire.data, b"")

    def test_actual_serial_transport_through_pty(self):
        master, slave = pty.openpty()
        received = bytearray()
        errors = []
        expected_length = 16 + 6 + 6 + 6 + 307200
        def consume():
            try:
                while len(received) < expected_length:
                    if not select.select([master], [], [], 5)[0]:
                        raise TimeoutError("O emulador não recebeu o quadro completo.")
                    received.extend(os.read(master, 8192))
            except Exception as exc:
                errors.append(exc)
        try:
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            with serial.Serial(os.ttyname(slave), 115200, timeout=1, write_timeout=2,
                               rtscts=True, exclusive=True) as transport:
                display = Display(transport)
                display.configure(Config(rotation=90, brightness=100))
                display.show(Image.new("RGB", (480, 320), "blue"))
                reader.join(timeout=6)
                self.assertFalse(reader.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(received), expected_length)
            self.assertEqual(received[28:34], bytes.fromhex("0000077d3fc5"))
            self.assertEqual(received[34:], b"\x1f\x00" * 153600)
        finally:
            os.close(master)
            os.close(slave)
