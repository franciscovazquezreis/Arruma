# SPDX-License-Identifier: GPL-3.0-or-later
"""Tira as capturas de ecrã do Arruma no Linux para o manual, com dados fictícios.

Cria uma pasta pessoal de exemplo (a da «Ana», com uma pasta Transferências desarrumada), abre o
Arruma com essa pasta pessoal e percorre as vistas pelos mesmos caminhos que uma pessoa: escolher a
pasta, analisar, procurar duplicados, criar o plano, rever um ficheiro, aplicar, ver o histórico,
anular, Definições, Acerca e a ajuda da IA. Cada imagem é só a janela (ou o diálogo), sem o
ambiente de trabalho à volta.

Uso (o Python tem de ter o PyGObject, o Pillow e o mutagen):

    python3 docs/manual/capturar.py --casa /tmp/capturas/ana [--imagens docs/manual/imagens]

A pasta dada em --casa passa a ser a pasta pessoal do Arruma durante as capturas: tem de estar
vazia (ou não existir) e é preenchida com os ficheiros de exemplo. O histórico e as definições
ficam lá dentro, por isso cada execução começa do zero. O nome da pasta aparece no seletor de
pastas; o cartão «Todo o computador» conta também as outras pastas de /home e os discos montados.

Sem ecrã (DISPLAY), o script volta a correr dentro do xvfb-run e, se houver o xcompmgr, o próprio
GTK desenha a barra de título e a sombra das janelas, como no Linux Mint. Os botões do GTK
(Cancelar, Fechar…) saem na língua do sistema: corre-o com LANG=pt_PT.UTF-8 num sistema com as
traduções do GTK instaladas.

Todos os documentos, nomes e números são inventados (vêm de tests/avaliacao/gerar_corpus.py).
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
TAMANHO_ECRA = "1600x1000x24"
# O mesmo tamanho para todas as imagens: a largura com que o Arruma abre (ArrumaWindow) e a altura
# necessária para o Início caber inteiro (o Arruma abre com 760; o resto do Início fica para baixo).
LARGURA, ALTURA = 1180, 880

# Aspeto predefinido do Linux Mint 22 (mint-artwork): tema Mint-Y-Aqua, ícones Mint-Y-Sand e letra
# Ubuntu 10. Só conta quando não há um ambiente de trabalho a definir o tema (por exemplo, no
# Xvfb); se estes temas não estiverem instalados, o GTK usa o Adwaita.
GTK_SETTINGS = """[Settings]
gtk-theme-name=Mint-Y-Aqua
gtk-icon-theme-name=Mint-Y-Sand
gtk-font-name=Ubuntu 10
"""

# Pastas pessoais com os nomes que o xdg-user-dirs cria num sistema em português de Portugal.
PASTAS_PESSOAIS = {
    "DESKTOP": "Secretária", "DOWNLOAD": "Transferências", "TEMPLATES": "Modelos", "PUBLICSHARE": "Público",
    "DOCUMENTS": "Documentos", "MUSIC": "Música", "PICTURES": "Imagens", "VIDEOS": "Vídeos",
}


# =========================================================================== dados de exemplo

# Documentos de tests/avaliacao/gerar_corpus.py: nome, tamanho em KB (para parecerem digitalizações
# e documentos reais) e data em que foram descarregados.
DOCUMENTOS = [
    ("scan_001.pdf", 184, "2025-03-14 21:02"),
    ("Fatura Telecom Atlântico março.pdf", 96, "2025-03-06 08:40"),
    ("doc20250131.pdf", 142, "2025-02-03 12:15"),
    ("8f3a2c9d1e7b.pdf", 211, "2025-05-15 19:31"),
    ("extrato.pdf", 78, "2025-03-02 10:05"),
    ("Documento (1).docx", 36, "2025-02-21 17:48"),
    ("Receita.pdf", 64, "2025-11-08 09:12"),
    ("relatorio.pdf", 320, "2025-10-02 15:20"),
    ("Contrato.pdf", 540, "2024-06-27 18:03"),
    ("orcamento_obras.pdf", 122, "2026-04-11 11:30"),
    ("contrato_trabalho_assinado.pdf", 1240, "2025-09-30 16:44"),
    ("Proposta Cliente Atlântida.docx", 58, "2026-01-20 10:10"),
    ("notas reuniao.txt", 3, "2026-01-22 14:37"),
    ("Sprint Review Q1.pptx", 860, "2026-03-31 17:05"),
    ("timesheet_outubro.xlsx", 22, "2025-11-03 09:00"),
    ("certificado.pdf", 410, "2023-12-15 13:22"),
    ("CV_2025.docx", 44, "2026-01-09 22:16"),
    ("inspecao.pdf", 155, "2026-05-20 10:48"),
    ("seguro_carro.pdf", 230, "2026-01-31 20:05"),
    ("boarding_pass.pdf", 88, "2026-07-03 06:55"),
    ("booking_confirmation.pdf", 72, "2026-06-18 23:10"),
    ("garantia_portatil.pdf", 133, "2025-12-27 16:00"),
    ("receita_bacalhau.docx", 27, "2025-12-20 19:42"),
    ("digitalizacao_0007.pdf", 1880, "2026-08-29 11:03"),
    ("boletim_vacinas.pdf", 260, "2026-03-12 09:30"),
    ("bilhete_cp.pdf", 54, "2026-07-25 07:20"),
    ("multa.pdf", 98, "2026-09-04 18:11"),
    ("scan_0091.pdf", 2210, "2026-09-17 10:26"),
    ("Nova pasta/recibo_agua.txt", 2, "2026-02-14 08:50"),
]

# Uma subpasta com nome próprio, que o Arruma muda inteira: nome, data e texto de cada fatura.
FATURAS_2023 = [
    ("fatura_luz_janeiro.pdf", "2023-02-02 20:14", [
        "LusoEnergia, S.A.   NIF 509 876 543", "FATURA N.º FT 2023/011845   Data: 2023-01-31",
        "Cliente: Ana Ribeiro", "TOTAL A PAGAR: 61,20 EUR"]),
    ("fatura_luz_fevereiro.pdf", "2023-03-01 21:40", [
        "LusoEnergia, S.A.   NIF 509 876 543", "FATURA N.º FT 2023/029310   Data: 2023-02-28",
        "Cliente: Ana Ribeiro", "TOTAL A PAGAR: 57,85 EUR"]),
    ("fatura_agua_marco.pdf", "2023-04-03 19:05", [
        "Águas de Vila Exemplo   NIF 510 222 333", "Fatura n.º AVE/2023/11870   Data: 2023-03-31",
        "Total a pagar: 18,40 EUR"]),
]

# Fotografias: nome, (marca, modelo) da câmara e data registada pela câmara (EXIF DateTimeOriginal).
FOTOS = [
    ("IMG_20240812_101010.jpg", ("samsung", "SM-A546B"), "2024:08:12 10:10:10"),
    ("IMG_20240812_101544.jpg", ("samsung", "SM-A546B"), "2024:08:12 10:15:44"),
    ("IMG_20240813_093000.jpg", ("samsung", "SM-A546B"), "2024:08:13 09:30:00"),
    ("PXL_20231224_201500.jpg", ("Google", "Pixel 7"), "2023:12:24 20:15:00"),
    ("DSC_0457.JPG", ("NIKON CORPORATION", "NIKON D3500"), "2026:04:19 16:42:10"),
]
# Imagens recebidas pelo WhatsApp (sem dados de câmara; a data vem do nome).
WHATSAPP = ["IMG-20240512-WA0003.jpg", "IMG-20240512-WA0004.jpg", "IMG-20260301-WA0005.jpg"]
# Instaladores, vídeos e comprimidos: nome, tamanho em MB e data. São ficheiros esparsos (ocupam
# pouco no disco), com o tamanho de um ficheiro verdadeiro.
GRANDES = [
    ("vlc-3.0.21-win64.exe", 41.6, "2024-02-10 20:31", b"MZ"),
    ("virtualbox-7.1_7.1.4_amd64.deb", 103.2, "2025-10-14 22:05", b"!<arch>\n"),
    ("linuxmint-22.2-cinnamon-64bit.iso", 2995.4, "2026-09-12 21:40", b"\x00"),
    ("VID_20240812_120000.mp4", 86.3, "2024-08-12 12:00", b"\x00\x00\x00\x18ftypmp42"),
    ("VID-20260315-WA0002.mp4", 12.8, "2026-03-15 13:02", b"\x00\x00\x00\x18ftypmp42"),
    ("Gravação de ecrã de 2026-02-10 09-15-02.webm", 31.5, "2026-02-10 09:16", b"\x1aE\xdf\xa3"),
    ("fotos_jantar_natal.zip", 24.1, "2025-01-03 11:27", b"PK\x03\x04"),
    ("documentos_IRS_2025.zip", 2.1, "2026-04-02 21:13", b"PK\x03\x04"),
]


def _quando(texto: str) -> float:
    formato = "%Y:%m:%d %H:%M:%S" if texto.count(":") == 4 else "%Y-%m-%d %H:%M"
    return datetime.strptime(texto, formato).astimezone().timestamp()  # hora local


def _data(path: Path, texto: str) -> None:
    t = _quando(texto)
    os.utime(path, (t, t))


def _engordar_pdf(path: Path, kb: int, rnd: random.Random) -> None:
    """Acrescenta ao PDF uma atualização incremental com um objeto de enchimento (PDF válido)."""
    data = path.read_bytes()
    falta = kb * 1024 - len(data)
    if falta <= 256:
        return
    xref_antiga = int(data.rsplit(b"startxref", 1)[1].split()[0])
    tamanho = int(data.rsplit(b"/Size", 1)[1].split()[0])
    enchimento = rnd.randbytes(falta - 200)
    obj = len(data)
    novo = b"%d 0 obj\n<< /Length %d >>\nstream\n" % (tamanho, len(enchimento)) + enchimento + \
        b"\nendstream\nendobj\n"
    xref = obj + len(novo)
    novo += b"xref\n0 1\n0000000000 65535 f \n%d 1\n%010d 00000 n \n" % (tamanho, obj)
    novo += b"trailer\n<< /Size %d /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (tamanho + 1, xref_antiga, xref)
    path.write_bytes(data + novo)


def _engordar_zip(path: Path, kb: int, rnd: random.Random) -> None:
    """Junta uma imagem (bytes ao acaso) ao docx/pptx/xlsx, como os documentos com imagens."""
    falta = kb * 1024 - path.stat().st_size
    if falta > 512:
        pasta = {".docx": "word", ".pptx": "ppt", ".xlsx": "xl"}[path.suffix.lower()]
        with zipfile.ZipFile(path, "a") as z:
            z.writestr(f"{pasta}/media/image1.jpeg", rnd.randbytes(falta - 200), zipfile.ZIP_STORED)


def _foto(path: Path, rnd: random.Random, cor: tuple[int, int, int], camera: tuple[str, str] | None = None,
          data: str | None = None) -> None:
    """Fotografia JPEG de 1600×1200 (gradiente com ruído, para ter o tamanho de uma fotografia real)."""
    from PIL import Image
    w, h = 1600, 1200
    fundo = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    fundo = Image.blend(fundo, Image.new("RGB", (w, h), cor), 0.6)
    ruido = Image.frombytes("RGB", (w, h), rnd.randbytes(w * h * 3))
    img = Image.blend(fundo, ruido, 0.18)
    exif = Image.Exif()
    if camera:
        exif[0x010F], exif[0x0110] = camera
    if data:
        exif[0x0132] = data
        exif.get_ifd(0x8769)[0x9003] = data  # DateTimeOriginal
    img.save(path, "JPEG", quality=90, exif=exif.tobytes())


def _mp3(path: Path, artista: str, album: str, titulo: str, mb: float) -> None:
    from gerar_corpus import _mp3 as mp3_curto
    mp3_curto(path, artista, album, titulo)
    trama = b"\xff\xfb\x90\x00" + b"\x00" * 413  # MPEG-1 Layer III mudo, 128 kbit/s
    with path.open("ab") as f:
        f.write(trama * int(mb * 1024 * 1024 / len(trama)))


def _grande(path: Path, mb: float, cabecalho: bytes) -> None:
    with path.open("wb") as f:
        f.write(cabecalho)
        f.truncate(int(mb * 1024 * 1024))


def preparar_casa(casa: Path) -> None:
    """Cria a pasta pessoal de exemplo: pastas pessoais, uma Transferências desarrumada e duplicados."""
    sys.path.insert(0, str(RAIZ / "tests" / "avaliacao"))
    import gerar_corpus as corpus

    rnd = random.Random(2026)
    textos = {**corpus.DOCUMENTOS, **corpus.VALIDACAO}
    cfg = casa / ".config"
    (cfg / "gtk-3.0").mkdir(parents=True)
    (cfg / "user-dirs.dirs").write_text(
        "".join(f'XDG_{k}_DIR="$HOME/{v}"\n' for k, v in PASTAS_PESSOAIS.items()), encoding="utf-8")
    (cfg / "gtk-3.0" / "settings.ini").write_text(GTK_SETTINGS, encoding="utf-8")
    # Marcadores que o Linux Mint cria para o painel lateral do gestor e dos seletores de ficheiros.
    (cfg / "gtk-3.0" / "bookmarks").write_text("".join(
        f"{(casa / PASTAS_PESSOAIS[k]).as_uri()}\n" for k in ("DOCUMENTS", "MUSIC", "PICTURES", "VIDEOS", "DOWNLOAD")),
        encoding="utf-8")
    for nome in PASTAS_PESSOAIS.values():
        (casa / nome).mkdir()

    # Pastas pessoais com alguma coisa já arrumada.
    doc = casa / "Documentos"
    (doc / "Finanças" / "Banco").mkdir(parents=True)
    corpus._pdf(doc / "Finanças" / "Banco" / "extrato_dezembro_2025.pdf",
                ["Banco Douro, S.A.", "Extrato da conta à ordem   Período: dezembro de 2025"])
    (doc / "Trabalho").mkdir()
    corpus._docx(doc / "Trabalho" / "Relatório anual 2025.docx", ["Relatório anual de atividades 2025"])
    (doc / "Receitas da avó").mkdir()
    (doc / "Receitas da avó" / "bolo_de_laranja.txt").write_text("Bolo de laranja\n4 ovos, 2 laranjas\n",
                                                                   encoding="utf-8")
    agosto = casa / "Imagens" / "Fotografias" / "2024" / "2024-08 Agosto"
    agosto.mkdir(parents=True)
    _foto(agosto / "IMG_20240810_183000.jpg", rnd, (230, 150, 60), ("samsung", "SM-A546B"), "2024:08:10 18:30:00")
    _foto(casa / "Imagens" / "serra_da_estrela.jpg", rnd, (90, 130, 170))
    musica = casa / "Música" / "Fado da Ribeira" / "Noites de Alfama"
    musica.mkdir(parents=True)
    _mp3(musica / "01 Lisboa ao luar.mp3", "Fado da Ribeira", "Noites de Alfama", "Lisboa ao luar", 4.2)
    (casa / "Secretária" / "lista de compras.txt").write_text("Arroz\nAzeite\nPão\n", encoding="utf-8")
    (casa / "Secretária" / "Notas.txt").write_text("Ligar ao canalizador na segunda-feira.\n", encoding="utf-8")

    # A pasta Transferências, desarrumada.
    tr = casa / "Transferências"
    for rel, kb, quando in DOCUMENTOS:
        path = tr / rel
        corpus._escrever_documentos(tr, {rel: textos[rel]})
        if path.suffix == ".pdf":
            _engordar_pdf(path, kb, rnd)
        elif path.suffix in (".docx", ".pptx", ".xlsx"):
            _engordar_zip(path, kb, rnd)
        _data(path, quando)
    for nome, quando, linhas in FATURAS_2023:
        path = tr / "Faturas 2023" / nome
        path.parent.mkdir(exist_ok=True)
        corpus._pdf(path, linhas)
        _engordar_pdf(path, rnd.randint(70, 160), rnd)
        _data(path, quando)
    for i, (nome, camera, quando) in enumerate(FOTOS):
        _foto(tr / nome, rnd, (180 - i * 20, 120 + i * 15, 70 + i * 25), camera, quando)
        _data(tr / nome, quando)
    for i, nome in enumerate(WHATSAPP):
        _foto(tr / nome, rnd, (60 + i * 40, 160, 120))
        _data(tr / nome, f"{nome[4:8]}-{nome[8:10]}-{nome[10:12]} {10 + i}:{20 + i}")
    album = tr / "Férias Algarve"
    album.mkdir()
    for i in range(1, 7):
        quando = f"2024:08:{14 + i // 3:02d} {10 + i}:{5 * i:02d}:00"
        _foto(album / f"praia_{i:02d}.jpg", rnd, (40, 140 + i * 10, 210 - i * 12), ("Apple", "iPhone 13"), quando)
        _data(album / f"praia_{i:02d}.jpg", quando)
    corpus._png(tr / "Captura de ecrã de 2026-01-02 10-00-00.png")
    _data(tr / "Captura de ecrã de 2026-01-02 10-00-00.png", "2026-01-02 10:00")
    (tr / "logotipo_associacao.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="30" '
        'fill="#3a7"/></svg>\n', encoding="utf-8")
    _data(tr / "logotipo_associacao.svg", "2025-05-08 18:20")
    _mp3(tr / "Os Ventos do Sul - Ao fim da tarde.mp3", "Os Ventos do Sul", "Marés", "Ao fim da tarde", 7.4)
    _mp3(tr / "audio_0002.mp3", "Os Ventos do Sul", "Marés", "Maré cheia", 6.1)  # nome vago: ganha um nome novo
    for nome in ("Os Ventos do Sul - Ao fim da tarde.mp3", "audio_0002.mp3"):
        _data(tr / nome, "2025-06-21 22:30")
    for nome, mb, quando, cabecalho in GRANDES:
        _grande(tr / nome, mb, cabecalho)
        _data(tr / nome, quando)
    (tr / "script_backup.sh").write_text("#!/bin/sh\nrsync -a ~/Documentos /media/disco/copia\n", encoding="utf-8")
    _data(tr / "script_backup.sh", "2025-02-02 23:01")

    # Lixo: miniaturas do Windows, uma transferência incompleta e o ficheiro de bloqueio do Word.
    (tr / "Thumbs.db").write_bytes(rnd.randbytes(18 * 1024))
    _grande(tr / "relatorio_trimestral.pdf.crdownload", 3.4, b"%PDF-1.7\n")
    (tr / "~$CV_2025.docx").write_bytes(rnd.randbytes(162))
    for nome in ("Thumbs.db", "relatorio_trimestral.pdf.crdownload", "~$CV_2025.docx"):
        _data(tr / nome, "2026-01-09 22:16")
    (tr / "Nova pasta (2)").mkdir()

    # Cópias exatas (o mesmo conteúdo, byte a byte), como as que se descarregam duas vezes.
    for original, copia in (("CV_2025.docx", "CV_2025 (1).docx"), ("extrato.pdf", "extrato (1).pdf"),
                            ("IMG-20240512-WA0003.jpg", "IMG-20240512-WA0003 (1).jpg")):
        shutil.copy2(tr / original, tr / copia)
        st = (tr / original).stat()
        os.utime(tr / copia, (st.st_mtime + 86400 * 3, st.st_mtime + 86400 * 3))


# =========================================================================== capturas

def anunciar_molduras():
    """Diz ao GTK que pode desenhar ele próprio a moldura das janelas (barra de título e sombra).

    O GTK só o faz quando o gestor de janelas anuncia _GTK_FRAME_EXTENTS, como o Muffin do Linux Mint,
    e há um compositor (o xcompmgr). No Xvfb não há gestor de janelas: aqui só se faz o anúncio, que
    o GTK lê na janela raiz; as janelas não passam a ser geridas por ninguém. Devolve a ligação ao X,
    que tem de ficar aberta até ao fim."""
    import ctypes
    from ctypes import c_char_p, c_int, c_uint, c_ulong, c_void_p
    x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
    x11.XOpenDisplay.restype = c_void_p
    x11.XOpenDisplay.argtypes = [c_char_p]
    x11.XDefaultRootWindow.restype = c_ulong
    x11.XDefaultRootWindow.argtypes = [c_void_p]
    x11.XCreateSimpleWindow.restype = c_ulong
    x11.XCreateSimpleWindow.argtypes = [c_void_p, c_ulong, c_int, c_int, c_uint, c_uint, c_uint, c_ulong, c_ulong]
    x11.XInternAtom.restype = c_ulong
    x11.XInternAtom.argtypes = [c_void_p, c_char_p, c_int]
    x11.XChangeProperty.argtypes = [c_void_p, c_ulong, c_ulong, c_ulong, c_int, c_int, c_void_p, c_int]
    x11.XFlush.argtypes = [c_void_p]
    xa_atom, xa_window, substituir = 4, 33, 0

    dpy = x11.XOpenDisplay(None)
    raiz = x11.XDefaultRootWindow(dpy)
    marca = x11.XCreateSimpleWindow(dpy, raiz, -10, -10, 1, 1, 0, 0, 0)

    def atomo(nome: bytes) -> int:
        return x11.XInternAtom(dpy, nome, 0)

    janela = (c_ulong * 1)(marca)
    for w in (raiz, marca):
        x11.XChangeProperty(dpy, w, atomo(b"_NET_SUPPORTING_WM_CHECK"), xa_window, 32, substituir, janela, 1)
    nome = b"capturas do Arruma"
    x11.XChangeProperty(dpy, marca, atomo(b"_NET_WM_NAME"), atomo(b"UTF8_STRING"), 8, substituir, nome, len(nome))
    suportado = (c_ulong * 1)(atomo(b"_GTK_FRAME_EXTENTS"))
    x11.XChangeProperty(dpy, raiz, atomo(b"_NET_SUPPORTED"), xa_atom, 32, substituir, suportado, 1)
    x11.XFlush(dpy)
    return x11, dpy


def correr(casa: Path, saida: Path) -> int:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gio, GLib, Gtk

    sys.path.insert(0, str(RAIZ))
    from arruma.ui.app import ArrumaApp

    def descendentes(widget):
        yield widget
        if isinstance(widget, Gtk.Container):
            filhos: list = []
            widget.forall(filhos.append)
            for f in filhos:
                yield from descendentes(f)

    def textos(widget) -> list[str]:
        return [w.get_text() for w in descendentes(widget) if isinstance(w, Gtk.Label)]

    def botao(widget, texto: str) -> Gtk.Button:
        for w in descendentes(widget):
            if isinstance(w, Gtk.Button) and (w.get_label() == texto or texto in textos(w)) and w.get_visible():
                return w
        raise LookupError(f"Botão «{texto}» não encontrado")

    def dialogo(tipo):
        for w in Gtk.Window.list_toplevels():
            if isinstance(w, tipo) and w.get_mapped():
                return w
        return None

    def depois(funcao) -> None:
        """Corre «funcao» fora do passo atual (para os diálogos que esperam pela resposta)."""
        GLib.idle_add(lambda: (funcao(), False)[1])

    class Guiao:
        def __init__(self, app):
            self.app = app
            self.gen = None
            self.cond = None
            self.ate = 0.0
            self.limite = 0.0
            self.erro: str | None = None
            self.feitas: list[str] = []

        # ------------------------------------------------------------------ motor
        def comecar(self) -> None:
            self.gen = self.passos()
            GLib.timeout_add(100, self.avancar)

        def avancar(self) -> bool:
            try:
                agora = time.monotonic()
                if self.cond is not None:
                    if not self.cond():
                        if agora > self.limite:
                            raise TimeoutError("o Arruma não chegou ao estado esperado a tempo")
                        return True
                    self.cond = None
                if agora < self.ate:
                    return True
                pedido = next(self.gen)
                if callable(pedido):
                    self.cond, self.limite = pedido, agora + 60
                else:
                    self.ate = agora + float(pedido)
                return True
            except StopIteration:
                self.app.quit()
            except Exception:  # noqa: BLE001 (fica no relatório)
                self.erro = traceback.format_exc()
                for w in Gtk.Window.list_toplevels():
                    if isinstance(w, Gtk.Dialog):
                        w.response(Gtk.ResponseType.CANCEL)
                self.app.quit()
            return False

        def captura(self, nome: str, janela: Gtk.Window | None = None) -> None:
            janela = janela or self.app.win
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            gdkwin = janela.get_window()
            pixbuf = Gdk.pixbuf_get_from_window(gdkwin, 0, 0, gdkwin.get_width(), gdkwin.get_height())
            destino = saida / f"{nome}.png"
            pixbuf.savev(str(destino), "png", [], [])
            self.feitas.append(destino.name)
            print(f"{destino.name}  ({pixbuf.get_width()}×{pixbuf.get_height()})", flush=True)

        def focar(self, janela: Gtk.Window) -> None:
            janela.get_window().focus(Gdk.CURRENT_TIME)

        # ------------------------------------------------------------------ o percurso
        def passos(self):
            win = self.app.win
            home, analise, plano = win.home_page, win.analysis_page, win.plan_page
            dup, hist = win.duplicates_page, win.history_page
            # O ponteiro fica num canto do ecrã, fora da janela, para não aparecerem dicas.
            seat = Gdk.Display.get_default().get_default_seat()
            seat.get_pointer().warp(win.get_screen(), 1, 1)
            yield lambda: win.get_window() is not None and win.get_mapped()
            self.focar(win)
            yield lambda: win.ai_status is not None and win.is_active()
            yield 1.0

            # Início, sem nada selecionado; os estados vazios do Plano e do Histórico.
            adj = home.get_vadjustment()
            if adj.get_upper() > adj.get_page_size():
                print(f"Aviso: o Início só cabe inteiro com mais {adj.get_upper() - adj.get_page_size():.0f} píxeis "
                      "de altura (ALTURA).", file=sys.stderr)
            self.captura("01-inicio")
            win.navigate("plan")
            yield 0.6
            self.captura("13-plano-vazio")
            win.navigate("history")
            yield 0.6
            self.captura("14-historico-vazio")
            win.navigate("home")
            yield 0.6

            # O seletor de pastas de «Outras pastas…», com Transferências escolhida.
            depois(botao(home, "Outras pastas…").clicked)
            yield lambda: dialogo(Gtk.FileChooserDialog) is not None
            seletor = dialogo(Gtk.FileChooserDialog)
            seletor.resize(880, 660)
            yield 1.0
            seletor.select_filename(str(casa / "Transferências"))
            yield 1.0
            self.captura("02-escolher-pastas", seletor)
            seletor.response(Gtk.ResponseType.CANCEL)
            yield lambda: dialogo(Gtk.FileChooserDialog) is None

            # Uma pasta do sistema não se pode escolher.
            depois(lambda: win.start_scan(["/etc"]))
            yield lambda: dialogo(Gtk.MessageDialog) is not None
            yield 0.8
            self.captura("12-pasta-protegida", dialogo(Gtk.MessageDialog))
            dialogo(Gtk.MessageDialog).response(Gtk.ResponseType.OK)
            yield lambda: dialogo(Gtk.MessageDialog) is None
            self.focar(win)
            yield lambda: win.is_active()

            # Um clique num cartão seleciona-o; «Todo o computador» exclui as outras pastas.
            botao(home, "Transferências").clicked()
            yield 0.6
            self.captura("01b-inicio-selecao")
            botao(home, "Todo o computador").clicked()
            yield 0.6
            self.captura("01c-inicio-todo-o-computador")
            botao(home, "Transferências").clicked()
            yield 0.6

            # Analisar.
            home.start_btn.clicked()
            yield lambda: analise.get_visible_child_name() == "content"
            yield 1.0
            self.captura("03-analise")
            adj = analise.scroller.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            yield 0.8
            self.captura("03b-analise-pronto")

            # Duplicados: procurar, rever e enviar as cópias para o Lixo.
            win.navigate("duplicates")
            yield 0.8
            self.captura("08a-duplicados-procurar")
            botao(dup.intro, "Procurar duplicados").clicked()
            yield lambda: dup.get_visible_child_name() == "content"
            yield 1.0
            self.captura("08-duplicados")
            depois(dup.trash_btn.clicked)
            yield lambda: dialogo(Gtk.MessageDialog) is not None
            yield 0.8
            self.captura("08b-duplicados-confirmar", dialogo(Gtk.MessageDialog))
            dialogo(Gtk.MessageDialog).response(Gtk.ResponseType.OK)
            yield lambda: dialogo(Gtk.MessageDialog) is None and dup.get_visible_child_name() == "none"
            self.focar(win)
            yield 1.0
            self.captura("08c-duplicados-enviados")

            # Criar o plano (nas pastas pessoais, a opção recomendada para Transferências).
            win.navigate("analysis")
            yield 0.6
            botao(analise, "Criar plano de organização").clicked()
            yield lambda: plano.get_visible_child_name() == "content" and not win.toast.get_child_revealed()
            yield 1.0
            self.captura("04-plano")

            # Rever um documento de nome vago: o painel de detalhes à direita.
            acao = next(a for a in plano.plan.actions if a.src_name == "scan_001.pdf")
            tv, store = plano.trees["after"]
            caminho = self._caminho(store, acao.id)
            tv.expand_to_path(caminho)
            tv.set_cursor(caminho, None, False)
            tv.scroll_to_cell(caminho, None, True, 0.3, 0)
            tv.grab_focus()
            yield 1.0
            self.captura("05-plano-detalhe")
            adj = plano.detail_scroll.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            yield 0.8
            self.captura("05a-plano-detalhe-fim")

            # F2: mudar o nome proposto, escrevendo um nome que diz o que o documento é.
            evento = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
            evento.key.keyval = Gdk.KEY_F2
            evento.key.window = tv.get_window()
            depois(lambda: tv.event(evento))
            yield lambda: dialogo(Gtk.Dialog) is not None
            pedido = dialogo(Gtk.Dialog)
            caixa = next(w for w in descendentes(pedido) if isinstance(w, Gtk.Entry))
            caixa.set_text("Fatura da luz março 2025.pdf")
            caixa.set_position(-1)
            yield 0.8
            self.captura("05b-mudar-nome", pedido)
            pedido.response(Gtk.ResponseType.OK)
            yield lambda: dialogo(Gtk.Dialog) is None
            self.focar(win)
            yield 1.0
            self.captura("05c-plano-nome-mudado")

            # Uma pasta sugerida: mudar-lhe o nome ou mudá-la para outro sítio.
            caminho = self._caminho(store, -1, "Faturas e Recibos")
            tv.set_cursor(caminho, None, False)
            tv.scroll_to_cell(caminho, None, True, 0.3, 0)
            yield 1.0
            self.captura("05d-plano-pasta")

            # A árvore «Antes» (onde os ficheiros estão agora), com uma pasta que vai inteira.
            plano.views.set_visible_child_name("before")
            yield 0.6
            tv_antes, store_antes = plano.trees["before"]
            album = next(a for a in plano.plan.actions if a.src_name == "Férias Algarve")
            tv_antes.set_cursor(self._caminho(store_antes, album.id), None, False)
            yield 1.0
            self.captura("05e-plano-antes")
            plano.views.set_visible_child_name("after")
            yield 0.6

            # Aplicar: a confirmação e o fim da arrumação.
            depois(plano.apply_btn.clicked)
            yield lambda: dialogo(Gtk.MessageDialog) is not None
            yield 0.8
            self.captura("06-confirmar", dialogo(Gtk.MessageDialog))
            dialogo(Gtk.MessageDialog).response(Gtk.ResponseType.OK)
            yield lambda: dialogo(Gtk.MessageDialog) is None and plano.get_visible_child_name() == "done"
            self.focar(win)
            yield 1.0
            self.captura("06b-arrumado")

            # Histórico, com as duas operações e o botão Anular.
            win.navigate("history")
            yield lambda: not win.toast.get_child_revealed()
            yield 0.5
            self.captura("07-historico")

            # Definições (o princípio e o fim da página).
            win.navigate("settings")
            yield 1.0
            self.captura("09-definicoes")
            adj = win.settings_page.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            yield 0.8
            self.captura("09b-definicoes-fim")
            adj.set_value(0)

            # Acerca.
            win.show_about()
            yield lambda: dialogo(Gtk.AboutDialog) is not None
            yield 1.2
            acerca = dialogo(Gtk.AboutDialog)
            self.captura("10-acerca", acerca)
            acerca.destroy()
            yield lambda: dialogo(Gtk.AboutDialog) is None

            # Como ativar a IA local (botão do cartão da IA no Início).
            win.navigate("home")
            yield 0.6
            depois(home.ai_btn.clicked)
            yield lambda: dialogo(Gtk.Dialog) is not None
            yield 1.0
            self.captura("11-ia-como-ativar", dialogo(Gtk.Dialog))
            dialogo(Gtk.Dialog).response(Gtk.ResponseType.CLOSE)
            yield lambda: dialogo(Gtk.Dialog) is None
            self.focar(win)

            # Anular a arrumação no Histórico.
            win.navigate("history")
            yield 0.8
            linha = next(r for r in hist.list.get_children() if any(t.startswith("Arrumação") for t in textos(r)))
            botao(linha, "Anular").clicked()
            yield lambda: any("Anulada" in textos(r) for r in hist.list.get_children()) and \
                analise.get_visible_child_name() == "content"
            win.navigate("history")
            yield 1.0
            self.captura("07b-historico-anulada")

        @staticmethod
        def _caminho(store, aid: int, pasta: str = ""):
            """Linha de uma alteração do plano (pelo número) ou de uma pasta (aid -1, pelo nome)."""
            def procura(it):
                while it is not None:
                    if store.get_value(it, 4) == aid and (  # COL_ID
                            not pasta or store.get_value(it, 5).split("\x1f")[-1] == pasta):  # COL_KEY
                        return store.get_path(it)
                    achado = procura(store.iter_children(it))
                    if achado is not None:
                        return achado
                    it = store.iter_next(it)
                return None
            return procura(store.get_iter_first())

    class AppCapturas(ArrumaApp):
        def __init__(self):
            super().__init__()
            # Sem D-Bus de sessão (Xvfb): cada arranque abre a sua janela.
            self.set_flags(self.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
            self.guiao = Guiao(self)

        def do_activate(self) -> None:
            primeira = self.win is None
            ArrumaApp.do_activate(self)
            if primeira:
                self.win.resize(LARGURA, ALTURA)
                Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
                self.guiao.comecar()

    app = AppCapturas()
    app.run([sys.argv[0]])
    if app.guiao.erro:
        print(app.guiao.erro, file=sys.stderr)
        return 1
    print(f"{len(app.guiao.feitas)} capturas em {saida}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--casa", required=True, type=Path,
                        help="pasta pessoal de exemplo (vazia ou nova); é preenchida com ficheiros fictícios")
    parser.add_argument("--imagens", type=Path, default=Path(__file__).resolve().parent / "imagens",
                        help="onde guardar as capturas (PNG)")
    args = parser.parse_args()

    if not os.environ.get("DISPLAY"):
        if not shutil.which("xvfb-run"):
            sys.exit("Sem ecrã e sem o xvfb-run (sudo apt install xvfb).")
        os.environ["ARRUMA_CAPTURAS_XVFB"] = "1"
        os.execvp("xvfb-run", ["xvfb-run", "-a", "-s", f"-screen 0 {TAMANHO_ECRA}", sys.executable,
                               os.path.abspath(__file__), *sys.argv[1:]])

    casa = args.casa.resolve()
    if casa == Path.home().resolve() or (casa.exists() and any(casa.iterdir())):
        sys.exit(f"A pasta {casa} tem de estar vazia: é usada como pasta pessoal de exemplo.")
    casa.mkdir(parents=True, exist_ok=True)
    preparar_casa(casa)

    # A partir daqui, o Arruma (e o GTK) veem a pasta de exemplo como pasta pessoal.
    os.environ["HOME"] = str(casa)
    os.environ["USER"] = os.environ["LOGNAME"] = casa.name
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "GTK_THEME"):
        os.environ.pop(var, None)
    os.environ["GDK_BACKEND"] = "x11"  # Gdk.pixbuf_get_from_window só funciona no X11
    os.environ["GSETTINGS_BACKEND"] = "memory"  # o seletor de ficheiros não grava nada no dconf
    if not os.environ.get("LANG", "").startswith("pt"):
        print("Aviso: o sistema não está em português; os botões do GTK podem sair noutra língua.",
              file=sys.stderr)
    args.imagens.mkdir(parents=True, exist_ok=True)

    compositor = None
    if os.environ.pop("ARRUMA_CAPTURAS_XVFB", None):
        # No Xvfb não há gestor de janelas: sem isto, os diálogos não teriam barra de título.
        if shutil.which("xcompmgr"):
            compositor = subprocess.Popen(["xcompmgr"], stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            _x11 = anunciar_molduras()  # a ligação ao X tem de ficar aberta até ao fim
            os.environ["GTK_CSD"] = "1"
        else:
            print("Aviso: sem o xcompmgr, os diálogos ficam sem barra de título (sudo apt install xcompmgr).",
                  file=sys.stderr)
    try:
        return correr(casa, args.imagens.resolve())
    finally:
        if compositor:
            compositor.terminate()


if __name__ == "__main__":
    sys.exit(main())
