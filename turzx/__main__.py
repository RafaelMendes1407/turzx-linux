import argparse
import json
import sys

from . import __version__


def main():
    parser = argparse.ArgumentParser(description="Turzx Linux · configurador da tela USB Turing 3,5″")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--run", action="store_true", help="executa o painel sem interface gráfica")
    commands.add_argument("--stop", action="store_true", help="para o painel e apaga a tela")
    commands.add_argument("--diagnose", action="store_true", help="mostra identificação USB e diagnóstico")
    commands.add_argument("--preview", metavar="PNG", help="salva uma prévia com dados reais sem acessar o USB")
    commands.add_argument("--test", action="store_true", help="solicita 8 segundos de teste de cores ao painel ativo")
    commands.add_argument("--smoke-gui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--simulate", action="store_true", help="com --run, testa o serviço sem acessar o USB")
    parser.add_argument("--wait-for-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.simulate and not args.run:
        parser.error("--simulate precisa de --run")
    try:
        if args.diagnose:
            from .diagnostics import diagnose
            print(json.dumps(diagnose(), ensure_ascii=False, indent=2))
        elif args.preview:
            from .config import load_config
            from .sensors import Sampler
            from .render import render
            import time
            sampler = Sampler()
            time.sleep(.15)
            render(load_config(), sampler.sample()).save(args.preview, format="PNG")
            print(f"Prévia salva em {args.preview}")
        elif args.run:
            from .service import Worker, configure_logging
            configure_logging()
            return Worker(simulate=args.simulate, wait=args.wait_for_worker).run()
        elif args.stop or args.test:
            from .service import request
            if not request("STOP" if args.stop else "TEST"):
                print("O painel não está em execução.", file=sys.stderr)
                return 1
        else:
            from .gui import main as gui_main
            return gui_main(smoke=args.smoke_gui)
        return 0
    except ImportError as exc:
        print(f"Dependência ausente: {exc}. Execute ./instalar.sh.", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
