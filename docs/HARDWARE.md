# Hardware e diagnóstico

## Tela suportada

| Propriedade | Valor |
| --- | --- |
| Modelo | Turing/TURZX 3,5″, revisão A |
| USB VID:PID | `1a86:5722` |
| Serial USB | `USB35INCHIPSV2` |
| Driver Linux | `cdc_acm` |
| Porta usual | `/dev/ttyACM0` — o número pode variar |
| Resolução | 320×480 retrato; 480×320 paisagem |
| Transporte | Comandos revisão A e pixels RGB565 pela porta serial USB |

A detecção e a regra udev são específicas desse dispositivo. Outras revisões
e tamanhos não têm compatibilidade garantida. Este aplicativo não estende o desktop.
Referências: [fabricante](https://www.turzx.com/) e
[protocolo de referência](https://github.com/mathoudebine/turing-smart-screen-python/blob/main/library/lcd/lcd_comm_rev_a.py).

## Sensores

- **CPU:** psutil, `/proc/cpuinfo` e sensores térmicos do kernel.
  Núcleos físicos e threads lógicas são informações distintas.
- **AMD:** DRM/sysfs e hwmon; [documentação](https://docs.kernel.org/gpu/amdgpu/thermal.html).
- **NVIDIA:** [`nvidia-smi`](https://docs.nvidia.com/deploy/nvidia-smi/index.html)
  quando executável e driver estão disponíveis. O app não instala o driver NVIDIA.
- **Intel:** identificação DRM e frequência quando exposta pelo driver;
  outras métricas podem ficar indisponíveis.
- **Memória:** percentual e quantidades em GiB reportadas pelo sistema.
- **Rede:** diferença dos contadores agregados entre amostras, dividida pelo
  tempo decorrido. Não há seleção por interface nesta versão.
- **Disco:** ocupação do sistema de arquivos raiz `/`.

Sensores ausentes aparecem como **N/D**. Em APUs, potência pode representar o SoC
inteiro. VRAM é a memória exposta pelo driver, não toda a RAM compartilhável.
RPM e percentual de ventoinha são leituras distintas. Consultas GPU são limitadas
a cerca de uma a cada dois segundos. A interface coleta em segundo plano.

## Comandos

```bash
turzx-linux --diagnose
turzx-linux --preview /tmp/turzx-previa.png
turzx-linux --run
turzx-linux --test
turzx-linux --stop
```

`--preview` renderiza sem USB. `--run` transmite em primeiro plano. `--test`
envia o teste de cores pelo transmissor; `--stop` encerra.
Do código-fonte, substitua `turzx-linux` por `./abrir.sh`.

## Problemas comuns

| Sintoma | O que conferir |
| --- | --- |
| Dispositivo não encontrado | Cabo com dados, conexão, VID/PID e revisão |
| Detectado no sysfs, mas porta ausente | Sandbox pode não expor o USB; execute no desktop |
| Acesso negado | Regra udev, cabo reconectado, sessão local ativa ou grupo dialout |
| Porta ocupada | Encerre outros programas que controlem a tela |
| Não há sessão gráfica | Abra no desktop; para transmissão sem janela use `--run` |
| Cores erradas após interrupção | Reconecte o cabo e use **Testar cores** |
| Sensor N/D | Confira suporte do hardware e driver |
| Gráfico inicialmente vazio | Aguarde a coleta; o histórico começa com o processo |
| Prévia mudou, painel não | Use **Aplicar na tela** novamente |

O transmissor tenta reconectar a cada três segundos. Bloqueio por usuário e
acesso exclusivo à porta evitam disputa pelo USB. Logs com rotação ficam em
`~/.local/state/turzx-linux/turzx.log`, respeitando XDG.
