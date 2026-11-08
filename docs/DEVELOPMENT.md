# Desenvolvimento e manutenção

## Ambiente

Python ≥3.10, GTK ≥4.6 e pacotes da distribuição:

```bash
sudo apt install python3 python3-gi gir1.2-gtk-4.0 python3-pil python3-serial python3-psutil fonts-dejavu-core
./abrir.sh
```

O CI usa Ubuntu 24.04. Não há etapa de compilação do aplicativo.

## Arquitetura

| Módulo | Responsabilidade |
| --- | --- |
| `editor.py`, `gui.py` | Studio GTK, biblioteca, propriedades e configuração USB |
| `themes.py` | Documento, migração e edição sem depender do GTK |
| `palette.py`, `metrics.py` | Categorias, busca e catálogo |
| `sensors.py`, `gpu.py` | Amostragem em segundo plano e identidade das GPUs |
| `history.py`, `charts.py` | Histórico limitado e gráficos |
| `theme_render.py`, `render.py` | Renderização compartilhada entre prévia e USB |
| `protocol.py`, `device.py` | Revisão A, RGB565 e descoberta |
| `service.py` | Transmissor, comandos locais, exclusividade e reconexão |
| `config.py`, `desktop.py` | Gravação atômica, XDG e início no login |

Formato 2: `containers` e `items` na raiz; `z` ordena elementos da raiz e a
ordem da lista define a ordem dos filhos. O formato 1 migra ao carregar.
Campos desconhecidos, IDs duplicados e geometrias inválidas são rejeitados.
Imagens são normalizadas e incorporadas em PNG.

O tema aplicado é um snapshot. Histórico não pertence ao documento e não é
exportado. Gráficos usam tempo monotônico e preservam lacunas. Séries GPU são
identificadas por dispositivo, sem misturar placas.

## Verificação

```bash
python3 -m unittest discover -s tests -v
./abrir.sh --smoke-gui
python3 scripts/render_demo.py
python3 scripts/build_deb.py
desktop-file-validate packaging/turzx-linux.desktop
```

Testes cobrem protocolo/pseudoterminal, serviço, migração, validação, undo/redo,
arrastar/redimensionar, callbacks do editor, GPUs, gráficos, histórico e ausência
de guias na imagem transmitida. Não precisam de USB.

`--smoke-gui` constrói editor, propriedades de textos e gráficos, categorias
Memória/Rede/GPU, prévia e janela USB. Não aplica temas nem inicia transmissão.
Sem desktop:

```bash
sudo apt install xvfb xauth dbus-x11
GSK_RENDERER=cairo xvfb-run -a dbus-run-session -- ./abrir.sh --smoke-gui
```

O servidor gráfico precisa abrir sockets locais; sandboxes que os bloqueiem
não permitem esse teste. Use variáveis XDG apontando para diretórios temporários
para isolar preferências. `--run --simulate` exercita o transmissor sem USB e
identifica a simulação no status.

`render_demo.py` gera imagens e exemplo com dados fictícios fixos; não coleta
dados da máquina. `build_deb.py` usa `dpkg-deb` sem root; a versão vem de
`turzx/__init__.py`. O pacote inclui documentação, exemplo, ícone e regra udev.
`dist/`, caches, logs e configurações pessoais ficam fora do Git.

Antes de uma entrega com hardware, confira detecção, permissão, orientação,
cores, aplicação, reconexão e parada. Testes de software e sensores simulados
não demonstram que a transferência física foi validada.

## GitHub e proteção da main

O workflow **Linux CI** executa testes, smoke GTK com Xvfb e construção do pacote.
O check estável se chama **Linux checks**. Actions são fixadas por SHA.

[main-protection.json](../.github/main-protection.json) define PR obrigatório,
check aprovado e atualizado, conversas resolvidas, histórico linear e proibição
de force push e exclusão, inclusive para administradores. Revisões de outra
pessoa são opcionais para permitir manutenção por um único dono; PR é obrigatório.

**O arquivo no Git não ativa a proteção.** É preciso aplicar a política ao remoto
e confirmar a resposta. Repositórios privados podem exigir plano pago; o script
não altera plano ou visibilidade. Veja a
[documentação do GitHub](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

Para a primeira publicação, com GitHub CLI autenticado e código commitado:

```bash
python3 scripts/publish_github.py --visibility public
```

Use `private` se preferir. O script usa a conta autenticada, cria `turzx-linux`
se necessário, recusa um remoto diferente, publica `main`, aplica/verifica a
proteção e aguarda o CI. Não grava credenciais no projeto.
Depois, trabalhe em branches e abra PRs; não reduza proteção para contornar checks.
