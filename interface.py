"""Interface CustomTkinter: Design Moderno Dark Studio com Bordas Arredondadas."""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog, messagebox

from conversao_gui import ConversaoCancelada, converter, normalizar_nome, validar_pasta

# Configurações do Tema
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# Paleta Estúdio Premium
COLOR_BG = "#0f1015"        # Fundo Principal
COLOR_CARD = "#181a20"      # Cartões em Alto Relevo
COLOR_CARD_BORDER = "#262933" # Borda sutil dos cartões
COLOR_INPUT = "#21242d"     # Campos de entrada
COLOR_CYAN = "#38bdf8"      # Acento Ciano / LEDs
COLOR_GREEN = "#10b981"     # Botão Ação (Verde Neon)
COLOR_GREEN_HOVER = "#059669"
TEXT_MAIN = "#f8fafc"
TEXT_MUTED = "#94a3b8"
LOG_BG = "#090a0f"
LOG_FG = "#34d399"


class Interface:
    def __init__(self, janela: ctk.CTk):
        self.janela = janela
        self.pasta = None
        self.resultado = None
        self.ocupado = False
        self.fechar_depois = False
        self.eventos = queue.Queue()
        self.cancelar = threading.Event()
        self.inicio = 0.0

        janela.title("Canto MIDI — Audio-to-MIDI Studio")
        janela.geometry("860x820")
        janela.minsize(760, 720)
        janela.configure(fg_color=COLOR_BG)
        janela.protocol("WM_DELETE_WINDOW", self.fechar)

        # Container Principal com Margens
        painel = ctk.CTkFrame(janela, fg_color="transparent")
        painel.pack(fill="both", expand=True, padx=25, pady=25)
        painel.columnconfigure(0, weight=1)
        painel.rowconfigure(8, weight=1)

        # Cabeçalho
        ctk.CTkLabel(painel, text="AUDIO-TO-MIDI ENGINE", font=("Segoe UI", 10, "bold"),
                     text_color=COLOR_CYAN).grid(sticky="w")
        ctk.CTkLabel(painel, text="Canto MIDI", font=("Segoe UI", 26, "bold"),
                     text_color=TEXT_MAIN).grid(sticky="w", pady=(0, 2))
        ctk.CTkLabel(painel, text="Sua voz e áudios convertidos em arranjos MIDI precisos.",
                     font=("Segoe UI", 12), text_color=TEXT_MUTED).grid(sticky="w", pady=(0, 15))

        # Cartão 1: Seleção de Pasta
        card_pasta = ctk.CTkFrame(painel, fg_color=COLOR_CARD, border_color=COLOR_CARD_BORDER,
                                  border_width=1, corner_radius=12)
        card_pasta.grid(row=3, column=0, sticky="ew", pady=(0, 12), ipadx=10, ipady=10)
        card_pasta.columnconfigure(0, weight=1)

        topo_pasta = ctk.CTkFrame(card_pasta, fg_color="transparent")
        topo_pasta.grid(row=0, column=0, sticky="ew", padx=10, pady=(5, 0))
        topo_pasta.columnconfigure(0, weight=1)

        ctk.CTkLabel(topo_pasta, text="PASTA DA MÚSICA", font=("Segoe UI", 10, "bold"),
                     text_color=COLOR_CYAN).grid(sticky="w")
        self.escolher = ctk.CTkButton(topo_pasta, text="Selecionar pasta", command=self.selecionar,
                                       corner_radius=8, font=("Segoe UI", 11, "bold"))
        self.escolher.grid(row=0, column=1, sticky="e")

        self.caminho = ctk.StringVar(value="Nenhuma pasta selecionada")
        ctk.CTkLabel(card_pasta, textvariable=self.caminho, wraplength=760, justify="left",
                     font=("Segoe UI", 12), text_color=TEXT_MUTED).grid(row=1, sticky="w", padx=10, pady=(6, 2))

        self.arquivos = ctk.StringVar(value="Requisitos: voz, instrumental, letra.srt e letra.txt no diretório.")
        ctk.CTkLabel(card_pasta, textvariable=self.arquivos, wraplength=760, justify="left",
                     font=("Segoe UI", 11), text_color=TEXT_MUTED).grid(row=2, sticky="w", padx=10)

        # Cartão 2: Nome do MIDI
        card_saida = ctk.CTkFrame(painel, fg_color=COLOR_CARD, border_color=COLOR_CARD_BORDER,
                                  border_width=1, corner_radius=12)
        card_saida.grid(row=4, column=0, sticky="ew", pady=(0, 15), ipadx=10, ipady=10)
        card_saida.columnconfigure(0, weight=1)

        ctk.CTkLabel(card_saida, text="NOME DO ARQUIVO MIDI", font=("Segoe UI", 10, "bold"),
                     text_color=COLOR_CYAN).grid(sticky="w", padx=10, pady=(5, 0))

        self.nome = ctk.StringVar(value="voz.mid")
        self.entrada = ctk.CTkEntry(card_saida, textvariable=self.nome, corner_radius=8,
                                    fg_color=COLOR_INPUT, border_color=COLOR_CARD_BORDER,
                                    text_color=TEXT_MAIN, font=("Segoe UI", 12))
        self.entrada.grid(row=1, sticky="ew", padx=10, pady=(8, 6))

        ctk.CTkLabel(card_saida, text="Letra consolidada, MIDI, SRT silábico e relatórios serão salvos na pasta de origem.",
                     font=("Segoe UI", 11), text_color=TEXT_MUTED).grid(row=2, sticky="w", padx=10)

        # Botões de Ação
        acoes = ctk.CTkFrame(painel, fg_color="transparent")
        acoes.grid(row=5, sticky="ew", pady=(0, 15))

        self.gerar = ctk.CTkButton(acoes, text="▶   GERAR MIDI", command=self.iniciar,
                                   state="disabled", corner_radius=8, fg_color=COLOR_GREEN,
                                   hover_color=COLOR_GREEN_HOVER, text_color="#000000",
                                   font=("Segoe UI", 12, "bold"), height=40)
        self.gerar.pack(side="left")

        self.botao_cancelar = ctk.CTkButton(acoes, text="Cancelar", command=self.pedir_cancelamento,
                                            state="disabled", corner_radius=8, fg_color="#272932",
                                            hover_color="#3b3e50", font=("Segoe UI", 12), height=40)
        self.botao_cancelar.pack(side="left", padx=10)

        self.abrir = ctk.CTkButton(acoes, text="Abrir Pasta de Saída", command=self.abrir_pasta,
                                   state="disabled", corner_radius=8, fg_color="#272932",
                                   hover_color="#3b3e50", font=("Segoe UI", 12), height=40)
        self.abrir.pack(side="right")

        # Barra de Status e Relógio
        estado = ctk.CTkFrame(painel, fg_color="transparent")
        estado.grid(row=6, sticky="ew", pady=(0, 6))

        self.status = ctk.StringVar(value="Aguardando seleção de diretório...")
        self.relogio = ctk.StringVar(value="00:00")

        ctk.CTkLabel(estado, textvariable=self.status, font=("Segoe UI", 11), text_color=TEXT_MUTED).pack(side="left")
        ctk.CTkLabel(estado, textvariable=self.relogio, font=("Segoe UI", 11, "bold"), text_color=COLOR_CYAN).pack(side="right")

        self.barra = ctk.CTkProgressBar(painel, mode="indeterminate", corner_radius=4, height=6,
                                        fg_color=COLOR_CARD, progress_color=COLOR_CYAN)
        self.barra.grid(row=7, sticky="ew", pady=(0, 15))
        self.barra.set(0)

        # Console de Logs Estilo Terminal
        detalhes = ctk.CTkFrame(painel, fg_color="transparent")
        detalhes.grid(row=8, sticky="nsew")

        ctk.CTkLabel(detalhes, text="CONSOLE DE PROCESSAMENTO", font=("Segoe UI", 10, "bold"),
                     text_color=COLOR_CYAN).pack(anchor="w", pady=(0, 4))

        self.log = ctk.CTkTextbox(detalhes, corner_radius=10, fg_color=LOG_BG,
                                   text_color=LOG_FG, font=("Consolas", 11),
                                   border_width=1, border_color=COLOR_CARD_BORDER)
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

        janela.after(100, self.atualizar)

    def registrar(self, texto: str):
        texto = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", texto).replace("\r", "\n")
        self.log.configure(state="normal")
        self.log.insert("end", texto)
        if int(self.log.index("end-1c").split(".")[0]) > 1200:
            self.log.delete("1.0", "end-1000l")
        self.log.see("end")
        self.log.configure(state="disabled")

    def selecionar(self):
        pasta = filedialog.askdirectory(title="Selecione a pasta da música", parent=self.janela)
        if not pasta:
            return
        try:
            encontrados = validar_pasta(Path(pasta))
        except Exception as erro:
            messagebox.showerror("Verifique a pasta", str(erro), parent=self.janela)
            return
        self.pasta = Path(pasta).resolve()
        self.caminho.set(str(self.pasta))
        self.arquivos.set("Arquivos detectados: " + "  ·  ".join(p.name for p in encontrados.values()))
        self.status.set("Pronto para iniciar a conversão.")
        self.gerar.configure(state="normal")
        self.resultado = None
        self.abrir.configure(state="disabled")
        self.escolher.configure(text="Alterar pasta")

    def iniciar(self):
        if self.ocupado or self.pasta is None:
            return
        try:
            nome = normalizar_nome(self.nome.get())
            validar_pasta(self.pasta)
        except Exception as erro:
            messagebox.showerror("Verifique os dados", str(erro), parent=self.janela)
            return
        self.nome.set(nome)
        self.ocupado = True
        self.resultado = None
        self.cancelar.clear()
        self.inicio = time.monotonic()
        self.status.set("Iniciando conversão de áudio...")
        
        self.escolher.configure(state="disabled")
        self.entrada.configure(state="disabled")
        self.gerar.configure(state="disabled")
        self.abrir.configure(state="disabled")
        self.botao_cancelar.configure(state="normal")
        
        self.barra.configure(mode="indeterminate")
        self.barra.start()
        
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.registrar("Carregando modelos de áudio. Isso pode levar alguns momentos...\n")
        threading.Thread(target=self.trabalhar, args=(self.pasta, nome), daemon=False).start()

    def trabalhar(self, pasta: Path, nome: str):
        try:
            destino = converter(pasta, nome, self.cancelar,
                                lambda tipo, valor: self.eventos.put((tipo, valor)))
            self.eventos.put(("concluido", destino))
        except ConversaoCancelada:
            self.eventos.put(("cancelado", "Conversão cancelada pelo usuário."))
        except Exception as erro:
            self.eventos.put(("erro", str(erro)))

    def atualizar(self):
        for _ in range(80):
            try:
                tipo, valor = self.eventos.get_nowait()
            except queue.Empty:
                break
            if tipo == "log":
                self.registrar(valor)
            elif tipo == "etapa":
                if not self.cancelar.is_set():
                    self.status.set(valor)
                self.registrar("\n" + valor + "\n")
            else:
                self.finalizar(tipo, valor)
                if self.fechar_depois:
                    self.janela.destroy()
                    return
        if self.ocupado:
            segundos = int(time.monotonic() - self.inicio)
            self.relogio.set(f"{segundos // 60:02d}:{segundos % 60:02d}")
        self.janela.after(100, self.atualizar)

    def finalizar(self, tipo: str, valor):
        self.ocupado = False
        self.barra.stop()
        self.barra.configure(mode="determinate")
        self.barra.set(1.0 if tipo == "concluido" else 0.0)
        
        self.escolher.configure(state="normal")
        self.entrada.configure(state="normal")
        self.gerar.configure(state="normal")
        self.botao_cancelar.configure(state="disabled")
        
        if tipo == "concluido":
            self.resultado = valor.midi
            self.status.set(f"Concluído · Dificuldade estimada: {valor.dificuldade}")
            self.registrar(
                f"\n[SUCESSO] Arquivos gerados:\n{valor.midi}\n{valor.srt}\n{valor.metadata}\n"
                f"Dificuldade estimada: {valor.dificuldade}\n"
            )
            self.abrir.configure(state="normal")
            self.escolher.configure(text="Converter outro áudio")
        elif tipo == "cancelado":
            self.status.set(valor)
            self.registrar("\n" + valor + "\n")
        else:
            self.status.set("Erro na execução da conversão")
            self.registrar("\n[ERRO]: " + valor + "\n")
            if not self.fechar_depois:
                messagebox.showerror("Erro na conversão", valor, parent=self.janela)

    def pedir_cancelamento(self):
        if self.ocupado:
            self.cancelar.set()
            self.status.set("Encerrando threads de conversão...")
            self.botao_cancelar.configure(state="disabled")

    def abrir_pasta(self):
        if self.resultado is None:
            return
        pasta = str(self.resultado.parent)
        try:
            if os.name == "nt":
                os.startfile(pasta)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", pasta])
        except OSError as erro:
            messagebox.showerror("Abrir pasta", str(erro), parent=self.janela)

    def fechar(self):
        if not self.ocupado:
            self.janela.destroy()
        elif messagebox.askyesno("Conversão em andamento", "Deseja cancelar o processo e fechar a aplicação?",
                                parent=self.janela):
            self.fechar_depois = True
            self.pedir_cancelamento()


def iniciar_interface():
    janela = ctk.CTk()
    Interface(janela)
    janela.mainloop()
