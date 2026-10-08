"""Composição visual da revisão. As decisões permanecem em revisao_interface."""
import tkinter as tk
import customtkinter as ctk
from estilo_revisao import (BRANCO, TEXTO, MUTED, AZUL, painel, rotulo, instrucao,
                            botao, caixa_selecao, entrada, texto_editavel, configurar_tabelas)


def secao(parent, titulo, ajuda):
    card = painel(parent, borda=True)
    card.pack(fill='x', padx=8, pady=(0, 12))
    rotulo(card, titulo, destaque=True, cor=AZUL, tamanho=15).pack(fill='x', padx=12, pady=(10, 4))
    instrucao(card, ajuda)
    return card


def montar_interface(j):
    j.title('Revisão da letra — ' + j.sessao.pasta.name)
    j.geometry('1280x900')
    j.minsize(1000, 720)
    j.configure(fg_color=BRANCO)
    j.protocol('WM_DELETE_WINDOW', j.salvar_sair)
    j.columnconfigure(0, weight=1)
    j.rowconfigure(1, weight=1)
    configurar_tabelas(j)

    cabecalho = painel(j)
    cabecalho.grid(row=0, column=0, sticky='ew', padx=22, pady=(16, 10))
    rotulo(cabecalho, 'Revisão da letra', tamanho=23, destaque=True).pack(anchor='w')
    rotulo(cabecalho, '1  Escolha a frase   →   2  Compare   →   3  Ouça e ajuste   →   4  Aplique', cor=AZUL).pack(anchor='w', pady=4)
    j.resumo = tk.StringVar()
    rotulo(cabecalho, variavel=j.resumo, cor=MUTED, tamanho=12).pack(anchor='w')

    panes = tk.PanedWindow(j, orient='horizontal', background=BRANCO, borderwidth=0,
                           sashwidth=8, sashrelief='flat', opaqueresize=True)
    panes.grid(row=1, column=0, sticky='nsew', padx=18)
    esquerda = painel(panes)
    area = painel(panes)
    panes.add(esquerda, minsize=290, width=340, stretch='never')
    panes.add(area, minsize=620, stretch='always')
    rotulo(esquerda, '1  Escolha uma frase', destaque=True, tamanho=15, cor=AZUL).pack(anchor='w', pady=(0, 4))
    instrucao(esquerda, 'Clique em uma linha para ver o texto completo e as sugestões ao lado →')
    j.filtro = tk.StringVar(value='Revisões' if j.sessao.itens else 'Legenda completa')
    ctk.CTkSegmentedButton(esquerda, values=['Revisões', 'Legenda completa'], variable=j.filtro,
        command=j.filtrar_lista, font=('Segoe UI', 12), corner_radius=8, height=34,
        fg_color='#eff6fb', selected_color='#bae6fd', selected_hover_color='#7dd3fc',
        unselected_color='#eff6fb', unselected_hover_color='#dbeafe', text_color=TEXTO,
        text_color_disabled=MUTED).pack(fill='x', pady=(0, 8))
    j.lista = j._criar_tabela(esquerda, columns=('estado',), show='tree headings', selectmode='browse')
    j.lista.heading('#0', text='Frase / ocorrência')
    j.lista.heading('estado', text='Situação')
    j.lista.column('#0', width=225, minwidth=160)
    j.lista.column('estado', width=105, stretch=False)
    j.lista.bind('<<TreeviewSelect>>', j.selecionar_item)
    botao(esquerda, 'Próxima pendência →', j.proxima_pendencia, tipo='azul').pack(fill='x', pady=(8, 0))
    botao(esquerda, '↶  Desfazer última decisão', j.desfazer).pack(fill='x', pady=(8, 4))
    botao(esquerda, 'Histórico e versões anteriores', j.historico).pack(fill='x')

    canvas = tk.Canvas(area, background=BRANCO, highlightthickness=0)
    scroll = ctk.CTkScrollbar(area, command=canvas.yview, fg_color=BRANCO,
                              button_color='#cbd5e1', button_hover_color='#94a3b8')
    scroll.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    canvas.configure(yscrollcommand=scroll.set)
    direita = painel(canvas)
    janela_canvas = canvas.create_window((0, 0), window=direita, anchor='nw')
    direita.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(janela_canvas, width=e.width))
    j.canvas_conteudo = canvas
    def ir_para(card):
        canvas.update_idletasks()
        canvas.yview_moveto(card.winfo_y() / max(1, direita.winfo_height()))
    j.ir_para = ir_para

    comparar = secao(direita, '2  Compare com a legenda',
        'Confira qual repetição corresponde à frase. As sugestões não confirmam que o trecho foi cantado.')
    contexto = tk.Frame(comparar, background=BRANCO)
    contexto.pack(fill='x', padx=12, pady=(0, 8))
    j.contexto = texto_editavel(contexto, altura=4, somente_leitura=True)
    rolagem_contexto = ctk.CTkScrollbar(contexto, command=j.contexto.yview, fg_color=BRANCO,
                                       button_color='#cbd5e1', button_hover_color='#94a3b8', width=12)
    rolagem_contexto.pack(side='right', fill='y')
    j.contexto.pack(side='left', fill='both', expand=True)
    j.contexto.configure(yscrollcommand=rolagem_contexto.set)
    j.contexto.configure(state='normal')
    j.contexto.insert('1.0', '← Selecione uma frase na lista para começar.')
    j.contexto.configure(state='disabled')
    rotulo(comparar, 'Trechos que já estão na legenda', destaque=True).pack(anchor='w', padx=12)
    j.trechos = j._criar_tabela(comparar, expand=False, columns=('tempo', 'texto'), show='headings', height=4)
    for campo, texto, largura in [('tempo', 'Início → fim', 165), ('texto', 'Texto atual', 450)]:
        j.trechos.heading(campo, text=texto)
        j.trechos.column(campo, width=largura, stretch=campo == 'texto')
    j.trechos.bind('<Double-1>', lambda e: j.carregar_trecho())
    botao(comparar, '↓  Carregar seleção no editor', j.carregar_trecho).pack(anchor='w', padx=12, pady=6)
    instrucao(comparar, 'Para corrigir: selecione o trecho acima e carregue-o no editor. Ctrl/Shift seleciona vários. Duplo clique também carrega.')

    ouvir = secao(direita, '3  Ouça e ajuste o texto',
        'Para inserir uma frase, localize-a na voz, marque seu início e fim e confira o texto abaixo.')
    j.card_edicao = ouvir
    faixa = painel(ouvir)
    faixa.pack(fill='x', padx=12)
    comandos = [('▶  Tocar / pausar', j.play, 'azul'), ('←  3 s', lambda: j.pular(-3), 'neutro'),
                 ('3 s  →', lambda: j.pular(3), 'neutro'), ('Ouvir intervalo', j.ouvir_intervalo, 'neutro'),
                 ('Ampliar intervalo', j.zoom_intervalo, 'neutro'), ('Ver áudio inteiro', j.zoom_total, 'neutro')]
    for n, (texto, fn, tipo) in enumerate(comandos):
        faixa.columnconfigure(n % 3, weight=1)
        botao(faixa, texto, fn, tipo=tipo).grid(row=n // 3, column=n % 3, sticky='ew', padx=3, pady=3)
    j.repetir = tk.BooleanVar(value=False)
    caixa_selecao(ouvir, 'Repetir ao ouvir o intervalo', j.repetir).pack(anchor='w', padx=14, pady=6)
    j.relogio = tk.StringVar(value='Carregando voz…')
    rotulo(ouvir, variavel=j.relogio, cor=AZUL, destaque=True).pack(anchor='w', padx=14)
    j.onda = tk.Canvas(ouvir, height=92, background='#f0f9ff', highlightthickness=0)
    j.onda.pack(fill='x', padx=12, pady=6)
    j.onda.bind('<Configure>', lambda e: j.desenhar_onda())
    j.onda.bind('<Button-1>', j.inicio_selecao)
    j.onda.bind('<B1-Motion>', j.arrastar_selecao)
    j.onda.bind('<ButtonRelease-1>', j.fim_selecao)
    instrucao(ouvir, 'Clique na onda para buscar; arraste para selecionar. Os botões “Marcar” usam a posição atual do áudio.')
    limites = painel(ouvir)
    limites.pack(fill='x', padx=12, pady=(0, 8))
    j.inicio, j.fim = tk.StringVar(value='0'), tk.StringVar(value='0')
    for n, (label, var) in enumerate([('Início', j.inicio), ('Fim', j.fim)]):
        lado = painel(limites)
        lado.grid(row=0, column=n, sticky='ew', padx=3)
        limites.columnconfigure(n, weight=1)
        rotulo(lado, label, destaque=True).pack(anchor='w')
        entrada(lado, var).pack(side='left', padx=(0, 5))
        botao(lado, 'Marcar ' + label.lower(), lambda v=var: j.marcar(v), largura=112).pack(side='left')
    instrucao(ouvir, 'Tempos: use 01:42,900 ou 102.9 segundos. Corrigir apenas o texto mantém o intervalo carregado.')
    rotulo(ouvir, 'Texto que será aplicado', destaque=True).pack(anchor='w', padx=12)
    j.texto = texto_editavel(ouvir, altura=3)
    j.texto.pack(fill='x', padx=12, pady=6)
    linha = painel(ouvir)
    linha.pack(fill='x', padx=12, pady=(0, 8))
    j.botao_alinhar = botao(linha, 'Buscar tempos na voz', j.alinhar, tipo='azul')
    j.botao_alinhar.pack(side='left', padx=(0, 6))
    botao(linha, 'Cancelar busca', j.cancelar_busca).pack(side='left')
    instrucao(ouvir, 'A busca sugere tempos por palavra dentro do intervalo. Ouça e confirme as sugestões antes de aplicar sua decisão.')
    j.avancado = tk.BooleanVar(value=False)
    caixa_selecao(ouvir, 'Ajuste avançado: tempos por palavra', j.avancado, j.mostrar_avancado).pack(anchor='w', padx=14, pady=(0, 12))

    j.painel_palavras = painel(direita, borda=True)
    rotulo(j.painel_palavras, 'Ajuste fino · palavra por palavra', destaque=True, cor=AZUL).pack(anchor='w', padx=12, pady=10)
    instrucao(j.painel_palavras, 'Duplo clique em Incluir, Início, Fim ou Confirmado para editar. ✓ Confirmado preserva o tempo na conversão. Desmarcar Incluir retira a palavra ao aplicar o texto.')
    j.tabela = j._criar_tabela(j.painel_palavras, expand=False,
        columns=('usar', 'texto', 'inicio', 'fim', 'confirmado', 'score'), show='headings', height=5, selectmode='extended')
    for campo, texto, largura in [('usar', 'Incluir', 65), ('texto', 'Palavra', 125), ('inicio', 'Início', 90),
                                   ('fim', 'Fim', 90), ('confirmado', 'Confirmado', 105), ('score', 'Modelo', 75)]:
        j.tabela.heading(campo, text=texto)
        j.tabela.column(campo, width=largura)
    j.tabela.bind('<Double-1>', j.editar_palavra)
    botoes = painel(j.painel_palavras)
    botoes.pack(fill='x', padx=12, pady=8)
    for n, (label, fn) in enumerate([('↻ Recriar palavras do texto', j.recriar_palavras), ('▶ Ouvir selecionadas', j.ouvir_palavras),
        ('✓ Confirmar selecionadas', j.confirmar_palavras), ('Marcar grupo no intervalo', j.marcar_grupo), ('Dividir trecho no cursor', j.dividir)]):
        botao(botoes, label, fn).grid(row=n // 2, column=n % 2, sticky='ew', padx=3, pady=3)
        botoes.columnconfigure(n % 2, weight=1)
    instrucao(j.painel_palavras, 'Recriar: refaz a tabela após editar a frase e apaga os ajustes da tabela. Marcar grupo: sugere uma distribuição aproximada. Dividir: escolha a primeira palavra da segunda parte e posicione o áudio no corte.')

    j.acoes = secao(direita, '4  O que fazer com esta frase?',
        'Escolha uma ação abaixo. Cada decisão aplicada é salva; você pode desfazer a última pela coluna à esquerda.')
    atalhos = painel(cabecalho)
    atalhos.pack(fill='x', pady=(8, 0))
    for label, card in [('2  Comparar', comparar), ('3  Ouvir e editar', ouvir), ('4  Aplicar decisão →', j.acoes)]:
        botao(atalhos, label, lambda c=card: ir_para(c), largura=165).pack(side='left', padx=(0, 8))
    grade = painel(j.acoes)
    grade.pack(fill='x', padx=10, pady=(0, 8))
    j.botoes_decisao = {}
    decisoes = [
        ('✓ Já está na legenda', 'associar', 'azul', 'O texto já aparece nos trechos selecionados acima. Associa a ocorrência sem inserir outra cópia.'),
        ('✎ Corrigir seleção', 'corrigir', 'azul', 'Substitui os trechos selecionados pelo texto e pelo intervalo do editor. Carregue a seleção antes de editar.'),
        ('+ Inserir nova frase', 'inserir', 'verde', 'A frase foi cantada, mas falta na legenda. Adiciona o texto no intervalo marcado.'),
        ('× Descartar pendência', 'descartar', 'neutro', 'Esta ocorrência não precisa entrar. Encerra a pendência e mantém os trechos existentes.'),
        ('→ Decidir depois', 'depois', 'neutro', 'Ainda há dúvida? Mantém a pendência e salva seu rascunho para retomar depois.'),
        ('− Remover da legenda…', 'remover', 'remover', 'O trecho existente não deve aparecer. Exclui os trechos selecionados da versão validada, após confirmação.'),
    ]
    for n, (texto, acao, tipo, ajuda) in enumerate(decisoes):
        card = painel(grade, cor='#f8fbfd', borda=True)
        card.grid(row=n // 2, column=n % 2, sticky='nsew', padx=4, pady=4)
        grade.columnconfigure(n % 2, weight=1, uniform='decisao')
        b = botao(card, texto, lambda a=acao: j.aplicar(a), tipo=tipo)
        b.pack(fill='x', padx=10, pady=(10, 6))
        instrucao(card, ajuda)
        j.botoes_decisao[acao] = b

    j.status = tk.StringVar(value='Comece pela lista à esquerda. Depois compare, ouça e escolha uma ação.')
    status = rotulo(j, variavel=j.status, cor=AZUL, tamanho=12)
    status.configure(wraplength=960)
    status.grid(row=2, column=0, sticky='ew', padx=22, pady=8)
    rodape = painel(j)
    rodape.grid(row=3, column=0, sticky='ew', padx=22, pady=(0, 16))
    botao(rodape, 'Salvar e sair por enquanto', j.salvar_sair, largura=220).pack(side='left')
    botao(rodape, '✓ Publicar legenda e continuar →', j.continuar, tipo='verde', largura=290).pack(side='right')
    rotulo(j, 'Pendências podem ficar para depois. Só os trechos aplicados entram na legenda publicada.', cor=MUTED, tamanho=11).grid(row=4, column=0, sticky='w', padx=22, pady=(0, 10))

    # Roda apenas nesta janela. As tabelas/textos preservam sua própria rolagem.
    def roda(event):
        if event.widget.winfo_class() not in ('Treeview', 'Text'):
            canvas.yview_scroll(-int(event.delta / 120), 'units')
    j.bind('<MouseWheel>', roda, add='+')
