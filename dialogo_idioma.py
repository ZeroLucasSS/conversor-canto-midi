"""Seleção modal do idioma antes da geração de legendas."""
import tkinter as tk
from tkinter import simpledialog, ttk

OPCOES_IDIOMA = {'Português': 'pt', 'Inglês': 'en', 'Bilíngue (português e inglês)': 'bilingue'}


class DialogoIdioma(simpledialog.Dialog):
    def body(self, master):
        ttk.Label(master, text='Qual é o idioma da música?').pack(anchor='w', pady=(4, 10))
        self.idioma = tk.StringVar(master, value='Português')
        primeiro = None
        for texto in OPCOES_IDIOMA:
            botao = ttk.Radiobutton(master, text=texto, variable=self.idioma, value=texto)
            botao.pack(anchor='w', pady=3)
            primeiro = primeiro or botao
        return primeiro

    def buttonbox(self):
        caixa = ttk.Frame(self)
        ttk.Button(caixa, text='Gerar SRT', command=self.ok).pack(side='left', padx=5)
        ttk.Button(caixa, text='Cancelar', command=self.cancel).pack(side='left', padx=5)
        caixa.pack(pady=10)
        self.bind('<Return>', self.ok)
        self.bind('<Escape>', self.cancel)

    def apply(self):
        self.result = OPCOES_IDIOMA[self.idioma.get()]


def escolher_idioma(janela):
    return DialogoIdioma(janela, title='Idioma da música').result
