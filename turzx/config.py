"""Validated, atomic, per-user settings."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

THEMES = {"aurora": "Aurora", "ocean": "Oceano", "ember": "Âmbar"}
MODES = {"dashboard": "Monitor do sistema", "clock": "Relógio", "image": "Imagem personalizada", "custom": "Tema do editor visual"}
ROTATIONS = {0: "Retrato · 0°", 90: "Paisagem · 90°", 180: "Retrato · 180°", 270: "Paisagem · 270°"}


def config_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "turzx-linux"


def state_dir():
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "turzx-linux"


def runtime_dir():
    base = Path(os.environ.get("XDG_RUNTIME_DIR", state_dir()))
    result = base / "turzx-linux"
    result.mkdir(parents=True, exist_ok=True, mode=0o700)
    return result


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".turzx-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@dataclass(frozen=True)
class Config:
    port: str = "auto"
    brightness: int = 60
    rotation: int = 90
    theme: str = "aurora"
    mode: str = "dashboard"
    title: str = "MEU LINUX"
    interval: float = 2.0
    image_path: str = ""
    screen_on: bool = True
    custom_theme: str = ""
    custom_theme_data: dict | None = None

    @property
    def size(self):
        return (480, 320) if self.rotation in (90, 270) else (320, 480)

    def validate(self):
        if not isinstance(self.port, str) or (self.port != "auto" and not self.port.startswith("/dev/")):
            raise ValueError("Escolha detecção automática ou uma porta em /dev/.")
        if type(self.brightness) is not int or not 0 <= self.brightness <= 100:
            raise ValueError("O brilho deve estar entre 0 e 100%.")
        if type(self.rotation) is not int or self.rotation not in ROTATIONS:
            raise ValueError("Rotação inválida.")
        if not isinstance(self.theme, str) or self.theme not in THEMES:
            raise ValueError("Tema inválido.")
        if not isinstance(self.mode, str) or self.mode not in MODES:
            raise ValueError("Modo de exibição inválido.")
        if type(self.interval) not in (int, float) or not 1 <= self.interval <= 60:
            raise ValueError("O intervalo deve estar entre 1 e 60 segundos.")
        if not isinstance(self.title, str) or len(self.title) > 28 or any(ord(c) < 32 for c in self.title):
            raise ValueError("Use um título de até 28 caracteres, em uma linha.")
        if not isinstance(self.image_path, str):
            raise ValueError("Caminho da imagem inválido.")
        if type(self.screen_on) is not bool:
            raise ValueError("Estado da tela inválido.")
        if not isinstance(self.custom_theme, str):
            raise ValueError("Tema personalizado inválido.")
        if self.mode == "custom":
            from .themes import valid_id, from_dict
            if not valid_id(self.custom_theme):
                raise ValueError("Crie ou selecione um tema no editor visual.")
            if self.custom_theme_data is not None:
                theme = from_dict(self.custom_theme_data)
                if theme.id != self.custom_theme:
                    raise ValueError("O tema aplicado não corresponde à seleção.")
        return self


def load_config(path=None):
    path = path or config_dir() / "config.json"
    if not path.exists():
        return Config()
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("A configuração precisa ser um objeto JSON.")
        names = {f.name for f in fields(Config)}
        return Config(**{k: v for k, v in data.items() if k in names}).validate()
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Configuração inválida em {path}: {exc}") from exc


def save_config(config, path=None):
    config.validate()
    atomic_write(path or config_dir() / "config.json",
                 json.dumps(asdict(config), ensure_ascii=False, indent=2).encode())
