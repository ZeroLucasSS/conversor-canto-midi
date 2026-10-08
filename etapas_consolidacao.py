"""Preservação, correção textual e inserção acústica são operações distintas.

Não altera tempos de blocos existentes. Um trecho novo só é exportado com
tempos retornados pelo alinhador dentro de uma lacuna livre do SRT.
"""
from __future__ import annotations

import consolidar_letra as c


def planejar_lacunas(blocos, consultas, ref, duracao, janela_maxima):
    """Conta ocorrências pelo intervalo de tokens, inclusive frases idênticas.

    Retornos no TXT indicam repetição, não autorização para inserir o restante
    da letra. Blocos sem correspondência não são atravessados silenciosamente.
    """
    lacunas = []
    pares = [(None, 0)] + [(i, i + 1) for i in range(len(blocos) - 1)] + [(len(blocos)-1, None)]
    for esquerda, direita in pares:
        q = consultas[esquerda] if esquerda is not None else None
        r = consultas[direita] if direita is not None else None
        if (q and q['txt_fim'] is None) or (r and r['txt_inicio'] is None):
            continue
        a = q['txt_fim'] if q else 0
        b = r['txt_inicio'] if r else len(ref)
        if a >= b:
            continue
        inicio = blocos[esquerda].fim if q else 0.
        fim = blocos[direita].inicio if r else duracao
        motivo = None
        if fim - inicio <= .01:
            motivo = 'sem_espaco_temporal_entre_blocos'
        elif fim - inicio > min(janela_maxima, max(30., 2. * (b-a))):
            motivo = 'lacuna_excede_limite_de_busca'
        elif any(x is not None and x['score'] < .75 for x in (q, r)):
            motivo = 'referencias_textuais_insuficientes'
        lacunas.append(dict(id=len(lacunas)+1, txt_inicio=a, txt_fim=b,
                            inicio=inicio, fim=fim,
                            bloco_anterior=blocos[esquerda].indice if q else None,
                            bloco_seguinte=blocos[direita].indice if r else None,
                            limite_busca=min(janela_maxima, max(30., 2. * (b-a))),
                            motivo_nao_pesquisado=motivo))
    return lacunas


def _atividade(alinhador, a, b):
    """Energia vocal auxiliar: silêncio não confirma uma inserção forçada.

    O sinal pode conter instrumentos/ruído; atividade não certifica fonemas.
    Motores alternativos sem áudio conservam explicitamente essa limitação.
    """
    if not hasattr(alinhador, 'audio'):
        return None
    import numpy as np
    audio = alinhador.audio
    trecho = np.asarray(audio[max(0, int(a*16000)):int(b*16000)])
    if trecho.size == 0:
        return 0.
    n = 320
    quadros = trecho[:len(trecho)//n*n].reshape(-1, n)
    if len(quadros) == 0:
        return float(np.sqrt(np.mean(trecho**2)) > 1e-4)
    return float(np.mean(np.sqrt(np.mean(quadros**2, axis=1)) > 1e-4))


def recuperar_lacuna(g, texto, ref, alinhador, score_minimo):
    registro = dict(g, estado='nao_pesquisado', tentativas=[], inseridos=[], tokens_recuperados=[])
    if g['motivo_nao_pesquisado']:
        return registro
    a, b = g['txt_inicio'], g['txt_fim']
    esperadas = [t.texto for t in ref[a:b]]
    registro['texto'] = c.trecho_txt(texto, ref, a, b)
    registro['estado'] = 'pesquisado_sem_confirmacao'
    tentativa = dict(janela=[g['inicio'], g['fim']], texto=' '.join(esperadas))
    registro['tentativas'].append(tentativa)
    try:
        ps = alinhador.alinhar(' '.join(esperadas), g['inicio'], g['fim'])
        tentativa['palavras'] = [c._palavra_json(p) for p in ps]
        escolhidas = c.aproveitar_palavras(ps, esperadas, g['inicio'], g['fim'])
    except Exception as erro:
        tentativa['erro'] = f'{type(erro).__name__}: {erro}'
        return registro
    k = 0
    while k < len(esperadas):
        if escolhidas[k] is None:
            k += 1
            continue
        j = k + 1
        while j < len(esperadas) and escolhidas[j] is not None and ref[a+j].unidade == ref[a+k].unidade:
            j += 1
        palavras = escolhidas[k:j]
        inicio, fim = palavras[0].inicio, palavras[-1].fim
        atividade = _atividade(alinhador, inicio, fim)
        scores = [p.score for p in palavras if c._numero(p.score)]
        # Scores baixos individuais não impedem publicação. Um trecho sem
        # suporte algum do modelo ou predominantemente silencioso não entra.
        suporte = bool(scores) and max(scores) >= .10
        if suporte and (atividade is None or atividade >= .20):
            registro['inseridos'].append(dict(inicio=inicio, fim=fim,
                texto=c.trecho_txt(texto, ref, a+k, a+j), origem='insercao_acustica',
                lacuna=g['id'], txt_inicio=a+k, txt_fim=a+j,
                score_minimo=float(min(scores)), atividade_audio=atividade,
                palavras_baixa_confianca=sum(bool(not c._numero(p.score) or p.score < score_minimo) for p in palavras)))
            registro['tokens_recuperados'].extend(range(a+k, a+j))
        else:
            tentativa.setdefault('trechos_nao_confirmados', []).append(
                dict(txt_inicio=a+k, txt_fim=a+j, motivo='suporte_acustico_insuficiente', atividade_audio=atividade))
        k = j
    n = len(registro['tokens_recuperados'])
    if n:
        registro['estado'] = 'recuperado' if n == len(esperadas) else 'parcialmente_recuperado'
    return registro


def consolidar_etapas(blocos, texto, alinhador, *, score_minimo=.30, margem=.40,
                      janela_maxima=90., progresso=None):
    if not blocos or not c.tokenizar(texto):
        raise ValueError('SRT e TXT precisam conter palavras.')
    if not c._numero(janela_maxima) or janela_maxima <= 0 or not c._numero(margem) or margem < 0:
        raise ValueError('Limites de busca inválidos.')
    if not c._numero(score_minimo) or not 0 <= score_minimo <= 1:
        raise ValueError('Score mínimo inválido.')
    duracao = alinhador.duracao_audio
    if not c._numero(duracao) or duracao <= 0 or any(not 0 <= b.inicio < b.fim <= duracao for b in blocos):
        raise ValueError('SRT contém tempos fora do áudio.')
    if any(b.inicio < a.fim for a,b in zip(blocos,blocos[1:])):
        raise ValueError('Blocos fora de ordem ou sobrepostos.')
    plano = c.planejar_estrutura(blocos, texto)
    ref = c.tokenizar(texto)
    saida, auditoria, pendencias, avisos, usados = [], [], [], [], set()
    if progresso:
        progresso('Etapas 1 e 2: preservação e correção textual, sem alterar os tempos do SRT.')
    for bloco, q in zip(blocos, plano['consultas']):
        motivo = q['aviso']
        novo = bloco.texto
        if motivo is None:
            _, _, comp = c.preparar_comparacao([bloco], q['texto'])
            if any(d['tipo'] == 'somente_srt' for d in comp['divergencias']):
                motivo = 'texto_exclusivo_srt_preservado'
            else:
                novo = q['texto']
            # Mesmo se houver ad-libs exclusivos, o trecho correspondente
            # não deve ser reinserido como se tivesse sido omitido inteiro.
            usados.update(range(q['txt_inicio'], q['txt_fim']))
        origem = 'texto_corrigido' if novo != bloco.texto else 'original_preservado'
        saida.append(dict(inicio=bloco.inicio, fim=bloco.fim, texto=novo,
                          origem=origem, bloco_original=bloco.indice))
        auditoria.append(dict(bloco_srt=bloco.indice, inicio_original=bloco.inicio,
                              fim_original=bloco.fim, texto_original=bloco.texto,
                              texto_publicado=novo, tratamento=origem, aviso=motivo))
        if motivo:
            pendencias.append(dict(bloco_srt=bloco.indice, motivo=motivo))
            avisos.append(f"Bloco {bloco.indice}: {motivo.replace('_', ' ')}.")
    lacunas = planejar_lacunas(blocos, plano['consultas'], ref, duracao, janela_maxima)
    recuperacoes = []
    for g in lacunas:
        if progresso:
            progresso(f"Etapa 3: lacuna {g['id']}/{len(lacunas)}, "
                      f"{c.timestamp(g['inicio'])}–{c.timestamp(g['fim'])}.")
        r = recuperar_lacuna(g, texto, ref, alinhador, score_minimo)
        recuperacoes.append(r)
        saida.extend(r['inseridos'])
        usados.update(r['tokens_recuperados'])
        if r['estado'] != 'recuperado':
            pendencias.append(dict(lacuna=g['id'], motivo=r['estado'], detalhe=g['motivo_nao_pesquisado']))
            avisos.append(f"Lacuna {g['id']}: {r['estado'].replace('_', ' ')} "
                          f"({c.timestamp(g['inicio'])}–{c.timestamp(g['fim'])}).")
        for b in r['inseridos']:
            if b['palavras_baixa_confianca']:
                avisos.append(f"Inserção em {c.timestamp(b['inicio'])}: "
                              f"{b['palavras_baixa_confianca']} palavra(s) com baixa confiança; mantidas.")
                pendencias.append(dict(lacuna=g['id'], motivo='insercao_baixa_confianca', texto=b['texto']))
    sem_tempo = sorted(set(range(len(ref))) - usados)
    pesquisados = {i for r in recuperacoes if r['tentativas'] for i in range(r['txt_inicio'], r['txt_fim'])}
    if sem_tempo:
        pendencias.append(dict(motivo='texto_txt_sem_tempo', tokens_txt=sem_tempo))
        # Mostra o conteúdo, não somente índices abstratos.
        for linha in sorted({ref[i].unidade for i in sem_tempo}):
            ids = [i for i in sem_tempo if ref[i].unidade == linha]
            avisos.append(f"TXT linha {linha+1}, sem tempo: " + ' '.join(ref[i].texto for i in ids))
    saida.sort(key=lambda b:b['inicio'])
    if any(round(b['inicio']*1000) < round(a['fim']*1000) for a,b in zip(saida,saida[1:])):
        raise ValueError('Inserções sobrepõem blocos existentes.')
    return dict(versao=5, status='pendente' if pendencias else 'consolidado',
        estrategia='preservar_corrigir_inserir', motor=alinhador.nome, duracao_audio=duracao,
        scores_sao_probabilidades=False, aprovacao_musical_automatica=False,
        parametros=dict(score_minimo=score_minimo, janela_maxima=janela_maxima,
                        score_suporte_insercao=.10, atividade_minima_insercao=.20,
                        margem=margem, margem_aplicada=False),
        total_palavras_txt=len(ref), total_palavras_srt=sum(len(c.tokenizar(b.texto)) for b in blocos),
        metricas=dict(palavras_publicadas=sum(len(c.tokenizar(b['texto'])) for b in saida),
            blocos_srt_auditados=len(auditoria), blocos_srt_descartados=0,
            blocos_texto_corrigido=sum(b['origem']=='texto_corrigido' for b in saida),
            blocos_inseridos=sum(len(r['inseridos']) for r in recuperacoes),
            palavras_txt_sem_tempo=len(sem_tempo),
            palavras_txt_nao_pesquisadas=len(set(sem_tempo)-pesquisados),
            palavras_txt_pesquisadas_sem_tempo=len(set(sem_tempo)&pesquisados),
            palavras_baixa_confianca=sum(b['palavras_baixa_confianca'] for r in recuperacoes for b in r['inseridos']),
            tentativas_acusticas=sum(len(r['tentativas']) for r in recuperacoes)),
        comparacao=plano, auditoria_estrutura=auditoria, recuperacoes=recuperacoes,
        tentativas=[dict(t,lacuna=r['id']) for r in recuperacoes for t in r['tentativas']],
        pendencias=pendencias, blocos=saida, resumo_avisos=avisos)
