# Como contribuir

Abra uma branch a partir da `main` e descreva no PR o problema e o comportamento
resultante. Inclua distribuição, versão do aplicativo e revisão da tela quando
envolver USB. Não publique tokens ou configurações pessoais; revise logs.

Execute os checks pertinentes do [guia de desenvolvimento](docs/DEVELOPMENT.md).
Mudanças no protocolo precisam de vetores de bytes verificáveis. Sensores
ausentes devem continuar como N/D. Mudanças de formato devem preservar leitura
de temas existentes.

Para alterações visuais, execute `--smoke-gui` e confira numa sessão GTK. Informe
separadamente hardware real e simulação. Atualize documentação quando o uso mudar.

Contribuições seguem GPL-3.0-or-later. Preserve créditos em `NOTICE` e use apenas
imagens e exemplos redistribuíveis sob termos compatíveis.
