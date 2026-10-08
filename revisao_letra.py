"""Revisão persistente, independente da interface e do motor de alinhamento.

O SRT automático é imutável. Decisões editam uma cópia e só são publicadas
após validar texto, duração, sobreposição e identidade das fontes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from consolidar_letra import ler_srt, tokenizar, chave
from normalizacao_legenda import normalizar_frase

MARCA_MANUAL = "tempo_confirmado_manualmente"


def hash_arquivo(caminho):
    h = hashlib.sha256()
    with Path(caminho).open('rb') as f:
        for parte in iter(lambda: f.read(1024 * 1024), b''):
            h.update(parte)
    return h.hexdigest()


def instante():
    return datetime.now(timezone.utc).isoformat()


def gravar_json(caminho, dados):
    caminho = Path(caminho)
    fd, temp = tempfile.mkstemp(prefix='.' + caminho.name, dir=caminho.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(dados, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, caminho)
    finally:
        Path(temp).unlink(missing_ok=True)


def tempo(valor):
    """Segundos ou mm:ss,mmm / hh:mm:ss,mmm."""
    partes = str(valor).strip().replace(',', '.').split(':')
    if len(partes) > 3:
        raise ValueError('Tempo inválido. Use segundos ou mm:ss,mmm.')
    numeros = [float(x) for x in partes]
    if any(not math.isfinite(x) or x < 0 for x in numeros):
        raise ValueError('O tempo deve ser finito e positivo.')
    if len(partes) > 1 and any(x >= 60 for x in numeros[1:]):
        raise ValueError('Minutos/segundos fora do intervalo.')
    return round(sum(x * 60 ** i for i, x in enumerate(reversed(numeros))), 3)


def formatar_tempo(segundos, srt=False):
    ms = round(segundos * 1000)
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    if srt:
        h, m = divmod(m, 60)
        return f'{h:02}:{m:02}:{s:02},{ms:03}'
    return f'{m:02}:{s:02},{ms:03}'


def palavras_editor(texto):
    return [dict(texto=t.texto, incluir=True, confirmado=False, inicio=None, fim=None)
            for t in tokenizar(texto)]


def validar_blocos(blocos, duracao):
    if not math.isfinite(duracao) or duracao <= 0:
        raise ValueError('Duração do áudio inválida.')
    ids = set()
    anterior = None
    for b in sorted(blocos, key=lambda b: (b['inicio'], b['fim'])):
        if b['id'] in ids:
            raise ValueError('Identificador de trecho repetido.')
        ids.add(b['id'])
        a, z = b['inicio'], b['fim']
        if not (math.isfinite(a) and math.isfinite(z) and 0 <= a < z <= duracao + .001):
            raise ValueError('Trecho com duração inválida ou fora do áudio.')
        if not tokenizar(b['texto']):
            raise ValueError('Um trecho precisa conter palavras.')
        if anterior and a < anterior['fim'] - .00001:
            raise ValueError(f"Conflito com '{anterior['texto']}' ({formatar_tempo(anterior['inicio'])}–"
                             f"{formatar_tempo(anterior['fim'])}). Associe, substitua ou divida o trecho.")
        ps = b.get('palavras', [])
        if ps and [chave(p['texto']) for p in ps] != [chave(t.texto) for t in tokenizar(b['texto'])]:
            raise ValueError('A tabela de palavras não corresponde ao texto. Recrie a tabela.')
        ultimo_fim, ultimo_indice = a, -1
        for i, p in enumerate(ps):
            if not p.get('confirmado'):
                continue
            x, y = p.get('inicio'), p.get('fim')
            if not (isinstance(x, (int, float)) and isinstance(y, (int, float))
                    and math.isfinite(x) and math.isfinite(y) and a <= x < y <= z):
                raise ValueError(f"Tempo confirmado inválido: {p['texto']}.")
            if x < ultimo_fim or (i > ultimo_indice + 1 and x <= ultimo_fim):
                raise ValueError('Palavras sobrepostas ou sem espaço para alinhar palavras intermediárias.')
            ultimo_fim, ultimo_indice = y, i
        if ps and ultimo_indice >= 0 and ultimo_indice < len(ps) - 1 and ultimo_fim >= z:
            raise ValueError('Falta espaço após a última palavra confirmada.')
        anterior = b


class SessaoRevisao:
    def __init__(self, pasta, voz=None):
        self.pasta = Path(pasta).resolve()
        self.caminho = self.pasta / 'revisao_letra.json'
        self.automatico = self.pasta / 'letra_consolidada.srt'
        self.relatorio = json.loads(self.automatico.with_suffix('.json').read_text(encoding='utf-8'))
        if self.relatorio.get('versao', 0) < 5:
            raise ValueError('Execute novamente a consolidação antes da revisão (relatório versão 5).')
        fontes = self.relatorio.get('fontes', {})
        self.voz = Path(voz or fontes.get('voz', {}).get('caminho', ''))
        self.arquivos = {'consolidada': self.automatico, 'txt': self.pasta / 'letra.txt',
                        'srt': self.pasta / 'letra.srt', 'voz': self.voz}
        self.fontes = {k: hash_arquivo(v) for k, v in self.arquivos.items()}
        for k in ('txt', 'srt', 'voz'):
            if fontes.get(k, {}).get('sha256') != self.fontes[k]:
                raise ValueError(f'A fonte {k} mudou desde a consolidação. Consolide novamente antes de revisar.')
        self.duracao = float(self.relatorio['duracao_audio'])
        self.base = [dict(id=f'srt:{b.indice}', inicio=b.inicio, fim=b.fim, texto=b.texto,
                          palavras=[]) for b in ler_srt(self.automatico)]
        self.itens = self._itens()
        antiga = json.loads(self.caminho.read_text(encoding='utf-8')) if self.caminho.exists() else None
        if antiga and antiga.get('versao') != 1:
            raise ValueError('Versão de revisão desconhecida; o arquivo existente foi preservado.')
        self.reconciliar = bool(antiga and antiga['fontes'] != self.fontes)
        if antiga and not self.reconciliar:
            self.dados = antiga
        else:
            self.dados = dict(versao=1, fontes=self.fontes, criado=instante(), blocos=copy.deepcopy(self.base),
                              decisoes={}, rascunhos={}, historico=[], revisoes_anteriores=[])
            if antiga:
                # A versão inteira continua consultável. Nunca reaplicar tempos de outro áudio.
                historico = antiga.pop('revisoes_anteriores', [])
                self.dados['revisoes_anteriores'] = historico + [antiga]
        validar_blocos(self.blocos, self.duracao)

    @property
    def blocos(self):
        return self.dados['blocos']

    @property
    def pendentes(self):
        return [i for i in self.itens if self.dados['decisoes'].get(i['id'], {}).get('acao')
                in (None, 'depois')]

    def _itens(self):
        texto = self.arquivos['txt'].read_text(encoding='utf-8-sig')
        ts = tokenizar(texto)
        faltantes = sorted({i for p in self.relatorio.get('pendencias', []) for i in p.get('tokens_txt', [])})
        grupos = []
        for i in faltantes:
            if not grupos or i != grupos[-1][-1] + 1 or ts[i].unidade != ts[grupos[-1][-1]].unidade:
                grupos.append([])
            grupos[-1].append(i)
        itens = [dict(id=f'txt:{g[0]}:{g[-1]+1}', texto=texto[ts[g[0]].inicio:ts[g[-1]].fim],
                      linha=ts[g[0]].unidade + 1, tokens=g, motivo='TXT sem associação confirmada', tipo='txt')
                 for g in grupos]
        for p in self.relatorio.get('pendencias', []):
            if 'bloco_srt' not in p:
                continue
            orig = p['bloco_srt']
            # A numeração publicada pode mudar após inserir frases.
            for n, b in enumerate(self.relatorio['blocos'], 1):
                if b.get('bloco_original') == orig:
                    itens.append(dict(id=f'pendencia:srt:{n}', bloco=f'srt:{n}', texto=b['texto'],
                                      motivo=p['motivo'], tipo='srt'))
        return itens

    def candidatos(self, item):
        from rapidfuzz.fuzz import ratio
        texto = chave(item['texto'])
        opcoes = []
        for i, b in enumerate(self.blocos):
            for quantidade in range(1, 4):
                grupo = self.blocos[i:i + quantidade]
                if len(grupo) != quantidade:
                    break
                score = ratio(texto, chave(' '.join(x['texto'] for x in grupo)))
                opcoes.append(dict(ids=[x['id'] for x in grupo], score=round(score, 1),
                                   inicio=grupo[0]['inicio'], fim=grupo[-1]['fim'],
                                   texto=' '.join(x['texto'] for x in grupo)))
        return sorted(opcoes, key=lambda x: (-x['score'], x['inicio']))[:12]

    def verificar_fontes(self):
        if {k: hash_arquivo(v) for k, v in self.arquivos.items()} != self.fontes:
            raise ValueError('As fontes mudaram durante a revisão. Feche e reabra após consolidar novamente.')

    def salvar(self):
        self.verificar_fontes()
        self.dados['atualizado'] = instante()
        self.dados['pendencias'] = copy.deepcopy(self.pendentes)
        self.dados['resumo'] = dict(ocorrencias_pendentes=len(self.pendentes), blocos=len(self.blocos),
                                    palavras_confirmadas=sum(p.get('confirmado', False)
                                        for b in self.blocos for p in b.get('palavras', [])))
        gravar_json(self.caminho, self.dados)

    def aplicar(self, item_id, acao, *, alvos=(), novos=()):
        """Edição transacional. Substituir admite vários trechos (divisão explícita)."""
        if acao not in {'associar', 'corrigir', 'inserir', 'descartar', 'depois', 'remover', 'substituir'}:
            raise ValueError('Ação desconhecida.')
        ids = {b['id'] for b in self.blocos}
        if not set(alvos) <= ids:
            raise ValueError('Trecho não existe mais. Atualize a seleção.')
        if acao in {'associar', 'corrigir', 'remover', 'substituir'} and not alvos:
            raise ValueError('Selecione o(s) trecho(s) da legenda.')
        if acao == 'inserir' and alvos:
            raise ValueError('Inserção não remove trechos existentes.')
        alterados = copy.deepcopy(self.blocos)
        if acao in {'corrigir', 'remover', 'substituir'}:
            alterados = [b for b in alterados if b['id'] not in alvos]
        if acao in {'corrigir', 'inserir', 'substituir'}:
            if not novos:
                raise ValueError('Informe o trecho a publicar.')
            for numero, original in enumerate(novos):
                b = copy.deepcopy(original)
                b['texto'] = ' '.join(b['texto'].split())
                b['id'] = f'edicao:{item_id}:{len(self.dados["historico"])}:{numero}'
                b['inicio'], b['fim'] = tempo(b['inicio']), tempo(b['fim'])
                ps = b.get('palavras', [])
                if ps:
                    if [chave(p['texto']) for p in ps] != [chave(t.texto) for t in tokenizar(b['texto'])]:
                        raise ValueError('Texto alterado: recrie a tabela de palavras antes de aplicar.')
                    incluidos = [p for p in ps if p.get('incluir', True)]
                    if len(incluidos) != len(ps):
                        b['texto'] = ' '.join(p['texto'] for p in incluidos)
                    b['palavras'] = incluidos
                    for p in incluidos:
                        if p.get('confirmado'):
                            p['inicio'], p['fim'] = tempo(p['inicio']), tempo(p['fim'])
                alterados.append(b)
        alterados.sort(key=lambda b: b['inicio'])
        validar_blocos(alterados, self.duracao)
        antes = copy.deepcopy(self.dados)
        decisao = dict(acao=acao, alvos=list(alvos), novos=copy.deepcopy(list(novos)), data=instante())
        self.dados['historico'].append(dict(item=item_id, decisao=decisao,
                                          blocos_antes=copy.deepcopy(self.blocos),
                                          decisoes_antes=copy.deepcopy(self.dados['decisoes'])))
        self.dados['blocos'] = alterados
        self.dados['decisoes'][item_id] = decisao
        # Remover/substituir uma associação anterior a torna pendente novamente.
        for k, d in list(self.dados['decisoes'].items()):
            if k != item_id and d['acao'] == 'associar' and not set(d['alvos']) <= {b['id'] for b in alterados}:
                self.dados['decisoes'][k] = dict(acao='depois', motivo='Trecho associado foi alterado.')
        try:
            self.salvar()
        except Exception:
            self.dados = antes
            raise

    def desfazer(self):
        if not self.dados['historico']:
            return
        antes = copy.deepcopy(self.dados)
        ultima = self.dados['historico'].pop()
        self.dados['blocos'] = ultima['blocos_antes']
        self.dados['decisoes'] = ultima['decisoes_antes']
        try:
            self.salvar()
        except Exception:
            self.dados = antes
            raise

    def publicar(self):
        self.verificar_fontes()
        validar_blocos(self.blocos, self.duracao)
        if not self.blocos:
            raise ValueError('Não há nenhum trecho para converter.')
        self.salvar()
        publicados = copy.deepcopy(self.blocos)
        for b in publicados:
            b['texto'] = normalizar_frase(' '.join(b['texto'].split()))
            # Manifesto e SRT precisam ter a mesma grafia, inclusive quando
            # as palavras já têm tempos humanos confirmados.
            for p, t in zip(b.get('palavras', []), tokenizar(b['texto'])):
                p['texto'] = t.texto
        texto = '\n\n'.join(f"{i}\n{formatar_tempo(b['inicio'], True)} --> {formatar_tempo(b['fim'], True)}\n{' '.join(b['texto'].split())}"
                            for i, b in enumerate(publicados, 1)) + '\n'
        destino = self.pasta / 'letra_validada.srt'
        manifesto = dict(versao=1, fontes=self.fontes, sha256_srt=hashlib.sha256(texto.encode('utf-8')).hexdigest(),
                         pendencias=len(self.pendentes), blocos={str(i): b.get('palavras', [])
                                                               for i, b in enumerate(publicados, 1)})
        # O consumidor exige o hash do SRT. Uma interrupção entre os replaces
        # é detectada, nunca mistura tempos de publicações diferentes.
        fd, temp = tempfile.mkstemp(prefix='.letra_validada_', dir=self.pasta)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
                f.write(texto)
                f.flush()
                os.fsync(f.fileno())
            gravar_json(destino.with_suffix('.json'), manifesto)
            os.replace(temp, destino)
        finally:
            Path(temp).unlink(missing_ok=True)
        return destino, destino.with_suffix('.json')


def carregar_tempos_confirmados(manifesto, srt, voz):
    m = json.loads(Path(manifesto).read_text(encoding='utf-8'))
    if m.get('versao') != 1 or m.get('sha256_srt') != hash_arquivo(srt) or m['fontes']['voz'] != hash_arquivo(voz):
        raise ValueError('Revisão incompatível com o SRT ou a voz. Republique a revisão.')
    return {int(k): v for k, v in m['blocos'].items() if any(p.get('confirmado') for p in v)}


def propor_tempos(alinhador, texto, inicio, fim):
    """Interface do alinhador substituível; sugestões nunca viram confirmação sozinhas."""
    from consolidar_letra import aproveitar_palavras
    ps = palavras_editor(texto)
    obtidas = alinhador.alinhar(texto, inicio, fim)
    mapeadas = aproveitar_palavras(obtidas, [p['texto'] for p in ps], inicio, fim)
    for p, sugestao in zip(ps, mapeadas):
        if sugestao is not None:
            p.update(inicio=round(sugestao.inicio, 3), fim=round(sugestao.fim, 3),
                     score=float(sugestao.score) if sugestao.score is not None else None, origem='alinhador')
    return ps
