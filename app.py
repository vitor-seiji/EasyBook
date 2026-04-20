import os
import asyncio
import threading
import pathlib
import customtkinter as ctk
from tkinter import messagebox
import tkinter as tk
import sys

from config import *
from kindle import (Base, Ebook, engine, Session, salvar_no_banco,
                    enviar_para_kindle, converter_para_mobi,
                    marcar_como_enviado, FORMATOS_ACEITOS)

# ─── TEMA ─────────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C = {
    "bg":           "#0d0d0f",
    "surface":      "#131318",
    "surface2":     "#1a1a24",
    "border":       "#2a2a3a",
    "accent":       "#7c6af7",
    "accent2":      "#a78bfa",
    "accent_hover": "#6d5ce8",
    "accent_soft":  "#2a2440",
    "danger":       "#f43f5e",
    "danger_hover": "#e11d48",
    "success":      "#10b981",
    "warning":      "#f59e0b",
    "text":         "#f0eeff",
    "text2":        "#9d9db8",
    "text3":        "#5a5a78",
}

FONT_TITLE = ("Georgia", 22, "bold")
FONT_HEAD  = ("Georgia", 15, "bold")
FONT_BODY  = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 10)
FONT_MONO  = ("Consolas", 11)
FONT_LABEL = ("Segoe UI", 11)

# ─── WIDGETS CUSTOMIZADOS ─────────────────────────────────────────────────────

class Divider(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, height=1, fg_color=C["border"], **kwargs)
        self.pack(fill="x", padx=0, pady=8)

class Badge(ctk.CTkLabel):
    def __init__(self, parent, text, color, **kwargs):
        super().__init__(
            parent, text=text,
            fg_color="#2a2440",
            text_color=color,
            corner_radius=6,
            font=("Segoe UI", 10, "bold"),
            padx=8, pady=2, **kwargs
        )

# ─── GERENCIADOR DO TELEGRAM (singleton) ─────────────────────────────────────

class TelegramManager:
    """Cliente Telegram único que fica vivo durante toda a execução do app."""

    def __init__(self):
        self._client = None
        self._loop   = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._rodar_loop, daemon=True)
        self._thread.start()

    def _rodar_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def conectar(self, callback_ok, callback_erro):
        async def _conectar():
            from telethon import TelegramClient
            try:
                if getattr(sys, 'frozen', False):
                    base_dir = pathlib.Path(sys.executable).parent
                else:
                    base_dir = pathlib.Path(__file__).parent

                sessao = str(base_dir / "sessao_kindle")
                self._client = TelegramClient(sessao, TELEGRAM_API_ID, TELEGRAM_API_HASH)
                await self._client.connect()
                callback_ok()
            except Exception as e:
                callback_erro(str(e))
        self._run(_conectar())

    def buscar(self, termo, callback_resultado, callback_fim):
        async def _buscar():
            if not self._client or not self._client.is_connected():
                await self._client.connect()

            resultados = []
            for canal in CANAIS:
                callback_resultado(f"▦ Verificando @{canal}...")
                try:
                    async for msg in self._client.iter_messages(canal, limit=500, search=termo):
                        if not msg.document:
                            continue
                        nome = next(
                            (a.file_name for a in msg.document.attributes if hasattr(a, "file_name")), None
                        )
                        if not nome:
                            continue
                        ext = os.path.splitext(nome)[1].lower()
                        if ext not in FORMATOS_ACEITOS:
                            continue
                        titulo = os.path.splitext(nome)[0]
                        item = {"titulo": titulo, "extensao": ext, "nome_arquivo": nome, "mensagem": msg}
                        resultados.append(item)
                        callback_resultado(f"  [{len(resultados)}] {titulo} ({ext.upper()}) — @{canal}")
                except Exception as e:
                    callback_resultado(f"  ⚠ Erro em @{canal}: {e}")

            callback_fim(resultados)

        self._run(_buscar())

    def baixar(self, item, callback_ok, callback_erro):
        async def _baixar():
            try:
                caminho = os.path.join(PASTA_EBOOKS, item["nome_arquivo"])
                await self._client.download_media(item["mensagem"], file=caminho)
                salvar_no_banco(item["titulo"], caminho, item["extensao"])
                callback_ok(item["titulo"])
            except Exception as e:
                callback_erro(str(e))
        self._run(_baixar())


# ─── APP ──────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Kindle Library")
        self.geometry("1180x720")
        self.minsize(960, 620)
        self.configure(fg_color=C["bg"])
        self.resultados_busca = []
        self._telegram = TelegramManager()
        self._telegram.conectar(
            callback_ok=lambda: None,
            callback_erro=lambda e: print(f"Erro ao conectar Telegram: {e}")
        )
        self._build_ui()
        self._nav("biblioteca")

    # ── LAYOUT BASE ───────────────────────────────────────────────────────────

    def _build_ui(self):
        self.sidebar = ctk.CTkFrame(self, width=240, fg_color=C["surface"], corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        ctk.CTkFrame(self.sidebar, width=1, fg_color=C["border"]).pack(side="right", fill="y")

        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", padx=24, pady=(32, 28))
        ctk.CTkLabel(logo_frame, text="◈", font=("Georgia", 28), text_color=C["accent"]).pack(side="left")
        ctk.CTkLabel(
            logo_frame, text=" Kindle\nLibrary",
            font=("Georgia", 15, "bold"), text_color=C["text"], justify="left"
        ).pack(side="left", padx=(6, 0))

        Divider(self.sidebar)

        self._nav_btns = {}
        itens = [
            ("biblioteca", "  Biblioteca",        "▦"),
            ("busca",      "  Buscar Canais",      "◎"),
            ("enviar",     "  Enviar ao Kindle",   "▶"),
            ("config",     "  Configurações",      "◈"),
        ]
        for chave, texto, icone in itens:
            btn = ctk.CTkButton(
                self.sidebar, text=icone + texto, anchor="w",
                fg_color="transparent", hover_color=C["surface2"],
                text_color=C["text2"], font=("Segoe UI", 13),
                height=44, corner_radius=10,
                command=lambda c=chave: self._nav(c)
            )
            btn.pack(fill="x", padx=12, pady=2)
            self._nav_btns[chave] = btn

        ctk.CTkLabel(
            self.sidebar, text="v1.0", font=FONT_SMALL, text_color=C["text3"]
        ).pack(side="bottom", pady=16)

        self.main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        self.main.pack(side="right", fill="both", expand=True)

    def _nav(self, chave):
        for w in self.main.winfo_children():
            w.destroy()

        # Reseta todos os atributos de tela
        self._frame_botoes_download = None
        self._frame_filtros         = None
        self.frame_livros           = None
        self.frame_enviar           = None

        for k, b in self._nav_btns.items():
            if k == chave:
                b.configure(fg_color=C["accent_soft"], text_color=C["accent2"], font=("Segoe UI", 13, "bold"))
            else:
                b.configure(fg_color="transparent", text_color=C["text2"], font=("Segoe UI", 13))

        {
            "biblioteca": self._tela_biblioteca,
            "busca":      self._tela_busca,
            "enviar":     self._tela_enviar,
            "config":     self._tela_config,
        }[chave]()

    # ── COMPONENTES ───────────────────────────────────────────────────────────

    def _header(self, titulo, subtitulo=""):
        frame = ctk.CTkFrame(self.main, fg_color="transparent")
        frame.pack(fill="x", padx=32, pady=(28, 0))
        ctk.CTkLabel(frame, text=titulo, font=FONT_TITLE, text_color=C["text"]).pack(anchor="w")
        if subtitulo:
            ctk.CTkLabel(frame, text=subtitulo, font=FONT_LABEL, text_color=C["text3"]).pack(anchor="w", pady=(2, 0))
        ctk.CTkFrame(self.main, height=1, fg_color=C["border"]).pack(fill="x", padx=32, pady=(12, 20))

    def _entry(self, parent, placeholder, **kwargs):
        return ctk.CTkEntry(
            parent, placeholder_text=placeholder, height=40, font=FONT_BODY,
            fg_color=C["surface2"], border_color=C["border"], border_width=1,
            text_color=C["text"], placeholder_text_color=C["text3"], **kwargs
        )

    def _btn_primary(self, parent, text, command, width=120):
        return ctk.CTkButton(
            parent, text=text, command=command, width=width, height=40,
            fg_color=C["accent"], hover_color=C["accent_hover"],
            text_color=C["text"], font=("Segoe UI", 12, "bold"), corner_radius=8
        )

    def _btn_ghost(self, parent, text, command, width=100):
        return ctk.CTkButton(
            parent, text=text, command=command, width=width, height=40,
            fg_color=C["surface2"], hover_color=C["border"],
            text_color=C["text2"], font=FONT_LABEL, corner_radius=8,
            border_width=1, border_color=C["border"]
        )

    def _btn_danger(self, parent, text, command, width=40):
        return ctk.CTkButton(
            parent, text=text, command=command, width=width, height=36,
            fg_color="transparent", hover_color="#3a1a24",
            text_color=C["text3"], font=FONT_LABEL, corner_radius=8,
            border_width=1, border_color=C["border"]
        )

    # ── BIBLIOTECA ────────────────────────────────────────────────────────────

    def _tela_biblioteca(self):
        self._header("Biblioteca", "Seus ebooks baixados")

        barra = ctk.CTkFrame(self.main, fg_color="transparent")
        barra.pack(fill="x", padx=32, pady=(0, 16))

        self.campo_pesquisa = self._entry(barra, "Pesquisar por título...")
        self.campo_pesquisa.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.campo_pesquisa.bind("<Return>", lambda e: self._filtrar_biblioteca())

        self._btn_primary(barra, "Buscar", self._filtrar_biblioteca, width=100).pack(side="left", padx=(0, 6))
        self._btn_ghost(barra, "Todos", self._tela_biblioteca, width=80).pack(side="left")

        self.frame_livros = ctk.CTkScrollableFrame(
            self.main, fg_color="transparent",
            scrollbar_button_color=C["surface2"],
            scrollbar_button_hover_color=C["border"]
        )
        self.frame_livros.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        self._carregar_livros()

    def _carregar_livros(self, termo=""):
        for w in self.frame_livros.winfo_children():
            w.destroy()

        session = Session()
        if termo:
            livros = session.query(Ebook).filter(Ebook.titulo.ilike(f"%{termo}%")).all()
        else:
            livros = session.query(Ebook).order_by(Ebook.data_download.desc()).all()
        session.close()

        if not livros:
            vazio = ctk.CTkFrame(self.frame_livros, fg_color=C["surface"], corner_radius=16)
            vazio.pack(fill="x", padx=8, pady=40)
            ctk.CTkLabel(vazio, text="◎", font=("Georgia", 36), text_color=C["text3"]).pack(pady=(32, 8))
            ctk.CTkLabel(vazio, text="Nenhum livro encontrado", font=("Georgia", 15), text_color=C["text2"]).pack()
            ctk.CTkLabel(
                vazio, text="Use 'Buscar Canais' para baixar ebooks",
                font=FONT_LABEL, text_color=C["text3"]
            ).pack(pady=(4, 32))
            return

        for livro in livros:
            self._card_livro(livro)

    def _card_livro(self, livro):
        fmt_colors = {
            ".epub": C["accent"], ".mobi": C["success"],
            ".pdf": C["warning"], ".azw3": C["accent2"]
        }
        fmt_cor = fmt_colors.get(livro.formato.lower(), C["text3"])

        card = ctk.CTkFrame(self.frame_livros, fg_color=C["surface"], corner_radius=14, border_width=1, border_color=C["border"])
        card.pack(fill="x", padx=8, pady=5)

        icone = ctk.CTkFrame(card, width=48, height=48, fg_color=C["surface2"], corner_radius=10)
        icone.pack(side="left", padx=(16, 12), pady=14)
        icone.pack_propagate(False)
        ctk.CTkLabel(
            icone, text=livro.formato.upper().replace(".", ""),
            font=("Segoe UI", 9, "bold"), text_color=fmt_cor
        ).place(relx=0.5, rely=0.5, anchor="center")

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, pady=14)

        ctk.CTkLabel(
            info, text=livro.titulo,
            font=("Segoe UI", 13, "bold"), text_color=C["text"],
            anchor="w", wraplength=500
        ).pack(anchor="w")

        meta = ctk.CTkFrame(info, fg_color="transparent")
        meta.pack(anchor="w", pady=(4, 0))

        status_cor = C["success"] if livro.enviado_kindle else C["warning"]
        status_txt = "Enviado" if livro.enviado_kindle else "Não enviado"
        Badge(meta, text=status_txt, color=status_cor).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            meta, text=f"Baixado em {livro.data_download.strftime('%d/%m/%Y')}",
            font=FONT_SMALL, text_color=C["text3"]
        ).pack(side="left")

        acoes = ctk.CTkFrame(card, fg_color="transparent")
        acoes.pack(side="right", padx=16)
        self._btn_primary(acoes, "▶  Kindle", lambda l=livro: self._enviar_livro(l), width=100).pack(side="left", padx=(0, 8))
        self._btn_danger(acoes, "✕", lambda l=livro: self._deletar_livro(l), width=36).pack(side="left")

    def _filtrar_biblioteca(self):
        self._carregar_livros(self.campo_pesquisa.get().strip())

    def _enviar_livro(self, livro):
        if messagebox.askyesno("Confirmar envio", f"Enviar '{livro.titulo}' para o Kindle?"):
            try:
                caminho = livro.arquivo
                if not caminho.endswith((".mobi", ".epub")):
                    caminho = converter_para_mobi(caminho)
                enviar_para_kindle(caminho)
                marcar_como_enviado(livro.id)
                messagebox.showinfo("Enviado!", "Livro enviado. Verifique seu Kindle.")
                self._nav("biblioteca")
            except Exception as e:
                messagebox.showerror("Erro ao enviar", str(e))

    def _deletar_livro(self, livro):
        if messagebox.askyesno("Confirmar exclusão", f"Deletar '{livro.titulo}'?\nO arquivo também será removido."):
            session = Session()
            obj = session.query(Ebook).filter_by(id=livro.id).first()
            if obj:
                if os.path.exists(obj.arquivo):
                    os.remove(obj.arquivo)
                session.delete(obj)
                session.commit()
            session.close()
            self._nav("biblioteca")

    # ── BUSCA ─────────────────────────────────────────────────────────────────

    def _tela_busca(self):
        self._header("Buscar nos Canais", "Pesquise ebooks diretamente nos canais do Telegram")
        self.resultados_busca = []

        form = ctk.CTkFrame(self.main, fg_color=C["surface"], corner_radius=14, border_width=1, border_color=C["border"])
        form.pack(fill="x", padx=32, pady=(0, 12))

        inner = ctk.CTkFrame(form, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=14)

        ctk.CTkLabel(inner, text="Título do livro", font=FONT_LABEL, text_color=C["text3"]).pack(anchor="w", pady=(0, 4))

        linha = ctk.CTkFrame(inner, fg_color="transparent")
        linha.pack(fill="x")

        self.campo_busca_canal = self._entry(linha, "Ex: Harry Potter, Duna, 1984...")
        self.campo_busca_canal.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.campo_busca_canal.bind("<Return>", lambda e: self._executar_busca())
        self._btn_primary(linha, "◎  Buscar", self._executar_busca, width=120).pack(side="left")

        # Log menor
        log_frame = ctk.CTkFrame(self.main, fg_color=C["surface"], corner_radius=14, border_width=1, border_color=C["border"])
        log_frame.pack(fill="x", padx=32, pady=(0, 12))

        ctk.CTkLabel(log_frame, text="Log", font=FONT_SMALL, text_color=C["text3"]).pack(anchor="w", padx=16, pady=(10, 2))

        self.log_busca = ctk.CTkTextbox(
            log_frame, height=120, fg_color="transparent",
            text_color=C["text2"], font=FONT_MONO,
            state="disabled", border_width=0
        )
        self.log_busca.pack(fill="x", padx=8, pady=(0, 8))

        # Filtros de formato
        self._frame_filtros = ctk.CTkFrame(self.main, fg_color="transparent")
        self._frame_filtros.pack(fill="x", padx=32, pady=(0, 8))

        # Resultados
        self._frame_botoes_download = ctk.CTkScrollableFrame(
            self.main, fg_color="transparent",
            scrollbar_button_color=C["surface2"],
            scrollbar_button_hover_color=C["border"]
        )
        self._frame_botoes_download.pack(fill="both", expand=True, padx=32, pady=(0, 16))

    def _log(self, texto):
        try:
            self.log_busca.configure(state="normal")
            self.log_busca.insert("end", texto + "\n")
            self.log_busca.see("end")
            self.log_busca.configure(state="disabled")
        except Exception:
            pass

    def _executar_busca(self):
        termo = self.campo_busca_canal.get().strip()
        if not termo:
            messagebox.showwarning("Atenção", "Digite um título para buscar.")
            return

        # Limpa log e botões antigos
        self.log_busca.configure(state="normal")
        self.log_busca.delete("1.0", "end")
        self.log_busca.configure(state="disabled")
        self.resultados_busca = []

        if self._frame_botoes_download:
            for w in self._frame_botoes_download.winfo_children():
                w.destroy()

        self._log(f"◎ Buscando '{termo}'...\n")

        self._telegram.buscar(
            termo=termo,
            callback_resultado=lambda txt: self.after(0, self._log, txt),
            callback_fim=lambda res: self.after(0, self._busca_concluida, res)
        )

    def _busca_concluida(self, resultados):
        self.resultados_busca = resultados
        self._log(f"\n✓ {len(resultados)} resultado(s) encontrado(s).")

        if not resultados:
            return

        # Descobre formatos disponíveis
        formatos = ["TODOS"] + sorted(set(
            i["extensao"].upper().replace(".", "") for i in resultados
        ))

        # Limpa e reconstrói filtros
        for w in self._frame_filtros.winfo_children():
            w.destroy()

        ctk.CTkLabel(
            self._frame_filtros, text="Filtrar:",
            font=FONT_LABEL, text_color=C["text3"]
        ).pack(side="left", padx=(0, 8))

        for fmt in formatos:
            fmt_colors = {"EPUB": C["accent"], "MOBI": C["success"], "PDF": C["warning"], "AZW3": C["accent2"]}
            cor = fmt_colors.get(fmt, C["text2"])
            ctk.CTkButton(
                self._frame_filtros, text=fmt, width=70, height=30,
                fg_color=C["accent"] if fmt == "TODOS" else C["surface2"],
                hover_color=C["accent_hover"],
                text_color=C["text"], font=("Segoe UI", 11, "bold"),
                corner_radius=8, border_width=1, border_color=cor,
                command=lambda f=fmt: self._aplicar_filtro(f)
            ).pack(side="left", padx=4)

        self._mostrar_botoes_download("TODOS")

    def _aplicar_filtro(self, fmt):
        # Atualiza visual dos botões de filtro
        for i, btn in enumerate(self._frame_filtros.winfo_children()):
            if isinstance(btn, ctk.CTkButton):
                btn.configure(fg_color=C["accent"] if btn.cget("text") == fmt else C["surface2"])
        self._mostrar_botoes_download(fmt)

    def _mostrar_botoes_download(self, filtro="TODOS"):
        for w in self._frame_botoes_download.winfo_children():
            w.destroy()

        fmt_colors = {
            ".epub": C["accent"], ".mobi": C["success"],
            ".pdf": C["warning"], ".azw3": C["accent2"]
        }

        itens = [
            i for i in self.resultados_busca
            if filtro == "TODOS" or i["extensao"].upper().replace(".", "") == filtro
        ]

        if not itens:
            ctk.CTkLabel(
                self._frame_botoes_download,
                text=f"Nenhum resultado em {filtro}",
                font=FONT_LABEL, text_color=C["text3"]
            ).pack(pady=20)
            return

        for item in itens:
            cor = fmt_colors.get(item["extensao"], C["text3"])
            row = ctk.CTkFrame(
                self._frame_botoes_download, fg_color=C["surface"],
                corner_radius=10, border_width=1, border_color=C["border"]
            )
            row.pack(fill="x", pady=3, padx=4)

            Badge(row, text=item["extensao"].upper().replace(".", ""), color=cor).pack(side="left", padx=12, pady=10)
            ctk.CTkLabel(
                row, text=item["titulo"],
                font=("Segoe UI", 12), text_color=C["text"], anchor="w"
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                row, text="⬇  Baixar", width=100, height=32,
                fg_color=C["accent"], hover_color=C["accent_hover"],
                text_color=C["text"], font=("Segoe UI", 11, "bold"), corner_radius=8,
                command=lambda it=item: self._baixar_item(it)
            ).pack(side="right", padx=12, pady=8)

    def _baixar_item(self, item):
        self._log(f"\n⬇ Baixando '{item['titulo']}'...")
        self._telegram.baixar(
            item=item,
            callback_ok=lambda titulo: self.after(0, self._download_ok, titulo),
            callback_erro=lambda e: self.after(0, self._download_erro, e)
        )

    def _download_ok(self, titulo):
        self._log(f"✓ '{titulo}' salvo na biblioteca!")
        messagebox.showinfo("Salvo!", f"'{titulo}' adicionado à biblioteca.")

    def _download_erro(self, erro):
        self._log(f"✕ Erro: {erro}")
        messagebox.showerror("Erro no download", erro)

    # ── ENVIAR ────────────────────────────────────────────────────────────────

    def _tela_enviar(self):
        self._header("Enviar ao Kindle", "Escolha um livro da biblioteca para enviar")

        barra = ctk.CTkFrame(self.main, fg_color="transparent")
        barra.pack(fill="x", padx=32, pady=(0, 16))

        self.campo_enviar = self._entry(barra, "Pesquisar livro...")
        self.campo_enviar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.campo_enviar.bind("<Return>", lambda e: self._filtrar_enviar())

        self._btn_primary(barra, "Buscar", self._filtrar_enviar, width=100).pack(side="left")

        self.frame_enviar = ctk.CTkScrollableFrame(
            self.main, fg_color="transparent",
            scrollbar_button_color=C["surface2"],
            scrollbar_button_hover_color=C["border"]
        )
        self.frame_enviar.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        self._carregar_enviar()

    def _carregar_enviar(self, termo=""):
        for w in self.frame_enviar.winfo_children():
            w.destroy()

        session = Session()
        if termo:
            livros = session.query(Ebook).filter(Ebook.titulo.ilike(f"%{termo}%")).all()
        else:
            livros = session.query(Ebook).order_by(Ebook.data_download.desc()).all()
        session.close()

        if not livros:
            ctk.CTkLabel(self.frame_enviar, text="Nenhum livro na biblioteca.", font=("Georgia", 14), text_color=C["text3"]).pack(pady=40)
            return

        for livro in livros:
            card = ctk.CTkFrame(self.frame_enviar, fg_color=C["surface"], corner_radius=14, border_width=1, border_color=C["border"])
            card.pack(fill="x", padx=8, pady=5)

            status_cor = C["success"] if livro.enviado_kindle else C["text3"]
            status_txt = "✓" if livro.enviado_kindle else "○"
            ctk.CTkLabel(card, text=status_txt, font=("Georgia", 18), text_color=status_cor).pack(side="left", padx=(16, 12), pady=14)
            ctk.CTkLabel(card, text=livro.titulo, font=("Segoe UI", 13, "bold"), text_color=C["text"], anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                card, text="▶  Enviar ao Kindle", width=150, height=36,
                fg_color=C["accent"], hover_color=C["accent_hover"],
                text_color=C["text"], font=("Segoe UI", 11, "bold"), corner_radius=8,
                command=lambda l=livro: self._enviar_livro(l)
            ).pack(side="right", padx=16, pady=10)

    def _filtrar_enviar(self):
        self._carregar_enviar(self.campo_enviar.get().strip())

    # ── CONFIG ────────────────────────────────────────────────────────────────

    def _tela_config(self):
        self._header("Configurações", "Gerencie credenciais e preferências")

        frame = ctk.CTkScrollableFrame(
            self.main, fg_color="transparent",
            scrollbar_button_color=C["surface2"],
            scrollbar_button_hover_color=C["border"]
        )
        frame.pack(fill="both", expand=True, padx=32, pady=(0, 16))

        campos = [
            ("Telegram API ID",   "TELEGRAM_API_ID",   str(TELEGRAM_API_ID)),
            ("Telegram API Hash", "TELEGRAM_API_HASH", TELEGRAM_API_HASH),
            ("Email remetente",   "HOTMAIL_REMETENTE", HOTMAIL_REMETENTE),
            ("Email do Kindle",   "KINDLE_EMAIL",      KINDLE_EMAIL),
            ("SendGrid API Key",  "SENDGRID_API_KEY",  SENDGRID_API_KEY),
            ("Pasta dos ebooks",  "PASTA_EBOOKS",      PASTA_EBOOKS),
        ]

        self.campos_config = {}
        card = ctk.CTkFrame(frame, fg_color=C["surface"], corner_radius=14, border_width=1, border_color=C["border"])
        card.pack(fill="x", pady=(0, 16))

        for i, (label, chave, valor) in enumerate(campos):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=(14 if i == 0 else 4, 4 if i < len(campos)-1 else 14))

            ctk.CTkLabel(row, text=label, font=FONT_LABEL, text_color=C["text3"], width=160, anchor="w").pack(side="left")

            entry = ctk.CTkEntry(
                row, height=36, font=FONT_BODY,
                fg_color=C["surface2"], border_color=C["border"], border_width=1,
                text_color=C["text"],
                show="*" if "key" in chave.lower() or "hash" in chave.lower() else ""
            )
            entry.insert(0, valor)
            entry.pack(side="left", fill="x", expand=True)
            self.campos_config[chave] = entry

            if i < len(campos) - 1:
                ctk.CTkFrame(card, height=1, fg_color=C["border"]).pack(fill="x", padx=20)

        card2 = ctk.CTkFrame(frame, fg_color=C["surface"], corner_radius=14, border_width=1, border_color=C["border"])
        card2.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(card2, text="Canais monitorados", font=FONT_LABEL, text_color=C["text3"]).pack(anchor="w", padx=20, pady=(14, 2))
        ctk.CTkLabel(card2, text="Um canal por linha, sem o @", font=FONT_SMALL, text_color=C["text3"]).pack(anchor="w", padx=20)

        self.campo_canais = ctk.CTkTextbox(
            card2, height=130, font=FONT_MONO,
            fg_color=C["surface2"], text_color=C["text"],
            border_width=1, border_color=C["border"]
        )
        self.campo_canais.insert("1.0", "\n".join(CANAIS))
        self.campo_canais.pack(fill="x", padx=20, pady=(8, 16))

        self._btn_primary(frame, "  Salvar configurações", self._salvar_config, width=200).pack(anchor="w")

    def _salvar_config(self):
        canais = [c.strip() for c in self.campo_canais.get("1.0", "end").splitlines() if c.strip()]
        linhas = [
            f'TELEGRAM_API_ID   = {self.campos_config["TELEGRAM_API_ID"].get()}',
            f'TELEGRAM_API_HASH = "{self.campos_config["TELEGRAM_API_HASH"].get()}"',
            f'CANAIS = {canais}',
            f'HOTMAIL_REMETENTE = "{self.campos_config["HOTMAIL_REMETENTE"].get()}"',
            f'KINDLE_EMAIL      = "{self.campos_config["KINDLE_EMAIL"].get()}"',
            f'SENDGRID_API_KEY  = "{self.campos_config["SENDGRID_API_KEY"].get()}"',
            f'PASTA_EBOOKS      = "{self.campos_config["PASTA_EBOOKS"].get()}"',
        ]
        base_dir = pathlib.Path(__file__).parent
        with open(base_dir / "config.py", "w", encoding="utf-8") as f:
            f.write("\n".join(linhas))
        messagebox.showinfo("Salvo!", "Configurações salvas. Reinicie o app para aplicar.")

# ─── INÍCIO ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(PASTA_EBOOKS, exist_ok=True)
    app = App()
    app.mainloop()