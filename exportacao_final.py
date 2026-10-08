"""Auditoria de cobertura, SRT por evento MIDI e dificuldade heurística.

Não modifica pitches nem durações. Falhas de cobertura interrompem a saída.
A cobertura textual não comprova a pronúncia ou a afinação real do cantor.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

# Critérios experimentais, não uma escala clínica/pedagógica universal.
# Aumentar estes referenciais torna a classificação menos exigente.
PITCH_BASE = 60             # C4
PITCH_AGUDO = 84            # C6
REFERENCIA_ALTURAS_DISTINTAS = 12  # alturas MIDI absolutas, incluindo oitavas
PESO_VARIEDADE = 0.15
PESO_PICO = 0.85
LIMIAR_INTERMEDIATE = 0.35
LIMIAR_ADVANCED = 0.65


def _unicos(itens, campo, rotulo):
    valores = [x.get(campo) for x in itens]
    if any(v is None or v == "" for v in valores) or len(set(valores)) != len(valores):
        raise ValueError(f"{rotulo}: {campo} ausente ou duplicado.")


def validar_cobertura(dados: dict, blocos_fonte=None) -> dict:
    """Confere cada ocorrência, inclusive palavras repetidas, em cada bloco.

    blocos_fonte pode receber a leitura do SRT original para evitar validar
    somente uma cópia incompleta dos blocos dentro do JSON.
    """
    from letra import Silabificador, extrair_palavras, normalizar_palavra
    from config_alinhamento import IDIOMA_SILABIFICACAO

    blocos = (list(blocos_fonte) if blocos_fonte is not None else dados.get("blocos"))
    palavras, silabas = dados.get("palavras"), dados.get("silabas")
    if not all(isinstance(x, list) for x in (blocos, palavras, silabas)):
        raise ValueError("Auditoria exige listas de blocos, palavras e sílabas.")
    blocos = [b.para_dict() if hasattr(b, "para_dict") else b for b in blocos]
    if not palavras or not silabas:
        raise ValueError("A letra não produziu palavras e sílabas para converter.")
    _unicos(blocos, "indice", "Blocos")
    _unicos(palavras, "id", "Palavras")
    _unicos(palavras, "ordem_global", "Palavras")
    _unicos(silabas, "id", "Sílabas")
    _unicos(silabas, "ordem_global", "Sílabas")
    por_bloco, por_palavra = defaultdict(list), defaultdict(list)
    ids_blocos = {b["indice"] for b in blocos}
    ids_palavras = {p["id"] for p in palavras}
    for p in palavras:
        if p["bloco_indice"] not in ids_blocos:
            raise ValueError(f"Palavra {p['id']} sem bloco correspondente no SRT.")
        por_bloco[p["bloco_indice"]].append(p)
    for s in silabas:
        if s["palavra_id"] not in ids_palavras:
            raise ValueError(f"Sílaba {s['id']} sem palavra correspondente.")
        por_palavra[s["palavra_id"]].append(s)
    limpar = lambda texto: normalizar_palavra(texto).casefold()
    for b in blocos:
        esperadas = [limpar(t) for t in extrair_palavras(b["texto_normalizado"])]
        presentes = sorted(por_bloco[b["indice"]], key=lambda p: p["ordem_no_bloco"])
        if [p["ordem_no_bloco"] for p in presentes] != list(range(1, len(esperadas) + 1)):
            raise ValueError(f"Cobertura incompleta/ordem inválida no bloco {b['indice']}.")
        if [limpar(p["texto"]) for p in presentes] != esperadas:
            raise ValueError(f"Palavras diferentes do SRT no bloco {b['indice']}.")
    idioma = dados.get("metadados", {}).get("idioma_silabificacao", IDIOMA_SILABIFICACAO)
    separador = Silabificador(idioma)
    for p in palavras:
        esperadas = separador.separar(p["texto"])
        presentes = sorted(por_palavra[p["id"]], key=lambda s: s["ordem_na_palavra"])
        if not esperadas or not presentes:
            raise ValueError(f"Palavra sem sílabas: {p['id']} ({p['texto']}).")
        if [s["ordem_na_palavra"] for s in presentes] != list(range(1, len(esperadas) + 1)):
            raise ValueError(f"Faltam sílabas ou há duplicações em {p['id']} ({p['texto']}).")
        if ([limpar(s["texto"]) for s in presentes] != [limpar(t) for t in esperadas]
                or limpar("".join(s["texto"] for s in presentes)) != limpar(p["texto"])):
            raise ValueError(f"Sílabas não recompõem a palavra {p['id']} ({p['texto']}).")
        if any(s["bloco_indice"] != p["bloco_indice"] for s in presentes):
            raise ValueError(f"Sílaba associada ao bloco errado: {p['id']}.")
    return {"palavras_verificadas": len(palavras), "silabas_verificadas": len(silabas)}


def validar_notas(silabas, notas):
    if len(notas) != len(silabas):
        raise ValueError("A quantidade de notas não corresponde à quantidade de sílabas.")
    ids = [n.silaba_id for n in notas]
    if len(set(ids)) != len(ids) or set(ids) != {s["id"] for s in silabas}:
        raise ValueError("Há sílabas sem nota, notas extras ou associações duplicadas.")
    mapa = {s["id"]: s for s in silabas}
    for n in notas:
        s = mapa[n.silaba_id]
        if (n.palavra_id != s["palavra_id"] or n.bloco_indice != s["bloco_indice"]
                or n.silaba != s["texto"] or n.ordem_global != s["ordem_global"]):
            raise ValueError(f"Nota associada à sílaba errada: {n.silaba_id}.")


def reler_midi_validado(caminho, notas):
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(str(caminho))
    instrumentos = [i for i in midi.instruments if i.notes]
    if len(instrumentos) != 1 or instrumentos[0].is_drum:
        raise ValueError("Esperada uma única melodia vocal no MIDI.")
    eventos = sorted(instrumentos[0].notes, key=lambda n: (n.start, n.end, n.pitch))
    esperadas = sorted(notas, key=lambda n: (n.inicio_nota, n.ordem_global))
    if not eventos or len(eventos) != len(esperadas):
        raise ValueError("A gravação do MIDI perdeu ou acrescentou notas.")
    for i, (e, n) in enumerate(zip(eventos, esperadas)):
        if e.pitch != n.pitch_midi or not 0 <= e.start < e.end:
            raise ValueError(f"Evento MIDI divergente da sílaba {n.silaba_id}.")
        # Compara na grade de ticks do próprio arquivo: não exige igualdade
        # de floats entre segundos solicitados e tempos quantizados do MIDI.
        if any(midi.time_to_tick(a) != midi.time_to_tick(b) for a, b in
               ((e.start, n.inicio_nota), (e.end, n.fim_nota))):
            raise ValueError(f"Tempos MIDI divergentes da sílaba {n.silaba_id}.")
        if i and e.start < eventos[i - 1].end - 1e-9:
            raise ValueError("MIDI contém notas sobrepostas após gravação.")
    return esperadas, eventos


def _ms(segundos):
    if not math.isfinite(segundos) or segundos < 0:
        raise ValueError("Tempo inválido para SRT.")
    return int(math.floor(segundos * 1000.0 + 0.5))


def _timestamp(ms):
    segundos, milis = divmod(ms, 1000)
    minutos, segundos = divmod(segundos, 60)
    horas, minutos = divmod(minutos, 60)
    return f"{horas:02d}:{minutos:02d}:{segundos:02d},{milis:03d}"


def escrever_srt(caminho, notas, eventos):
    if len(notas) != len(eventos) or not notas:
        raise ValueError("SRT exige uma sílaba por evento MIDI.")
    blocos = []
    for i, (n, e) in enumerate(zip(notas, eventos), 1):
        inicio, fim = _ms(e.start), _ms(e.end)
        texto = str(n.silaba).strip()
        if not texto or "\n" in texto or "\r" in texto:
            raise ValueError(f"Texto inválido para a sílaba {n.silaba_id}.")
        if fim <= inicio:
            raise ValueError(f"Sílaba {n.silaba_id} menor que a precisão do SRT; revise o alinhamento.")
        blocos.append(f"{i}\n{_timestamp(inicio)} --> {_timestamp(fim)}\n{texto}\n")
    Path(caminho).write_text("\n".join(blocos), encoding="utf-8")


def avaliar_dificuldade(eventos):
    """Pico vocal (85%) e variedade de alturas (15%), sem contar sílabas.

    Dividir uma nota em várias ocorrências da mesma altura não muda o score.
    O pico é o máximo presente no MIDI; a estimativa depende da precisão
    do pitch exportado e usa uma referência absoluta, não a tessitura pessoal.
    """
    if not eventos:
        raise ValueError("Não é possível avaliar um MIDI vazio.")
    if any(not math.isfinite(n.start) or not math.isfinite(n.end) or n.end <= n.start
           or not math.isfinite(n.pitch) or not 0 <= n.pitch <= 127 or int(n.pitch) != n.pitch
           for n in eventos):
        raise ValueError('Evento MIDI com altura ou duração inválida.')
    duracao = sum(n.end - n.start for n in eventos)
    alturas = sorted({int(n.pitch) for n in eventos})
    pico = alturas[-1]
    limitar = lambda x: min(1.0, max(0.0, x))
    componente_pico = limitar((pico - PITCH_BASE) / (PITCH_AGUDO - PITCH_BASE))
    componente_variedade = limitar((len(alturas) - 1) / (REFERENCIA_ALTURAS_DISTINTAS - 1))
    score = PESO_PICO * componente_pico + PESO_VARIEDADE * componente_variedade
    dificuldade = ("advanced" if score >= LIMIAR_ADVANCED else
                   "intermediate" if score >= LIMIAR_INTERMEDIATE else "beginner")
    diagnostico = {"criterio": "heuristica_v2_pico_e_variedade", "total_notas": len(eventos),
                  "segundos_cantados": duracao, "alturas_distintas": alturas,
                  "total_alturas_distintas": len(alturas), "pitch_pico": pico,
                  "componente_pico": componente_pico, "componente_variedade": componente_variedade,
                  "peso_pico": PESO_PICO, "peso_variedade": PESO_VARIEDADE,
                  "pitch_base": PITCH_BASE, "pitch_agudo_referencia": PITCH_AGUDO,
                  "referencia_alturas_distintas": REFERENCIA_ALTURAS_DISTINTAS,
                  "limiares": {"intermediate": LIMIAR_INTERMEDIATE, "advanced": LIMIAR_ADVANCED},
                  "score": score}
    return dificuldade, diagnostico


def exportar_complementos(caminho_midi, silabas, notas):
    validar_notas(silabas, notas)
    ordenadas, eventos = reler_midi_validado(caminho_midi, notas)
    midi = Path(caminho_midi)
    srt = midi.with_name(midi.stem + "_silabas.srt")
    metadata = midi.with_name(midi.stem + "_metadata.json")
    dificuldade, diagnostico = avaliar_dificuldade(eventos)
    escrever_srt(srt, ordenadas, eventos)
    metadata.write_text(json.dumps({
        "title": "", "artist": "", "difficulty": dificuldade,
        "language": "pt-BR", "offset": 0, "lyricsOffset": 0,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Cobertura confirmada: {len(silabas)} sílabas / {len(eventos)} notas / {len(eventos)} legendas.")
    print(f"Dificuldade estimada: {dificuldade} (score {diagnostico['score']:.3f}).")
    print("Observação: cobertura completa não comprova a precisão acústica das notas estimadas.")
    print(f"SRT silábico: {srt}\nMetadados: {metadata}")
    return diagnostico
