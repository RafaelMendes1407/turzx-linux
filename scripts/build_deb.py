#!/usr/bin/env python3
"""Build a distributable package without root, network, pip, or third-party build tools."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import runpy

ROOT = Path(__file__).resolve().parent.parent
VERSION = runpy.run_path(str(ROOT / "turzx/__init__.py"))["__version__"]


def build():
    output = ROOT / f"dist/turzx-linux_{VERSION}_all.deb"
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="turzx-build-") as tmp:
        stage = Path(tmp)
        def copy(source, target, mode=0o644):
            destination = stage / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / source, destination)
            destination.chmod(mode)
        for file in (ROOT / "turzx").glob("*.py"):
            copy(str(file.relative_to(ROOT)), "usr/lib/turzx-linux/turzx/" + file.name)
        copy("launch.py", "usr/lib/turzx-linux/launch.py")
        for file in ("README.md", "LICENSE", "NOTICE", "CHANGELOG.md", "CONTRIBUTING.md"):
            copy(file, "usr/share/doc/turzx-linux/" + file)
        copy(".github/main-protection.json", "usr/share/doc/turzx-linux/.github/main-protection.json")
        for directory in ("docs", "examples"):
            for file in (ROOT / directory).rglob("*"):
                if file.is_file():
                    relative = str(file.relative_to(ROOT))
                    copy(relative, "usr/share/doc/turzx-linux/" + relative)
        copy("NOTICE", "usr/share/doc/turzx-linux/copyright")
        copy("packaging/control", "DEBIAN/control")
        control = stage / "DEBIAN/control"
        lines = control.read_text().splitlines()
        control.write_text("\n".join(f"Version: {VERSION}" if line.startswith("Version:") else line for line in lines) + "\n")
        copy("packaging/postinst", "DEBIAN/postinst", 0o755)
        copy("packaging/postrm", "DEBIAN/postrm", 0o755)
        copy("packaging/70-turzx-linux.rules", "usr/lib/udev/rules.d/70-turzx-linux.rules")
        copy("packaging/turzx-linux.desktop", "usr/share/applications/turzx-linux.desktop")
        copy("assets/turzx-linux.svg", "usr/share/icons/hicolor/scalable/apps/turzx-linux.svg")
        binary = stage / "usr/bin/turzx-linux"
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/lib/turzx-linux/launch.py "$@"\n')
        binary.chmod(0o755)
        # Never propagate the builder's umask or TemporaryDirectory's 0700 mode
        # into system directories in the archive.
        stage.chmod(0o755)
        for directory in stage.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o755)
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(output)], check=True)
    print(output)
    return output


if __name__ == "__main__":
    build()
