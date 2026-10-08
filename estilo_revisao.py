"""Componentes claros da revisão, sem mudar o tema da janela principal."""
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

BRANCO = '#ffffff'
TEXTO = '#172b46'
MUTED = '#52657c'
AZUL = '#0369a1'
VERDE = '#047857'
BORDA = '#dce5ee'


def painel(parent, *, cor=BRANCO, borda=False):
    return ctk.CTkFrame(parent, fg_color=cor, bg_color=BRANCO,
                        corner_radius=10 if borda else 0,
                        border_width=1 if borda else 0, border_color=BORDA)


def rotulo(parent, texto='', *, variavel=None, destaque=False, cor=TEXTO, tamanho=13):
    return ctk.CTkLabel(parent, text=texto, textvariable=variavel, text_color=cor,
                        fg_color='transparent', font=('Segoe UI', tamanho, 'bold' if destaque else 'normal'),
                        anchor='w', justify='left')


def instrucao(parent, texto):
    label = rotulo(parent, texto, cor=MUTED, tamanho=12)
    label.pack(fill='x', padx=12, pady=(0, 8))
    # Usa a largura do recipiente, inclusive quando o painel é redimensionado.
    largura_anterior = None
    def ajustar(e):
        nonlocal largura_anterior
        largura = max(160, e.width-30)
        if largura != largura_anterior:
            largura_anterior = largura
            label.configure(wraplength=largura)
    parent.bind('<Configure>', ajustar, add='+')
    return label


def botao(parent, texto, comando, *, tipo='neutro', largura=120):
    cores = {
        'neutro': ('#eff6fb', '#dbeafe', AZUL, BORDA),
        'azul': (AZUL, '#075985', BRANCO, AZUL),
        'verde': (VERDE, '#065f46', BRANCO, VERDE),
        'remover': (BRANCO, '#fff1f2', '#b42332', '#f1ced3'),
    }
    fundo, hover, texto_cor, borda = cores[tipo]
    return ctk.CTkButton(parent, text=texto, command=comando, width=largura, height=34,
                         corner_radius=8, fg_color=fundo, hover_color=hover,
                         text_color=texto_cor, text_color_disabled='#738499',
                         border_width=1, border_color=borda, font=('Segoe UI', 12, 'bold'))


def caixa_selecao(parent, texto, variavel, comando=None):
    return ctk.CTkCheckBox(parent, text=texto, variable=variavel, command=comando,
                          text_color=TEXTO, fg_color=AZUL, hover_color='#0284c7',
                          border_color='#7993aa', checkmark_color=BRANCO,
                          checkbox_width=19, checkbox_height=19, corner_radius=4,
                          font=('Segoe UI', 12))


def entrada(parent, variavel):
    return ctk.CTkEntry(parent, textvariable=variavel, width=112, height=34,
                        corner_radius=7, fg_color=BRANCO, text_color=TEXTO,
                        border_color=BORDA, font=('Segoe UI', 13))


def texto_editavel(parent, *, altura=3, somente_leitura=False):
    return tk.Text(parent, height=altura, wrap='word', state='disabled' if somente_leitura else 'normal',
                   background='#f5faff' if somente_leitura else BRANCO, foreground=TEXTO,
                   insertbackground=AZUL, selectbackground='#bae6fd', selectforeground=TEXTO,
                   font=('Segoe UI', 12), relief='flat', borderwidth=0, padx=12, pady=10,
                   highlightthickness=1, highlightbackground=BORDA, highlightcolor=AZUL)


def configurar_tabelas(parent):
    style = ttk.Style(parent)
    # Estilos exclusivos; não chama theme_use nem set_appearance_mode global.
    style.configure('Revisao.Treeview', background=BRANCO, fieldbackground=BRANCO,
                    foreground=TEXTO, rowheight=30, font=('Segoe UI', 11), borderwidth=0)
    style.map('Revisao.Treeview', background=[('selected', '#dbeafe')],
              foreground=[('selected', '#075985')])
    style.configure('Revisao.Treeview.Heading', background='#eff6fb', foreground=AZUL,
                    font=('Segoe UI', 11, 'bold'), relief='flat')
