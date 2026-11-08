#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if ! command -v apt-get >/dev/null || ! command -v dpkg-deb >/dev/null; then
    echo 'O instalador automático atende Ubuntu/Debian. Veja o README.md para outras distribuições.' >&2
    exit 1
fi
python3 scripts/build_deb.py
version=$(python3 launch.py --version)
echo 'Instalando Turzx Linux, dependências e acesso USB para a tela 3,5″.'
echo 'A senha de administrador é usada pelo apt. O aplicativo roda como seu usuário.'
package_copy=$(mktemp /tmp/turzx-linux-XXXXXX.deb)
trap 'rm -f -- "$package_copy"' EXIT
cp -- "dist/turzx-linux_${version}_all.deb" "$package_copy"
chmod 644 "$package_copy"
if [[ $EUID -eq 0 ]]; then
    apt-get update
    apt-get install -y "$package_copy"
else
    sudo apt-get update
    sudo apt-get install -y "$package_copy"
fi
echo
echo 'Instalado. Abra “Turzx Linux” no menu de aplicativos ou execute: turzx-linux'
echo 'Se a conexão indicar falta de permissão, retire e reconecte o cabo USB da tela.'
