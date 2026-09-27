"""Equivalência das otimizações de desempenho com as versões originais.

Executar na pasta do projeto:  python -m unittest discover -s testes -v
Usa apenas sinais sintéticos; não depende dos áudios da pasta audios/.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import librosa  # noqa: E402
import soundfile  # noqa: E402

import config_alinhamento as cfg  # noqa: E402
import pyin_rapido  # noqa: E402
from letra import analisar_audio_canto  # noqa: E402
from notas_silabicas import CAMPOS_ANALISE, AnalisadorNotasSilabicas, identidade_analise  # noqa: E402


def sinal_cantado(sr, segundos=2.0, semente=0):
    """Glissando com vibrato, uma pausa e ruído leve."""
    rng = np.random.default_rng(semente)
    t = np.arange(int(sr * segundos)) / sr
    f0 = 220 * 2 ** ((t / segundos) + 0.03 * np.sin(2 * np.pi * 5.5 * t))
    y = 0.4 * np.sin(2 * np.pi * np.cumsum(f0) / sr)
    y[(t > 0.8) & (t < 1.0)] = 0.0
    return (y + 0.003 * rng.standard_normal(len(t))).astype(np.float32)


def analisar_audio_canto_referencia(audio, sr):
    """Laço quadro a quadro da versão anterior à vetorização."""
    y = np.asarray(audio, dtype=float)
    hop = max(1, round(sr * cfg.PASSO_ACUSTICO))
    tamanho = max(8, round(sr * cfg.JANELA_ACUSTICA))
    nfft = 1 << (2 * tamanho - 1).bit_length()
    centros = np.arange(0, len(y), hop)
    padded = np.pad(y, (tamanho // 2, tamanho))
    lags = np.arange(max(1, int(sr / cfg.FREQUENCIA_MAXIMA_VOZ)),
                     min(tamanho - 2, int(sr / cfg.FREQUENCIA_MINIMA_VOZ)) + 1)
    rms, per, fluxo, timbres, anterior = [], [], [], [], None
    for centro in centros:
        x = padded[centro:centro + tamanho].copy()
        rms.append(float(np.sqrt(np.mean(x * x))))
        x -= x.mean()
        espectro = np.abs(np.fft.rfft(x * np.hanning(tamanho)))
        espectro /= np.linalg.norm(espectro) + 1e-12
        bandas = np.array([np.linalg.norm(b) for b in np.array_split(espectro, 16)])
        timbres.append(bandas / (np.linalg.norm(bandas) + 1e-12))
        fluxo.append(0.0 if anterior is None else float(np.linalg.norm(espectro - anterior)))
        anterior = espectro
        tr = np.fft.rfft(x, nfft)
        ac = np.fft.irfft(tr * tr.conj(), nfft)[:tamanho]
        energia = np.r_[0.0, np.cumsum(x * x)]
        den = np.sqrt(energia[tamanho - lags] * (energia[-1] - energia[lags]))
        per.append(float(np.clip(np.max(ac[lags] / (den + 1e-12)), 0, 1)))
    fluxo = np.asarray(fluxo)
    escala = max(float(np.percentile(fluxo, 90)), 0.05)
    return {"tempos": centros / sr, "rms": np.asarray(rms), "periodicidade": np.asarray(per),
            "fluxo": np.clip(fluxo / escala, 0, 1), "passo": hop / sr,
            "timbres": np.asarray(timbres)}


class TesteViterbiEsparso(unittest.TestCase):
    def test_identico_ao_librosa_com_zeros_e_empates(self):
        rng = np.random.default_rng(1)
        for caso in range(200):
            n, t = int(rng.integers(2, 30)), int(rng.integers(1, 40))
            tr = rng.random((n, n)) * (rng.random((n, n)) < rng.uniform(0.05, 1))
            if caso % 2:
                tr = np.round(tr * 2) / 2  # valores repetidos provocam empates
            tr[np.arange(n), rng.integers(0, n, n)] += 1
            tr /= tr.sum(1, keepdims=True)
            p = rng.random((n, t)) * (rng.random((n, t)) < 0.7)
            if caso % 3 == 0:
                p = np.round(p * 3) / 3
            esperado = librosa.sequence.viterbi(p, tr, return_logp=True)
            obtido = pyin_rapido.viterbi_esparso(p, tr, return_logp=True)
            np.testing.assert_array_equal(esperado[0], obtido[0], err_msg=f"caso {caso}")
            np.testing.assert_array_equal(esperado[1], obtido[1], err_msg=f"caso {caso}")

    def test_pyin_identico_ao_librosa(self):
        from config_notas import (FRAME_LENGTH_NOTAS, HOP_LENGTH_NOTAS, NOTA_VOCAL_MAXIMA,
                                  NOTA_VOCAL_MINIMA, SAMPLE_RATE_NOTAS)
        sr = SAMPLE_RATE_NOTAS
        kw = dict(fmin=librosa.note_to_hz(NOTA_VOCAL_MINIMA),
                  fmax=librosa.note_to_hz(NOTA_VOCAL_MAXIMA), sr=sr,
                  frame_length=FRAME_LENGTH_NOTAS, hop_length=HOP_LENGTH_NOTAS)
        y = sinal_cantado(sr, 2.0)
        for esperado, obtido in zip(librosa.pyin(y, **kw), pyin_rapido.pyin(y, **kw)):
            np.testing.assert_array_equal(esperado, obtido)
        # A substituição é temporária: o librosa volta ao Viterbi original.
        self.assertIsNot(librosa.sequence.viterbi, pyin_rapido.viterbi_esparso)


class TesteEvidenciaAcustica(unittest.TestCase):
    def test_vetorizada_equivale_ao_laco_original(self):
        for sr in (16000, 22050):
            y = sinal_cantado(sr, 3.0, semente=sr)
            esperado = analisar_audio_canto_referencia(y, sr)
            obtido = analisar_audio_canto(y, sr)
            self.assertEqual(esperado["passo"], obtido["passo"])
            for chave in ("tempos", "rms", "periodicidade", "fluxo", "timbres"):
                self.assertEqual(esperado[chave].shape, obtido[chave].shape, chave)
                np.testing.assert_allclose(obtido[chave], esperado[chave], rtol=0,
                                           atol=1e-12, err_msg=f"{chave} sr={sr}")


class TesteReusoDaAnaliseDeAudio(unittest.TestCase):
    def test_reuso_exige_mesma_identidade(self):
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            voz, instrumental = pasta / "voz.wav", pasta / "instrumental.wav"
            soundfile.write(voz, sinal_cantado(22050, 3.0, 1), 22050)
            soundfile.write(instrumental, sinal_cantado(22050, 3.0, 2) * 0.5, 22050)

            original = AnalisadorNotasSilabicas(voz, instrumental)
            original.salvar_analise(pasta / "analise.npz")
            reuso = AnalisadorNotasSilabicas(voz, instrumental, analise_audio=pasta / "analise.npz")
            self.assertFalse(hasattr(reuso, "y_voz"), "deveria reaproveitar sem ler o áudio")
            for nome in CAMPOS_ANALISE:
                np.testing.assert_array_equal(getattr(original, nome), getattr(reuso, nome), nome)
            for chave, valor in original.evidencia_duracao().items():
                np.testing.assert_array_equal(valor, reuso.evidencia_duracao()[chave], chave)

            # Mesmo nome, conteúdo diferente: a análise antiga é descartada.
            identidade = identidade_analise(voz, instrumental)
            soundfile.write(instrumental, sinal_cantado(22050, 3.0, 3) * 0.5, 22050)
            self.assertNotEqual(identidade, identidade_analise(voz, instrumental))
            recalculado = AnalisadorNotasSilabicas(voz, instrumental, analise_audio=pasta / "analise.npz")
            self.assertTrue(hasattr(recalculado, "y_voz"), "deveria recalcular")


if __name__ == "__main__":
    unittest.main()
