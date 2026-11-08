"""Read-only discovery through serial enumeration and Linux sysfs."""

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from serial.tools import list_ports

VID, PID, SERIAL = 0x1A86, 0x5722, "USB35INCHIPSV2"


@dataclass
class Device:
    port: str
    model: str = "TURZX 3,5″ · revisão A"
    serial: str = ""
    driver: str = ""
    accessible: bool = False
    present: bool = False

    def as_dict(self):
        return asdict(self)


def discover(sysfs=Path("/sys/bus/usb/devices"), ports=None):
    found = {}
    for p in list_ports.comports() if ports is None else ports:
        if (p.vid, p.pid) == (VID, PID) and p.serial_number == SERIAL:
            found[p.device] = Device(p.device, serial=p.serial_number,
                                     accessible=os.access(p.device, os.R_OK | os.W_OK),
                                     present=Path(p.device).exists())
    # sysfs remains useful when a sandbox does not expose the device node.
    for usb in sysfs.glob("*"):
        try:
            if (usb / "idVendor").read_text().strip() != "1a86" or (usb / "idProduct").read_text().strip() != "5722":
                continue
            serial = (usb / "serial").read_text().strip()
            if serial != SERIAL:
                continue
            ttys = list(usb.glob("*/tty/tty*"))
            for tty in ttys or [None]:
                port = f"/dev/{tty.name}" if tty else ""
                driver = (tty.parent.parent / "driver").resolve().name if tty else ""
                found[port] = Device(port, serial=serial, driver=driver,
                                     accessible=bool(port) and os.access(port, os.R_OK | os.W_OK),
                                     present=bool(port) and Path(port).exists())
        except (OSError, ValueError):
            continue
    return list(found.values())


def select_device(port="auto"):
    candidates = discover()
    if port != "auto":
        candidates = [d for d in candidates if d.port and Path(d.port).resolve() == Path(port).resolve()]
    if not candidates:
        raise OSError("Tela compatível não encontrada. Conecte a TURZX 3,5″ com um cabo USB de dados.")
    if len(candidates) > 1:
        raise OSError("Há mais de uma tela. Selecione a porta desejada nas configurações.")
    device = candidates[0]
    if not device.port:
        raise OSError("USB encontrado, mas sem porta serial. Instale o suporte USB (cdc_acm).")
    if not device.present:
        raise OSError(f"Tela detectada, mas {device.port} não está disponível neste ambiente. Abra o aplicativo diretamente no Linux.")
    if not device.accessible:
        raise PermissionError(f"Sem acesso a {device.port}. Execute o instalador e reconecte o cabo USB.")
    return device
