"""Ajustes experimentais de duração: piso viável e cauda acústica de fim de bloco.

Trabalha em cópias das notas. Conserva os tempos originais das sílabas e não
reescreve o alinhamento. Cada ajuste é exportado no diagnóstico das notas.
"""
from __future__ import annotations

from dataclasses import replace
import numpy as np
import config_alinhamento as cfg


def _marcar(nota, motivo):
    nota.revisao_recomendada = True
    if motivo not in nota.motivos_revisao:
        nota.motivos_revisao.append(motivo)


def _estender(nota, limite, e):
    t = np.asarray(e['tempos'], dtype=float)
    rms = np.asarray(e['rms'], dtype=float)
    per = np.asarray(e['periodicidade'], dtype=float)
    timbre = np.asarray(e['timbres'], dtype=float)
    dt = float(e['passo'])
    if dt <= 0 or not np.isfinite(dt):
        raise ValueError('Passo acústico inválido.')
    if any(len(v) != len(t) or not np.isfinite(v).all()
           for v in (rms, per, timbre)) or not np.isfinite(t).all():
        raise ValueError('Evidência acústica inválida.')
    if len(t) > 1 and np.any(np.diff(t) <= 0):
        raise ValueError('Tempos acústicos fora de ordem.')
    a = float(nota.fim_nota)
    refs = np.flatnonzero((t >= max(nota.inicio_nota,
                           a - cfg.RAIO_REFERENCIA_FINAL_FRASE)) & (t < a))
    ids = np.flatnonzero((t >= a) & (t < limite))
    registro = {'tipo': 'busca_cauda_final', 'fim_original': a,
                'fim_ajustado': a, 'limite': float(limite),
                'motivo': 'ancora_insuficiente'}
    nota.ajustes_duracao.append(registro)
    piso = cfg.SILENCIO_RMS_ABSOLUTO
    validos = refs[(rms[refs] > piso) &
                  (per[refs] >= cfg.PERIODICIDADE_MINIMA_SUSTENTACAO)]
    if not len(ids) or not len(validos) or t[validos[-1]] < a - 0.060:
        return
    referencia = np.median(timbre[validos], axis=0)
    referencia /= np.linalg.norm(referencia) + 1e-12
    timbre_normal = timbre[ids] / (np.linalg.norm(timbre[ids], axis=1)[:, None] + 1e-12)
    distancia = 1 - np.clip(timbre_normal @ referencia, 0, 1)
    nivel = float(np.percentile(rms[validos], 75))
    limiar = max(piso, min(float(np.percentile(rms, 10)) *
                 cfg.SILENCIO_MULTIPLICADOR_RUIDO,
                 nivel * cfg.SILENCIO_FRACAO_REFERENCIA))
    silencio_seguido = falha = 0
    ultimo = None
    bons = 0
    registro['motivo'] = 'limite_temporal'
    for k, i in enumerate(ids):
        periodico = per[i] >= cfg.PERIODICIDADE_MINIMA_SUSTENTACAO
        silencio = rms[i] <= piso or (rms[i] <= limiar and not periodico)
        compativel = not silencio and periodico and distancia[k] <= cfg.DISTANCIA_TIMBRE_MAXIMA
        silencio_seguido = silencio_seguido + 1 if silencio else 0
        falha = 0 if compativel else falha + 1
        if silencio_seguido * dt >= cfg.SILENCIO_FINAL_FRASE_CONFIRMADO - 1e-9:
            registro['motivo'] = 'silencio_confirmado'
            break
        if falha * dt >= cfg.FALHA_FINAL_FRASE_MAXIMA - 1e-9:
            registro['motivo'] = 'continuidade_nao_confirmada'
            break
        if compativel:
            ultimo = k
            bons += 1
    if ultimo is not None and bons / (ultimo + 1) >= cfg.COBERTURA_SUSTENTACAO_MINIMA:
        fim = min(limite, float(t[ids[ultimo]]) + dt / 2)
        if fim - a >= 0.020:
            nota.fim_nota = fim
            registro['fim_ajustado'] = float(fim)
            _marcar(nota, 'cauda_final_estendida_por_evidencia_acustica')


def _redistribuir(grupo):
    # Só redistribui regiões contíguas: não transforma pausas em notas.
    alvo = float(cfg.DURACAO_ALVO_MINIMA_MIDI)
    limite = float(cfg.DESLOCAMENTO_MAXIMO_FRONTEIRA_MIDI)
    if alvo <= 0 or limite < 0:
        raise ValueError('Parâmetros de duração inválidos.')
    duracoes = np.array([n.fim_nota - n.inicio_nota for n in grupo])
    deficit = np.maximum(alvo - duracoes, 0)
    excesso = np.maximum(duracoes - alvo, 0)
    if deficit.sum() == 0:
        return
    if excesso.sum() == 0:
        for n, d in zip(grupo, duracoes):
            if d < alvo:
                _marcar(n, 'duracao_minima_inviavel_sem_tempo_disponivel')
        return
    ganho = min(float(deficit.sum()), float(excesso.sum()))
    novas = duracoes + deficit / deficit.sum() * ganho - excesso / excesso.sum() * ganho
    bordas = np.r_[grupo[0].inicio_nota,
                    grupo[0].inicio_nota + np.cumsum(duracoes)]
    propostas = np.r_[grupo[0].inicio_nota,
                       grupo[0].inicio_nota + np.cumsum(novas)]
    deslocamento = float(np.max(np.abs(propostas - bordas)))
    fator = min(1.0, limite / deslocamento) if deslocamento > 0 else 1.0
    ajustadas = bordas + fator * (propostas - bordas)
    for i, n in enumerate(grupo):
        inicio, fim = float(ajustadas[i]), float(ajustadas[i + 1])
        if abs(inicio - n.inicio_nota) + abs(fim - n.fim_nota) > 1e-9:
            n.ajustes_duracao.append({'tipo': 'redistribuicao_na_palavra',
                'inicio_original': n.inicio_nota, 'fim_original': n.fim_nota,
                'inicio_ajustado': inicio, 'fim_ajustado': fim})
            n.inicio_nota, n.fim_nota = inicio, fim
            _marcar(n, 'fronteira_silabica_ajustada_para_duracao')
        if fim - inicio < alvo - 1e-9:
            _marcar(n, 'duracao_minima_nao_atingida_por_limite_temporal')


def ajustar_tempos_midi(notas, evidencia, duracao_audio):
    """Uma nota por sílaba; blocos SRT são a aproximação de frases.

    O piso é um alvo, não uma garantia: não cria tempo além do áudio nem
    sobrepõe palavras. Uma cauda só cresce até o último frame compatível.
    """
    resultado = [replace(n, motivos_revisao=list(n.motivos_revisao),
                         ajustes_duracao=list(n.ajustes_duracao)) for n in notas]
    for i, n in enumerate(resultado):
        if not 0 <= n.inicio_nota < n.fim_nota <= duracao_audio + 1e-6:
            raise ValueError('Nota fora dos limites do áudio.')
        if i and n.inicio_nota < resultado[i - 1].fim_nota - 1e-6:
            raise ValueError('Notas sobrepostas antes do ajuste de duração.')
    if cfg.ALONGAR_FINAL_FRASE_MIDI:
        for i, n in enumerate(resultado):
            proxima = resultado[i + 1] if i + 1 < len(resultado) else None
            if proxima is not None and proxima.bloco_indice == n.bloco_indice:
                continue
            limite = min(duracao_audio, n.fim_nota + cfg.EXTENSAO_MAXIMA_FINAL_FRASE,
                         proxima.inicio_nota if proxima else duracao_audio)
            if limite <= n.fim_nota:
                continue
            if evidencia is None:
                _marcar(n, 'cauda_final_sem_evidencia_acustica')
            else:
                _estender(n, limite, evidencia)
    if cfg.AJUSTAR_DURACOES_MIDI:
        grupo = []
        for n in resultado:
            if grupo and (n.palavra_id != grupo[-1].palavra_id or
                          n.bloco_indice != grupo[-1].bloco_indice or
                          abs(n.inicio_nota - grupo[-1].fim_nota) > 1e-9):
                _redistribuir(grupo)
                grupo = []
            grupo.append(n)
        if grupo:
            _redistribuir(grupo)
    return resultado
