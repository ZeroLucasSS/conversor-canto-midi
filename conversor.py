# conversor.py

from pathlib import Path

import librosa
import numpy as np

from config import (
    SAMPLE_RATE,
    MONO,
    NOTA_MINIMA,
    NOTA_MAXIMA,
    FRAME_LENGTH,
    HOP_LENGTH,
    VOICED_PROB_MIN,
    VOICED_PROB_MIN_SUSTENTACAO,
    FRAMES_ESTABILIDADE_SUSTENTACAO,
    FRAMES_MEMORIA_SUSTENTACAO,
    DISTANCIA_MAXIMA_SUSTENTACAO_CENTS,
    DURACAO_MINIMA_SUSTENTACAO,
    GAP_MAXIMO_SUSTENTACAO,
    GAP_MAXIMO_TRANSICAO_SUSTENTADA,
    EXTENSAO_MAXIMA_FINAL_SUSTENTADO,
    GAP_F0_MAXIMO,
    DISTANCIA_MAXIMA_INTERPOLACAO_CENTS,
    JANELA_MEDIANA,
    DURACAO_MINIMA_NOTA,
    GAP_MAXIMO,
    LIMIAR_TROCA_CENTS,
    FRAMES_CONFIRMACAO_NOTA,
    DISTANCIA_MAXIMA_AGRUPAMENTO_SEMITONS,
    DURACAO_MAXIMA_NOTA_TRANSITORIA,
    GAP_MAXIMO_AGRUPAMENTO,
    JANELA_SUAVIZACAO_HARMONICA,
    BINS_POR_OITAVA_CQT,
    PESO_HARMONIA,
    PESO_CONTINUIDADE,
    ESCALA_DISTANCIA_VOZ_CENTS,
    CONFIANCA_HARMONICA_MINIMA,
    VANTAGEM_HARMONICA_MINIMA,
    MARGEM_SCORE_TROCA,
    DISTANCIA_MAXIMA_CORRECAO_CENTS,
    VANTAGEM_HARMONICA_PARA_PRESERVAR,
    DESLOCAMENTO_INSTRUMENTAL_SEGUNDOS,
    TOLERANCIA_DURACAO_ARQUIVOS,
    MOSTRAR_DETALHES,
)

from processamento import (
    hz_para_midi_decimal,
    mediana_movel,
    preencher_pequenos_buracos,
    extrair_contexto_harmonico,
    fundir_pitch_com_harmonia,
    detectar_notas_com_histerese,
    estados_para_notas,
    agrupar_notas_transitorias,
    juntar_notas_iguais,
    juntar_notas_proximas,
)

from midi import exportar_midi


def carregar_audio(caminho):
    """
    Carrega o arquivo de áudio e converte para mono.

    O librosa fará também o resampling para SAMPLE_RATE.
    """

    caminho = Path(caminho)

    if not caminho.exists():
        raise FileNotFoundError(
            f"Arquivo de áudio não encontrado:\n{caminho}"
        )

    if MOSTRAR_DETALHES:
        print()
        print("=" * 60)
        print("CARREGANDO ÁUDIO")
        print("=" * 60)
        print(f"Arquivo: {caminho}")

    y, sr = librosa.load(
        str(caminho),
        sr=SAMPLE_RATE,
        mono=MONO,
    )

    if len(y) == 0:
        raise ValueError(
            "O arquivo de áudio foi carregado, mas está vazio."
        )

    duracao = librosa.get_duration(
        y=y,
        sr=sr
    )

    if MOSTRAR_DETALHES:
        print(f"Sample rate: {sr} Hz")
        print(f"Duração: {duracao:.2f} segundos")

    return y, sr


def detectar_f0(y, sr):
    """
    Executa o algoritmo pYIN.

    Retorna:

    - frequência fundamental F0
    - indicador voiced/unvoiced
    - probabilidade de voz
    """

    fmin = librosa.note_to_hz(NOTA_MINIMA)
    fmax = librosa.note_to_hz(NOTA_MAXIMA)

    if MOSTRAR_DETALHES:
        print()
        print("=" * 60)
        print("DETECTANDO FREQUÊNCIA FUNDAMENTAL")
        print("=" * 60)

        print(
            f"Faixa: "
            f"{NOTA_MINIMA} ({fmin:.1f} Hz) "
            f"até "
            f"{NOTA_MAXIMA} ({fmax:.1f} Hz)"
        )

    f0, voiced_flag, voiced_prob = librosa.pyin(
        y,
        fmin=fmin,
        fmax=fmax,
        sr=sr,
        frame_length=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
        fill_na=np.nan,
    )

    return f0, voiced_flag, voiced_prob


def filtrar_frames_nao_confiaveis(
    f0,
    voiced_flag,
    voiced_prob,
):
    """
    Remove frames realmente pouco confiáveis, mas preserva
    quedas momentâneas de confiança dentro de uma nota
    sustentada.

    Existem dois modos:

        modo normal:
            probabilidade >= VOICED_PROB_MIN

        modo sustentação:
            probabilidade menor, mas F0 próximo do histórico
            estável da nota

    O voiced_flag não é usado como veto absoluto.
    """

    resultado = np.asarray(
        f0,
        dtype=float,
    ).copy()

    voiced_prob = np.asarray(
        voiced_prob,
        dtype=float,
    )

    historico_midi = []
    frames_sem_pitch_aceito = 0

    for i in range(len(resultado)):
        frequencia = resultado[i]

        if not np.isfinite(frequencia):
            resultado[i] = np.nan
            frames_sem_pitch_aceito += 1

            if (
                frames_sem_pitch_aceito
                > FRAMES_MEMORIA_SUSTENTACAO
            ):
                historico_midi.clear()

            continue

        probabilidade = (
            voiced_prob[i]
            if i < len(voiced_prob)
            else np.nan
        )

        midi_atual = hz_para_midi_decimal(
            frequencia
        )

        aceitar = False

        # ----------------------------------------------------
        # CASO 1: probabilidade não disponível
        # ----------------------------------------------------

        if not np.isfinite(probabilidade):
            aceitar = True

        # ----------------------------------------------------
        # CASO 2: confiança normal
        # ----------------------------------------------------

        elif probabilidade >= VOICED_PROB_MIN:
            aceitar = True

        # ----------------------------------------------------
        # CASO 3: memória de sustentação
        # ----------------------------------------------------

        elif (
            probabilidade
            >= VOICED_PROB_MIN_SUSTENTACAO
            and len(historico_midi)
            >= FRAMES_ESTABILIDADE_SUSTENTACAO
        ):
            pitch_referencia = float(
                np.median(
                    historico_midi[
                        -FRAMES_ESTABILIDADE_SUSTENTACAO:
                    ]
                )
            )

            distancia_cents = abs(
                midi_atual
                - pitch_referencia
            ) * 100.0

            if (
                distancia_cents
                <= DISTANCIA_MAXIMA_SUSTENTACAO_CENTS
            ):
                aceitar = True

        if aceitar:
            resultado[i] = frequencia
            frames_sem_pitch_aceito = 0

            historico_midi.append(
                midi_atual
            )

            tamanho_maximo_historico = (
                FRAMES_ESTABILIDADE_SUSTENTACAO
                * 3
            )

            if (
                len(historico_midi)
                > tamanho_maximo_historico
            ):
                historico_midi = historico_midi[
                    -tamanho_maximo_historico:
                ]

        else:
            resultado[i] = np.nan
            frames_sem_pitch_aceito += 1

            if (
                frames_sem_pitch_aceito
                > FRAMES_MEMORIA_SUSTENTACAO
            ):
                historico_midi.clear()

    return resultado


def imprimir_notas(notas):
    """
    Exibe as notas detectadas no terminal.
    """

    print()
    print("=" * 60)
    print("NOTAS DETECTADAS")
    print("=" * 60)

    if not notas:
        print("Nenhuma nota detectada.")
        return

    for i, nota in enumerate(notas, start=1):

        nome = librosa.midi_to_note(
            nota.pitch
        )

        print(
            f"{i:03d} | "
            f"{nome:5s} | "
            f"MIDI {nota.pitch:3d} | "
            f"{nota.inicio:8.3f}s -> "
            f"{nota.fim:8.3f}s | "
            f"{nota.duracao:6.3f}s"
        )


def converter_audio_para_midi(
    caminho_voz,
    caminho_instrumental,
    caminho_midi,
):
    """
    Pipeline Nível 3 revisado:

        voz
          ↓
        detecção de F0
          ↓
        filtro de confiança
          ↓
        recuperação de lacunas baseada na energia vocal
          ↓
        suavização
          ↓
        análise harmônica do instrumental
          ↓
        fusão voz + harmonia
          ↓
        histerese
          ↓
        agrupamento conservador
          ↓
        MIDI
    """

    # ========================================================
    # 1. CARREGAMENTO DOS ÁUDIOS
    # ========================================================

    print()
    print("=" * 60)
    print("CARREGANDO VOZ")
    print("=" * 60)

    y_voz, sr_voz = carregar_audio(
        caminho_voz
    )

    print()
    print("=" * 60)
    print("CARREGANDO INSTRUMENTAL")
    print("=" * 60)

    y_instrumental, sr_instrumental = carregar_audio(
        caminho_instrumental
    )

    if sr_voz != sr_instrumental:
        raise ValueError(
            "A voz e o instrumental foram carregados "
            "com sample rates diferentes."
        )

    sr = sr_voz

    duracao_voz = (
        len(y_voz)
        / float(sr)
    )

    duracao_instrumental = (
        len(y_instrumental)
        / float(sr)
    )

    diferenca_duracao = abs(
        duracao_voz
        - duracao_instrumental
    )

    print()
    print(
        f"Duração da voz: "
        f"{duracao_voz:.3f} s"
    )

    print(
        f"Duração do instrumental: "
        f"{duracao_instrumental:.3f} s"
    )

    if (
        diferenca_duracao
        > TOLERANCIA_DURACAO_ARQUIVOS
    ):
        print()
        print(
            "AVISO: os arquivos possuem diferença "
            "de duração superior à tolerância."
        )

        print(
            "A análise continuará usando tempo absoluto."
        )

    # ========================================================
    # 2. DETECÇÃO DO PITCH VOCAL
    # ========================================================

    print()
    print("=" * 60)
    print("ANALISANDO PITCH VOCAL")
    print("=" * 60)

    f0, voiced_flag, voiced_prob = detectar_f0(
        y_voz,
        sr,
    )

    # ========================================================
    # 3. FILTRAGEM DE CONFIANÇA
    # ========================================================

    f0_filtrado = filtrar_frames_nao_confiaveis(
        f0,
        voiced_flag,
        voiced_prob,
    )

    # ========================================================
    # 4. HZ -> MIDI DECIMAL
    # ========================================================

    midi_decimal = np.array(
        [
            hz_para_midi_decimal(freq)
            for freq in f0_filtrado
        ],
        dtype=float,
    )

    # ========================================================
    # 5. RECUPERAÇÃO DE BURACOS E SUSTENTAÇÃO VOCAL
    # ========================================================

    midi_recuperado = preencher_pequenos_buracos(
        valores=midi_decimal,
        sr=sr,
        hop_length=HOP_LENGTH,
        gap_maximo_segundos=GAP_F0_MAXIMO,
        distancia_maxima_cents=(
            DISTANCIA_MAXIMA_INTERPOLACAO_CENTS
        ),
        duracao_minima_sustentacao=(
            DURACAO_MINIMA_SUSTENTACAO
        ),
        gap_maximo_sustentacao=(
            GAP_MAXIMO_SUSTENTACAO
        ),
        gap_maximo_transicao_sustentada=(
            GAP_MAXIMO_TRANSICAO_SUSTENTADA
        ),
        extensao_maxima_final_sustentado=(
            EXTENSAO_MAXIMA_FINAL_SUSTENTADO
        ),
        distancia_maxima_sustentacao_cents=(
            DISTANCIA_MAXIMA_SUSTENTACAO_CENTS
        ),
    )

    # ========================================================
    # 6. SUAVIZAÇÃO VOCAL
    # ========================================================

    midi_suavizado = mediana_movel(
        midi_recuperado,
        tamanho_janela=JANELA_MEDIANA,
    )

    # ========================================================
    # 7. LINHA TEMPORAL
    # ========================================================

    tempos = librosa.times_like(
        midi_suavizado,
        sr=sr,
        hop_length=HOP_LENGTH,
    )

    duracao_frame = (
        HOP_LENGTH
        / float(sr)
    )

    # ========================================================
    # 8. ANÁLISE HARMÔNICA
    # ========================================================

    print()
    print("=" * 60)
    print("ANALISANDO HARMONIA DO INSTRUMENTAL")
    print("=" * 60)

    (
        chroma_harmonico,
        confianca_harmonica,
    ) = extrair_contexto_harmonico(
        y_instrumental=y_instrumental,
        sr=sr,
        tempos_destino=tempos,
        hop_length=HOP_LENGTH,
        frame_length=FRAME_LENGTH,
        janela_suavizacao=(
            JANELA_SUAVIZACAO_HARMONICA
        ),
        bins_por_oitava=(
            BINS_POR_OITAVA_CQT
        ),
        deslocamento_segundos=(
            DESLOCAMENTO_INSTRUMENTAL_SEGUNDOS
        ),
    )

    # ========================================================
    # 9. FUSÃO VOZ + HARMONIA
    # ========================================================

    print()
    print("=" * 60)
    print("FUNDINDO VOZ E EVIDÊNCIA HARMÔNICA")
    print("=" * 60)

    (
        midi_fundido,
        diagnostico_fusao,
    ) = fundir_pitch_com_harmonia(
        midi_vocal=midi_suavizado,
        chroma_harmonico=chroma_harmonico,
        confianca_harmonica=(
            confianca_harmonica
        ),
        voiced_prob=voiced_prob,
        peso_harmonia=PESO_HARMONIA,
        peso_continuidade=PESO_CONTINUIDADE,
        escala_distancia_voz_cents=(
            ESCALA_DISTANCIA_VOZ_CENTS
        ),
        confianca_harmonica_minima=(
            CONFIANCA_HARMONICA_MINIMA
        ),
        vantagem_harmonica_minima=(
            VANTAGEM_HARMONICA_MINIMA
        ),
        margem_score_troca=(
            MARGEM_SCORE_TROCA
        ),
        distancia_maxima_correcao_cents=(
            DISTANCIA_MAXIMA_CORRECAO_CENTS
        ),
    )

    print(
        "Frames analisados: "
        f"{diagnostico_fusao['frames_totais']}"
    )

    print(
        "Frames com harmonia confiável: "
        f"{diagnostico_fusao['frames_com_harmonia']}"
    )

    print(
        "Frames alterados pela harmonia: "
        f"{diagnostico_fusao['frames_alterados']}"
    )

    # ========================================================
    # 10. HISTERESE
    # ========================================================

    estados = detectar_notas_com_histerese(
        midi_fundido,
        tempos,
        limiar_troca_cents=(
            LIMIAR_TROCA_CENTS
        ),
        frames_confirmacao=(
            FRAMES_CONFIRMACAO_NOTA
        ),
    )

    # ========================================================
    # 11. FRAMES -> NOTAS
    # ========================================================

    notas = estados_para_notas(
        estados,
        tempos,
        duracao_frame,
    )

    # ========================================================
    # 12. AGRUPAMENTO CONSERVADOR DE DESVIOS
    # ========================================================

    notas = agrupar_notas_transitorias(
        notas,
        duracao_maxima_transitoria=(
            DURACAO_MAXIMA_NOTA_TRANSITORIA
        ),
        distancia_maxima_semitons=(
            DISTANCIA_MAXIMA_AGRUPAMENTO_SEMITONS
        ),
        chroma_harmonico=chroma_harmonico,
        confianca_harmonica=(
            confianca_harmonica
        ),
        tempos=tempos,
        confianca_harmonica_minima=(
            CONFIANCA_HARMONICA_MINIMA
        ),
        vantagem_harmonica_para_preservar=(
            VANTAGEM_HARMONICA_PARA_PRESERVAR
        ),
    )

    # ========================================================
    # 13. JUNÇÃO DE NOTAS IGUAIS
    # ========================================================

    notas = juntar_notas_iguais(
        notas,
        GAP_MAXIMO,
    )

    # ========================================================
    # 14. FECHAMENTO CONSERVADOR DE PEQUENOS GAPS
    # ========================================================

    notas = juntar_notas_proximas(
        notas,
        gap_maximo=GAP_MAXIMO_AGRUPAMENTO,
        distancia_maxima_semitons=(
            DISTANCIA_MAXIMA_AGRUPAMENTO_SEMITONS
        ),
        duracao_maxima_desvio=(
            DURACAO_MAXIMA_NOTA_TRANSITORIA
        ),
        chroma_harmonico=chroma_harmonico,
        confianca_harmonica=(
            confianca_harmonica
        ),
        tempos=tempos,
        confianca_harmonica_minima=(
            CONFIANCA_HARMONICA_MINIMA
        ),
        vantagem_harmonica_para_preservar=(
            VANTAGEM_HARMONICA_PARA_PRESERVAR
        ),
    )

    # ========================================================
    # 15. JUNÇÃO FINAL DE NOTAS IGUAIS
    # ========================================================

    notas = juntar_notas_iguais(
        notas,
        GAP_MAXIMO,
    )

    # ========================================================
    # 16. EXPORTAÇÃO MIDI
    # ========================================================

    caminho_midi = exportar_midi(
        notas,
        caminho_midi,
    )

    if MOSTRAR_DETALHES:
        imprimir_notas(
            notas
        )

    print()
    print("=" * 60)
    print("CONVERSÃO CONCLUÍDA")
    print("=" * 60)

    print(
        f"Total de notas: {len(notas)}"
    )

    print(
        f"MIDI salvo em:\n{caminho_midi}"
    )

    return notas