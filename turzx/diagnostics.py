import importlib.util
from pathlib import Path
import platform

from . import __version__
from .device import discover


def diagnose():
    from dataclasses import asdict
    from .gpu import sample_gpus
    devices = discover()
    notes = []
    for d in devices:
        if not d.port:
            notes.append("Tela USB encontrada sem porta serial: carregue cdc_acm usando o instalador.")
        elif not d.present:
            notes.append(f"{d.port} existe no sistema, mas não está exposta a este ambiente de execução.")
        elif not d.accessible:
            notes.append(f"Falta permissão em {d.port}: instale as regras USB e reconecte a tela.")
    if not devices:
        notes.append("Conecte a tela a uma porta USB com um cabo de dados.")
    return {"versao": __version__, "sistema": platform.platform(),
            "driver_cdc_acm_carregado": Path("/sys/module/cdc_acm").exists(),
            "dispositivos": [d.as_dict() for d in devices],
            "placas_de_video": [asdict(gpu) for gpu in sample_gpus()],
            "dependencias": {m: importlib.util.find_spec(m) is not None for m in ("gi", "PIL", "psutil", "serial")},
            "orientacoes": notes or ["Dispositivo acessível. Use Aplicar e iniciar, depois Testar cores."]}
