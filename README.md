# Arruma

Organizador de ficheiros que corre no teu computador, sem internet. Analisa as pastas que escolheres, propõe uma organização clara e só altera alguma coisa depois de reveres e aprovares o plano. Tudo o que faz fica no Histórico e pode ser anulado.

Funciona em **Linux** (pensado para o Linux Mint), **Windows 10/11** e **macOS 15 ou mais recente**.

Para instalar e usar o Arruma passo a passo, com imagens, lê o [manual de utilização](docs/manual/README.md).

## Instalar

O GitHub gera automaticamente as versões prontas a instalar a cada alteração no ramo `main`. Ficam na página [Releases](https://github.com/franciscovazquezreis/Arruma/releases) quando se publica uma versão, ou em [Actions → Construir e testar](https://github.com/franciscovazquezreis/Arruma/actions/workflows/construir.yml) → última execução do `main` → *Artifacts*, durante 14 dias. Quem tem acesso de escrita ao repositório pode também pedi-las à mão, para qualquer ramo, no botão *Run workflow* dessa página.

### Linux Mint, Ubuntu e Debian

Com o pacote `arruma_<versão>_all.deb` da página Releases:

```bash
sudo apt install ./arruma_*_all.deb
```

Cada versão nova instala-se da mesma maneira e substitui a anterior.

Fica no menu de aplicações (Acessórios → Arruma) e no clique direito das pastas do Nemo («Arrumar com o Arruma»). Precisa do Python 3.10 ou mais recente (Linux Mint 21 ou mais recente).

Em alternativa, sem `sudo` e só para o teu utilizador, a partir do código:

```bash
./instalar.sh
```

As duas formas não se misturam. A cópia do `instalar.sh` fica na tua pasta pessoal e teria prioridade sobre o pacote, por isso o pacote retira-a quando é instalado; se essa cópia for mais recente do que o pacote, fica onde está e o pacote avisa. Com o pacote instalado, o `instalar.sh` recusa-se a instalar. Para retirar a cópia à mão: `./instalar.sh --remover`. O histórico e as definições ficam sempre.

### Windows

Abre o instalador `Arruma-<versão>-windows-instalador.exe`. Não pede permissões de administrador, cria a entrada no menu Iniciar e acrescenta «Arrumar com o Arruma» ao clique direito das pastas (no Windows 11 aparece em «Mostrar mais opções»). Há também uma versão portátil em `.zip`, que não precisa de instalação.

O instalador não tem um certificado de assinatura de código, por isso o Windows pode mostrar o aviso «O Windows protegeu o seu PC». Para continuar, carrega em «Mais informações» e depois em «Executar mesmo assim» (a redação pode variar ligeiramente; há versões que dizem «Executar de qualquer forma»). No Windows 11, se o Controlo Inteligente de Aplicações (Smart App Control) estiver ativo, é muito provável que bloqueie o Arruma, por não estar assinado, sem opção para continuar; o [manual](docs/manual/README.md#controlo-inteligente-de-aplicações-windows-11) explica como ver se está ativo.

### macOS

Abre o instalador `.pkg` certo para o teu Mac (`apple-silicon` para os modelos M1, M2, M3… e `intel` para os mais antigos). O Arruma fica na pasta Aplicações; o instalador pede a palavra-passe de administrador.

O instalador não está assinado com um certificado de programador da Apple nem passou pela notarização, por isso, da primeira vez, o macOS recusa abri-lo. Para autorizar, vai a **Definições do Sistema → Privacidade e segurança** e, em «Segurança», carrega em «Abrir» ao lado da indicação de que o instalador foi bloqueado (o nome do botão pode variar ligeiramente, por exemplo «Abrir mesmo assim»). Em alternativa, no Terminal (com o nome do ficheiro que descarregaste):

```bash
xattr -d com.apple.quarantine ~/Downloads/Arruma-*-macos-*.pkg
```

### Atualizar

Em qualquer sistema, basta instalar a versão nova da mesma maneira. O instalador vê se o Arruma já está instalado e em que versão: se não estiver, instala; se a instalada for mais antiga, atualiza; se for a mesma, avisa que não há nada a atualizar; se for mais recente, pede confirmação antes de a substituir e, numa instalação sem perguntas (pela linha de comandos), deixa-a como está. O histórico e as definições ficam sempre. No macOS, se o Arruma estiver aberto, o instalador pede para o fechar primeiro; pela linha de comandos, ou com o Arruma aberto noutra conta do Mac, a instalação para com um erro genérico e o motivo fica em `/var/log/install.log`. No Linux, o pacote retira também as cópias antigas que o `instalar.sh` tenha posto na pasta pessoal.

Para voltar a instalar a mesma versão (por exemplo, para reparar a instalação ou, no Windows, escolher outras opções), desinstala primeiro o Arruma: no Windows em Definições → Aplicações, no macOS pondo-o no Lixo. No Linux basta `sudo apt install --reinstall ./arruma_*_all.deb`.

## Ativar a IA local (opcional)

Sem IA, o Arruma usa regras, metadados (datas das fotografias, etiquetas da música) e palavras-chave. Com a IA local, lê o texto dos documentos para escolher a área certa e propor nomes claros. Tudo continua a correr no computador: o Arruma recusa ligar-se a uma IA que não esteja em `localhost`.

Funciona em Linux, Windows e macOS. Em qualquer deles são dois passos, e só precisam de internet da primeira vez: instalar o [Ollama](https://ollama.com/download) e descarregar o modelo recomendado (`qwen2.5:3b`, cerca de 2 GB).

| Sistema | 1. Instalar o Ollama | 2. Descarregar o modelo |
|---|---|---|
| Linux | No Terminal: `curl -fsSL https://ollama.com/install.sh \| sh` | No Terminal: `ollama pull qwen2.5:3b` |
| Windows | Instalador em [ollama.com/download/windows](https://ollama.com/download/windows) | No PowerShell: `ollama pull qwen2.5:3b` |
| macOS | Aplicação em [ollama.com/download/mac](https://ollama.com/download/mac): arrasta-a para Aplicações e abre-a uma vez | No Terminal: `ollama pull qwen2.5:3b` |

Depois disso funciona sem internet. O botão «Como ativar», na página inicial do Arruma, mostra os mesmos passos para o sistema onde está a correr.

Para ler PDF digitalizados (OCR), instala o Tesseract com o idioma português e os idiomas dos teus documentos: no Linux, `sudo apt install tesseract-ocr-por` e, se precisares, `tesseract-ocr-spa`, `tesseract-ocr-fra`, `tesseract-ocr-deu` ou `tesseract-ocr-ita`; no macOS, `brew install tesseract tesseract-lang poppler`, que traz todos os idiomas; no Windows, o instalador do Tesseract, escolhendo os idiomas durante a instalação. O Arruma usa os que estiverem instalados de entre português, espanhol, francês, alemão, italiano e inglês: lê sempre em português e, se o texto lido mostrar que o documento está noutro desses idiomas, lê-o também nesse idioma e fica com a leitura mais segura. As definições do Arruma mostram os idiomas que encontrou. O OCR não lê documentos noutros alfabetos (grego, cirílico, árabe, chinês…): esses são arrumados sobretudo pelo nome e pelos metadados.

## Como arruma

Os documentos vão para uma de 13 áreas fixas (Finanças, Saúde, Casa, Trabalho, Educação, Pessoal, Jurídico, Veículos, Viagens, Compras e Garantias, Livros e Leituras, Lazer, Outros), cada uma com subáreas também fixas. A IA escolhe sempre de uma lista fechada, por isso nunca aparecem pastas com nomes inventados.

Para evitar pastas que não fazem sentido:

- uma subárea (por exemplo «Finanças/Faturas e Recibos») ou um álbum de música só ganham pasta própria quando têm pelo menos 3 ficheiros; com menos, ficam na pasta de cima;
- as fotografias só são separadas por ano quando algum ano tem pelo menos 3, e por mês a partir de 40 fotografias nesse ano;
- ao arrumar dentro de uma pasta, as subpastas que já têm nome próprio ficam onde estão; só as pastas genéricas («Nova pasta», «temp», «Diversos») são esvaziadas;
- as imagens recebidas por WhatsApp, Telegram ou Signal ficam em «Recebidas por mensagem», separadas das fotografias tiradas por ti.

Os ficheiros com nomes vagos («scan_003.pdf», «Documento (1).docx», «Contrato.pdf») podem receber um nome claro, com a data no início quando ela está escrita no documento (por exemplo `2025-02-20 Contrato de arrendamento para habitação.pdf`). Um nome proposto pela IA é recusado se citar uma empresa ou pessoa que não aparece no texto.

O Arruma nunca toca em pastas de programas, projetos de programação, bibliotecas (Calibre, Fotografias do macOS, Steam…), pastas sincronizadas (Dropbox, OneDrive, Nextcloud…) nem em pastas do sistema.

## Qualidade da organização

O workflow [Avaliar IA](https://github.com/franciscovazquezreis/Arruma/actions/workflows/avaliar-ia.yml) instala o Ollama num servidor do GitHub e compara duas versões do Arruma, com o modelo `qwen2.5:3b`, em dois conjuntos de documentos fictícios:

- **desenvolvimento** (36 documentos, mais fotografias, música e instaladores): foi usado para afinar as regras, por isso os números são otimistas;
- **validação** (26 documentos diferentes): as áreas esperadas foram fixadas antes de qualquer teste e o conjunto não serve para afinar nada. É este o resultado que conta.

Resultados da avaliação de 16 de outubro de 2026 (versão original 0.1.0 e versão 0.2.0):

| Indicador | Desenvolvimento 0.1.0 | Desenvolvimento 0.2.0 | Validação 0.1.0 | Validação 0.2.0 |
|---|---|---|---|---|
| Documentos na área certa | 28 de 36 | 36 de 36 | 19 de 26 | 21 de 26 |
| Pastas novas | 48 | 26 | 14 | 11 |
| Pastas novas com um só item | 26 | 9 | 4 | 3 |
| Subpastas com nome inventado | 2 | 0 | 3 | 0 |
| Profundidade máxima | 4 | 3 | 2 | 2 |
| Tempo da análise | 274 s | 285 s | 163 s | 177 s |

Nos documentos que nunca serviram para afinar nada, a versão 0.2.0 acerta na área de 81 % (21 de 26), contra 73 % na original, e deixou de criar subpastas com nomes inventados, como «Casa/Manutenção Veículos» ou «Saúde/Vacinas». Os cinco documentos que ainda ficam fora da área esperada são casos em que um modelo de 3 mil milhões de parâmetros hesita: um manual de televisor em «Pessoal», uma multa em «Finanças», um contrato de ginásio em «Trabalho», um artigo de revista em «Lazer» e uma lista de compras em «Compras e Garantias». Como o plano é sempre revisto antes de ser aplicado, estes casos corrigem-se na vista Plano.

Os números variam um pouco de uma execução para outra, mesmo com o mesmo código, porque o modelo nem sempre responde exatamente da mesma forma em máquinas diferentes: numa execução anterior, a versão original acertou 27 de 36 no conjunto de desenvolvimento, em vez de 28. Num servidor do GitHub sem placa gráfica, a IA demora 7 a 8 segundos por documento.

## Para quem desenvolve

```bash
python3 -m arruma                          # correr a partir do código (Linux)
python3 -m unittest discover -s tests -v   # testes
python3 -m arruma --self-test              # verifica a interface e o plano (precisa de ecrã)
packaging/linux/build-deb.sh               # cria dist/arruma_<versão>_all.deb
```

As versões de Windows e macOS são construídas com o PyInstaller (`packaging/pyinstaller/arruma.spec`) a partir do GTK do MSYS2 e do Homebrew; os passos exatos estão em `.github/workflows/construir.yml`. Os testes correm em todas as alterações. As versões para instalar só são construídas no `main`, nas etiquetas e quando pedidas à mão, porque demoram (sobretudo no macOS) e cada uma leva consigo cerca de 1 GB de código-fonte de componentes de terceiros. Para publicar uma versão, cria uma etiqueta `vX.Y.Z` igual à versão em `arruma/__init__.py`; se for diferente, a publicação para.

| Pasta | Conteúdo |
|---|---|
| `arruma/core` | análise, regras, IA local, plano, execução e anulação (sem interface) |
| `arruma/ui` | interface GTK 3 |
| `packaging` | pacote `.deb`, instalador do Windows, instalador `.pkg` do macOS e ícones |
| `tests` | testes automáticos e avaliação com a IA real (`tests/avaliacao`) |

## Licença

O Arruma é software livre: podes usá-lo, estudá-lo, alterá-lo e distribuí-lo nos termos da [GNU General Public License](LICENSE), versão 3 ou (à tua escolha) qualquer versão posterior. É distribuído sem qualquer garantia. Copyright © 2026 Francisco Reis.

As versões para Windows e macOS incluem componentes de outros autores (Python, GTK, mutagen e, no Windows, Poppler, entre outros), cada um com a sua licença. A lista completa, os textos das licenças e o endereço do código-fonte de cada componente vão dentro de cada versão, na pasta `licencas` (no Windows em `_internal\licencas`, no macOS em `Arruma.app/Contents/Resources/licencas`), e abrem-se no botão «Acerca do Arruma» → «Licenças de terceiros». Isto inclui as bibliotecas Rust que alguns componentes trazem dentro (librsvg e libimagequant; no Windows também rav1e e, no macOS, cryptography), cada uma com a sua licença, na subpasta `crates` desse componente. O código-fonte desses componentes acompanha os instaladores: nas versões publicadas, na mesma página de Releases (ficheiros `Arruma-<versão>-codigo-fonte-terceiros-<sistema>.tar`); nas versões de teste, na mesma execução do Actions (artefacto `arruma-codigo-fonte-terceiros`). O pacote `.deb` não inclui componentes de terceiros: usa os que o sistema já tem.
