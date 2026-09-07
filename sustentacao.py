"""Recuperação tolerante: silêncio precisa persistir; quedas breves são provisórias.
Toda associação à palavra anterior é heurística e aparece no diagnóstico.
"""
from __future__ import annotations
import numpy as np
import config_alinhamento as cfg
from letra import VOGAIS, normalizar_palavra


def _avisar(palavra, mensagem, avisos):
    if mensagem not in palavra.avisos:
        palavra.avisos.append(mensagem)
    texto = f"{palavra.id}: {mensagem}"
    if texto not in avisos:
        avisos.append(texto)


def recuperar_sustentacoes(palavras, evidencia, avisos=None):
    """Prolonga somente a última sílaba através do fim da palavra.
    Não atravessa blocos SRT. Retorna os mesmos objetos, como na versão anterior.
    Falhas só entram na extensão se a evidência compatível retornar depois.
    """
    if avisos is None:
        avisos = []
    if not cfg.RECUPERAR_SUSTENTACOES:
        return palavras
    campos = ("tempos", "rms", "periodicidade", "timbres", "passo")
    if evidencia is None or any(c not in evidencia for c in campos):
        for p in palavras:
            _avisar(p, "recuperacao_sem_evidencia_acustica", avisos)
        return palavras
    t = np.asarray(evidencia["tempos"])
    dt = float(evidencia["passo"])
    if len(t) == 0 or not np.isfinite(dt) or dt <= 0 or (np.diff(t) <= 0).any():
        raise ValueError("Tempos acústicos vazios ou inválidos.")
    for c in campos[:-1]:
        if len(evidencia[c]) != len(t) or not np.isfinite(evidencia[c]).all():
            raise ValueError(f"Evidência acústica inválida: {c}")
    rms = np.maximum(np.asarray(evidencia["rms"]), 0.0)
    per = np.asarray(evidencia["periodicidade"])
    timbre = np.asarray(evidencia["timbres"])
    piso = cfg.SILENCIO_RMS_ABSOLUTO
    ruido = float(np.percentile(rms, 10))

    for esquerda, direita in zip(palavras, palavras[1:]):
        if esquerda.bloco_indice != direita.bloco_indice:
            continue
        if any(a.get("palavra_seguinte") == direita.id for a in esquerda.ajustes):
            continue
        a, b = float(esquerda.fim), float(direita.inicio)
        if b - a < cfg.GAP_MINIMO_ANALISAR:
            continue
        ids = np.flatnonzero((t >= a) & (t < b))
        refs = np.flatnonzero(
            (t >= max(esquerda.inicio, a - cfg.JANELA_REFERENCIA_SUSTENTACAO)) & (t < a)
        )
        if not len(ids) or not len(refs):
            _avisar(esquerda, "gap_sem_frames_para_avaliacao", avisos)
            continue
        nivel = float(np.percentile(rms[refs], 75))
        # O percentil de ruído não pode elevar o limiar acima de uma pequena
        # fração da voz de referência em gravações que não possuem pausas.
        limiar = max(piso, min(
            ruido * cfg.SILENCIO_MULTIPLICADOR_RUIDO,
            nivel * cfg.SILENCIO_FRACAO_REFERENCIA,
        ))
        valida = (rms[refs] > piso) & (per[refs] >= cfg.PERIODICIDADE_MINIMA_SUSTENTACAO)
        texto = normalizar_palavra(esquerda.texto)
        chars = "".join(str(c.get("char", "")) for c in esquerda.caracteres)
        recente = max(1, int(np.ceil(0.060 / dt)))
        candidata = (
            bool(texto) and texto[-1] in VOGAIS
            and esquerda.origem_tempos.startswith("whisperx")
            and normalizar_palavra(chars).casefold() == texto.casefold()
            and float(valida.mean()) >= cfg.COBERTURA_REFERENCIA_MINIMA
            and bool(valida[-recente:].any())
        )
        motivo = "ancora_insuficiente"
        inicio_interrupcao = confirmado_em = None
        if candidata:
            referencia = np.median(timbre[refs[valida]], axis=0)
            referencia /= np.linalg.norm(referencia) + 1e-12
            distancia = 1.0 - np.clip(timbre[ids] @ referencia, 0, 1)
            periodico = per[ids] >= cfg.PERIODICIDADE_MINIMA_SUSTENTACAO
            # Periodicidade acima do piso numérico preserva caudas muito fracas.
            silencio = (rms[ids] <= piso) | ((rms[ids] <= limiar) & ~periodico)
            compativel = (~silencio) & periodico & (distancia <= cfg.DISTANCIA_TIMBRE_MAXIMA)
            ultimo_bom, silencios, falhas = -1, 0, 0
            motivo = "limite_palavra_seguinte"
            for k in range(len(ids)):
                silencios = silencios + 1 if silencio[k] else 0
                if silencios * dt >= cfg.SILENCIO_CONFIRMADO_SEGUNDOS - 1e-9:
                    motivo = "silencio_confirmado"
                    inicio_interrupcao = max(a, float(t[ids[k - silencios + 1]]) - dt / 2)
                    confirmado_em = float(t[ids[k]])
                    break
                if compativel[k]:
                    ultimo_bom, falhas = k, 0
                else:
                    falhas += 1
                    if falhas * dt >= cfg.FALHA_CONTINUIDADE_MAXIMA - 1e-9:
                        motivo = "continuidade_acustica_nao_confirmada"
                        inicio_interrupcao = max(a, float(t[ids[k - falhas + 1]]) - dt / 2)
                        confirmado_em = float(t[ids[k]])
                        break
            else:
                if ultimo_bom != len(ids) - 1:
                    motivo = "cauda_final_sem_confirmacao"

            if ultimo_bom >= 0:
                fim_candidato = min(b, float(t[ids[ultimo_bom]]) + dt / 2)
                cobertura = float(compativel[:ultimo_bom + 1].mean())
                if (fim_candidato - a >= cfg.RECUPERACAO_MINIMA - 1e-9
                        and cobertura >= cfg.COBERTURA_SUSTENTACAO_MINIMA):
                    if esquerda.fim_original is None:
                        esquerda.fim_original = a
                    if esquerda.inicio_original is None:
                        esquerda.inicio_original = esquerda.inicio
                    esquerda.fim = fim_candidato
                    esquerda.ajustes.append({
                        "tipo": "cauda_vocal_tolerante_v22",
                        "inicio": a, "fim": fim_candidato,
                        "duracao_recuperada": fim_candidato - a,
                        "palavra_seguinte": direita.id,
                        "cobertura_compativel": cobertura,
                        "limiar_silencio_rms": limiar,
                        "motivo_encerramento": motivo,
                        "inicio_interrupcao": inicio_interrupcao,
                        "criterio_confirmado_em": confirmado_em,
                        "associacao_fonetica_confirmada": False,
                    })
                    _avisar(esquerda, "sustentacao_recuperada_por_heuristica", avisos)
                else:
                    motivo = "recuperacao_insuficiente:" + motivo
        _avisar(esquerda, f"fim_recuperacao:{motivo}", avisos)
        restantes = ids[t[ids] >= esquerda.fim]
        voz_restante = float(np.sum(
            (rms[restantes] > piso) & (per[restantes] >= cfg.PERIODICIDADE_MINIMA_SUSTENTACAO)
        ) * dt)
        if voz_restante >= cfg.GAP_COM_VOZ_AVISO:
            _avisar(esquerda, f"voz_nao_atribuida_antes_de_{direita.id}:{voz_restante:.3f}s", avisos)
    return palavras