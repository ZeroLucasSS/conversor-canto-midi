"""Duas hipóteses do mesmo áudio, antes do alinhamento por palavra.

Não lê letras de referência. Os scores são do mesmo reconhecedor e não dos
alinhadores de idiomas diferentes; a decisão continua sendo uma estimativa.
"""
import math

from idioma_transcricao import evidencia_acustica, evidencia_textual, selecionar_idioma


def janelas_audio(audio, *, taxa=16000, minimo=12., maximo=20.):
    """Cobertura integral, com cortes de baixa energia e sem remover sustentações."""
    import numpy as np
    if (not all(math.isfinite(x) for x in (minimo, maximo, taxa)) or
            not 0 < minimo <= maximo or taxa <= 0 or round(minimo*taxa) < 1):
        raise ValueError('Limites de janela inválidos.')
    passo = max(1, round(.02 * taxa))
    inicio, total = 0, len(audio)
    while inicio < total:
        fim = min(total, inicio + round(maximo * taxa))
        if fim < total:
            candidatos = np.arange(inicio + round(minimo * taxa), fim + 1, passo)
            # 200 ms ao redor do corte: evita confundir passagem por zero com pausa.
            raio = max(1, round(.1 * taxa))
            energia = [float(np.mean(np.square(audio[max(inicio, p-raio):min(total, p+raio)],
                                               dtype=np.float64))) for p in candidatos]
            fim = int(candidatos[int(np.argmin(energia))])
        yield inicio, fim
        inicio = fim


def reconhecer_hipotese(backend, recorte, lingua):
    trechos, _ = backend.transcribe(
        recorte, language=lingua, task='transcribe', multilingual=False,
        vad_filter=False, chunk_length=30, condition_on_previous_text=False,
        temperature=(0., .2, .4), beam_size=5, no_speech_threshold=None,
        compression_ratio_threshold=2.4, log_prob_threshold=None)
    segmentos = []
    for s in trechos:
        segmentos.append(dict(start=float(s.start), end=float(s.end), text=s.text.strip(),
                              avg_logprob=float(s.avg_logprob),
                              no_speech_prob=float(s.no_speech_prob),
                              compression_ratio=float(s.compression_ratio),
                              temperature=float(getattr(s, 'temperature', 0.)),
                              tokens=len(s.tokens)))
    peso = sum(s['tokens'] for s in segmentos)
    media = lambda campo, vazio: (sum(s[campo]*s['tokens'] for s in segmentos)/peso
                                  if peso else vazio)
    return dict(idioma=lingua, segmentos=segmentos,
                texto=' '.join(s['text'] for s in segmentos).strip(),
                avg_logprob=media('avg_logprob', -10.),
                no_speech_prob=media('no_speech_prob', 1.),
                compression_ratio=max((s['compression_ratio'] for s in segmentos), default=0.))


def escolher_hipotese(hipoteses, probabilidades, *, tem_voz=True):
    """Compara hipóteses com evidência de língua, logprob e sinais de falha.

    Nenhum score é uma probabilidade calibrada de letra correta. Repetição e
    silêncio suspeitos são auditados, sem eliminar refrões só por repetirem.
    """
    acustica = evidencia_acustica(probabilidades)
    validas = [h for h in hipoteses if h['texto'].strip() and math.isfinite(h['avg_logprob'])]
    if not validas:
        return None, dict(motivo='sem_texto', revisao_recomendada=True)
    # O VAD é apenas uma confirmação para rejeitar silêncio. Nunca recorta a
    # janela: ataques suaves e vogais sustentadas continuam disponíveis ao ASR.
    if not tem_voz and all(h['no_speech_prob'] > .6 for h in validas):
        return None, dict(motivo='silencio_confirmado', revisao_recomendada=False,
                          audio=acustica, idioma_escolhido=None)
    # Loops podem ter logprob artificialmente alto. O limiar de compressão é
    # o mesmo sinal usado pelo Whisper para pedir uma nova decodificação.
    # A penalidade é limitada: repetição legítima de refrão não é veto ao texto.
    scores = {h['idioma']: h['avg_logprob'] - min(1., max(0., h['compression_ratio']-2.4)*.25)
              for h in validas}
    ordenadas = sorted(validas, key=lambda h: scores[h['idioma']], reverse=True)
    melhor = ordenadas[0]
    margem = (scores[melhor['idioma']]-scores[ordenadas[1]['idioma']]) if len(ordenadas)>1 else None
    motivo = 'probabilidade_do_reconhecimento'
    compativel = next((h for h in validas if h['idioma']==acustica['idioma']), None)
    if acustica['forte'] and compativel is not None:
        # Logprob condicional não compara fidelidade entre línguas: uma tradução
        # fluente pode receber score maior que a letra original. Áudio forte
        # tem prioridade quando sua hipótese não apresenta falha de decodificação.
        if compativel['avg_logprob'] >= -1. and compativel['compression_ratio'] <= 2.4:
            melhor = compativel
            motivo = 'idioma_acustico_forte'
        elif margem is not None and margem < .15:
            melhor = compativel
            motivo = 'desempate_acustico'
    return melhor, dict(
        motivo=motivo, idioma_escolhido=melhor['idioma'], margem_score=margem,
        scores_comparacao=scores,
        audio=acustica, revisao_recomendada=margem is None or margem < .15
        or melhor['idioma'] != ordenadas[0]['idioma']
        or not acustica['forte'] or melhor['idioma'] != acustica['idioma']
        or melhor['compression_ratio'] > 2.4 or melhor['avg_logprob'] < -1.)


def transcrever_bilingue(backend, audio, *, registrar=None):
    """Decodifica PT e EN em recortes idênticos; preserva alternativas no diagnóstico."""
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    voz = get_speech_timestamps(audio, VadOptions(threshold=.25,
        min_speech_duration_ms=100, min_silence_duration_ms=500, speech_pad_ms=200))
    saida, auditoria = [], []
    def processar(a, b, nivel=0):
        recorte = audio[a:b]
        print(f'Comparando português e inglês: {a/16000:.1f}–{b/16000:.1f} s', flush=True)
        hipoteses = [reconhecer_hipotese(backend, recorte, l) for l in ('pt', 'en')]
        _, _, probabilidades = backend.detect_language(audio=recorte)
        tem_voz = any(s['start'] < b and s['end'] > a for s in voz)
        escolhida, decisao = escolher_hipotese(hipoteses, probabilidades, tem_voz=tem_voz)
        acustica = evidencia_acustica(probabilidades)
        texto = evidencia_textual(escolhida['texto']) if escolhida else None
        # Uma única língua pode traduzir a outra involuntariamente. Repete a
        # comparação em recortes menores quando há indícios de transição.
        misto = min(acustica['probabilidades'].values()) >= .15 or (
            texto is not None and texto['misto'] and
            min(texto['votos'].values()) / max(1, sum(texto['votos'].values())) >= .2)
        divergencia = bool(escolhida and acustica['forte'] and
                           escolhida['idioma'] != acustica['idioma'])
        refinar = bool(escolhida and (misto or divergencia) and nivel == 0 and b-a > 12*16000)
        indice = len(auditoria)
        registro = dict(inicio=a/16000, fim=b/16000, hipoteses=hipoteses,
                        tem_voz=tem_voz, nivel=nivel, usada=not refinar,
                        probabilidades=[(l, float(p)) for l,p in probabilidades], decisao=decisao)
        auditoria.append(registro)
        if refinar:
            if registrar:
                registrar(registro)
            duracao = (b-a)/16000
            corte = next(janelas_audio(recorte, minimo=duracao*.4, maximo=duracao*.6))[1]
            print(f'Idioma incerto em {a/16000:.1f}–{b/16000:.1f} s; comparando duas partes.', flush=True)
            processar(a, a+corte, nivel+1)
            processar(a+corte, b, nivel+1)
            return
        if escolhida:
            trechos = escolhida['segmentos']
            anterior = 0.
            for s in trechos:
                if not s['text']:
                    continue
                x, y = s['start'], min((b-a)/16000, s['end'])
                if not (math.isfinite(x) and math.isfinite(y) and
                        0 <= round(x*1000) < round(y*1000) and
                        round(x*1000) >= round(anterior*1000)):
                    # Um timestamp degenerado não pode apagar texto escolhido.
                    trechos = [dict(start=0., end=(b-a)/16000, text=escolhida['texto'])]
                    decisao['tempos_aproximados'] = True
                    decisao['revisao_recomendada'] = True
                    break
                anterior = y
            for s in trechos:
                inicio, fim = max(0., s['start']), min((b-a)/16000, s['end'])
                if not s['text'] or fim <= inicio:
                    continue
                analise = selecionar_idioma(s['text'], probabilidades)
                analise['revisao_recomendada'] |= decisao['revisao_recomendada']
                saida.append(dict(start=a/16000+inicio, end=a/16000+fim, text=s['text'],
                                  idioma=analise['idioma'], analise_idioma=analise,
                                  confianca_idioma=analise['audio_local']['probabilidades'][analise['idioma']],
                                  janela_bilingue=indice))
        if registrar:
            registrar(registro)
        print(f'Reconhecimento duplo: {a/16000:.1f}–{b/16000:.1f} s · '
              f"{decisao.get('idioma_escolhido') or decisao['motivo']}", flush=True)
    for a, b in janelas_audio(audio):
        processar(a,b)
    return saida, auditoria
