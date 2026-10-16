# Arruma — Organizador de ficheiros local para o Linux Mint

O **Arruma** analisa as tuas pastas, propõe uma organização clara e só altera alguma coisa depois de reveres e aprovares. Tudo corre localmente neste computador, sem acesso à internet.

## Executar já

```bash
cd /home/francisco/.gemini/antigravity/scratch/arruma
python3 -m arruma
```

## Instalar no menu do Linux Mint e no clique direito do Nemo

```bash
cd /home/francisco/.gemini/antigravity/scratch/arruma
./instalar.sh
```

Isto instala:
- A aplicação **Arruma** no menu do Linux Mint;
- A opção **«Arrumar esta pasta com o Arruma»** ao clicar com o botão direito numa pasta no gestor de ficheiros Nemo;
- O comando `~/.local/bin/arruma`.

## Ativar a IA local (opcional, uma única vez)

Para que o modelo de linguagem local leia o conteúdo dos documentos, escolha a área temática e proponha nomes claros em português:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b
```

Depois disso pode usar-se totalmente sem internet. Para ler também PDFs digitalizados (OCR):

```bash
sudo apt install tesseract-ocr tesseract-ocr-por
```

## Testes

```bash
python3 -m unittest discover -s tests -v
```
