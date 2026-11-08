# Instalação e atualização

## Ubuntu e Debian

Requisitos: Python ≥3.10, GTK ≥4.6 e sessão gráfica Linux. O instalador usa os
pacotes da distribuição. Não é necessário instalar bibliotecas com `pip`.

```bash
./instalar.sh
```

Execute como seu usuário normal. O `sudo` é usado pelo `apt` para instalar o
programa, dependências e regra udev. Há necessidade de internet para atualizar o
índice e obter dependências. Depois, abra **Turzx Linux** no menu ou execute:

```bash
turzx-linux
turzx-linux --diagnose
```

Para instalar um pacote já construído:

```bash
sudo apt install ./dist/turzx-linux_1.2.0_all.deb
```

O driver `cdc_acm` vem com o kernel. O pacote tenta carregá-lo e configura acesso
USB para o usuário da sessão local ativa e o grupo `dialout`. Reconecte o cabo
se a permissão ainda não estiver disponível. O aplicativo roda sem root.

## Atualizar da versão 1.0 ou 1.1

Feche a janela antiga, execute novamente `./instalar.sh` e abra o Studio.
Preferências, imagens e início automático são preservados. Ao aplicar um tema,
um transmissor de versão anterior é encerrado antes de iniciar o novo.

Temas no formato 1 são lidos e migrados em memória para o formato 2. Ao salvar ou
exportar, passam a usar o formato 2, com elementos livres e gráficos. Guarde uma
cópia anterior se precisar continuar abrindo o tema na versão 1.1.

## Executar sem instalar

No Ubuntu/Debian:

```bash
sudo apt install python3 python3-gi gir1.2-gtk-4.0 python3-pil python3-serial python3-psutil fonts-dejavu-core
./abrir.sh
```

Em outras distribuições, instale pacotes equivalentes. A execução portátil também
precisa da permissão USB. Um administrador pode instalar a regra:

```bash
sudo install -m 644 packaging/70-turzx-linux.rules /etc/udev/rules.d/70-turzx-linux.rules
sudo udevadm control --reload-rules
```

Reconecte a tela. Para uso sem sessão local ativa, como via SSH, o administrador
pode conceder acesso pelo grupo `dialout`; é preciso entrar novamente na sessão.

## Dados e início automático

| Local padrão | Conteúdo |
| --- | --- |
| `~/.config/turzx-linux/config.json` | Preferências e cópia do tema aplicado |
| `~/.config/turzx-linux/themes/` | Biblioteca pessoal de temas |
| `~/.config/turzx-linux/images/` | Imagens importadas |
| `~/.local/state/turzx-linux/turzx.log` | Log com rotação |
| `~/.config/autostart/turzx-linux.desktop` | Início no login, quando ativado |

As variáveis XDG são respeitadas. **Iniciar ao entrar no Linux**, em **Configurar
tela USB**, inicia a transmissão no próximo login sem abrir a janela. Fechar o
Studio mantém a transmissão; **Parar painel** encerra e apaga a tela.

## Remover

Desative o início automático, aplique e pare o painel. Depois:

```bash
sudo apt remove turzx-linux
```

Preferências e temas pessoais são preservados. Se instalou a regra udev
manualmente em `/etc`, remova essa cópia separadamente quando não for mais usá-la.
