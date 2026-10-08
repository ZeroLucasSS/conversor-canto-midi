"""Janela de revisão da letra, aberta na thread do Tk.

Também pode ser executada isoladamente: python revisao_interface.py PASTA.
"""
from __future__ import annotations

import copy
import json
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from revisao_letra import SessaoRevisao, formatar_tempo, tempo, palavras_editor


class JanelaRevisao(tk.Toplevel):
    def __init__(self, parent, sessao, ao_fechar=None):
        super().__init__(parent)
        self.sessao = sessao
        self.ao_fechar = ao_fechar
        self.player = None
        self.eventos = queue.Queue()
        self.fechada = False
        self.processo = None
        self.worker_cancelar = threading.Event()
        self.alinhando = False
        self.geracao = 0
        self.item = None
        self.ps = []
        self.mapa_itens = {}
        self.zoom = (0., sessao.duracao)
        self.audio = None
        self.title('Revisão da letra — ' + sessao.pasta.name)
        self.geometry('1180x860')
        self.minsize(960, 720)
        self.protocol('WM_DELETE_WINDOW', self.salvar_sair)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.resumo = tk.StringVar()
        ttk.Label(self, textvariable=self.resumo).grid(row=0, column=0, sticky='ew', padx=10, pady=5)
        panes = ttk.Panedwindow(self, orient='horizontal')
        panes.grid(row=1, column=0, sticky='nsew', padx=10)
        esquerda = ttk.Frame(panes)
        area = ttk.Frame(panes)
        canvas = tk.Canvas(area, highlightthickness=0)
        scroll = ttk.Scrollbar(area, command=canvas.yview)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        direita = ttk.Frame(canvas)
        janela_canvas = canvas.create_window((0,0), window=direita, anchor='nw')
        direita.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(janela_canvas, width=e.width))
        panes.add(esquerda, weight=1)
        panes.add(area, weight=3)
        ttk.Label(esquerda, text='Ocorrências do TXT e trechos da legenda').pack(anchor='w')
        self.lista = self._criar_tabela(esquerda, columns=('estado',), show='tree headings', selectmode='browse')
        self.lista.heading('#0', text='Frase / ocorrência')
        self.lista.heading('estado', text='Decisão')
        self.lista.column('#0', width=250)
        self.lista.column('estado', width=80, stretch=False)
        self.lista.bind('<<TreeviewSelect>>', self.selecionar_item)
        ttk.Button(esquerda, text='Histórico / versões anteriores', command=self.historico).pack(fill='x', pady=3)
        ttk.Button(esquerda, text='Desfazer última decisão', command=self.desfazer).pack(fill='x')

        self.contexto = tk.Text(direita, height=5, wrap='word', state='disabled')
        self.contexto.pack(fill='x')
        ttk.Label(direita, text='Legenda atual (Ctrl/Shift: vários trechos; duplo clique: carregar para edição)').pack(anchor='w')
        self.trechos = self._criar_tabela(direita, expand=False, columns=('tempo', 'texto'), show='headings', height=5)
        self.trechos.heading('tempo', text='Início — fim')
        self.trechos.heading('texto', text='Texto')
        self.trechos.column('tempo', width=165, stretch=False)
        self.trechos.column('texto', width=420)
        self.trechos.bind('<Double-1>', lambda e: self.carregar_trecho())

        faixa = ttk.Frame(direita)
        faixa.pack(fill='x', pady=4)
        for rotulo, fn in [('▶ / Pausa', self.play), ('−3 s', lambda: self.pular(-3)),
                           ('+3 s', lambda: self.pular(3)), ('Ouvir intervalo', self.ouvir_intervalo),
                           ('Zoom intervalo', self.zoom_intervalo), ('Áudio inteiro', self.zoom_total)]:
            ttk.Button(faixa, text=rotulo, command=fn).pack(side='left')
        self.repetir = tk.BooleanVar(value=False)
        ttk.Checkbutton(faixa, text='Repetir', variable=self.repetir).pack(side='left')
        self.relogio = tk.StringVar(value='Carregando voz…')
        ttk.Label(direita, textvariable=self.relogio).pack(anchor='w')
        self.onda = tk.Canvas(direita, height=90, background='#111827', highlightthickness=0)
        self.onda.pack(fill='x')
        self.onda.bind('<Configure>', lambda e: self.desenhar_onda())
        self.onda.bind('<Button-1>', self.inicio_selecao)
        self.onda.bind('<B1-Motion>', self.arrastar_selecao)
        self.onda.bind('<ButtonRelease-1>', self.fim_selecao)
        ttk.Label(direita, text='Clique: buscar no áudio. Arraste: selecionar intervalo. Tempos em mm:ss,mmm ou segundos.').pack(anchor='w')
        limites = ttk.Frame(direita)
        limites.pack(fill='x')
        self.inicio = tk.StringVar(value='0')
        self.fim = tk.StringVar(value='0')
        for label, var in [('Início', self.inicio), ('Fim', self.fim)]:
            ttk.Label(limites, text=label).pack(side='left')
            ttk.Entry(limites, textvariable=var, width=13).pack(side='left', padx=3)
            ttk.Button(limites, text='Marcar ' + label.lower(), command=lambda v=var: self.marcar(v)).pack(side='left')
        self.texto = tk.Text(direita, height=2, wrap='word')
        self.texto.pack(fill='x', pady=4)
        linha = ttk.Frame(direita)
        linha.pack(fill='x')
        self.avancado = tk.BooleanVar(value=False)
        ttk.Checkbutton(linha, text='Tempos por palavra', variable=self.avancado, command=self.mostrar_avancado).pack(side='left')
        self.botao_alinhar = ttk.Button(linha, text='Sugerir tempos neste intervalo', command=self.alinhar)
        self.botao_alinhar.pack(side='left')
        ttk.Button(linha, text='Cancelar busca', command=self.cancelar_busca).pack(side='left')
        self.painel_palavras = ttk.Frame(direita)
        ttk.Label(self.painel_palavras, text='Duplo clique para editar. ✓ confirmado = tempo preservado na conversão; sugestão não confirmada é só referência.').pack(anchor='w')
        self.tabela = self._criar_tabela(self.painel_palavras, expand=False, columns=('usar', 'texto', 'inicio', 'fim', 'confirmado', 'score'),
                                   show='headings', height=5, selectmode='extended')
        for campo, label, largura in [('usar', 'Incluir', 50), ('texto', 'Palavra', 130), ('inicio', 'Início', 100),
                                       ('fim', 'Fim', 100), ('confirmado', 'Confirmado', 80), ('score', 'Modelo', 70)]:
            self.tabela.heading(campo, text=label)
            self.tabela.column(campo, width=largura)
        self.tabela.bind('<Double-1>', self.editar_palavra)
        botoes = ttk.Frame(self.painel_palavras)
        botoes.pack(fill='x')
        for label, fn in [('Recriar tabela', self.recriar_palavras), ('Ouvir palavras', self.ouvir_palavras),
                          ('Confirmar selecionadas', self.confirmar_palavras), ('Marcar grupo no intervalo', self.marcar_grupo),
                          ('Dividir trecho aqui', self.dividir)]:
            ttk.Button(botoes, text=label, command=fn).pack(side='left')
        acoes = ttk.Frame(direita)
        acoes.pack(fill='x', pady=5)
        for n, (label, acao) in enumerate([('Já está na legenda', 'associar'), ('Corrigir / substituir seleção', 'corrigir'),
                       ('Inserir trecho', 'inserir'), ('Descartar pendência', 'descartar'), ('Revisar depois', 'depois'),
                       ('Remover trechos selecionados…', 'remover')]):
            ttk.Button(acoes, text=label, command=lambda a=acao: self.aplicar(a)).grid(row=n//3, column=n%3, sticky='ew', padx=2, pady=2)
            acoes.columnconfigure(n%3, weight=1)
        self.status = tk.StringVar(value='Selecione uma ocorrência. Associar nunca insere nem duplica palavras.')
        ttk.Label(self, textvariable=self.status, wraplength=920).grid(row=2, column=0, sticky='ew', padx=10, pady=4)
        rodape = ttk.Frame(self)
        rodape.grid(row=3, column=0, sticky='ew', padx=10, pady=8)
        ttk.Button(rodape, text='Salvar e continuar depois', command=self.salvar_sair).pack(side='left')
        ttk.Button(rodape, text='Publicar e continuar (mesmo com pendências)', command=self.continuar).pack(side='right')
        self.atualizar_listas()
        if sessao.reconciliar:
            self.status.set('As fontes mudaram: decisões antigas foram arquivadas e não serão aplicadas. Consulte o histórico e confirme novamente nos trechos atuais.')
        threading.Thread(target=self.carregar_audio, daemon=True).start()
        self.after(80, self.atualizar)

    @staticmethod
    def _criar_tabela(parent, expand=True, **opcoes):
        frame = ttk.Frame(parent)
        frame.pack(fill='both' if expand else 'x', expand=expand)
        # Criar a tabela DENTRO do frame. pack(in_=...) só muda o gerente
        # de geometria; não muda o pai nem impede um frame irmão de cobri-la.
        tree = ttk.Treeview(frame, **opcoes)
        tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(frame, command=tree.yview)
        scroll.pack(side='right', fill='y')
        tree.configure(yscrollcommand=scroll.set)
        return tree

    def erro(self, erro):
        self.status.set(str(erro))
        messagebox.showerror('Revisão da letra', str(erro), parent=self)

    def atualizar_listas(self):
        self.lista.delete(*self.lista.get_children())
        self.trechos.delete(*self.trechos.get_children())
        self.mapa_itens = {}
        for i in self.sessao.itens:
            self.mapa_itens[i['id']] = i
            estado = self.sessao.dados['decisoes'].get(i['id'], {}).get('acao', 'pendente')
            local = f"TXT linha {i['linha']}: " if i['tipo'] == 'txt' else 'SRT: '
            self.lista.insert('', 'end', iid=i['id'], text=local+i['texto'], values=(estado,))
        for b in self.sessao.blocos:
            id_item = 'editar:' + b['id']
            self.mapa_itens[id_item] = dict(id=id_item, bloco=b['id'], texto=b['texto'], motivo='Edição livre de trecho existente', tipo='srt')
            self.lista.insert('', 'end', iid=id_item, text=formatar_tempo(b['inicio'])+' '+b['texto'], values=('legenda',))
            self.trechos.insert('', 'end', iid=b['id'], values=(f"{formatar_tempo(b['inicio'])} — {formatar_tempo(b['fim'])}", b['texto']))
        self.resumo.set(f'{len(self.sessao.pendentes)} ocorrências pendentes · {len(self.sessao.blocos)} trechos publicados · '
                       'SRT automático preservado; saída: letra_validada.srt')

    def guardar_rascunho(self):
        if self.item:
            self.sessao.dados['rascunhos'][self.item['id']] = dict(texto=self.texto.get('1.0', 'end-1c'),
                inicio=self.inicio.get(), fim=self.fim.get(), palavras=copy.deepcopy(self.ps), alvos=list(self.trechos.selection()))

    def selecionar_item(self, event=None):
        selecionados = self.lista.selection()
        if not selecionados or selecionados[0] not in self.mapa_itens:
            return
        self.guardar_rascunho()
        self.geracao += 1
        self.item = self.mapa_itens[selecionados[0]]
        item = self.item
        candidatos = self.sessao.candidatos(item)
        motivos = {
            'texto_exclusivo_srt_exige_revisao': 'Trecho exclusivo do SRT, preservado para conferência.',
            'consulta_txt_ambigua_original_preservado': 'Há várias correspondências possíveis no TXT; o trecho original foi preservado.',
        }
        info = f"{item['texto']}\nMotivo: {motivos.get(item['motivo'], item['motivo'])}\n"
        info += 'Sugestões textuais (verifique a repetição no áudio):\n' + '\n'.join(
            f"{formatar_tempo(c['inicio'])}–{formatar_tempo(c['fim'])} · {c['score']:.0f}% · {c['texto']}" for c in candidatos[:4])
        self.contexto.configure(state='normal')
        self.contexto.delete('1.0', 'end')
        self.contexto.insert('end', info)
        self.contexto.configure(state='disabled')
        rascunho = self.sessao.dados['rascunhos'].get(item['id'])
        alvo = item.get('bloco')
        ids = [alvo] if alvo and self.trechos.exists(alvo) else (candidatos[0]['ids'] if candidatos else [])
        if rascunho:
            ids = [i for i in rascunho.get('alvos', []) if self.trechos.exists(i)]
            self.carregar_editor(rascunho)
        else:
            blocos = [b for b in self.sessao.blocos if b['id'] in ids]
            self.carregar_editor(dict(texto=item['texto'], inicio=blocos[0]['inicio'] if blocos else 0,
                                     fim=blocos[-1]['fim'] if blocos else 0))
        self.trechos.selection_set(ids)
        if ids:
            self.trechos.see(ids[0])

    def carregar_editor(self, b):
        self.texto.delete('1.0', 'end')
        self.texto.insert('1.0', b['texto'])
        self.inicio.set(formatar_tempo(b['inicio']) if isinstance(b['inicio'], (int, float)) else b['inicio'])
        self.fim.set(formatar_tempo(b['fim']) if isinstance(b['fim'], (int, float)) else b['fim'])
        self.ps = copy.deepcopy(b.get('palavras') or palavras_editor(b['texto']))
        self.atualizar_palavras()

    def carregar_trecho(self):
        ids = self.trechos.selection()
        bs = [b for b in self.sessao.blocos if b['id'] in ids]
        if not bs:
            return
        self.geracao += 1
        b = dict(texto=' '.join(b['texto'] for b in bs), inicio=bs[0]['inicio'], fim=bs[-1]['fim'])
        if len(bs) == 1:
            b['palavras'] = bs[0].get('palavras', [])
        self.carregar_editor(b)

    def mostrar_avancado(self):
        if self.avancado.get():
            # Antes das ações, mantendo o rodapé sempre acessível.
            self.painel_palavras.pack(fill='x', before=self.painel_palavras.master.winfo_children()[-1])
        else:
            self.painel_palavras.pack_forget()

    def atualizar_palavras(self):
        self.tabela.delete(*self.tabela.get_children())
        for i,p in enumerate(self.ps):
            self.tabela.insert('', 'end', iid=str(i), values=('✓' if p.get('incluir', True) else '—', p['texto'],
                formatar_tempo(p['inicio']) if p.get('inicio') is not None else '',
                formatar_tempo(p['fim']) if p.get('fim') is not None else '',
                '✓' if p.get('confirmado') else '—', f"{p['score']:.2f}" if p.get('score') is not None else ''))

    def recriar_palavras(self):
        self.ps = palavras_editor(self.texto.get('1.0', 'end-1c'))
        self.geracao += 1
        self.atualizar_palavras()

    def editar_palavra(self, event):
        row, col = self.tabela.identify_row(event.y), self.tabela.identify_column(event.x)
        if not row:
            return
        p = self.ps[int(row)]
        if col == '#1':
            p['incluir'] = not p.get('incluir', True)
        elif col == '#5':
            if p.get('inicio') is None or p.get('fim') is None:
                self.erro('Preencha início e fim antes de confirmar a palavra.')
                return
            p['confirmado'] = not p.get('confirmado', False)
        elif col in ('#3', '#4'):
            campo = 'inicio' if col == '#3' else 'fim'
            valor = simpledialog.askstring('Tempo da palavra', f"{campo} de {p['texto']}:",
                                            initialvalue=str(p.get(campo) or ''), parent=self)
            if valor is None:
                return
            try:
                p[campo] = tempo(valor) if valor.strip() else None
                p['confirmado'] = False
            except ValueError as e:
                self.erro(e)
        self.geracao += 1
        self.atualizar_palavras()

    def confirmar_palavras(self):
        selecionadas = self.tabela.selection()
        if not selecionadas:
            self.erro('Selecione as palavras que deseja confirmar após ouvir o áudio.')
            return
        for id in selecionadas:
            p = self.ps[int(id)]
            if p.get('inicio') is None or p.get('fim') is None or p['fim'] <= p['inicio']:
                self.erro(f"Preencha um intervalo válido para {p['texto']}.")
                return
        for id in selecionadas:
            self.ps[int(id)]['confirmado'] = True
        self.geracao += 1
        self.atualizar_palavras()

    def marcar_grupo(self):
        ids = sorted(int(x) for x in self.tabela.selection())
        if not ids or ids != list(range(ids[0], ids[-1]+1)):
            self.erro('Selecione palavras consecutivas.')
            return
        try:
            a,b = self.intervalo()
            # Marca só as fronteiras conhecidas. Distribuição é uma sugestão,
            # não confirmação acústica automática.
            pesos = [max(1, len(self.ps[i]['texto'])) for i in ids]
            t = a
            for i,peso in zip(ids, pesos):
                fim = t + (b-a)*peso/sum(pesos)
                self.ps[i].update(inicio=round(t,3), fim=round(fim,3), confirmado=False, origem='aproximacao_manual')
                t = fim
            self.atualizar_palavras()
            self.geracao += 1
            self.status.set('Grupo marcado aproximadamente. Ajuste e confirme as palavras após escutar.')
        except Exception as e:
            self.erro(e)

    def intervalo(self):
        a,b = tempo(self.inicio.get()), tempo(self.fim.get())
        if not 0 <= a < b <= self.sessao.duracao + .001:
            raise ValueError('Selecione início e fim válidos dentro do áudio.')
        return a,b

    def aplicar(self, acao):
        if not self.item:
            self.erro('Selecione uma ocorrência ou um trecho na lista à esquerda.')
            return
        try:
            alvos = self.trechos.selection() if acao in ('associar', 'corrigir', 'remover') else ()
            novos = []
            if acao in ('inserir', 'corrigir'):
                a,b = self.intervalo()
                existentes = [b for b in self.sessao.blocos if b['id'] in alvos]
                if existentes and (a != existentes[0]['inicio'] or b != existentes[-1]['fim']):
                    if not messagebox.askyesno('Alteração dos tempos do trecho',
                            f"A seleção vai de {formatar_tempo(existentes[0]['inicio'])} a {formatar_tempo(existentes[-1]['fim'])}.\n"
                            f"Confirmar substituição pelo intervalo {formatar_tempo(a)} a {formatar_tempo(b)}?", parent=self):
                        return
                atuais = palavras_editor(self.texto.get('1.0','end-1c'))
                if [p['texto'] for p in atuais] != [p['texto'] for p in self.ps] and not any(p.get('confirmado') for p in self.ps):
                    self.ps = atuais
                novos = [dict(texto=self.texto.get('1.0','end-1c').strip(), inicio=a, fim=b, palavras=self.ps)]
            if acao == 'remover' and not messagebox.askyesno('Remover trechos',
                    'Excluir os trechos selecionados da legenda validada? Descartar uma pendência não exige isso.', parent=self):
                return
            if acao == 'associar':
                duplicadas = [k for k,d in self.sessao.dados['decisoes'].items() if k != self.item['id']
                              and d['acao'] == 'associar' and set(alvos) & set(d['alvos'])]
                if duplicadas and not messagebox.askyesno('Verificar repetição',
                        'Este trecho já foi associado a outra ocorrência do TXT. Confirmar que corresponde também a esta ocorrência?', parent=self):
                    return
            self.guardar_rascunho()
            self.sessao.aplicar(self.item['id'], acao, alvos=alvos, novos=novos)
            self.geracao += 1
            self.atualizar_listas()
            self.status.set('Decisão salva. Confirme as demais ocorrências antes de continuar, ou continue com pendências.')
        except Exception as e:
            self.erro(e)

    def dividir(self):
        """Divisão explícita de um bloco em dois, em palavra e tempo escolhidos."""
        ids = self.trechos.selection()
        selecionadas = self.tabela.selection()
        if len(ids) != 1 or not selecionadas or not self.player:
            self.erro('Selecione um trecho, carregue-o por duplo clique e selecione a primeira palavra da segunda parte. Posicione o áudio no corte.')
            return
        try:
            k = min(int(i) for i in selecionadas)
            if k == 0:
                raise ValueError('O corte deve deixar palavras em ambas as partes.')
            a,b = self.intervalo()
            t = round(self.player.posicao, 3)
            if not a < t < b:
                raise ValueError('O cursor do áudio precisa estar dentro do trecho.')
            if not messagebox.askyesno('Dividir trecho', f'Dividir em {formatar_tempo(t)} antes de {self.ps[k]["texto"]}?', parent=self):
                return
            partes = [dict(texto=' '.join(p['texto'] for p in grupo), inicio=x, fim=y, palavras=grupo)
                      for grupo,x,y in [(self.ps[:k],a,t),(self.ps[k:],t,b)]]
            self.sessao.aplicar(self.item['id'], 'substituir', alvos=ids, novos=partes)
            self.atualizar_listas()
            self.status.set('Trecho dividido. Edite os intervalos ou o texto de cada parte para completar a legenda.')
        except Exception as e:
            self.erro(e)

    def desfazer(self):
        try:
            self.sessao.desfazer()
            self.atualizar_listas()
        except Exception as e:
            self.erro(e)

    def historico(self):
        janela = tk.Toplevel(self)
        janela.title('Histórico de decisões — consulta')
        janela.geometry('850x550')
        texto = tk.Text(janela, wrap='word')
        texto.pack(fill='both', expand=True)
        texto.insert('end', 'Fontes alteradas: consulte as decisões antigas e reaplique explicitamente nos trechos atuais.\n\n')
        texto.insert('end', json.dumps(dict(historico=self.sessao.dados['historico'],
                                           revisoes_anteriores=self.sessao.dados['revisoes_anteriores']), ensure_ascii=False, indent=2))
        texto.configure(state='disabled')

    def carregar_audio(self):
        try:
            from audio_revisao import decodificar
            self.eventos.put(('audio', decodificar(self.sessao.voz)))
        except Exception as e:
            self.eventos.put(('erro', str(e)))

    def play(self):
        if not self.player:
            return
        try:
            if self.player.tocando:
                self.player.pausar()
            else:
                self.player.reproduzir()
        except Exception as e:
            self.erro(e)

    def pular(self, delta):
        if self.player:
            try:
                self.player.buscar(self.player.posicao+delta)
            except Exception as e:
                self.erro(e)

    def ouvir_intervalo(self):
        try:
            a,b = self.intervalo()
            if self.player:
                self.player.reproduzir(a,b,self.repetir.get())
        except Exception as e:
            self.erro(e)

    def ouvir_palavras(self):
        ps = [self.ps[int(i)] for i in self.tabela.selection()]
        if not ps or any(p.get('inicio') is None or p.get('fim') is None for p in ps):
            self.erro('Selecione palavras com tempos preenchidos.')
            return
        try:
            if self.player:
                self.player.reproduzir(max(0,min(p['inicio'] for p in ps)-.3),
                    min(self.player.duracao,max(p['fim'] for p in ps)+.3),self.repetir.get())
        except Exception as e:
            self.erro(e)

    def marcar(self, var):
        if self.player:
            var.set(formatar_tempo(self.player.posicao))

    def zoom_intervalo(self):
        try:
            a,b = self.intervalo()
            self.zoom = max(0,a-2),min(self.sessao.duracao,b+2)
            self.desenhar_onda()
        except Exception as e:
            self.erro(e)

    def zoom_total(self):
        self.zoom = (0.,self.sessao.duracao)
        self.desenhar_onda()

    def desenhar_onda(self):
        self.onda.delete('all')
        if self.audio is None:
            return
        from audio_revisao import envelope
        w,h = max(1,self.onda.winfo_width()),self.onda.winfo_height()
        a,b = self.zoom
        ys = envelope(self.audio[int(a*self.player.taxa):int(b*self.player.taxa)], min(w,1400))
        for i,(minimo,maximo) in enumerate(ys):
            x = i*w/max(1,len(ys))
            self.onda.create_line(x,h/2-minimo*h*.45,x,h/2-maximo*h*.45,fill='#38bdf8')

    def _tempo_x(self, x):
        a,b = self.zoom
        return max(a,min(b,a+(b-a)*x/max(1,self.onda.winfo_width())))

    def inicio_selecao(self, event):
        self.arraste = event.x

    def arrastar_selecao(self, event):
        a,b = sorted([self._tempo_x(self.arraste),self._tempo_x(event.x)])
        self.inicio.set(formatar_tempo(a))
        self.fim.set(formatar_tempo(b))

    def fim_selecao(self, event):
        if abs(event.x-self.arraste) < 4 and self.player:
            try:
                self.player.buscar(self._tempo_x(event.x))
            except Exception as e:
                self.erro(e)

    def alinhar(self):
        if self.alinhando:
            return
        try:
            a,b = self.intervalo()
            texto = self.texto.get('1.0','end-1c').strip()
            if not palavras_editor(texto):
                raise ValueError('Informe o texto a alinhar.')
            self.guardar_rascunho()
            self.sessao.salvar()
            self.alinhando = True
            self.worker_cancelar.clear()
            self.botao_alinhar.configure(state='disabled')
            self.status.set('Buscando tempos na região selecionada. Aguarde ou cancele a busca.')
            pedido = dict(voz=str(self.sessao.voz),texto=texto,inicio=a,fim=b)
            threading.Thread(target=self._alinhar, args=(pedido,self.geracao),daemon=False).start()
        except Exception as e:
            self.erro(e)

    def _alinhar(self, pedido, geracao):
        try:
            with tempfile.TemporaryDirectory(prefix='revisao_alinhar_') as temp:
                pasta = Path(temp)
                entrada,saida = pasta/'pedido.json',pasta/'resultado.json'
                entrada.write_text(json.dumps(pedido, ensure_ascii=False),encoding='utf-8')
                with (pasta/'log.txt').open('w+',encoding='utf-8') as log:
                    proc = subprocess.Popen([sys.executable,str(Path(__file__).with_name('alinhar_revisao.py')),str(entrada),str(saida)],
                        stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    self.processo = proc
                    while proc.poll() is None:
                        if self.worker_cancelar.wait(.1):
                            proc.terminate()
                            try:
                                proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait()
                            break
                    if self.worker_cancelar.is_set():
                        self.eventos.put(('cancelado',None))
                    elif proc.returncode:
                        log.seek(0)
                        raise RuntimeError(log.read()[-4000:])
                    else:
                        self.eventos.put(('alinhamento',(geracao,pedido,json.loads(saida.read_text(encoding='utf-8')))))
        except Exception as e:
            self.eventos.put(('erro',str(e)))
        finally:
            self.processo = None
            self.eventos.put(('fim_busca',None))

    def cancelar_busca(self):
        self.worker_cancelar.set()

    def atualizar(self):
        if self.fechada:
            return
        while True:
            try:
                tipo,dados = self.eventos.get_nowait()
            except queue.Empty:
                break
            if tipo == 'audio':
                from audio_revisao import PlayerVoz
                self.audio,taxa = dados
                self.player = PlayerVoz(self.audio,taxa)
                self.desenhar_onda()
            elif tipo == 'alinhamento':
                geracao,pedido,ps = dados
                try:
                    intervalo_atual = self.intervalo()
                except ValueError:
                    intervalo_atual = None
                if (geracao == self.geracao and pedido['texto'] == self.texto.get('1.0','end-1c').strip()
                        and intervalo_atual == (pedido['inicio'], pedido['fim'])):
                    self.ps = ps
                    self.atualizar_palavras()
                    self.avancado.set(True)
                    self.mostrar_avancado()
                    self.status.set('Sugestões prontas. Ouça, ajuste e confirme as palavras antes de aplicar a inserção/correção.')
                else:
                    self.status.set('A seleção/texto mudou durante a busca. Sugestões antigas não foram aplicadas; repita a busca.')
            elif tipo == 'erro':
                self.erro(dados)
            elif tipo == 'cancelado':
                self.status.set('Busca cancelada; decisões preservadas.')
            elif tipo == 'fim_busca':
                self.alinhando = False
                self.botao_alinhar.configure(state='normal')
        if self.player:
            pos = self.player.atualizar()
            self.relogio.set(f'{formatar_tempo(pos)} / {formatar_tempo(self.player.duracao)}'
                            + (' · '+self.player.aviso if self.player.aviso else ''))
            a,b = self.zoom
            w,h = self.onda.winfo_width(),self.onda.winfo_height()
            self.onda.delete('marcador')
            x = (pos-a)/max(.001,b-a)*w
            if 0 <= x <= w:
                self.onda.create_line(x,0,x,h,fill='#f59e0b',width=2,tags='marcador')
            try:
                x1 = (tempo(self.inicio.get())-a)/(b-a)*w
                x2 = (tempo(self.fim.get())-a)/(b-a)*w
                self.onda.create_rectangle(x1,2,x2,h-2,outline='#10b981',width=2,tags='marcador')
            except ValueError:
                pass
        self.after(80,self.atualizar)

    def salvar_sair(self):
        try:
            self.guardar_rascunho()
            self.sessao.salvar()
            self.fechar(None)
        except Exception as e:
            self.erro(e)

    def continuar(self):
        try:
            self.guardar_rascunho()
            resultado = self.sessao.publicar()
            self.fechar(resultado)
        except Exception as e:
            self.erro(e)

    def fechar(self, resultado=None):
        if self.fechada:
            return
        self.fechada = True
        self.worker_cancelar.set()
        if self.player:
            self.player.fechar()
        self.destroy()
        if self.ao_fechar:
            self.ao_fechar(resultado)


def main():
    import argparse
    from conversao_gui import validar_pasta
    parser = argparse.ArgumentParser(description='Revisão manual de letra consolidada')
    parser.add_argument('pasta',type=Path)
    args = parser.parse_args()
    fontes = validar_pasta(args.pasta)
    sessao = SessaoRevisao(args.pasta,fontes['voz'])
    root = tk.Tk()
    root.withdraw()
    JanelaRevisao(root,sessao,lambda resultado: root.destroy())
    root.mainloop()


if __name__ == '__main__':
    main()
