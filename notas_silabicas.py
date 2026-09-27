from __future__ import annotations

import csv
import json
import math
import time

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import librosa
import numpy as np
from config_alinhamento import PESO_MINIMO_ENERGIA_PITCH
from medicao import informar_ambiente, medir

from config_notas import (
    BINS_POR_OITAVA_CQT,
    CONFIANCA_HARMONICA_MINIMA,
    CONFIANCA_MINIMA_SEM_REVISAO,
    CORRECAO_CENTS_PARA_REVISAO,
    ESCALA_CONTINUIDADE_SEMITONS,
    ESCALA_DISTANCIA_VOCAL_CENTS,
    FRAME_LENGTH_NOTAS,
    FRAMES_VOCAIS_MINIMOS,
    GAP_MAXIMO_CONTINUIDADE,
    HOP_LENGTH_NOTAS,
    JANELA_CENTRO_PREDOMINANTE_CENTS,
    JANELA_SUAVIZACAO_CHROMA,
    MARGEM_FALLBACK_SILABA,
    MONO_NOTAS,
    NOTA_VOCAL_MAXIMA,
    NOTA_VOCAL_MINIMA,
    PESO_CONTINUIDADE,
    PESO_HARMONIA,
    PESO_OCUPACAO_VOZ,
    PESO_PROXIMIDADE_VOZ,
    RAIO_CANDIDATOS_SEMITONS,
    RAIO_ESTABILIDADE_CENTS,
    RAIO_OCUPACAO_CANDIDATO_CENTS,
    RESOLUCAO_HISTOGRAMA_CENTS,
    SAMPLE_RATE_NOTAS,
    VOICED_PROB_MIN_NOTAS,
)


@dataclass
class NotaSilabica:
    id: str
    silaba_id: str
    palavra_id: str
    bloco_indice: int
    ordem_global: int

    palavra: str
    silaba: str

    inicio_silaba: float
    fim_silaba: float
    inicio_nucleo_vogal: float
    fim_nucleo_vogal: float

    inicio_nota: float
    fim_nota: float

    pitch_midi: int
    nome_nota: str

    centro_vocal_midi: float
    correcao_cents: float

    fonte_pitch: str
    frames_vocais: int

    confianca_voz: float
    estabilidade_voz: float
    suporte_harmonico: float
    confianca_harmonica: float

    score_final: float
    margem_decisao: float
    confianca_final: float

    revisao_recomendada: bool
    motivos_revisao: list[str]

    candidatos: list[dict[str, Any]]
    ajustes_duracao: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duracao(self) -> float:
        return max(
            0.0,
            self.fim_nota - self.inicio_nota,
        )

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DadosVozSilaba:
    valores_midi: np.ndarray
    pesos: np.ndarray
    probabilidades: np.ndarray
    centro_vocal: float
    confianca_voz: float
    estabilidade: float
    fonte: str

    @property
    def quantidade_frames(self) -> int:
        return len(
            self.valores_midi
        )


def numero_valido(
    valor: Any,
) -> Optional[float]:
    if valor is None:
        return None

    try:
        numero = float(
            valor
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if not math.isfinite(numero):
        return None

    return numero


def media_ponderada(
    valores: np.ndarray,
    pesos: np.ndarray,
) -> float:
    valores = np.asarray(
        valores,
        dtype=float,
    )

    pesos = np.asarray(
        pesos,
        dtype=float,
    )

    if len(valores) == 0:
        return float("nan")

    soma_pesos = float(
        np.sum(pesos)
    )

    if soma_pesos <= 0.0:
        return float(
            np.mean(valores)
        )

    return float(
        np.sum(
            valores * pesos
        ) / soma_pesos
    )


def mediana_ponderada(
    valores: np.ndarray,
    pesos: np.ndarray,
) -> float:
    valores = np.asarray(
        valores,
        dtype=float,
    )

    pesos = np.asarray(
        pesos,
        dtype=float,
    )

    if len(valores) == 0:
        return float("nan")

    ordem = np.argsort(
        valores
    )

    valores_ordenados = valores[
        ordem
    ]

    pesos_ordenados = pesos[
        ordem
    ]

    soma_pesos = float(
        np.sum(pesos_ordenados)
    )

    if soma_pesos <= 0.0:
        return float(
            np.median(
                valores_ordenados
            )
        )

    acumulado = np.cumsum(
        pesos_ordenados
    )

    indice = int(
        np.searchsorted(
            acumulado,
            soma_pesos / 2.0,
            side="left",
        )
    )

    indice = min(
        indice,
        len(valores_ordenados) - 1,
    )

    return float(
        valores_ordenados[indice]
    )


def centro_pitch_predominante(
    valores_midi: np.ndarray,
    pesos: np.ndarray,
) -> float:
    """
    Encontra o plateau de pitch com maior ocupação.

    Como haverá apenas uma nota por sílaba, não calculamos
    uma média cega entre todos os pitches. Primeiro localizamos
    a região mais ocupada e depois calculamos sua mediana.
    """

    valores_midi = np.asarray(
        valores_midi,
        dtype=float,
    )

    pesos = np.asarray(
        pesos,
        dtype=float,
    )

    mascara = (
        np.isfinite(valores_midi)
        & np.isfinite(pesos)
        & (pesos > 0.0)
    )

    valores_midi = valores_midi[
        mascara
    ]

    pesos = pesos[
        mascara
    ]

    if len(valores_midi) == 0:
        return float("nan")

    resolucao_semitons = (
        RESOLUCAO_HISTOGRAMA_CENTS
        / 100.0
    )

    minimo = (
        math.floor(
            np.min(valores_midi)
            / resolucao_semitons
        )
        * resolucao_semitons
    )

    maximo = (
        math.ceil(
            np.max(valores_midi)
            / resolucao_semitons
        )
        * resolucao_semitons
    )

    if maximo <= minimo:
        return mediana_ponderada(
            valores_midi,
            pesos,
        )

    bordas = np.arange(
        minimo,
        maximo
        + resolucao_semitons * 2.0,
        resolucao_semitons,
    )

    histograma, bordas = np.histogram(
        valores_midi,
        bins=bordas,
        weights=pesos,
    )

    indice_pico = int(
        np.argmax(
            histograma
        )
    )

    centro_bin = (
        bordas[indice_pico]
        + bordas[indice_pico + 1]
    ) / 2.0

    janela_semitons = (
        JANELA_CENTRO_PREDOMINANTE_CENTS
        / 100.0
    )

    mascara_plateau = (
        np.abs(
            valores_midi - centro_bin
        )
        <= janela_semitons
    )

    if not np.any(
        mascara_plateau
    ):
        return mediana_ponderada(
            valores_midi,
            pesos,
        )

    return mediana_ponderada(
        valores_midi[
            mascara_plateau
        ],
        pesos[
            mascara_plateau
        ],
    )


def suavizar_matriz_temporal(
    matriz: np.ndarray,
    tamanho_janela: int,
) -> np.ndarray:
    matriz = np.asarray(
        matriz,
        dtype=float,
    )

    if matriz.ndim != 2:
        raise ValueError(
            "A matriz precisa possuir duas dimensões."
        )

    tamanho_janela = max(
        1,
        int(
            tamanho_janela
        ),
    )

    if tamanho_janela % 2 == 0:
        tamanho_janela += 1

    if (
        tamanho_janela == 1
        or matriz.shape[1] == 0
    ):
        return matriz.copy()

    margem = (
        tamanho_janela // 2
    )

    expandida = np.pad(
        matriz,
        pad_width=(
            (0, 0),
            (margem, margem),
        ),
        mode="edge",
    )

    janelas = (
        np.lib.stride_tricks.sliding_window_view(
            expandida,
            window_shape=tamanho_janela,
            axis=1,
        )
    )

    return np.median(
        janelas,
        axis=-1,
    )


def carregar_silabas_alinhadas(
    caminho_json: str | Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
]:
    caminho_json = Path(
        caminho_json
    ).expanduser().resolve()

    if not caminho_json.exists():
        raise FileNotFoundError(
            "Arquivo de alinhamento não encontrado:\n"
            f"{caminho_json}"
        )

    dados = json.loads(
        caminho_json.read_text(
            encoding="utf-8-sig",
        )
    )

    silabas = dados.get(
        "silabas"
    )

    if not isinstance(
        silabas,
        list,
    ):
        raise ValueError(
            'O JSON não contém a lista "silabas".'
        )

    if not silabas:
        raise ValueError(
            "O alinhamento não contém sílabas."
        )

    campos_obrigatorios = {
        "id",
        "palavra_id",
        "bloco_indice",
        "ordem_global",
        "texto",
        "inicio",
        "fim",
        "inicio_nucleo_vogal",
        "fim_nucleo_vogal",
    }

    for indice, silaba in enumerate(
        silabas,
        start=1,
    ):
        ausentes = (
            campos_obrigatorios
            - set(
                silaba.keys()
            )
        )

        if ausentes:
            raise ValueError(
                f"Sílaba {indice} sem os campos: "
                + ", ".join(
                    sorted(
                        ausentes
                    )
                )
            )

    silabas.sort(
        key=lambda item: (
            float(
                item["inicio"]
            ),
            int(
                item["ordem_global"]
            ),
        )
    )

    validar_tempos_silabas(silabas)
    return dados, silabas



def validar_tempos_silabas(silabas, duracao_audio=None):
    """Não corrige tempos silenciosamente nem invade sílabas vizinhas."""
    ultimo_fim = -1.0
    ids = set()
    for s in silabas:
        campos = ("inicio", "fim", "inicio_nucleo_vogal", "fim_nucleo_vogal")
        vals = [numero_valido(s.get(c)) for c in campos]
        if any(v is None for v in vals):
            raise ValueError(f"Tempos ausentes/não finitos: {s.get('id')}")
        a, b, x, y = vals
        if not 0 <= a <= x < y <= b or not a < b:
            raise ValueError(f"Intervalo inválido: {s.get('id')}")
        if a < ultimo_fim - 1e-9:
            raise ValueError(f"Sílabas sobrepostas: {s.get('id')}")
        if s["id"] in ids:
            raise ValueError(f"Sílaba duplicada: {s['id']}")
        if duracao_audio is not None and b > duracao_audio + 0.002:
            raise ValueError(f"Sílaba {s['id']} ultrapassa o áudio; refaça o alinhamento.")
        ids.add(s["id"])
        ultimo_fim = b


# Resultado da análise de áudio usado na escolha das notas.
CAMPOS_ANALISE = (
    "sr", "duracao_voz", "f0", "voiced_flag", "voiced_prob", "tempos",
    "midi_decimal", "energia_voz", "centro_vocal_global",
    "chroma_harmonico", "confianca_harmonica",
)
VERSAO_ANALISE_AUDIO = 1


def identidade_analise(caminho_voz: str | Path, caminho_instrumental: str | Path) -> str:
    """Identifica a análise por conteúdo, parâmetros, versões e código.

    Nunca depende só do nome do arquivo: qualquer mudança nos áudios, na
    configuração, nas bibliotecas ou nos módulos de análise invalida o reuso.
    """
    import hashlib
    import importlib.metadata as metadata

    import config_alinhamento
    import config_notas

    def sha256(caminho: Path) -> str:
        resumo = hashlib.sha256()
        with Path(caminho).open("rb") as arquivo:
            while bloco := arquivo.read(1024 * 1024):
                resumo.update(bloco)
        return resumo.hexdigest()

    def canonico(valor: Any) -> Any:
        # repr de set muda de ordem entre processos (hash aleatório do Python).
        if isinstance(valor, (set, frozenset)):
            return sorted(repr(canonico(v)) for v in valor)
        if isinstance(valor, dict):
            return {repr(k): canonico(v) for k, v in valor.items()}
        if isinstance(valor, (list, tuple)):
            return [canonico(v) for v in valor]
        return repr(valor)

    def configuracao(modulo) -> dict[str, Any]:
        return {nome: canonico(getattr(modulo, nome)) for nome in sorted(dir(modulo))
                if nome.isupper()}

    versoes = {}
    for pacote in ("librosa", "numpy", "scipy", "numba", "soundfile", "audioread", "soxr"):
        try:
            versoes[pacote] = metadata.version(pacote)
        except metadata.PackageNotFoundError:
            versoes[pacote] = None
    pasta = Path(__file__).resolve().parent
    return json.dumps({
        "versao": VERSAO_ANALISE_AUDIO,
        "voz": sha256(caminho_voz),
        "instrumental": sha256(caminho_instrumental),
        "config_notas": configuracao(config_notas),
        "config_alinhamento": configuracao(config_alinhamento),
        "bibliotecas": versoes,
        "codigo": {nome: sha256(pasta / nome) for nome in
                   ("notas_silabicas.py", "pyin_rapido.py", "letra.py")},
    }, sort_keys=True)


class AnalisadorNotasSilabicas:
    """
    Escolhe exatamente uma nota para cada sílaba.

    A voz fornece:
        - centro predominante;
        - confiança;
        - estabilidade;
        - ocupação dos candidatos.

    O instrumental fornece:
        - evidência harmônica por classe de pitch;
        - confiança do contexto harmônico.
    """

    def __init__(
        self,
        caminho_voz: str | Path,
        caminho_instrumental: str | Path,
        analise_audio: str | Path | None = None,
    ):
        self.caminho_voz = Path(
            caminho_voz
        ).expanduser().resolve()

        self.caminho_instrumental = Path(
            caminho_instrumental
        ).expanduser().resolve()

        if not self.caminho_voz.exists():
            raise FileNotFoundError(
                "Arquivo de voz não encontrado:\n"
                f"{self.caminho_voz}"
            )

        if not self.caminho_instrumental.exists():
            raise FileNotFoundError(
                "Instrumental não encontrado:\n"
                f"{self.caminho_instrumental}"
            )

        self._evidencia_duracao = None
        if analise_audio is not None and self._carregar_analise(analise_audio):
            return

        print()
        print("=" * 60)
        print("CARREGANDO VOZ E INSTRUMENTAL")
        print("=" * 60)

        inicio_leitura = time.perf_counter()
        self.y_voz, self.sr = librosa.load(
            str(
                self.caminho_voz
            ),
            sr=SAMPLE_RATE_NOTAS,
            mono=MONO_NOTAS,
        )

        (
            self.y_instrumental,
            sr_instrumental,
        ) = librosa.load(
            str(
                self.caminho_instrumental
            ),
            sr=SAMPLE_RATE_NOTAS,
            mono=True,
        )

        if sr_instrumental != self.sr:
            raise RuntimeError(
                "Os áudios foram carregados com "
                "sample rates diferentes."
            )

        print(f"[tempo] leitura da voz e do instrumental: "
              f"{time.perf_counter() - inicio_leitura:.1f} s")
        informar_ambiente("cpu")

        self.duracao_voz = (
            len(self.y_voz)
            / float(self.sr)
        )

        self.duracao_instrumental = (
            len(self.y_instrumental)
            / float(self.sr)
        )

        print(
            f"Voz: {self.duracao_voz:.3f} s"
        )

        print(
            "Instrumental: "
            f"{self.duracao_instrumental:.3f} s"
        )

        with medir("pitch vocal (pYIN)"):
            self._analisar_voz()
        with medir("contexto harmônico do instrumental"):
            self._analisar_harmonia()

    def evidencia_duracao(self) -> dict[str, Any]:
        """Evidência acústica da voz em SAMPLE_RATE_NOTAS para a cauda final."""
        if self._evidencia_duracao is None:
            from letra import analisar_audio_canto
            voz_mono = self.y_voz if self.y_voz.ndim == 1 else self.y_voz.mean(axis=0)
            self._evidencia_duracao = analisar_audio_canto(voz_mono, self.sr)
        return self._evidencia_duracao

    def salvar_analise(self, caminho: str | Path) -> None:
        """Grava a análise de áudio (independente das sílabas) para reuso.

        A identidade inclui o conteúdo dos áudios, os parâmetros, as versões
        das bibliotecas e o código-fonte da análise; ver identidade_analise.
        """
        import config_alinhamento as cfg_duracao
        dados = {nome: np.asarray(getattr(self, nome)) for nome in CAMPOS_ANALISE}
        if cfg_duracao.ALONGAR_FINAL_FRASE_MIDI:
            for chave, valor in self.evidencia_duracao().items():
                dados[f"evidencia_{chave}"] = np.asarray(valor)
        identidade = identidade_analise(self.caminho_voz, self.caminho_instrumental)
        caminho = Path(caminho).expanduser().resolve()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = caminho.with_name(caminho.name + ".parcial.npz")
        np.savez(temporario, identidade=np.array(identidade), **dados)
        temporario.replace(caminho)

    def _carregar_analise(self, caminho: str | Path) -> bool:
        caminho = Path(caminho).expanduser().resolve()
        if not caminho.is_file():
            print("Análise de áudio prévia não encontrada; recalculando.")
            return False
        with np.load(caminho, allow_pickle=False) as arquivo:
            esperada = identidade_analise(self.caminho_voz, self.caminho_instrumental)
            if "identidade" not in arquivo or str(arquivo["identidade"]) != esperada:
                print("Análise de áudio prévia não corresponde aos áudios, parâmetros "
                      "ou versões atuais; recalculando.")
                return False
            for nome in CAMPOS_ANALISE:
                valor = arquivo[nome]
                setattr(self, nome, valor.item() if valor.ndim == 0 else valor)
            evidencia = {chave[len("evidencia_"):]: arquivo[chave]
                         for chave in arquivo.files if chave.startswith("evidencia_")}
        if evidencia:
            evidencia["passo"] = float(evidencia["passo"])
            self._evidencia_duracao = evidencia
        self.sr = int(self.sr)
        self.duracao_voz = float(self.duracao_voz)
        self.centro_vocal_global = float(self.centro_vocal_global)
        print(f"Análise de áudio reaproveitada: {caminho.name}")
        print(f"Voz: {self.duracao_voz:.3f} s")
        return True

    def _analisar_voz(self):
        print()
        print("=" * 60)
        print("ANALISANDO PITCH VOCAL")
        print("=" * 60)

        fmin = librosa.note_to_hz(
            NOTA_VOCAL_MINIMA
        )

        fmax = librosa.note_to_hz(
            NOTA_VOCAL_MAXIMA
        )

        # Mesmo resultado de librosa.pyin; só a decodificação Viterbi é esparsa.
        from pyin_rapido import pyin

        (
            self.f0,
            self.voiced_flag,
            self.voiced_prob,
        ) = pyin(
            self.y_voz,
            fmin=fmin,
            fmax=fmax,
            sr=self.sr,
            frame_length=FRAME_LENGTH_NOTAS,
            hop_length=HOP_LENGTH_NOTAS,
        )

        self.tempos = librosa.times_like(
            self.f0,
            sr=self.sr,
            hop_length=HOP_LENGTH_NOTAS,
        )

        self.midi_decimal = np.full(
            len(self.f0),
            np.nan,
            dtype=float,
        )

        mascara_f0 = np.isfinite(
            self.f0
        )

        self.midi_decimal[
            mascara_f0
        ] = librosa.hz_to_midi(
            self.f0[
                mascara_f0
            ]
        )

        self.voiced_prob = np.nan_to_num(
            self.voiced_prob,
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )

        rms = librosa.feature.rms(
            y=self.y_voz,
            frame_length=FRAME_LENGTH_NOTAS,
            hop_length=HOP_LENGTH_NOTAS,
            center=True,
        )[0]

        tempos_rms = librosa.times_like(
            rms,
            sr=self.sr,
            hop_length=HOP_LENGTH_NOTAS,
        )

        self.energia_voz = np.interp(
            self.tempos,
            tempos_rms,
            rms,
            left=0.0,
            right=0.0,
        )

        mascara_global = (
            np.isfinite(
                self.midi_decimal
            )
            & (
                self.voiced_prob
                >= VOICED_PROB_MIN_NOTAS
            )
        )

        if not np.any(
            mascara_global
        ):
            raise RuntimeError(
                "Não foi encontrado pitch vocal "
                "suficiente no arquivo de voz."
            )

        pesos_globais = np.maximum(
            self.voiced_prob[
                mascara_global
            ],
            0.01,
        )

        self.centro_vocal_global = (
            centro_pitch_predominante(
                self.midi_decimal[
                    mascara_global
                ],
                pesos_globais,
            )
        )

        print(
            "Centro vocal global aproximado: "
            f"{self.centro_vocal_global:.2f} MIDI"
        )

    def _analisar_harmonia(self):
        print()
        print("=" * 60)
        print("ANALISANDO CONTEXTO HARMÔNICO")
        print("=" * 60)

        instrumental_harmonico = (
            librosa.effects.harmonic(
                self.y_instrumental,
                margin=8.0,
            )
        )

        afinacao_instrumental = (
            librosa.estimate_tuning(
                y=instrumental_harmonico,
                sr=self.sr,
                bins_per_octave=12,
            )
        )

        chroma = librosa.feature.chroma_cqt(
            y=instrumental_harmonico,
            sr=self.sr,
            hop_length=HOP_LENGTH_NOTAS,
            n_chroma=12,
            bins_per_octave=(
                BINS_POR_OITAVA_CQT
            ),
            tuning=afinacao_instrumental,
            norm=None,
        )

        chroma = np.nan_to_num(
            chroma,
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )

        chroma = np.maximum(
            chroma,
            0.0,
        )

        chroma = np.log1p(
            10.0 * chroma
        )

        chroma = suavizar_matriz_temporal(
            chroma,
            JANELA_SUAVIZACAO_CHROMA,
        )

        soma = np.sum(
            chroma,
            axis=0,
        )

        chroma_l1 = np.divide(
            chroma,
            soma[np.newaxis, :],
            out=np.zeros_like(
                chroma
            ),
            where=(
                soma[np.newaxis, :]
                > 1e-12
            ),
        )

        maximo = np.max(
            chroma,
            axis=0,
        )

        evidencia = np.divide(
            chroma,
            maximo[np.newaxis, :],
            out=np.zeros_like(
                chroma
            ),
            where=(
                maximo[np.newaxis, :]
                > 1e-12
            ),
        )

        pico_l1 = np.max(
            chroma_l1,
            axis=0,
        )

        valor_uniforme = (
            1.0 / 12.0
        )

        confianca_concentracao = (
            pico_l1 - valor_uniforme
        ) / (
            0.30 - valor_uniforme
        )

        confianca_concentracao = np.clip(
            confianca_concentracao,
            0.0,
            1.0,
        )

        rms = librosa.feature.rms(
            y=self.y_instrumental,
            frame_length=FRAME_LENGTH_NOTAS,
            hop_length=HOP_LENGTH_NOTAS,
            center=True,
        )[0]

        tempos_rms = librosa.times_like(
            rms,
            sr=self.sr,
            hop_length=HOP_LENGTH_NOTAS,
        )

        tempos_chroma = librosa.times_like(
            evidencia,
            sr=self.sr,
            hop_length=HOP_LENGTH_NOTAS,
        )

        rms_chroma = np.interp(
            tempos_chroma,
            tempos_rms,
            rms,
            left=0.0,
            right=0.0,
        )

        if len(rms_chroma) > 0:
            energia_baixa = np.percentile(
                rms_chroma,
                15,
            )

            energia_alta = np.percentile(
                rms_chroma,
                70,
            )
        else:
            energia_baixa = 0.0
            energia_alta = 0.0

        intervalo = (
            energia_alta
            - energia_baixa
        )

        if intervalo <= 1e-12:
            confianca_energia = np.where(
                rms_chroma > 0.0,
                1.0,
                0.0,
            )
        else:
            confianca_energia = np.clip(
                (
                    rms_chroma
                    - energia_baixa
                ) / intervalo,
                0.0,
                1.0,
            )

        confianca = (
            confianca_concentracao
            * confianca_energia
        )

        self.chroma_harmonico = np.zeros(
            (
                12,
                len(self.tempos),
            ),
            dtype=float,
        )

        for classe in range(12):
            self.chroma_harmonico[
                classe
            ] = np.interp(
                self.tempos,
                tempos_chroma,
                evidencia[classe],
                left=0.0,
                right=0.0,
            )

        self.confianca_harmonica = np.interp(
            self.tempos,
            tempos_chroma,
            confianca,
            left=0.0,
            right=0.0,
        )

        print(
            "Desvio de afinação estimado do "
            "instrumental: "
            f"{afinacao_instrumental * 100.0:+.1f} cents"
        )

    def _extrair_frames_voz(
        self,
        inicio: float,
        fim: float,
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
    ]:
        mascara_intervalo = (
            (self.tempos >= inicio)
            & (self.tempos < fim)
        )

        mascara_valida = (
            mascara_intervalo
            & np.isfinite(
                self.midi_decimal
            )
            & (
                self.voiced_prob
                >= VOICED_PROB_MIN_NOTAS
            )
        )

        valores = self.midi_decimal[
            mascara_valida
        ]

        probabilidades = self.voiced_prob[
            mascara_valida
        ]

        energias = self.energia_voz[
            mascara_valida
        ]

        if len(valores) == 0:
            return (
                np.array(
                    [],
                    dtype=float,
                ),
                np.array(
                    [],
                    dtype=float,
                ),
                np.array(
                    [],
                    dtype=float,
                ),
            )

        percentil_energia = float(
            np.percentile(
                energias,
                90,
            )
        )

        if percentil_energia <= 1e-12:
            pesos_energia = np.ones_like(
                energias
            )
        else:
            pesos_energia = np.clip(
                energias
                / percentil_energia,
                PESO_MINIMO_ENERGIA_PITCH,
                1.0,
            )

        pesos = (
            np.maximum(
                probabilidades,
                0.01,
            ) ** 2
            * pesos_energia
        )

        return (
            valores,
            pesos,
            probabilidades,
        )

    def _dados_voz_silaba(
        self,
        silaba: dict[str, Any],
        pitch_anterior: Optional[int],
    ) -> DadosVozSilaba:
        inicio_silaba = float(
            silaba["inicio"]
        )

        fim_silaba = float(
            silaba["fim"]
        )

        inicio_nucleo = float(
            silaba[
                "inicio_nucleo_vogal"
            ]
        )

        fim_nucleo = float(
            silaba[
                "fim_nucleo_vogal"
            ]
        )

        tentativas = [
            (
                "nucleo_vogal",
                inicio_nucleo,
                fim_nucleo,
            ),
            (
                "silaba_completa",
                inicio_silaba,
                fim_silaba,
            ),
            (
                "contexto_expandido",
                max(
                    0.0,
                    inicio_silaba
                    - MARGEM_FALLBACK_SILABA,
                    getattr(self, "_inicio_contexto", inicio_silaba),
                ),
                min(
                    self.duracao_voz,
                    fim_silaba
                    + MARGEM_FALLBACK_SILABA,
                    getattr(self, "_fim_contexto", fim_silaba),
                ),
            ),
        ]

        valores = np.array(
            [],
            dtype=float,
        )

        pesos = np.array(
            [],
            dtype=float,
        )

        probabilidades = np.array(
            [],
            dtype=float,
        )

        fonte = "sem_f0"

        for (
            nome_fonte,
            inicio,
            fim,
        ) in tentativas:
            (
                valores_tentativa,
                pesos_tentativa,
                probabilidades_tentativa,
            ) = self._extrair_frames_voz(
                inicio,
                fim,
            )

            if (
                len(valores_tentativa)
                >= FRAMES_VOCAIS_MINIMOS
            ):
                valores = valores_tentativa
                pesos = pesos_tentativa
                probabilidades = (
                    probabilidades_tentativa
                )
                fonte = nome_fonte
                break

            if (
                len(valores_tentativa)
                > len(valores)
            ):
                valores = valores_tentativa
                pesos = pesos_tentativa
                probabilidades = (
                    probabilidades_tentativa
                )
                fonte = nome_fonte

        if len(valores) == 0:
            centro_fallback = (
                float(
                    pitch_anterior
                )
                if pitch_anterior is not None
                else self.centro_vocal_global
            )

            return DadosVozSilaba(
                valores_midi=np.array(
                    [],
                    dtype=float,
                ),
                pesos=np.array(
                    [],
                    dtype=float,
                ),
                probabilidades=np.array(
                    [],
                    dtype=float,
                ),
                centro_vocal=centro_fallback,
                confianca_voz=0.0,
                estabilidade=0.0,
                fonte=(
                    "nota_anterior"
                    if pitch_anterior is not None
                    else "centro_vocal_global"
                ),
            )

        centro = centro_pitch_predominante(
            valores,
            pesos,
        )

        confianca_voz = float(
            np.average(
                probabilidades,
                weights=np.maximum(
                    pesos,
                    1e-9,
                ),
            )
        )

        raio_estabilidade = (
            RAIO_ESTABILIDADE_CENTS
            / 100.0
        )

        estabilidade = float(
            np.sum(
                pesos[
                    np.abs(
                        valores - centro
                    )
                    <= raio_estabilidade
                ]
            )
            / max(
                np.sum(pesos),
                1e-12,
            )
        )

        return DadosVozSilaba(
            valores_midi=valores,
            pesos=pesos,
            probabilidades=probabilidades,
            centro_vocal=float(
                centro
            ),
            confianca_voz=confianca_voz,
            estabilidade=estabilidade,
            fonte=fonte,
        )

    def _suporte_harmonico(
        self,
        inicio: float,
        fim: float,
        pitch_midi: int,
    ) -> tuple[float, float]:
        mascara = (
            (self.tempos >= inicio)
            & (self.tempos <= fim)
        )

        if not np.any(
            mascara
        ):
            return (
                0.0,
                0.0,
            )

        confiancas = self.confianca_harmonica[
            mascara
        ]

        confianca_media = float(
            np.mean(
                confiancas
            )
        )

        evidencias = self.chroma_harmonico[
            pitch_midi % 12,
            mascara,
        ]

        pesos = np.maximum(
            confiancas,
            0.05,
        )

        suporte = float(
            np.average(
                evidencias,
                weights=pesos,
            )
        )

        return (
            suporte,
            confianca_media,
        )

    def _avaliar_candidatos(
        self,
        silaba: dict[str, Any],
        dados_voz: DadosVozSilaba,
        pitch_anterior: Optional[int],
        fim_nota_anterior: Optional[float],
    ) -> list[dict[str, Any]]:
        centro = (
            dados_voz.centro_vocal
        )

        pitch_base = int(
            math.floor(
                centro + 0.5
            )
        )

        pitch_minimo = int(
            math.floor(
                librosa.note_to_midi(
                    NOTA_VOCAL_MINIMA
                )
            )
        )

        pitch_maximo = int(
            math.ceil(
                librosa.note_to_midi(
                    NOTA_VOCAL_MAXIMA
                )
            )
        )

        candidatos_pitch = range(
            max(
                pitch_minimo,
                pitch_base
                - RAIO_CANDIDATOS_SEMITONS,
            ),
            min(
                pitch_maximo,
                pitch_base
                + RAIO_CANDIDATOS_SEMITONS,
            )
            + 1,
        )

        inicio_silaba = float(
            silaba["inicio"]
        )

        fim_silaba = float(
            silaba["fim"]
        )

        continuidade_ativa = (
            pitch_anterior is not None
            and fim_nota_anterior is not None
            and (
                inicio_silaba
                - fim_nota_anterior
            ) <= GAP_MAXIMO_CONTINUIDADE
        )

        candidatos = []

        for pitch in candidatos_pitch:
            distancia_cents = abs(
                centro - pitch
            ) * 100.0

            proximidade_voz = math.exp(
                -0.5
                * (
                    distancia_cents
                    / ESCALA_DISTANCIA_VOCAL_CENTS
                ) ** 2
            )

            if (
                dados_voz.quantidade_frames > 0
            ):
                raio_ocupacao = (
                    RAIO_OCUPACAO_CANDIDATO_CENTS
                    / 100.0
                )

                mascara_ocupacao = (
                    np.abs(
                        dados_voz.valores_midi
                        - pitch
                    )
                    <= raio_ocupacao
                )

                ocupacao_voz = float(
                    np.sum(
                        dados_voz.pesos[
                            mascara_ocupacao
                        ]
                    )
                    / max(
                        np.sum(
                            dados_voz.pesos
                        ),
                        1e-12,
                    )
                )
            else:
                ocupacao_voz = 0.0

            (
                suporte_harmonico,
                confianca_harmonica,
            ) = self._suporte_harmonico(
                inicio=inicio_silaba,
                fim=fim_silaba,
                pitch_midi=pitch,
            )

            if (
                confianca_harmonica
                < CONFIANCA_HARMONICA_MINIMA
            ):
                componente_harmonia = 0.0
            else:
                componente_harmonia = (
                    suporte_harmonico
                    * confianca_harmonica
                )

            if continuidade_ativa:
                distancia_anterior = abs(
                    pitch
                    - pitch_anterior
                )

                continuidade = math.exp(
                    -distancia_anterior
                    / ESCALA_CONTINUIDADE_SEMITONS
                )
            else:
                continuidade = 0.0

            score = (
                PESO_PROXIMIDADE_VOZ
                * proximidade_voz
                + PESO_OCUPACAO_VOZ
                * ocupacao_voz
                + PESO_HARMONIA
                * componente_harmonia
                + PESO_CONTINUIDADE
                * continuidade
            )

            candidatos.append(
                {
                    "pitch_midi": int(
                        pitch
                    ),
                    "nome_nota": (
                        librosa.midi_to_note(
                            pitch,
                            unicode=False,
                        )
                    ),
                    "distancia_cents": float(
                        distancia_cents
                    ),
                    "proximidade_voz": float(
                        proximidade_voz
                    ),
                    "ocupacao_voz": float(
                        ocupacao_voz
                    ),
                    "suporte_harmonico": float(
                        suporte_harmonico
                    ),
                    "confianca_harmonica": float(
                        confianca_harmonica
                    ),
                    "componente_harmonia": float(
                        componente_harmonia
                    ),
                    "continuidade": float(
                        continuidade
                    ),
                    "score": float(
                        score
                    ),
                }
            )

        candidatos.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        return candidatos

    def analisar(
        self,
        silabas: list[dict[str, Any]],
        palavras: Optional[
            list[dict[str, Any]]
        ] = None,
    ) -> list[NotaSilabica]:
        mapa_palavras = {}

        if palavras:
            mapa_palavras = {
                palavra["id"]: palavra
                for palavra in palavras
                if "id" in palavra
            }

        silabas = sorted(silabas, key=lambda s: (float(s["inicio"]), int(s["ordem_global"])))
        validar_tempos_silabas(silabas, self.duracao_voz)
        resultado = []

        pitch_anterior = None
        fim_nota_anterior = None

        for posicao, silaba in enumerate(
            silabas,
            start=1,
        ):
            if fim_nota_anterior is not None and float(silaba["inicio"]) - fim_nota_anterior > GAP_MAXIMO_CONTINUIDADE:
                pitch_anterior = None
            # Contexto de fallback limitado pelo vizinho: não empresta pitch
            # de outra sílaba nem de uma frase separada por silêncio.
            anterior = silabas[posicao - 2] if posicao > 1 else None
            proxima = silabas[posicao] if posicao < len(silabas) else None
            self._inicio_contexto = (
                float(anterior["fim"]) if anterior and anterior["bloco_indice"] == silaba["bloco_indice"]
                else float(silaba["inicio"])
            )
            self._fim_contexto = (
                float(proxima["inicio"]) if proxima and proxima["bloco_indice"] == silaba["bloco_indice"]
                else float(silaba["fim"])
            )
            dados_voz = (
                self._dados_voz_silaba(
                    silaba,
                    pitch_anterior,
                )
            )

            candidatos = (
                self._avaliar_candidatos(
                    silaba=silaba,
                    dados_voz=dados_voz,
                    pitch_anterior=pitch_anterior,
                    fim_nota_anterior=(
                        fim_nota_anterior
                    ),
                )
            )

            if not candidatos:
                raise RuntimeError(
                    "Nenhum candidato musical foi "
                    f"gerado para a sílaba {silaba['id']}."
                )

            melhor = candidatos[0]

            segundo_score = (
                candidatos[1]["score"]
                if len(candidatos) > 1
                else 0.0
            )

            margem_decisao = max(
                0.0,
                melhor["score"]
                - segundo_score,
            )

            confianca_margem = min(
                1.0,
                margem_decisao / 0.20,
            )

            confianca_final = (
                0.35
                * dados_voz.confianca_voz
                + 0.25
                * dados_voz.estabilidade
                + 0.20
                * melhor[
                    "confianca_harmonica"
                ]
                + 0.20
                * confianca_margem
            )

            if (
                dados_voz.quantidade_frames == 0
            ):
                confianca_final *= 0.45

            confianca_final = float(
                np.clip(
                    confianca_final,
                    0.0,
                    1.0,
                )
            )

            correcao_cents = (
                melhor["pitch_midi"]
                - dados_voz.centro_vocal
            ) * 100.0

            inicio_silaba = float(
                silaba["inicio"]
            )

            fim_silaba = float(
                silaba["fim"]
            )

            inicio_nucleo = float(
                silaba[
                    "inicio_nucleo_vogal"
                ]
            )

            fim_nucleo = float(
                silaba[
                    "fim_nucleo_vogal"
                ]
            )

            # A janela do núcleo serve ao PITCH. A nota ocupa a sílaba inteira.
            inicio_nota = inicio_silaba
            fim_nota = fim_silaba

            motivos_revisao = list(dict.fromkeys(silaba.get("avisos", [])))

            if (
                confianca_final
                < CONFIANCA_MINIMA_SEM_REVISAO
            ):
                motivos_revisao.append(
                    "baixa confiança final"
                )

            if (
                dados_voz.quantidade_frames == 0
            ):
                motivos_revisao.append(
                    "sílaba sem F0 vocal confiável"
                )

            if (
                abs(correcao_cents)
                >= CORRECAO_CENTS_PARA_REVISAO
            ):
                motivos_revisao.append(
                    "correção vocal elevada"
                )

            if (
                melhor["confianca_harmonica"]
                < CONFIANCA_HARMONICA_MINIMA
            ):
                motivos_revisao.append(
                    "contexto harmônico fraco"
                )

            palavra_id = str(
                silaba["palavra_id"]
            )

            palavra_dados = mapa_palavras.get(
                palavra_id,
                {},
            )

            texto_palavra = str(
                palavra_dados.get(
                    "texto",
                    palavra_id,
                )
            )

            nota = NotaSilabica(
                id=f"nota_{silaba['id']}",
                silaba_id=str(
                    silaba["id"]
                ),
                palavra_id=palavra_id,
                bloco_indice=int(
                    silaba["bloco_indice"]
                ),
                ordem_global=int(
                    silaba["ordem_global"]
                ),
                palavra=texto_palavra,
                silaba=str(
                    silaba["texto"]
                ),
                inicio_silaba=inicio_silaba,
                fim_silaba=fim_silaba,
                inicio_nucleo_vogal=(
                    inicio_nucleo
                ),
                fim_nucleo_vogal=(
                    fim_nucleo
                ),
                inicio_nota=float(
                    inicio_nota
                ),
                fim_nota=float(
                    fim_nota
                ),
                pitch_midi=int(
                    melhor["pitch_midi"]
                ),
                nome_nota=str(
                    melhor["nome_nota"]
                ),
                centro_vocal_midi=float(
                    dados_voz.centro_vocal
                ),
                correcao_cents=float(
                    correcao_cents
                ),
                fonte_pitch=(
                    dados_voz.fonte
                ),
                frames_vocais=(
                    dados_voz.quantidade_frames
                ),
                confianca_voz=float(
                    dados_voz.confianca_voz
                ),
                estabilidade_voz=float(
                    dados_voz.estabilidade
                ),
                suporte_harmonico=float(
                    melhor[
                        "suporte_harmonico"
                    ]
                ),
                confianca_harmonica=float(
                    melhor[
                        "confianca_harmonica"
                    ]
                ),
                score_final=float(
                    melhor["score"]
                ),
                margem_decisao=float(
                    margem_decisao
                ),
                confianca_final=(
                    confianca_final
                ),
                revisao_recomendada=bool(
                    motivos_revisao
                ),
                motivos_revisao=(
                    motivos_revisao
                ),
                candidatos=candidatos,
            )

            resultado.append(
                nota
            )

            pitch_anterior = (
                nota.pitch_midi
            )

            fim_nota_anterior = (
                nota.fim_nota
            )

            print(
                f"[{posicao}/{len(silabas)}] "
                f"{nota.palavra} / {nota.silaba} -> "
                f"{nota.nome_nota} | "
                f"voz={nota.centro_vocal_midi:.2f} | "
                f"correção={nota.correcao_cents:+.1f} cents | "
                f"confiança={nota.confianca_final:.2f}"
            )

        import config_alinhamento as cfg_duracao
        if cfg_duracao.AJUSTAR_DURACOES_MIDI or cfg_duracao.ALONGAR_FINAL_FRASE_MIDI:
            from tempos_midi import ajustar_tempos_midi
            evidencia = None
            with medir("duração e sustentação das notas"):
                if cfg_duracao.ALONGAR_FINAL_FRASE_MIDI and resultado:
                    evidencia = self.evidencia_duracao()
                resultado = ajustar_tempos_midi(resultado, evidencia, self.duracao_voz)
        return resultado


def salvar_notas_json(
    caminho: str | Path,
    notas: list[NotaSilabica],
    metadados: Optional[
        dict[str, Any]
    ] = None,
):
    caminho = Path(
        caminho
    ).expanduser().resolve()

    caminho.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    dados = {
        "metadados": (
            metadados or {}
        ),
        "total_notas": len(
            notas
        ),
        "total_revisao": sum(
            1
            for nota in notas
            if nota.revisao_recomendada
        ),
        "notas": [
            nota.para_dict()
            for nota in notas
        ],
    }

    caminho.write_text(
        json.dumps(
            dados,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def salvar_notas_csv(
    caminho: str | Path,
    notas: list[NotaSilabica],
):
    caminho = Path(
        caminho
    ).expanduser().resolve()

    caminho.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    campos = [
        "ordem_global",
        "bloco_indice",
        "palavra",
        "silaba",
        "inicio_nota",
        "fim_nota",
        "pitch_midi",
        "nome_nota",
        "centro_vocal_midi",
        "correcao_cents",
        "fonte_pitch",
        "frames_vocais",
        "confianca_voz",
        "estabilidade_voz",
        "suporte_harmonico",
        "confianca_harmonica",
        "score_final",
        "margem_decisao",
        "confianca_final",
        "revisao_recomendada",
        "motivos_revisao",
    ]

    with caminho.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=campos,
            delimiter=";",
        )

        escritor.writeheader()

        for nota in notas:
            escritor.writerow(
                {
                    "ordem_global": (
                        nota.ordem_global
                    ),
                    "bloco_indice": (
                        nota.bloco_indice
                    ),
                    "palavra": nota.palavra,
                    "silaba": nota.silaba,
                    "inicio_nota": (
                        f"{nota.inicio_nota:.6f}"
                    ),
                    "fim_nota": (
                        f"{nota.fim_nota:.6f}"
                    ),
                    "pitch_midi": (
                        nota.pitch_midi
                    ),
                    "nome_nota": (
                        nota.nome_nota
                    ),
                    "centro_vocal_midi": (
                        f"{nota.centro_vocal_midi:.4f}"
                    ),
                    "correcao_cents": (
                        f"{nota.correcao_cents:.2f}"
                    ),
                    "fonte_pitch": (
                        nota.fonte_pitch
                    ),
                    "frames_vocais": (
                        nota.frames_vocais
                    ),
                    "confianca_voz": (
                        f"{nota.confianca_voz:.4f}"
                    ),
                    "estabilidade_voz": (
                        f"{nota.estabilidade_voz:.4f}"
                    ),
                    "suporte_harmonico": (
                        f"{nota.suporte_harmonico:.4f}"
                    ),
                    "confianca_harmonica": (
                        f"{nota.confianca_harmonica:.4f}"
                    ),
                    "score_final": (
                        f"{nota.score_final:.4f}"
                    ),
                    "margem_decisao": (
                        f"{nota.margem_decisao:.4f}"
                    ),
                    "confianca_final": (
                        f"{nota.confianca_final:.4f}"
                    ),
                    "revisao_recomendada": (
                        "SIM"
                        if nota.revisao_recomendada
                        else "NÃO"
                    ),
                    "motivos_revisao": " | ".join(
                        nota.motivos_revisao
                    ),
                }
            )
