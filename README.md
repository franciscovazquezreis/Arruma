# Arruma

Organizador de ficheiros que corre no teu computador, sem internet. Analisa as pastas que escolheres, propõe uma organização clara e só altera alguma coisa depois de reveres e aprovares o plano. Tudo o que faz fica no Histórico e pode ser anulado.

Funciona em **Linux** (pensado para o Linux Mint), **Windows 10/11** e **macOS 15 ou mais recente**.

## Instalar

As versões prontas a instalar são geradas automaticamente pelo GitHub a cada alteração. Ficam na página [Releases](https://github.com/franciscovazquezreis/Arruma/releases) quando é publicada uma versão, ou em [Actions → Construir e testar](https://github.com/franciscovazquezreis/Arruma/actions/workflows/construir.yml) → última execução → *Artifacts* (é preciso ter sessão iniciada no GitHub).

### Linux Mint, Ubuntu e Debian

Com o pacote `arruma_0.2.0_all.deb`:

```bash
sudo apt install ./arruma_0.2.0_all.deb
```

Fica no menu de aplicações (Acessórios → Arruma) e no clique direito das pastas do Nemo («Arrumar com o Arruma»). Precisa do Python 3.10 ou mais recente (Linux Mint 21 ou mais recente).

Em alternativa, sem `sudo` e só para o teu utilizador, a partir do código:

```bash
./instalar.sh
```

### Windows

Corre `Arruma-0.2.0-windows-instalador.exe`. Não pede permissões de administrador, cria a entrada no menu Iniciar e acrescenta «Arrumar com o Arruma» ao clique direito das pastas (no Windows 11 aparece em «Mostrar mais opções»). Há também uma versão portátil em `.zip`, que não precisa de instalação.

O instalador não tem assinatura digital paga, por isso o Windows pode mostrar o aviso «O Windows protegeu o seu PC». Para continuar: **Mais informações → Executar mesmo assim**.

### macOS

Abre o `.dmg` certo para o teu Mac (`apple-silicon` para os modelos M1, M2, M3… e `intel` para os mais antigos) e arrasta o Arruma para a pasta Aplicações.

A aplicação não está registada na Apple, por isso na primeira vez o macOS recusa abri-la. Para autorizar: **Definições do Sistema → Privacidade e segurança → Abrir mesmo assim**. Em alternativa, no Terminal:

```bash
xattr -dr com.apple.quarantine /Applications/Arruma.app
```

## Ativar a IA local (opcional)

Sem IA, o Arruma usa regras, metadados (datas das fotografias, etiquetas da música) e palavras-chave. Com a IA local, lê o texto dos documentos para escolher a área certa e propor nomes claros. Tudo continua a correr no computador: o Arruma recusa ligar-se a uma IA que não esteja em `localhost`.

1. Instala o [Ollama](https://ollama.com/download) (no Linux: `curl -fsSL https://ollama.com/install.sh | sh`).
2. Descarrega o modelo recomendado, cerca de 2 GB, uma única vez: `ollama pull qwen2.5:3b`

Depois disso funciona sem internet. O botão «Como ativar» na página inicial mostra os passos para o teu sistema.

Para ler PDF digitalizados (OCR), instala o Tesseract com o idioma português: `sudo apt install tesseract-ocr-por` no Linux, `brew install tesseract tesseract-lang poppler` no macOS, ou o instalador do Tesseract para Windows.

## Como arruma

Os documentos vão para uma de 13 áreas fixas (Finanças, Saúde, Casa, Trabalho, Educação, Pessoal, Jurídico, Veículos, Viagens, Compras e Garantias, Livros e Leituras, Lazer, Outros), cada uma com subáreas também fixas. A IA escolhe sempre de uma lista fechada, por isso nunca aparecem pastas com nomes inventados.

Para evitar pastas que não fazem sentido:

- uma subárea (por exemplo «Finanças/Faturas e Recibos») ou um álbum de música só ganham pasta própria quando têm pelo menos 3 ficheiros; com menos, ficam na pasta de cima;
- as fotografias só são separadas por ano quando algum ano tem pelo menos 3, e por mês a partir de 40 fotografias nesse ano;
- ao arrumar dentro de uma pasta, as subpastas que já têm nome próprio ficam onde estão; só as pastas genéricas («Nova pasta», «temp», «Diversos») são esvaziadas;
- as imagens recebidas por WhatsApp, Telegram ou Signal ficam em «Recebidas por mensagem», separadas das fotografias tiradas por ti.

Os ficheiros com nomes vagos («scan_003.pdf», «Documento (1).docx», «Contrato.pdf») podem receber um nome claro, com a data no início quando ela está escrita no documento (por exemplo `2025-02-20 Contrato de arrendamento para habitação.pdf`). Um nome proposto pela IA é recusado se citar uma empresa ou pessoa que não aparece no texto.

Pastas de programas, projetos de programação, bibliotecas (Calibre, Fotografias do macOS, Steam…), pastas sincronizadas (Dropbox, OneDrive, Nextcloud…) e pastas do sistema nunca são tocadas.

## Qualidade da organização

O workflow [Avaliar IA](https://github.com/franciscovazquezreis/Arruma/actions/workflows/avaliar-ia.yml) instala o Ollama num servidor do GitHub e compara duas versões do Arruma, com o modelo `qwen2.5:3b`, em dois conjuntos de documentos fictícios:

- **desenvolvimento** (36 documentos, mais fotografias, música e instaladores): foi usado para afinar as regras, por isso os números são otimistas;
- **validação** (26 documentos diferentes): as áreas esperadas foram fixadas antes de qualquer teste e o conjunto não serve para afinar nada. É a medida honesta.

Resultados da avaliação de 16 de outubro de 2026 (versão original 0.1.0 e versão 0.2.0):

| Indicador | Desenvolvimento 0.1.0 | Desenvolvimento 0.2.0 | Validação 0.1.0 | Validação 0.2.0 |
|---|---|---|---|---|
| Documentos na área certa | 28 de 36 | 36 de 36 | 19 de 26 | 21 de 26 |
| Pastas novas | 48 | 26 | 14 | 11 |
| Pastas novas com um só item | 26 | 9 | 4 | 3 |
| Subpastas com nome inventado | 2 | 0 | 3 | 0 |
| Profundidade máxima | 4 | 3 | 2 | 2 |
| Tempo da análise | 274 s | 285 s | 163 s | 177 s |

Nos documentos que nunca serviram para afinar nada, a versão 0.2.0 acerta na área de 81 % (21 de 26), contra 73 % na original, e deixou de criar subpastas com nomes inventados, como «Casa/Manutenção Veículos» ou «Educação/Escola Básica da Lourinhã». Os cinco documentos que ainda ficam fora da área esperada são casos em que um modelo de 3 mil milhões de parâmetros hesita: um manual de televisor em «Pessoal», uma multa em «Finanças», um contrato de ginásio em «Trabalho», um artigo de revista em «Lazer» e uma lista de compras em «Compras e Garantias». Como o plano é sempre revisto antes de ser aplicado, estes casos corrigem-se na página do plano.

Os números variam um pouco de uma execução para outra, mesmo com o mesmo código, porque o modelo nem sempre responde exatamente da mesma forma em máquinas diferentes: numa execução anterior, a versão original acertou 27 de 36 no conjunto de desenvolvimento, em vez de 28. Num servidor do GitHub sem placa gráfica, a IA demora 7 a 8 segundos por documento.

## Para quem desenvolve

```bash
python3 -m arruma                          # correr a partir do código (Linux)
python3 -m unittest discover -s tests -v   # testes
python3 -m arruma --self-test              # verifica a interface e o plano (precisa de ecrã)
packaging/linux/build-deb.sh               # cria dist/arruma_<versão>_all.deb
```

As versões de Windows e macOS são construídas com o PyInstaller (`packaging/pyinstaller/arruma.spec`) a partir do GTK do MSYS2 e do Homebrew; os passos exatos estão em `.github/workflows/construir.yml`. Para publicar uma versão, cria uma etiqueta `vX.Y.Z` igual à versão em `arruma/__init__.py`.

| Pasta | Conteúdo |
|---|---|
| `arruma/core` | análise, regras, IA local, plano, execução e anulação (sem interface) |
| `arruma/ui` | interface GTK 3 |
| `packaging` | pacote `.deb`, instalador do Windows, `.dmg` do macOS e ícones |
| `tests` | testes automáticos e avaliação com a IA real (`tests/avaliacao`) |
