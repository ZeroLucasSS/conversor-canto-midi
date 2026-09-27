from __future__ import annotations

import html
import json
import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pyphen

import config_alinhamento as cfg

PADRAO_TIMESTAMP = re.compile(
    r"^\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d+):(\d{2}):(\d{2})[,.](\d{3})(?:\s+.*)?$"
)
PADRAO_PALAVRA = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)
PADRAO_TAG_HTML = re.compile(r"<[^>]+>")
VOGAIS = set("aeiouáéíóúàâêôãõüAEIOUÁÉÍÓÚÀÂÊÔÃÕÜ")


@dataclass
class BlocoSRT:
    indice: int
    ordem: int
    inicio: float
    fim: float
    texto_original: str
    texto_normalizado: str
    vazio: bool

    @property
    def duracao(self):
        return max(0.0, self.fim - self.inicio)

    def para_dict(self):
        return asdict(self)


@dataclass
class PalavraAlinhada:
    id: str
    bloco_indice: int
    ordem_no_bloco: int
    ordem_global: int
    texto: str
    texto_normalizado: str
    inicio: float
    fim: float
    score: float
    origem_tempos: str
    caracteres: list[dict[str, Any]] = field(default_factory=list)
    inicio_original: Optional[float] = None
    fim_original: Optional[float] = None
    ajustes: list[dict[str, Any]] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    score_modelo: Optional[float] = None
    correspondencia_textual: bool = False
    tempos_modelo_aceitos: bool = False

    @property
    def duracao(self):
        return max(0.0, self.fim - self.inicio)

    def para_dict(self):
        return asdict(self)


@dataclass
class SilabaAlinhada:
    id: str
    palavra_id: str
    bloco_indice: int
    ordem_na_palavra: int
    ordem_global: int
    texto: str
    texto_normalizado: str
    inicio: float
    fim: float
    inicio_nucleo_vogal: float
    fim_nucleo_vogal: float
    score: float
    origem_tempos: str
    origem_nucleo: str = "estimado"
    precisa_revisao: bool = False
    avisos: list[str] = field(default_factory=list)
    cobertura_periodica: Optional[float] = None

    @property
    def duracao(self):
        return max(0.0, self.fim - self.inicio)

    @property
    def duracao_nucleo_vogal(self):
        return max(0.0, self.fim_nucleo_vogal - self.inicio_nucleo_vogal)

    def para_dict(self):
        return asdict(self)


def timestamp_para_segundos(horas, minutos, segundos, milissegundos):
    h, m, s, ms = map(int, (horas, minutos, segundos, milissegundos))
    if not (0 <= m < 60 and 0 <= s < 60 and 0 <= ms < 1000):
        raise ValueError("Timestamp SRT inválido.")
    return h * 3600.0 + m * 60.0 + s + ms / 1000.0


def normalizar_texto_srt(texto):
    texto = unicodedata.normalize("NFC", html.unescape(texto))
    texto = PADRAO_TAG_HTML.sub("", texto)
    texto = re.sub(r"\{\\[^}]*\}", "", texto)
    return re.sub(r"\s+", " ", texto.replace("\ufeff", "")
                  .replace("♪", " ").replace("♫", " ")).strip()


def normalizar_palavra(palavra):
    return "".join(c for c in unicodedata.normalize("NFC", palavra)
                   if c.isalpha() or c.isdigit())


def extrair_palavras(texto):
    return PADRAO_PALAVRA.findall(unicodedata.normalize("NFC", texto))


def ler_srt(caminho_srt):
    conteudo = Path(caminho_srt).expanduser().read_text(encoding="utf-8-sig")
    conteudo = conteudo.replace("\r\n", "\n").replace("\r", "\n")
    blocos, indices = [], set()
    for ordem, trecho in enumerate(re.split(r"\n\s*\n", conteudo.strip()), 1):
        linhas = trecho.strip().splitlines()
        achados = [(i, PADRAO_TIMESTAMP.match(l)) for i, l in enumerate(linhas)]
        achados = [(i, m) for i, m in achados if m]
        if not achados:
            raise ValueError(f"Bloco SRT sem timestamp válido: {trecho!r}")
        pos, match = achados[0]
        indice = int(linhas[pos - 1].strip()) if pos and linhas[pos - 1].strip().isdigit() else ordem
        if indice in indices:
            raise ValueError(f"Índice SRT repetido: {indice}")
        indices.add(indice)
        inicio = timestamp_para_segundos(*match.groups()[:4])
        fim = timestamp_para_segundos(*match.groups()[4:])
        if fim <= inicio:
            raise ValueError(f"Bloco {indice}: fim precisa ser maior que início.")
        original = " ".join(l.strip() for l in linhas[pos + 1:]).strip()
        normalizado = normalizar_texto_srt(original)
        blocos.append(BlocoSRT(indice, ordem, inicio, fim, original,
                               normalizado, not bool(extrair_palavras(normalizado))))
    if not blocos:
        raise ValueError("SRT sem blocos.")
    blocos.sort(key=lambda b: (b.inicio, b.ordem))
    return blocos


class Silabificador:
    """Hipótese ortográfica configurável; não determina a pronúncia pelo áudio."""

    def __init__(self, idioma="pt_BR", excecoes=None):
        self.idioma = idioma
        self._dicionario = pyphen.Pyphen(lang=idioma, left=1, right=1)
        self.excecoes = dict(cfg.EXCECOES_SILABICAS.get(idioma, {}))
        if excecoes:
            self.excecoes.update(excecoes)

    def separar(self, palavra):
        limpa = normalizar_palavra(palavra)
        if not limpa:
            return []
        partes = self.excecoes.get(limpa.casefold())
        if partes is None:
            partes = self._dicionario.inserted(limpa, hyphen="-").split("-")
        if not partes or any(not p for p in partes) or "".join(partes).casefold() != limpa.casefold():
            raise ValueError(f"Divisão silábica inválida para {palavra!r}: {partes}")
        # Mantém a caixa e os acentos da letra original.
        resultado, pos = [], 0
        for parte in partes:
            resultado.append(limpa[pos:pos + len(parte)])
            pos += len(parte)
        return resultado


def valor_numerico_valido(valor):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def agrupar_caracteres_em_palavras(caracteres):
    grupos, atual = [], []
    for c in caracteres:
        if str(c.get("char", "")).isspace():
            if atual:
                grupos.append(atual)
                atual = []
        else:
            atual.append(c)
    if atual:
        grupos.append(atual)
    return grupos


def filtrar_caracteres_lexicos(caracteres):
    return [c for c in caracteres if str(c.get("char", "")).isalnum()]


def media_scores(caracteres, fallback):
    valores = [valor_numerico_valido(c.get("score")) for c in caracteres]
    valores = [min(1.0, max(0.0, v)) for v in valores if v is not None]
    return float(np.mean(valores)) if valores else float(valor_numerico_valido(fallback) or 0.0)


def _trechos(mask):
    limites = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(int)))
    return list(zip(limites[::2], limites[1::2]))


def analisar_audio_canto(audio, sr=16000):
    """Energia, periodicidade e mudança espectral. Não estima a nota MIDI."""
    y = np.asarray(audio, dtype=float)
    if y.ndim != 1 or not len(y) or sr <= 0 or not np.isfinite(y).all():
        raise ValueError("Áudio deve ser mono, finito, não vazio e ter sr positivo.")
    hop = max(1, round(sr * cfg.PASSO_ACUSTICO))
    tamanho = max(8, round(sr * cfg.JANELA_ACUSTICA))
    nfft = 1 << (2 * tamanho - 1).bit_length()
    centros = np.arange(0, len(y), hop)
    padded = np.pad(y, (tamanho // 2, tamanho))
    rms, periodicidade, fluxo, timbres = [], [], [], []
    anterior = None
    lag_min = max(1, int(sr / cfg.FREQUENCIA_MAXIMA_VOZ))
    lag_max = min(tamanho - 2, int(sr / cfg.FREQUENCIA_MINIMA_VOZ))
    if lag_max <= lag_min:
        raise ValueError("Faixa de frequências incompatível com a janela acústica.")
    lags = np.arange(lag_min, lag_max + 1)
    janela = np.hanning(tamanho)
    # Mesmos cortes de np.array_split(espectro, 16), calculados uma única vez.
    n_bins = tamanho // 2 + 1
    cortes = np.cumsum([0] + [n_bins // 16 + (i < n_bins % 16) for i in range(16)])
    quadros = np.lib.stride_tricks.sliding_window_view(padded, tamanho)
    # Mesmo cálculo por frame, vetorizado em lotes para limitar a memória.
    for i in range(0, len(centros), 2048):
        x = quadros[centros[i:i + 2048]].copy()
        rms.append(np.sqrt(np.mean(x * x, axis=1)))
        x -= x.mean(axis=1, keepdims=True)
        espectro = np.abs(np.fft.rfft(x * janela, axis=1))
        espectro /= np.linalg.norm(espectro, axis=1, keepdims=True) + 1e-12
        # Bandas largas reduzem a influência de pequenas mudanças de pitch.
        bandas = np.stack([np.linalg.norm(espectro[:, a:b], axis=1)
                           for a, b in zip(cortes[:-1], cortes[1:])], axis=1)
        bandas /= np.linalg.norm(bandas, axis=1, keepdims=True) + 1e-12
        timbres.append(bandas)
        vizinho = np.vstack([espectro[:1] if anterior is None else anterior, espectro[:-1]])
        diferenca = np.linalg.norm(espectro - vizinho, axis=1)
        if anterior is None:
            diferenca[0] = 0.0
        fluxo.append(diferenca)
        anterior = espectro[-1:]
        transformada = np.fft.rfft(x, nfft, axis=1)
        ac = np.fft.irfft(transformada * transformada.conj(), nfft, axis=1)[:, :tamanho]
        energia = np.concatenate([np.zeros((len(x), 1)), np.cumsum(x * x, axis=1)], axis=1)
        den = np.sqrt(energia[:, tamanho - lags] * (energia[:, -1:] - energia[:, lags]))
        periodicidade.append(np.clip(np.max(ac[:, lags] / (den + 1e-12), axis=1), 0, 1))
    rms, fluxo = np.concatenate(rms), np.concatenate(fluxo)
    periodicidade = np.concatenate(periodicidade)
    timbres = np.concatenate(timbres)
    escala = max(float(np.percentile(fluxo, 90)), 0.05)
    return {"tempos": centros / sr, "rms": rms, "periodicidade": periodicidade,
            "fluxo": np.clip(fluxo / escala, 0, 1), "passo": hop / sr,
            "timbres": np.asarray(timbres)}


def _caracteres_correspondentes(palavra):
    cs = filtrar_caracteres_lexicos(palavra.caracteres)
    texto = "".join(str(c.get("char", "")) for c in cs)
    return cs if texto.casefold() == normalizar_palavra(palavra.texto).casefold() else []


def _intervalo_char(c, inicio, fim):
    a, b = valor_numerico_valido(c.get("start")), valor_numerico_valido(c.get("end"))
    score = valor_numerico_valido(c.get("score")) or 0.0
    if a is None or b is None or b <= a or score < cfg.SCORE_MINIMO_CARACTERE:
        return None
    # Não recorta caracteres externos: recortar mascarava erros como duração zero.
    if a < inicio - 1e-6 or b > fim + 1e-6:
        return None
    return a, b


def _refinar_fronteira(alvo, minimo, maximo, evidencia):
    if evidencia is None:
        return alvo, False
    t = evidencia["tempos"]
    ids = np.flatnonzero((t >= max(minimo, alvo - cfg.RAIO_REFINAMENTO)) &
                        (t <= min(maximo, alvo + cfg.RAIO_REFINAMENTO)))
    if not len(ids):
        return alvo, False
    rms = evidencia["rms"][ids]
    nivel = max(float(rms.max()), cfg.ENERGIA_ABSOLUTA_MINIMA)
    if nivel <= cfg.ENERGIA_ABSOLUTA_MINIMA:
        return alvo, False
    evento = (0.6 * evidencia["fluxo"][ids] +
              0.4 * (1.0 - np.clip(rms / nivel, 0, 1)))
    proximidade = np.abs(t[ids] - alvo) / max(cfg.RAIO_REFINAMENTO, 1e-6)
    melhor = int(np.argmax(evento - 0.3 * proximidade))
    if evento[melhor] < cfg.LIMIAR_EVENTO_FRONTEIRA:
        return alvo, False
    return float(t[ids[melhor]]), True


def _limites_silabas(palavra, silabas, evidencia=None):
    # A recuperação prolonga a última sílaba; não redistribui a duração
    # acrescentada entre todas as sílabas e não desloca ataques existentes.
    if palavra.fim_original is not None and palavra.fim > palavra.fim_original + 1e-9:
        base = replace(palavra, fim=palavra.fim_original, fim_original=None)
        limites, origens = _limites_silabas(base, silabas, evidencia)
        limites[-1] = palavra.fim
        return limites, origens
    n = len(silabas)
    if n == 0 or palavra.fim <= palavra.inicio:
        raise ValueError(f"Palavra sem intervalo utilizável: {palavra.id}")
    piso = min(cfg.DURACAO_MINIMA_SILABA, palavra.duracao / n * cfg.FRACAO_PISO_SILABA)
    cs = _caracteres_correspondentes(palavra)
    # Hipótese fraca: peso por núcleo + pequena contribuição das consoantes.
    pesos = np.array([1.0 + 0.12 * sum(c not in VOGAIS for c in s) for s in silabas])
    fallback = palavra.inicio + palavra.duracao * np.cumsum(pesos) / pesos.sum()
    limites, origens, pos = [palavra.inicio], ["srt"], 0
    for i in range(1, n):
        pos += len(silabas[i - 1])
        minimo = limites[-1] + piso
        maximo = palavra.fim - (n - i) * piso
        alvo, origem = float(fallback[i - 1]), "fallback_proporcional"
        if cs and 0 < pos < len(cs):
            esquerdo = _intervalo_char(cs[pos - 1], palavra.inicio, palavra.fim)
            direito = _intervalo_char(cs[pos], palavra.inicio, palavra.fim)
            # Prefere o ataque da próxima sílaba. O fim CTC da vogal anterior
            # pode ser curto mesmo quando a vogal continua sendo sustentada.
            if esquerdo and direito and esquerdo[1] <= direito[0] + 0.020:
                candidato = direito[0]
                if minimo <= candidato <= maximo:
                    alvo, origem = candidato, "caracteres_whisperx"
        alvo = float(np.clip(alvo, minimo, maximo))
        alvo, refinado = _refinar_fronteira(alvo, minimo, maximo, evidencia)
        if refinado:
            origem += "+refinamento_acustico"
        limites.append(alvo)
        origens.append(origem)
    limites.append(palavra.fim)
    origens.append("srt")
    return limites, origens


def calcular_limites_silabas(palavra, silabas):
    limites, origens = _limites_silabas(palavra, silabas, getattr(palavra, "_evidencia", None))
    return limites, [o.startswith("caracteres_whisperx") for o in origens]


def _nucleo(inicio, fim, caracteres, evidencia=None):
    if fim <= inicio:
        raise ValueError("Núcleo exige sílaba com duração positiva.")
    minimo = min(cfg.DURACAO_MINIMA_NUCLEO, (fim - inicio) * 0.4)
    vogais = [v for c in caracteres if str(c.get("char", "")) in VOGAIS
              if (v := _intervalo_char(c, inicio, fim)) is not None]
    if evidencia is not None:
        t = evidencia["tempos"]
        ids = np.flatnonzero((t >= inicio) & (t < fim))
        if len(ids):
            rms = evidencia["rms"][ids]
            limiar = max(cfg.ENERGIA_ABSOLUTA_MINIMA,
                         float(np.percentile(rms, 90)) * cfg.ENERGIA_RELATIVA_MINIMA)
            ativo = rms >= limiar
            periodico = ativo & (evidencia["periodicidade"][ids] >= cfg.PERIODICIDADE_MINIMA)
            cobertura = float(periodico.mean())
            mascara = periodico.copy()
            dt = evidencia["passo"]
            # Só atravessa quedas breves de periodicidade COM energia presente.
            for a, b in _trechos(~mascara):
                if a > 0 and b < len(mascara) and (b - a) * dt <= cfg.GAP_PERIODICIDADE_MAXIMO and ativo[a:b].all():
                    mascara[a:b] = True
            regioes = []
            for a, b in _trechos(mascara):
                x = max(inicio, float(t[ids[a]]) - dt / 2)
                y = min(fim, float(t[ids[b - 1]]) + dt / 2)
                if y - x >= minimo:
                    sobreposicao = sum(max(0.0, min(y, v) - max(x, u)) for u, v in vogais)
                    regioes.append((y - x + sobreposicao, x, y))
            avisos = []
            if any((b - a) * dt >= cfg.PAUSA_INTERNA_AVISO for a, b in _trechos(~ativo)):
                avisos.append("baixa_energia_prolongada_na_silaba")
            if regioes:
                _, x, y = max(regioes)
                if len(regioes) > 1:
                    avisos.append("multiplas_regioes_periodicas")
                return x, y, "regiao_periodica_estimada", cobertura, avisos
            return inicio + 0.2 * (fim - inicio), fim - 0.1 * (fim - inicio), "fallback_proporcional", cobertura, ["sem_nucleo_periodico_util"]
    if vogais:
        x, y = min(v[0] for v in vogais), max(v[1] for v in vogais)
        if y - x >= minimo:
            return x, y, "caracteres_whisperx_sem_audio", None, ["nucleo_nao_validado_no_audio"]
    return inicio + 0.2 * (fim - inicio), fim - 0.1 * (fim - inicio), "fallback_proporcional", None, ["nucleo_estimado_sem_audio"]


def calcular_nucleo_vogal(inicio_silaba, fim_silaba, caracteres_silaba):
    return _nucleo(inicio_silaba, fim_silaba, caracteres_silaba)[:2]


def gerar_silabas_alinhadas(palavras, idioma="pt_BR", *, audio=None, sr=16000, avisos=None):
    """Interface antiga preservada. O alinhador anexa a evidência em memória.

    Ao reconstruir palavras a partir de JSON, passe audio mono e sr explicitamente.
    Sem áudio, o fallback continua possível, mas fica identificado para revisão.
    """
    silabificador = Silabificador(idioma)
    evidencia_explicita = analisar_audio_canto(audio, sr) if audio is not None else None
    resultado = []
    for palavra in palavras:
        textos = silabificador.separar(palavra.texto)
        if not textos:
            continue
        evidencia = evidencia_explicita if evidencia_explicita is not None else getattr(palavra, "_evidencia", None)
        limites, origens = _limites_silabas(palavra, textos, evidencia)
        caracteres = _caracteres_correspondentes(palavra)
        pos = 0
        for i, texto in enumerate(textos):
            inicio, fim = limites[i:i + 2]
            cs = caracteres[pos:pos + len(texto)]
            pos += len(texto)
            a, b, origem_nucleo, cobertura, alertas = _nucleo(inicio, fim, cs, evidencia)
            alertas.extend(palavra.avisos)
            if i == len(textos) - 1 and palavra.ajustes:
                alertas.append("sustentacao_recuperada_por_heuristica")
            fontes = sorted(set(origens[max(1, i):min(len(textos), i + 2)]))
            origem = "|".join(fontes) if fontes else "palavra_inteira_srt"
            if "fallback" in origem:
                alertas.append("fronteira_silabica_estimada")
            if fim - inicio < cfg.DURACAO_MINIMA_SILABA - 1e-9:
                alertas.append("silaba_curta_piso_adaptado")
            if media_scores(cs, palavra.score) < cfg.SCORE_MINIMO_CARACTERE:
                alertas.append("score_alinhamento_baixo")
            if cobertura is not None and cobertura < 0.30:
                alertas.append("baixa_cobertura_periodica")
            if len(textos) > 1 and (fim - inicio) / palavra.duracao > 0.9:
                alertas.append("distribuicao_muito_desigual_verificar_sustentacao")
            score = media_scores(cs, palavra.score)
            if "fallback" in origem or "fallback" in origem_nucleo:
                score = min(score, 0.25)
            silaba = SilabaAlinhada(
                f"{palavra.id}_s{i + 1}", palavra.id, palavra.bloco_indice,
                i + 1, len(resultado) + 1, texto, normalizar_palavra(texto),
                float(inicio), float(fim), float(a), float(b), float(score),
                origem, origem_nucleo, bool(alertas), list(dict.fromkeys(alertas)), cobertura,
            )
            resultado.append(silaba)
            destinos = [avisos, getattr(palavra, "_avisos", None)]
            mensagem = f"{silaba.id} ({texto}): {', '.join(silaba.avisos)}"
            for destino in destinos:
                if destino is not None and alertas and mensagem not in destino:
                    destino.append(mensagem)
    return resultado


def salvar_json(caminho, dados):
    caminho = Path(caminho).expanduser().resolve()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(dados, dict) and "silabas" in dados and "metadados" in dados:
        dados = dict(dados)
        meta = dict(dados["metadados"])
        silabas = dados["silabas"]
        meta["versao_alinhador"] = "2.1-frases"
        meta["total_silabas_revisao"] = sum(bool(s.get("precisa_revisao")) for s in silabas)
        meta["scores_sao_probabilidades_calibradas"] = False
        meta["avisos"] = list(meta.get("avisos", []))
        palavras = dados.get("palavras", [])
        meta["total_palavras_com_recuperacao"] = sum(bool(p.get("ajustes")) for p in palavras)
        meta["duracao_recuperada_segundos"] = sum(
            ajuste.get("duracao_recuperada", 0.0)
            for p in palavras for ajuste in p.get("ajustes", [])
        )
        meta["aprovacao_musical_automatica"] = False
        for s in silabas:
            if s.get("avisos"):
                aviso = f"{s['id']} ({s['texto']}): {', '.join(s['avisos'])}"
                if aviso not in meta["avisos"]:
                    meta["avisos"].append(aviso)
        dados["metadados"] = meta
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")