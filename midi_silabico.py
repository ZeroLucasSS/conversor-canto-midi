from __future__ import annotations
import math
from pathlib import Path
import pretty_midi
from config_notas import INSTRUMENTO_MIDI, TEMPO_REFERENCIA_MIDI, VELOCIDADE_MIDI
from config_alinhamento import RESOLUCAO_MIDI_TICKS
from notas_silabicas import NotaSilabica


def gerar_midi_silabico(notas: list[NotaSilabica], caminho_saida: str | Path) -> Path:
    """Um evento por sílaba, sem cortes por confiança ou alongamento mínimo."""
    ordenadas = sorted(notas, key=lambda n: (n.inicio_nota, n.ordem_global))
    if not ordenadas:
        raise ValueError("Não há notas para exportar.")
    tempo = float(TEMPO_REFERENCIA_MIDI)
    if not math.isfinite(tempo) or tempo <= 0:
        raise ValueError("Tempo de referência inválido.")
    velocidade = int(VELOCIDADE_MIDI)
    if not 1 <= velocidade <= 127:
        raise ValueError("Velocidade MIDI deve estar entre 1 e 127.")
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo, resolution=RESOLUCAO_MIDI_TICKS)
    instrumento = pretty_midi.Instrument(
        program=pretty_midi.instrument_name_to_program(INSTRUMENTO_MIDI),
        name="Melodia vocal por sílaba",
    )
    fim_anterior = -1.0
    for nota in ordenadas:
        inicio, fim = float(nota.inicio_nota), float(nota.fim_nota)
        pitch = float(nota.pitch_midi)
        if not all(math.isfinite(v) for v in (inicio, fim, pitch)):
            raise ValueError(f"Valores não finitos na nota {nota.id}.")
        if not 0 <= inicio < fim or inicio < fim_anterior - 1e-9:
            raise ValueError(f"Intervalo inválido ou sobreposto na nota {nota.id}: {inicio}–{fim}")
        if pitch != int(pitch) or not 0 <= pitch <= 127:
            raise ValueError(f"Pitch inválido na nota {nota.id}: {pitch}")
        if midi.time_to_tick(fim) <= midi.time_to_tick(inicio):
            raise ValueError(f"Nota {nota.id} curta demais para a resolução MIDI; revise o alinhamento.")
        instrumento.notes.append(pretty_midi.Note(
            velocity=velocidade, pitch=int(pitch), start=inicio, end=fim,
        ))
        midi.lyrics.append(pretty_midi.Lyric(text=nota.silaba, time=inicio))
        fim_anterior = fim
    midi.instruments.append(instrumento)
    destino = Path(caminho_saida).expanduser().resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(destino))
    return destino