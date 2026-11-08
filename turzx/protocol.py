# SPDX-License-Identifier: GPL-3.0-or-later
# Protocol adapted from turing-smart-screen-python, lcd_comm_rev_a.py.
# Copyright (C) 2021 Matthieu Houdebine (mathoudebine)
# https://github.com/mathoudebine/turing-smart-screen-python
# Local transport, validation and conversion implementation: Turzx Linux, 2026.
"""Turing revision A wire protocol, 320×480, RGB565 little endian."""

import time

import serial

from .device import select_device


def command(code, x=0, y=0, ex=0, ey=0):
    if any(type(n) is not int or not 0 <= n <= 1023 for n in (x, y, ex, ey)):
        raise ValueError("Coordenada fora dos 10 bits do protocolo.")
    return bytes((x >> 2, ((x & 3) << 6) | (y >> 4), ((y & 15) << 4) | (ex >> 6),
                  ((ex & 63) << 2) | (ey >> 8), ey & 255, code))


def rgb565(image):
    rgb = image.convert("RGB").tobytes()
    data = bytearray(len(rgb) // 3 * 2)
    for i, j in zip(range(0, len(rgb), 3), range(0, len(data), 2)):
        r, g, b = rgb[i:i + 3]
        data[j] = ((g & 0x1C) << 3) | (b >> 3)
        data[j + 1] = (r & 0xF8) | (g >> 5)
    return bytes(data)


class Display:
    def __init__(self, transport):
        self.transport = transport
        self.size = (320, 480)

    @classmethod
    def connect(cls, port="auto"):
        device = select_device(port)
        transport = serial.Serial(device.port, baudrate=115200, timeout=1,
                                  write_timeout=2, rtscts=True, exclusive=True)
        return cls(transport)

    def write(self, data):
        # A short write must never silently truncate a command or framebuffer.
        deadline = time.monotonic() + 5
        view = memoryview(data)
        while view:
            count = self.transport.write(view)
            if not count or time.monotonic() > deadline:
                raise serial.SerialTimeoutException("Tempo limite ao enviar dados para a tela.")
            view = view[count:]

    def configure(self, config):
        config.validate()
        self.size = config.size
        w, h = self.size
        orientation = {0: 0, 90: 2, 180: 1, 270: 3}[config.rotation]
        self.write(command(121) + bytes((100 + orientation, w >> 8, w & 255, h >> 8, h & 255)) + bytes(5))
        # Controller brightness is inverted: 0 is maximum, 255 is off.
        self.write(command(110, int(255 - config.brightness * 255 / 100)))
        self.write(command(109 if config.screen_on else 108))

    def show(self, image):
        if image.size != self.size:
            raise ValueError(f"Imagem deve ter {self.size[0]}×{self.size[1]} pixels.")
        data = rgb565(image)
        w, h = self.size
        self.write(command(197, 0, 0, w - 1, h - 1))
        deadline = time.monotonic() + 10
        for start in range(0, len(data), w * 8):
            self.write(data[start:start + w * 8])
            if time.monotonic() > deadline:
                raise serial.SerialTimeoutException("A tela demorou demais para receber o quadro. Reconecte o USB.")

    def off(self):
        self.write(command(108))

    def close(self):
        self.transport.close()
