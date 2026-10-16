"""Página de análise: resumo da pasta, gráfico por tipo, observações e escolha do destino."""

from __future__ import annotations

import os
import time

from gi.repository import Gtk

from ..core import taxonomy as tx
from ..core.fsutil import (COMPUTER_TOKEN, display_path, human_count, human_size, is_unclear_name,
                           plural, split_ext, xdg_user_dirs)
from ..core.planner import MODE_INSIDE, MODE_PERSONAL, default_mode
from ..core.scanner import ScanResult, is_home
from .widgets import (DonutChart, Placeholder, ProgressPanel, StatCard, add_classes, button, card,
                      esc, hbox, icon, kind_color, kind_icon, kind_label, label, show_in_folder, vbox)


class AnalysisPage(Gtk.Stack):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.scan: ScanResult | None = None

        self.add_named(Placeholder("folder-symbolic", "Ainda não analisaste nenhuma pasta",
                                   "Escolhe uma ou mais pastas no Início para veres o que lá está.",
                                   ("Ir para o Início", lambda: win.navigate("home"))), "empty")
        self.progress = ProgressPanel(on_cancel=win.cancel_task)
        self.add_named(self.progress, "progress")

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.add_named(self.scroller, "content")
        self.set_visible_child_name("empty")

    # ------------------------------------------------------------------ progresso
    def show_progress(self, title: str) -> None:
        self.progress.start(f"A analisar «{title}»",
                            "Só leitura: nenhum ficheiro é alterado nesta fase.")
        self.set_visible_child_name("progress")

    def update_progress(self, count: int, current: str) -> None:
        self.progress.update(display_path(current), None, f"{plural(count, 'ficheiro encontrado', 'ficheiros encontrados')}")

    # ------------------------------------------------------------------ resultado
    def show_result(self, scan: ScanResult) -> None:
        self.progress.stop()
        self.scan = scan
        child = self.scroller.get_child()
        if child:
            self.scroller.remove(child)
        self.scroller.add(self._build(scan))
        self.scroller.show_all()
        self.set_visible_child_name("content")

    def _build(self, scan: ScanResult) -> Gtk.Widget:
        root_set = set(scan.roots)
        page = vbox(18, margin_top=28, margin_bottom=32, margin_start=32, margin_end=32)

        # Cabeçalho
        head = hbox(14)
        head.pack_start(icon("computer" if scan.whole_computer else "folder", 48), False, False, 0)
        titles = vbox(2)
        titles.set_valign(Gtk.Align.CENTER)
        titles.pack_start(label(scan.title, "page-title"), False, False, 0)
        titles.pack_start(label(scan.subtitle, "dim", selectable=True, wrap=True), False, False, 0)
        head.pack_start(titles, True, True, 0)
        rescan_target = COMPUTER_TOKEN if scan.whole_computer else list(scan.roots)
        again = button("Analisar novamente", "view-refresh-symbolic",
                       on_click=lambda: self.win.start_scan(rescan_target))
        again.set_valign(Gtk.Align.CENTER)
        head.pack_end(again, False, False, 0)
        page.pack_start(head, False, False, 0)

        # Números
        n_folders = sum(1 for f in scan.folders.values() if f.path not in root_set and not f.protected)
        insights = self._insights(scan)
        attention = sum(n for _, _, n, sev in insights if sev == "warn")
        stats = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        stats.attach(StatCard("text-x-generic-symbolic", human_count(len(scan.files)), "ficheiros"), 0, 0, 1, 1)
        stats.attach(StatCard("drive-harddisk-symbolic", human_size(scan.total_size), "espaço ocupado"), 1, 0, 1, 1)
        stats.attach(StatCard("folder-symbolic", human_count(n_folders), "subpastas"), 2, 0, 1, 1)
        stats.attach(StatCard("dialog-warning-symbolic", human_count(attention), "a precisar de atenção"), 3, 0, 1, 1)
        page.pack_start(stats, False, False, 0)

        # Gráfico + observações
        row = hbox(16)
        types = card(spacing=14)
        types.pack_start(label("Tipos de ficheiro", "section-title"), False, False, 0)
        inner = hbox(22)
        chart = DonutChart(190)
        kinds = [k for k in tx.KIND_ORDER if k in scan.by_kind]
        chart.set_data([(kind_label(k), scan.by_kind[k][1] or 1, kind_color(k)) for k in kinds],
                       human_size(scan.total_size), "no total")
        chart.set_valign(Gtk.Align.CENTER)
        inner.pack_start(chart, False, False, 0)
        legend = Gtk.Grid(column_spacing=12, row_spacing=7)
        legend.set_valign(Gtk.Align.CENTER)
        for i, k in enumerate(sorted(kinds, key=lambda k: -scan.by_kind[k][1])):
            count, size = scan.by_kind[k]
            dot = label(" ", "legend-dot")
            dot.set_size_request(10, 10)
            dot.set_valign(Gtk.Align.CENTER)
            dot.override_background_color(Gtk.StateFlags.NORMAL, self._rgba(kind_color(k)))
            legend.attach(dot, 0, i, 1, 1)
            legend.attach(label(kind_label(k)), 1, i, 1, 1)
            legend.attach(label(human_count(count), "dim", xalign=1), 2, i, 1, 1)
            legend.attach(label(human_size(size), "dim", xalign=1), 3, i, 1, 1)
        inner.pack_start(legend, True, True, 0)
        types.pack_start(inner, True, True, 0)
        row.pack_start(types, True, True, 0)

        obs = card(spacing=10)
        obs.pack_start(label("Observações", "section-title"), False, False, 0)
        if not insights:
            obs.pack_start(label("Tudo parece em ordem. 👍", "dim"), False, False, 0)
        for ico, text, _n, sev in insights[:8]:
            r = hbox(10)
            i = icon(ico, 16, "insight-icon", sev)
            i.set_valign(Gtk.Align.START)
            r.pack_start(i, False, False, 0)
            r.pack_start(label(text, wrap=True, max_width=46, markup=True), True, True, 0)
            obs.pack_start(r, False, False, 0)
        row.pack_start(obs, True, True, 0)
        page.pack_start(row, False, False, 0)

        # Maiores ficheiros
        big = sorted(scan.files, key=lambda f: f.size, reverse=True)[:6]
        if big:
            bc = card(spacing=4)
            bc.pack_start(label("Maiores ficheiros", "section-title"), False, False, 6)
            for f in big:
                r = hbox(12, margin_top=4, margin_bottom=4)
                r.pack_start(icon(kind_icon(f.kind), 24), False, False, 0)
                col = vbox(0)
                col.pack_start(label(f.name, ellipsize=True), False, False, 0)
                col.pack_start(label(display_path(f.parent), "small", "dim", ellipsize=True), False, False, 0)
                r.pack_start(col, True, True, 0)
                r.pack_start(label(human_size(f.size), "dim"), False, False, 0)
                show = button("", "folder-open-symbolic", "flat", on_click=lambda p=f.path: show_in_folder(p),
                              tooltip="Mostrar na pasta")
                r.pack_start(show, False, False, 0)
                bc.pack_start(r, False, False, 0)
            page.pack_start(bc, False, False, 0)

        page.pack_start(self._cta(scan), False, False, 0)
        return page

    def _rgba(self, color: str):
        from gi.repository import Gdk
        rgba = Gdk.RGBA()
        rgba.parse(color)
        return rgba

    def _insights(self, scan: ScanResult) -> list[tuple[str, str, int, str]]:
        out: list[tuple[str, str, int, str]] = []
        root_set = set(scan.roots)
        loose = sum(1 for f in scan.files if f.parent in root_set)
        if loose > 15:
            where = "nas pastas analisadas" if len(root_set) > 1 else "na pasta"
            out.append(("view-grid-symbolic", f"<b>{human_count(loose)}</b> ficheiros soltos diretamente {where}.",
                        loose, "warn"))
        unclear = sum(1 for f in scan.files if f.kind in (tx.DOCUMENT,) and is_unclear_name(split_ext(f.name)[0]))
        if unclear:
            out.append(("dialog-question-symbolic",
                        f"<b>{human_count(unclear)}</b> documentos com nomes pouco claros (ex.: «scan_003.pdf»).",
                        unclear, "warn"))
        junk = scan.by_kind.get(tx.JUNK, (0, 0))
        if junk[0]:
            out.append(("user-trash-symbolic", f"<b>{human_count(junk[0])}</b> ficheiros temporários ou incompletos "
                        f"({human_size(junk[1])}).", junk[0], "warn"))
        empty = sum(1 for f in scan.folders.values() if f.empty and f.path not in root_set)
        if empty:
            out.append(("folder-symbolic", f"<b>{human_count(empty)}</b> pastas vazias.", empty, "warn"))
        inst = scan.by_kind.get(tx.INSTALLER, (0, 0))
        arch = scan.by_kind.get(tx.ARCHIVE, (0, 0))
        if inst[0] + arch[0] >= 3:
            out.append(("package-x-generic-symbolic",
                        f"<b>{human_count(inst[0] + arch[0])}</b> instaladores e arquivos comprimidos "
                        f"({human_size(inst[1] + arch[1])}) que talvez já não sejam precisos.",
                        inst[0] + arch[0], "info"))
        year_ago = time.time() - 365 * 86400
        xdg = xdg_user_dirs()
        dl_dir = str(xdg["DOWNLOAD"])
        if dl_dir in root_set or scan.whole_computer:
            old = sum(1 for f in scan.files if f.mtime < year_ago and f.path.startswith(dl_dir + os.sep))
            if old:
                out.append(("document-open-recent-symbolic",
                            f"<b>{human_count(old)}</b> transferências com mais de um ano.", old, "info"))
        huge = sum(1 for f in scan.files if f.size > 1024 ** 3)
        if huge:
            out.append(("drive-harddisk-symbolic", f"<b>{human_count(huge)}</b> ficheiros com mais de 1 GB.", huge, "info"))
        if scan.protected:
            names = ", ".join(f"«{esc(os.path.basename(p))}»" for p, _ in scan.protected[:3])
            more = f" e mais {len(scan.protected) - 3}" if len(scan.protected) > 3 else ""
            out.append(("security-high-symbolic",
                        f"<b>{len(scan.protected)}</b> pastas protegidas que não vão ser alteradas: {names}{more} "
                        "(projetos, bibliotecas de programas, pastas sincronizadas).", len(scan.protected), "ok"))
        if scan.skipped_hidden:
            out.append(("view-paged-symbolic", f"{human_count(scan.skipped_hidden)} itens ocultos ignorados.",
                        scan.skipped_hidden, "info"))
        if scan.errors:
            out.append(("dialog-warning-symbolic", f"{human_count(len(scan.errors))} itens não puderam ser lidos "
                        "(sem permissão).", len(scan.errors), "info"))
        return out

    def _cta(self, scan: ScanResult) -> Gtk.Widget:
        root = scan.root
        name = os.path.basename(root) or root
        cta = card("accent", spacing=14)
        cta.pack_start(label("Pronto para arrumar?", "section-title"), False, False, 0)
        cta.pack_start(label("Primeiro vais ver um plano com todas as mudanças propostas. Podes mudar nomes de pastas, "
                             "arrastar ficheiros e ajustar tudo antes de carregares em «Aplicar».",
                             "dim", wrap=True), False, False, 0)

        mode = default_mode(scan)
        if scan.whole_computer:
            r1 = Gtk.RadioButton.new_with_label(None, "Dentro de cada pasta ou disco analisado")
            r2 = Gtk.RadioButton.new_with_label_from_widget(
                r1, "Nas pastas pessoais (Documentos, Imagens, Vídeos, Música…) e em cada disco externo")
            d1 = label("Em cada disco ou pasta principal, organiza os ficheiros dentro de subpastas próprias.",
                       "small", "dim", wrap=True, margin_start=26)
            d2 = label("Recomendado para todo o computador: organiza a tua Pasta Pessoal nas pastas Documentos, "
                       "Imagens, Vídeos e Música, e mantém os discos externos organizados dentro de si próprios.",
                       "small", "dim", wrap=True, margin_start=26)
            r1.set_sensitive(False)
        elif len(scan.roots) > 1:
            r1 = Gtk.RadioButton.new_with_label(None, f"Dentro de cada uma das {len(scan.roots)} pastas escolhidas")
            r2 = Gtk.RadioButton.new_with_label_from_widget(
                r1, "Nas pastas pessoais (Documentos, Imagens, Vídeos, Música…)")
            d1 = label("Cada pasta escolhida fica organizada dentro de si própria (ex.: «Pasta/Documentos/Finanças»).",
                       "small", "dim", wrap=True, margin_start=26)
            d2 = label("Junta e organiza os ficheiros de todas as pastas selecionadas nas tuas pastas pessoais.",
                       "small", "dim", wrap=True, margin_start=26)
            if any(is_home(rt) for rt in scan.roots):
                r1.set_sensitive(False)
                d1.set_text("Não disponível quando a Pasta Pessoal faz parte da seleção.")
        else:
            r1 = Gtk.RadioButton.new_with_label(None, f"Dentro de «{name}»")
            r2 = Gtk.RadioButton.new_with_label_from_widget(
                r1, "Nas pastas pessoais (Documentos, Imagens, Vídeos, Música…)")
            d1 = label(f"Cria subpastas como «{name}/Documentos/Finanças» ou «{name}/Imagens/Fotografias/2024».",
                       "small", "dim", wrap=True, margin_start=26)
            d2 = label("Recomendado para Transferências e Secretária: cada ficheiro vai para a pasta pessoal certa "
                       "(ex.: «Documentos/Saúde», «Imagens/Fotografias/2024»).", "small", "dim", wrap=True, margin_start=26)
            if is_home(root):
                r1.set_sensitive(False)
                d1.set_text("Não disponível para a pasta pessoal.")
        (r2 if mode == MODE_PERSONAL else r1).set_active(True)
        for w in (r1, d1, r2, d2):
            cta.pack_start(w, False, False, 0)

        go = button("Criar plano de organização", "emblem-ok-symbolic", "suggested-action", "big-button")
        go.set_halign(Gtk.Align.START)
        go.set_margin_top(6)
        go.connect("clicked", lambda *_: self.win.build_plan(MODE_PERSONAL if r2.get_active() else MODE_INSIDE))
        cta.pack_start(go, False, False, 0)
        return cta

