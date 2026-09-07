from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from sustentacao import recuperar_sustentacoes

import config_alinhamento as cfg
from letra import (
    PalavraAlinhada, agrupar_caracteres_em_palavras, analisar_audio_canto,
    extrair_palavras, filtrar_caracteres_lexicos, normalizar_palavra,
    valor_numerico_valido,
)

SAMPLE_RATE_WHISPERX = 16000


def resolver_dispositivo(dispositivo):
    import torch
    dispositivo = dispositivo.strip().lower()
    if dispositivo == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if dispositivo not in {"cpu", "cuda"}:
        raise ValueError('Dispositivo deve ser "auto", "cpu" ou "cuda".')
    if dispositivo == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA solicitada, mas indisponível.")
    return dispositivo


def extrair_caracteres_resultado(resultado):
    caracteres = []
    for segmento in resultado.get("segments", []):
        cs = segmento.get("chars") or []
        if caracteres and cs and not str(caracteres[-1].get("char", "")).isspace():
            caracteres.append({"char": " "})
        caracteres.extend(dict(c) for c in cs)
    return caracteres


def extrair_palavras_resultado(resultado):
    if resultado.get("word_segments") is not None:
        return [dict(p) for p in resultado["word_segments"]]
    return [dict(p) for s in resultado.get("segments", []) for p in s.get("words", [])]


def calcular_limites_fallback(textos, inicio, fim):
    if not textos or fim <= inicio:
        raise ValueError("Fallback exige texto e duração positiva.")
    pesos = [max(1, len(normalizar_palavra(t))) for t in textos]
    limites, acumulado = [inicio], 0
    for peso in pesos[:-1]:
        acumulado += peso
        limites.append(inicio + (fim - inicio) * acumulado / sum(pesos))
    return limites + [fim]


def escolher_limite_interno(fim_palavra_esquerda, inicio_palavra_direita, limite_fallback):
    if fim_palavra_esquerda is not None and inicio_palavra_direita is not None:
        return (fim_palavra_esquerda + inicio_palavra_direita) / 2.0, True
    for valor in (inicio_palavra_direita, fim_palavra_esquerda):
        if valor is not None:
            return valor, True
    return limite_fallback, False


def _mapear_textos(esperados, obtidos):
    """Não associa por posição após uma omissão do modelo."""
    matcher = SequenceMatcher(None, esperados, obtidos, autojunk=False)
    return {a + k: b + k for a, b, n in matcher.get_matching_blocks() for k in range(n)}


class AlinhadorLetraSRT:
    def __init__(self, caminho_voz, idioma=cfg.IDIOMA_ALINHAMENTO,
                 dispositivo=cfg.DISPOSITIVO_ALINHAMENTO,
                 modelo_alinhamento=cfg.MODELO_ALINHAMENTO,
                 margem_analise=cfg.MARGEM_ANALISE_SRT, pasta_modelos=None):
        import whisperx
        self.caminho_voz = Path(caminho_voz).expanduser().resolve()
        if not self.caminho_voz.is_file():
            raise FileNotFoundError(f"Voz não encontrada: {self.caminho_voz}")
        self.idioma = idioma
        self.dispositivo = resolver_dispositivo(dispositivo)
        self.modelo_alinhamento = modelo_alinhamento
        self.margem_analise = max(0.0, float(margem_analise))
        self.pasta_modelos = Path(pasta_modelos).expanduser().resolve() if pasta_modelos else None
        print("Carregando voz e evidências acústicas...")
        self.audio = whisperx.load_audio(str(self.caminho_voz))
        self.duracao_audio = len(self.audio) / SAMPLE_RATE_WHISPERX
        self.evidencia = analisar_audio_canto(self.audio, SAMPLE_RATE_WHISPERX)
        argumentos = dict(language_code=idioma, device=self.dispositivo, model_name=modelo_alinhamento)
        if self.pasta_modelos is not None:
            self.pasta_modelos.mkdir(parents=True, exist_ok=True)
            argumentos["model_dir"] = str(self.pasta_modelos)
        print(f"Carregando alinhador ({idioma}, {self.dispositivo})...")
        self.modelo, self.metadados_modelo = whisperx.load_align_model(**argumentos)

    def alinhar(self, blocos):
        import whisperx
        palavras, avisos = [], []
        ordenados = sorted(blocos, key=lambda b: (b.inicio, b.ordem))
        for anterior, atual in zip(ordenados, ordenados[1:]):
            if atual.inicio < anterior.fim - 1e-6:
                raise ValueError(f"SRT sobreposto: blocos {anterior.indice} e {atual.indice}. Corrija os tempos antes de gerar MIDI monofônico.")
        for pos, bloco in enumerate(ordenados, 1):
            if bloco.vazio:
                continue
            inicio, fim = max(0.0, bloco.inicio), min(self.duracao_audio, bloco.fim)
            if fim <= inicio:
                raise ValueError(f"Bloco {bloco.indice} fora do áudio: verifique sincronização.")
            if fim < bloco.fim:
                avisos.append(f"Bloco {bloco.indice}: final limitado à duração do áudio.")
            print(f"[{pos}/{len(ordenados)}] {bloco.texto_normalizado}")
            segmento = {"start": max(0.0, inicio - self.margem_analise),
                        "end": min(self.duracao_audio, fim + self.margem_analise),
                        "text": bloco.texto_normalizado}
            try:
                resultado = whisperx.align(
                    transcript=[segmento], model=self.modelo,
                    align_model_metadata=self.metadados_modelo, audio=self.audio,
                    device=self.dispositivo, interpolate_method="ignore",
                    return_char_alignments=True, print_progress=False,
                )
            except Exception as erro:
                # Falha do modelo não vira evidência acústica inventada.
                resultado = None
                avisos.append(f"Bloco {bloco.indice}: fallback após {type(erro).__name__}: {erro}")
            novas = self._construir_palavras_bloco(bloco, inicio, fim, resultado, len(palavras))
            for palavra in novas:
                # Dados auxiliares compartilhados, fora do JSON/asdict.
                palavra._evidencia = self.evidencia
                palavra._avisos = avisos
                if palavra.score < cfg.SCORE_MINIMO_PALAVRA or "fallback" in palavra.origem_tempos:
                    avisos.append(f"{palavra.id}: tempos/pontuação exigem revisão ({palavra.origem_tempos}).")
            palavras.extend(novas)
        recuperar_sustentacoes(palavras, self.evidencia, avisos)
        return palavras, avisos

    def _construir_palavras_bloco(self, bloco, inicio_referencia, fim_referencia,
                                 resultado, ordem_global_inicial):
        textos = extrair_palavras(bloco.texto_normalizado)
        if not textos:
            return []
        modelos = extrair_palavras_resultado(resultado or {})
        grupos = agrupar_caracteres_em_palavras(extrair_caracteres_resultado(resultado or {}))
        esperados = [normalizar_palavra(t).casefold() for t in textos]
        mapa = _mapear_textos(esperados, [normalizar_palavra(p.get("word", "")).casefold() for p in modelos])
        mapa_chars = _mapear_textos(esperados, ["".join(c["char"] for c in filtrar_caracteres_lexicos(g)).casefold() for g in grupos])
        n = len(textos)
        piso = min(cfg.DURACAO_MINIMA_UNIDADE, (fim_referencia - inicio_referencia) / n * 0.45)
        dados = []
        for i in range(n):
            p = modelos[mapa[i]] if i in mapa else {}
            a, b = valor_numerico_valido(p.get("start")), valor_numerico_valido(p.get("end"))
            score = min(1.0, max(0.0, valor_numerico_valido(p.get("score")) or 0.0))
            valido = a is not None and b is not None and inicio_referencia <= a < b <= fim_referencia and b - a >= piso and score >= cfg.SCORE_MINIMO_PALAVRA
            dados.append((a, b, score, valido))
        # Intervalos acústicos válidos conservam os espaços entre palavras.
        # Grupos sem evidência são distribuídos só no espaço entre âncoras.
        intervalos = [None] * n
        ultimo_fim = inicio_referencia
        for i, (a, b, score, valido) in enumerate(dados):
            if valido and a >= ultimo_fim and a >= inicio_referencia + i * piso and b <= fim_referencia - (n - i - 1) * piso:
                anteriores = [j for j in range(i) if intervalos[j] is not None]
                j = anteriores[-1] if anteriores else -1
                if a - ultimo_fim >= (i - j - 1) * piso:
                    intervalos[i] = (a, b)
                    ultimo_fim = b
        i = 0
        fontes = ["whisperx" if x else "fallback_proporcional_srt" for x in intervalos]
        while i < n:
            if intervalos[i] is not None:
                i += 1
                continue
            j = i
            while j < n and intervalos[j] is None:
                j += 1
            a = intervalos[i - 1][1] if i else inicio_referencia
            b = intervalos[j][0] if j < n else fim_referencia
            limites = calcular_limites_fallback(textos[i:j], a, b)
            for k in range(i, j):
                intervalos[k] = (limites[k - i], limites[k - i + 1])
            i = j
        if cfg.ANCORAR_EXTREMIDADES_NO_SRT:
            intervalos[0] = (inicio_referencia, intervalos[0][1])
            intervalos[-1] = (intervalos[-1][0], fim_referencia)
            for i in {0, n - 1}:
                fontes[i] += "_ancorado_srt"
        palavras = []
        for i, texto in enumerate(textos):
            a, b = intervalos[i]
            if b <= a:
                raise ValueError(f"Intervalo inválido no bloco {bloco.indice}, palavra {texto}.")
            cs = grupos[mapa_chars[i]] if i in mapa_chars else []
            score = dados[i][2] if fontes[i].startswith("whisperx") else min(dados[i][2], 0.25)
            palavras.append(PalavraAlinhada(
                f"b{bloco.indice}_p{i + 1}", bloco.indice, i + 1,
                ordem_global_inicial + i + 1, texto, normalizar_palavra(texto),
                float(a), float(b), score, fontes[i], cs,
            ))
            palavras[-1].score_modelo = dados[i][2] if i in mapa else None
            palavras[-1].correspondencia_textual = i in mapa
            palavras[-1].tempos_modelo_aceitos = fontes[i].startswith("whisperx")
            if n == 1 and cfg.ANCORAR_EXTREMIDADES_NO_SRT:
                palavras[-1].origem_tempos = "srt_palavra_unica"
                palavras[-1].score = dados[i][2]
        return palavras