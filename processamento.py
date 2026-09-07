# processamento.py

from dataclasses import dataclass
from typing import List

import librosa
import numpy as np


@dataclass
class NotaDetectada:
    pitch: int
    inicio: float
    fim: float

    @property
    def duracao(self):
        return self.fim - self.inicio


def hz_para_midi_decimal(freq):
    """
    Converte frequência em Hz para número MIDI decimal.

    Exemplo:
        440 Hz -> 69.0
    """

    if freq is None:
        return np.nan

    if not np.isfinite(freq):
        return np.nan

    if freq <= 0:
        return np.nan

    return 69.0 + 12.0 * np.log2(freq / 440.0)


def cents_entre_notas(midi_a, midi_b):
    """
    Distância em cents entre dois valores MIDI decimais.
    """

    return abs(float(midi_a) - float(midi_b)) * 100.0


def mediana_movel(valores, tamanho_janela=5):
    """
    Aplica filtro de mediana ignorando NaNs.

    Isso reduz pequenas oscilações provocadas por:

    - vibrato
    - ruído
    - transições vocais
    - erros momentâneos do pYIN
    """

    valores = np.asarray(valores, dtype=float)

    if tamanho_janela <= 1:
        return valores.copy()

    if tamanho_janela % 2 == 0:
        tamanho_janela += 1

    metade = tamanho_janela // 2

    resultado = np.full_like(
        valores,
        np.nan,
        dtype=float
    )

    for i in range(len(valores)):

        inicio = max(0, i - metade)
        fim = min(len(valores), i + metade + 1)

        janela = valores[inicio:fim]

        validos = janela[np.isfinite(janela)]

        if len(validos) > 0:
            resultado[i] = np.median(validos)

    return resultado


def suavizar_matriz_temporal(
    matriz,
    tamanho_janela,
):
    """
    Aplica filtro de mediana ao longo do tempo.

    A matriz esperada possui o formato:

        quantidade_de_caracteristicas x quantidade_de_frames

    No nosso caso:

        12 classes de pitch x frames do instrumental
    """

    matriz = np.asarray(
        matriz,
        dtype=float,
    )

    if matriz.ndim != 2:
        raise ValueError(
            "A matriz temporal precisa possuir duas dimensões."
        )

    if matriz.shape[1] == 0:
        return matriz.copy()

    tamanho_janela = int(
        max(1, tamanho_janela)
    )

    if tamanho_janela % 2 == 0:
        tamanho_janela += 1

    if tamanho_janela == 1:
        return matriz.copy()

    metade = tamanho_janela // 2

    matriz_expandida = np.pad(
        matriz,
        pad_width=(
            (0, 0),
            (metade, metade),
        ),
        mode="edge",
    )

    janelas = np.lib.stride_tricks.sliding_window_view(
        matriz_expandida,
        window_shape=tamanho_janela,
        axis=1,
    )

    return np.median(
        janelas,
        axis=-1,
    )


def extrair_contexto_harmonico(
    y_instrumental,
    sr,
    tempos_destino,
    hop_length,
    frame_length,
    janela_suavizacao=9,
    bins_por_oitava=36,
    deslocamento_segundos=0.0,
):
    """
    Extrai evidência harmônica do instrumental e a alinha
    aos mesmos tempos usados pela análise da voz.

    Retorna:

        chroma_alinhado:
            matriz 12 x frames_da_voz

        confianca_alinhada:
            confiança harmônica para cada frame da voz

    A confiança considera:

        - energia do instrumental;
        - concentração das classes de pitch;
        - diferença entre informação harmônica e ruído.

    O instrumental não escolhe sozinho uma nota.
    Ele apenas produz evidências entre 0 e 1.
    """

    y_instrumental = np.asarray(
        y_instrumental,
        dtype=float,
    )

    tempos_destino = np.asarray(
        tempos_destino,
        dtype=float,
    )

    quantidade_destino = len(
        tempos_destino
    )

    if quantidade_destino == 0:
        return (
            np.zeros(
                (12, 0),
                dtype=float,
            ),
            np.zeros(
                0,
                dtype=float,
            ),
        )

    if len(y_instrumental) == 0:
        return (
            np.zeros(
                (12, quantidade_destino),
                dtype=float,
            ),
            np.zeros(
                quantidade_destino,
                dtype=float,
            ),
        )

    # --------------------------------------------------------
    # 1. COMPONENTE HARMÔNICA
    # --------------------------------------------------------

    instrumental_harmonico = librosa.effects.harmonic(
        y_instrumental,
        margin=8.0,
    )

    # --------------------------------------------------------
    # 2. CHROMA CQT
    # --------------------------------------------------------

    chroma = librosa.feature.chroma_cqt(
        y=instrumental_harmonico,
        sr=sr,
        hop_length=hop_length,
        n_chroma=12,
        bins_per_octave=bins_por_oitava,
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

    # Compressão logarítmica para impedir que um único
    # instrumento muito alto domine completamente a análise.
    chroma = np.log1p(
        10.0 * chroma
    )

    chroma = suavizar_matriz_temporal(
        chroma,
        tamanho_janela=janela_suavizacao,
    )

    quantidade_frames_chroma = chroma.shape[1]

    if quantidade_frames_chroma == 0:
        return (
            np.zeros(
                (12, quantidade_destino),
                dtype=float,
            ),
            np.zeros(
                quantidade_destino,
                dtype=float,
            ),
        )

    tempos_chroma = librosa.frames_to_time(
        np.arange(
            quantidade_frames_chroma
        ),
        sr=sr,
        hop_length=hop_length,
    )

    # --------------------------------------------------------
    # 3. ENERGIA
    # --------------------------------------------------------

    rms = librosa.feature.rms(
        y=y_instrumental,
        frame_length=frame_length,
        hop_length=hop_length,
        center=True,
    )[0]

    tempos_rms = librosa.frames_to_time(
        np.arange(
            len(rms)
        ),
        sr=sr,
        hop_length=hop_length,
    )

    if len(rms) == 0:
        rms_no_chroma = np.zeros(
            quantidade_frames_chroma,
            dtype=float,
        )
    else:
        rms_no_chroma = np.interp(
            tempos_chroma,
            tempos_rms,
            rms,
            left=0.0,
            right=0.0,
        )

    # --------------------------------------------------------
    # 4. NORMALIZAÇÃO DO CHROMA
    # --------------------------------------------------------

    soma_chroma = np.sum(
        chroma,
        axis=0,
    )

    chroma_l1 = np.divide(
        chroma,
        soma_chroma[np.newaxis, :],
        out=np.zeros_like(chroma),
        where=(
            soma_chroma[np.newaxis, :]
            > 1e-12
        ),
    )

    maximo_chroma = np.max(
        chroma,
        axis=0,
    )

    # Evidência relativa:
    #
    # a classe mais presente no frame recebe valor próximo de 1.
    evidencia = np.divide(
        chroma,
        maximo_chroma[np.newaxis, :],
        out=np.zeros_like(chroma),
        where=(
            maximo_chroma[np.newaxis, :]
            > 1e-12
        ),
    )

    # --------------------------------------------------------
    # 5. CONFIANÇA PELA CONCENTRAÇÃO
    # --------------------------------------------------------

    pico_l1 = np.max(
        chroma_l1,
        axis=0,
    )

    valor_uniforme = 1.0 / 12.0
    valor_concentrado = 0.30

    confianca_concentracao = (
        pico_l1 - valor_uniforme
    ) / (
        valor_concentrado - valor_uniforme
    )

    confianca_concentracao = np.clip(
        confianca_concentracao,
        0.0,
        1.0,
    )

    # --------------------------------------------------------
    # 6. CONFIANÇA PELA ENERGIA
    # --------------------------------------------------------

    if len(rms_no_chroma) > 0:
        energia_baixa = np.percentile(
            rms_no_chroma,
            15,
        )

        energia_alta = np.percentile(
            rms_no_chroma,
            70,
        )
    else:
        energia_baixa = 0.0
        energia_alta = 0.0

    intervalo_energia = (
        energia_alta
        - energia_baixa
    )

    if intervalo_energia <= 1e-12:
        confianca_energia = np.where(
            rms_no_chroma > 0.0,
            1.0,
            0.0,
        )
    else:
        confianca_energia = (
            rms_no_chroma
            - energia_baixa
        ) / intervalo_energia

        confianca_energia = np.clip(
            confianca_energia,
            0.0,
            1.0,
        )

    confianca = (
        confianca_concentracao
        * confianca_energia
    )

    # --------------------------------------------------------
    # 7. ALINHAMENTO COM OS FRAMES DA VOZ
    # --------------------------------------------------------

    tempos_consulta = (
        tempos_destino
        + deslocamento_segundos
    )

    chroma_alinhado = np.zeros(
        (12, quantidade_destino),
        dtype=float,
    )

    for classe_pitch in range(12):
        chroma_alinhado[classe_pitch] = np.interp(
            tempos_consulta,
            tempos_chroma,
            evidencia[classe_pitch],
            left=0.0,
            right=0.0,
        )

    confianca_alinhada = np.interp(
        tempos_consulta,
        tempos_chroma,
        confianca,
        left=0.0,
        right=0.0,
    )

    return (
        chroma_alinhado,
        confianca_alinhada,
    )


def fundir_pitch_com_harmonia(
    midi_vocal,
    chroma_harmonico,
    confianca_harmonica,
    voiced_prob=None,
    peso_harmonia=0.85,
    peso_continuidade=0.12,
    escala_distancia_voz_cents=55.0,
    confianca_harmonica_minima=0.18,
    vantagem_harmonica_minima=0.12,
    margem_score_troca=0.08,
    distancia_maxima_correcao_cents=70.0,
):
    """
    Combina o pitch vocal com a evidência harmônica.

    Para cada frame vocal, são comparados:

        nota arredondada naturalmente
        nota um semitom abaixo
        nota um semitom acima

    Uma nota diferente da escolha vocal natural só vence quando:

        1. está suficientemente próxima do F0;
        2. a harmonia possui confiança;
        3. há vantagem harmônica real;
        4. o score total supera a escolha original.

    Portanto, a harmonia resolve ambiguidades, mas não pode
    deslocar livremente a melodia.
    """

    midi_vocal = np.asarray(
        midi_vocal,
        dtype=float,
    )

    chroma_harmonico = np.asarray(
        chroma_harmonico,
        dtype=float,
    )

    confianca_harmonica = np.asarray(
        confianca_harmonica,
        dtype=float,
    )

    if voiced_prob is not None:
        voiced_prob = np.asarray(
            voiced_prob,
            dtype=float,
        )

    resultado = midi_vocal.copy()

    quantidade_frames = len(
        midi_vocal
    )

    if chroma_harmonico.shape != (
        12,
        quantidade_frames,
    ):
        raise ValueError(
            "O chroma harmônico não está alinhado "
            "aos frames da voz."
        )

    if len(confianca_harmonica) != quantidade_frames:
        raise ValueError(
            "A confiança harmônica não está alinhada "
            "aos frames da voz."
        )

    nota_anterior = None
    frames_alterados = 0
    frames_com_harmonia = 0

    for i, valor_vocal in enumerate(
        midi_vocal
    ):
        if not np.isfinite(valor_vocal):
            nota_anterior = None
            continue

        confianca = float(
            np.clip(
                confianca_harmonica[i],
                0.0,
                1.0,
            )
        )

        # Arredondamento musical convencional.
        candidato_original = int(
            np.floor(
                valor_vocal + 0.5
            )
        )

        if confianca < confianca_harmonica_minima:
            resultado[i] = candidato_original
            nota_anterior = candidato_original
            continue

        frames_com_harmonia += 1

        candidatos = [
            candidato_original - 1,
            candidato_original,
            candidato_original + 1,
        ]

        probabilidade_voz = 0.5

        if (
            voiced_prob is not None
            and i < len(voiced_prob)
            and np.isfinite(voiced_prob[i])
        ):
            probabilidade_voz = float(
                np.clip(
                    voiced_prob[i],
                    0.0,
                    1.0,
                )
            )

        # Quando a voz está muito segura, reduzimos um pouco
        # a influência harmônica.
        fator_incerteza_vocal = (
            0.55
            + 0.45
            * (
                1.0
                - probabilidade_voz
            )
        )

        scores = {}

        for candidato in candidatos:
            distancia_cents = abs(
                valor_vocal - candidato
            ) * 100.0

            if (
                candidato != candidato_original
                and distancia_cents
                > distancia_maxima_correcao_cents
            ):
                continue

            score_voz = -(
                distancia_cents
                / escala_distancia_voz_cents
            ) ** 2

            evidencia_harmonica = float(
                chroma_harmonico[
                    candidato % 12,
                    i,
                ]
            )

            score_harmonia = (
                peso_harmonia
                * fator_incerteza_vocal
                * confianca
                * evidencia_harmonica
            )

            score_continuidade = 0.0

            if (
                nota_anterior is not None
                and candidato == nota_anterior
            ):
                score_continuidade = (
                    peso_continuidade
                )

            scores[candidato] = (
                score_voz
                + score_harmonia
                + score_continuidade
            )

        if candidato_original not in scores:
            resultado[i] = candidato_original
            nota_anterior = candidato_original
            continue

        melhor_candidato = max(
            scores,
            key=scores.get,
        )

        candidato_escolhido = candidato_original

        if melhor_candidato != candidato_original:
            evidencia_original = float(
                chroma_harmonico[
                    candidato_original % 12,
                    i,
                ]
            )

            evidencia_alternativa = float(
                chroma_harmonico[
                    melhor_candidato % 12,
                    i,
                ]
            )

            vantagem_harmonica = (
                evidencia_alternativa
                - evidencia_original
            )

            vantagem_score = (
                scores[melhor_candidato]
                - scores[candidato_original]
            )

            if (
                vantagem_harmonica
                >= vantagem_harmonica_minima
                and vantagem_score
                >= margem_score_troca
            ):
                candidato_escolhido = (
                    melhor_candidato
                )

        resultado[i] = candidato_escolhido

        if candidato_escolhido != candidato_original:
            frames_alterados += 1

        nota_anterior = candidato_escolhido

    diagnostico = {
        "frames_totais": quantidade_frames,
        "frames_com_harmonia": frames_com_harmonia,
        "frames_alterados": frames_alterados,
    }

    return resultado, diagnostico


def harmonia_sustenta_nota(
    pitch_candidato,
    pitch_alvo,
    inicio,
    fim,
    chroma_harmonico,
    confianca_harmonica,
    tempos,
    confianca_minima=0.18,
    vantagem_minima=0.15,
):
    """
    Verifica se o instrumental sustenta uma nota curta
    com mais força do que a nota que tentaria absorvê-la.

    Retorna True apenas quando existe evidência harmônica
    suficientemente clara.
    """

    if chroma_harmonico is None:
        return False

    if confianca_harmonica is None:
        return False

    if tempos is None:
        return False

    tempos = np.asarray(
        tempos,
        dtype=float,
    )

    confianca_harmonica = np.asarray(
        confianca_harmonica,
        dtype=float,
    )

    mascara = (
        (tempos >= inicio)
        & (tempos < fim)
    )

    if not np.any(mascara):
        return False

    confiancas = confianca_harmonica[
        mascara
    ]

    confianca_media = float(
        np.mean(confiancas)
    )

    if confianca_media < confianca_minima:
        return False

    pesos = np.maximum(
        confiancas,
        1e-6,
    )

    evidencia_candidato = float(
        np.average(
            chroma_harmonico[
                pitch_candidato % 12,
                mascara,
            ],
            weights=pesos,
        )
    )

    evidencia_alvo = float(
        np.average(
            chroma_harmonico[
                pitch_alvo % 12,
                mascara,
            ],
            weights=pesos,
        )
    )

    vantagem = (
        evidencia_candidato
        - evidencia_alvo
    )

    return vantagem >= vantagem_minima


def preencher_pequenos_buracos(
    valores,
    sr,
    hop_length,
    gap_maximo_segundos=0.120,
    distancia_maxima_cents=200.0,
    duracao_minima_sustentacao=0.300,
    gap_maximo_sustentacao=0.300,
    gap_maximo_transicao_sustentada=0.180,
    extensao_maxima_final_sustentado=0.120,
    distancia_maxima_sustentacao_cents=120.0,
):
    """
    Recupera falhas momentâneas na curva de pitch.

    Estratégias:

    1. Lacuna normal:
       interpola quando é curta e os pitches das extremidades
       estão próximos.

    2. Lacuna em nota sustentada:
       permite uma lacuna maior quando pelo menos uma das
       extremidades pertence a uma região vocal estável.

    3. Transição entre notas distantes:
       divide a lacuna entre a nota esquerda e a nota direita,
       evitando criar notas cromáticas intermediárias.

    4. Final de nota sustentada:
       permite uma pequena extensão unilateral.
    """

    valores = np.asarray(
        valores,
        dtype=float,
    ).copy()

    if len(valores) == 0:
        return valores

    duracao_frame = (
        hop_length
        / float(sr)
    )

    max_frames_gap_normal = max(
        1,
        int(
            round(
                gap_maximo_segundos
                / duracao_frame
            )
        ),
    )

    min_frames_sustentacao = max(
        1,
        int(
            round(
                duracao_minima_sustentacao
                / duracao_frame
            )
        ),
    )

    max_frames_gap_sustentado = max(
        1,
        int(
            round(
                gap_maximo_sustentacao
                / duracao_frame
            )
        ),
    )

    max_frames_transicao = max(
        1,
        int(
            round(
                gap_maximo_transicao_sustentada
                / duracao_frame
            )
        ),
    )

    max_frames_extensao_final = max(
        1,
        int(
            round(
                extensao_maxima_final_sustentado
                / duracao_frame
            )
        ),
    )

    def contar_estabilidade(
        indice_inicial,
        direcao,
        tolerancia_cents,
    ):
        """
        Conta quantos frames consecutivos permanecem próximos
        do pitch encontrado no índice inicial.
        """

        if (
            indice_inicial < 0
            or indice_inicial >= len(valores)
            or not np.isfinite(
                valores[indice_inicial]
            )
        ):
            return 0

        referencia = float(
            valores[indice_inicial]
        )

        quantidade = 0
        indice = indice_inicial

        while (
            0 <= indice < len(valores)
            and np.isfinite(valores[indice])
        ):
            distancia = abs(
                valores[indice]
                - referencia
            ) * 100.0

            if distancia > tolerancia_cents:
                break

            quantidade += 1
            indice += direcao

        return quantidade

    i = 0

    while i < len(valores):
        if np.isfinite(valores[i]):
            i += 1
            continue

        inicio_gap = i

        while (
            i < len(valores)
            and not np.isfinite(valores[i])
        ):
            i += 1

        fim_gap = i - 1

        quantidade_frames = (
            fim_gap
            - inicio_gap
            + 1
        )

        indice_esquerda = (
            inicio_gap - 1
        )

        indice_direita = i

        possui_esquerda = (
            indice_esquerda >= 0
            and np.isfinite(
                valores[indice_esquerda]
            )
        )

        possui_direita = (
            indice_direita < len(valores)
            and np.isfinite(
                valores[indice_direita]
            )
        )

        estabilidade_esquerda = 0
        estabilidade_direita = 0

        if possui_esquerda:
            estabilidade_esquerda = contar_estabilidade(
                indice_inicial=indice_esquerda,
                direcao=-1,
                tolerancia_cents=(
                    distancia_maxima_sustentacao_cents
                ),
            )

        if possui_direita:
            estabilidade_direita = contar_estabilidade(
                indice_inicial=indice_direita,
                direcao=1,
                tolerancia_cents=(
                    distancia_maxima_sustentacao_cents
                ),
            )

        possui_sustentacao = (
            estabilidade_esquerda
            >= min_frames_sustentacao
            or estabilidade_direita
            >= min_frames_sustentacao
        )

        # ----------------------------------------------------
        # CASO 1: lacuna entre dois pitches válidos
        # ----------------------------------------------------

        if possui_esquerda and possui_direita:
            valor_esquerda = float(
                valores[indice_esquerda]
            )

            valor_direita = float(
                valores[indice_direita]
            )

            distancia_cents = abs(
                valor_direita
                - valor_esquerda
            ) * 100.0

            lacuna_normal = (
                quantidade_frames
                <= max_frames_gap_normal
                and distancia_cents
                <= distancia_maxima_cents
            )

            lacuna_sustentada_proxima = (
                possui_sustentacao
                and quantidade_frames
                <= max_frames_gap_sustentado
                and distancia_cents
                <= distancia_maxima_sustentacao_cents
            )

            if (
                lacuna_normal
                or lacuna_sustentada_proxima
            ):
                passos = (
                    quantidade_frames + 1
                )

                for j in range(
                    1,
                    quantidade_frames + 1,
                ):
                    proporcao = (
                        j / passos
                    )

                    valores[
                        inicio_gap + j - 1
                    ] = (
                        valor_esquerda
                        + (
                            valor_direita
                            - valor_esquerda
                        )
                        * proporcao
                    )

                continue

            # Troca real de nota durante uma sustentação.
            #
            # Em vez de criar silêncio ou uma escala
            # intermediária, dividimos a lacuna.
            if (
                possui_sustentacao
                and quantidade_frames
                <= max_frames_transicao
            ):
                quantidade_esquerda = (
                    quantidade_frames // 2
                )

                if quantidade_frames % 2 != 0:
                    quantidade_esquerda += 1

                ponto_divisao = (
                    inicio_gap
                    + quantidade_esquerda
                )

                valores[
                    inicio_gap:
                    ponto_divisao
                ] = valor_esquerda

                valores[
                    ponto_divisao:
                    fim_gap + 1
                ] = valor_direita

                continue

        # ----------------------------------------------------
        # CASO 2: final de nota sustentada
        # ----------------------------------------------------

        if (
            possui_esquerda
            and not possui_direita
            and estabilidade_esquerda
            >= min_frames_sustentacao
        ):
            quantidade_extensao = min(
                quantidade_frames,
                max_frames_extensao_final,
            )

            fim_extensao = (
                inicio_gap
                + quantidade_extensao
            )

            valores[
                inicio_gap:
                fim_extensao
            ] = valores[indice_esquerda]

            continue

        # ----------------------------------------------------
        # CASO 3: ataque de nota sustentada
        # ----------------------------------------------------

        if (
            not possui_esquerda
            and possui_direita
            and estabilidade_direita
            >= min_frames_sustentacao
        ):
            quantidade_extensao = min(
                quantidade_frames,
                max_frames_extensao_final,
            )

            inicio_extensao = (
                fim_gap
                - quantidade_extensao
                + 1
            )

            valores[
                inicio_extensao:
                fim_gap + 1
            ] = valores[indice_direita]

    return valores


def quantizar_pitch(midi_decimal):
    """
    Converte valor MIDI decimal para nota MIDI inteira.

    Exemplo:

        69.02 -> 69
        69.41 -> 69
        69.78 -> 70
    """

    if not np.isfinite(midi_decimal):
        return None

    pitch = int(round(float(midi_decimal)))

    return max(0, min(127, pitch))


def detectar_notas_com_histerese(
    midi_decimal,
    tempos,
    limiar_troca_cents=55.0,
    frames_confirmacao=3,
):
    """
    Transforma a curva contínua de pitch em regiões de notas.

    A grande diferença aqui é a HISTERESE.

    Uma voz humana pode oscilar ao redor da nota:

        A3 = 69.0
        69.10
        68.91
        69.17
        68.87

    Esses valores continuam sendo musicalmente A3.

    Só mudamos de nota quando:

    1. o pitch ultrapassa suficientemente a região atual;
    2. a nova nota permanece por vários frames consecutivos.

    Isso evita explosão de micro-notas.
    """

    estados = []

    nota_atual = None

    candidata = None
    contador_candidata = 0

    centro_nota_atual = None

    for valor in midi_decimal:

        if not np.isfinite(valor):
            estados.append(None)

            candidata = None
            contador_candidata = 0

            continue

        nota_quantizada = quantizar_pitch(valor)

        if nota_atual is None:
            nota_atual = nota_quantizada
            centro_nota_atual = float(nota_atual)

            candidata = None
            contador_candidata = 0

            estados.append(nota_atual)

            continue

        distancia = cents_entre_notas(
            valor,
            centro_nota_atual
        )

        # Continua dentro da região da nota atual.
        if distancia < limiar_troca_cents:

            candidata = None
            contador_candidata = 0

            estados.append(nota_atual)

            continue

        # Temos possível mudança.
        if nota_quantizada == nota_atual:

            candidata = None
            contador_candidata = 0

            estados.append(nota_atual)

            continue

        if candidata == nota_quantizada:
            contador_candidata += 1

        else:
            candidata = nota_quantizada
            contador_candidata = 1

        # Enquanto não existe confirmação,
        # mantemos a nota anterior.
        if contador_candidata < frames_confirmacao:
            estados.append(nota_atual)
            continue

        # Mudança confirmada.
        nota_atual = candidata
        centro_nota_atual = float(nota_atual)

        candidata = None
        contador_candidata = 0

        estados.append(nota_atual)

    return estados


def estados_para_notas(
    estados,
    tempos,
    duracao_frame,
):
    """
    Agrupa frames consecutivos com o mesmo pitch.

    Exemplo:

        69 69 69 69 71 71 71

    vira:

        A4 -> início/fim
        B4 -> início/fim
    """

    notas = []

    pitch_atual = None
    inicio_atual = None

    for i, pitch in enumerate(estados):

        tempo = float(tempos[i])

        if pitch is None:

            if pitch_atual is not None:

                notas.append(
                    NotaDetectada(
                        pitch=pitch_atual,
                        inicio=inicio_atual,
                        fim=tempo
                    )
                )

                pitch_atual = None
                inicio_atual = None

            continue

        if pitch_atual is None:

            pitch_atual = pitch
            inicio_atual = tempo

            continue

        if pitch != pitch_atual:

            notas.append(
                NotaDetectada(
                    pitch=pitch_atual,
                    inicio=inicio_atual,
                    fim=tempo
                )
            )

            pitch_atual = pitch
            inicio_atual = tempo

    # Última nota
    if pitch_atual is not None:

        fim = float(tempos[-1]) + duracao_frame

        notas.append(
            NotaDetectada(
                pitch=pitch_atual,
                inicio=inicio_atual,
                fim=fim
            )
        )

    return notas


def tratar_notas_muito_curtas(
    notas: List[NotaDetectada],
    duracao_minima: float,
):
    """
    Trata notas muito curtas SEM simplesmente apagá-las.

    Filosofia:

    1. Se a nota curta puder ser incorporada musicalmente
       a uma vizinha, fazemos isso.

    2. Se ela estiver entre duas notas iguais,
       unificamos tudo.

    3. Se não houver evidência suficiente para considerá-la
       erro, PRESERVAMOS a nota.

    Isso evita criar buracos artificiais na melodia.
    """

    if not notas:
        return []

    if len(notas) == 1:
        return notas.copy()

    resultado = []
    i = 0

    while i < len(notas):

        atual = notas[i]

        # Nota suficientemente longa:
        # preservamos normalmente.
        if atual.duracao >= duracao_minima:

            resultado.append(atual)
            i += 1
            continue

        anterior = (
            resultado[-1]
            if resultado
            else None
        )

        proxima = (
            notas[i + 1]
            if i + 1 < len(notas)
            else None
        )

        # ----------------------------------------------------
        # CASO 1
        #
        # A3
        # A#3 muito curto
        # A3
        #
        # => A3 contínuo
        # ----------------------------------------------------

        if (
            anterior is not None
            and proxima is not None
            and anterior.pitch == proxima.pitch
        ):

            resultado[-1] = NotaDetectada(
                pitch=anterior.pitch,
                inicio=anterior.inicio,
                fim=proxima.fim,
            )

            i += 2
            continue

        # ----------------------------------------------------
        # CASO 2
        #
        # A micro-nota está muito próxima da nota anterior.
        #
        # Exemplo:
        #
        # A3 longo
        # A#3 30ms
        #
        # => incorporamos ao A3.
        # ----------------------------------------------------

        if anterior is not None:

            distancia_anterior = abs(
                atual.pitch - anterior.pitch
            )

            if distancia_anterior <= 1:

                resultado[-1] = NotaDetectada(
                    pitch=anterior.pitch,
                    inicio=anterior.inicio,
                    fim=atual.fim,
                )

                i += 1
                continue

        # ----------------------------------------------------
        # CASO 3
        #
        # Primeira nota curta próxima da seguinte.
        # ----------------------------------------------------

        if proxima is not None:

            distancia_proxima = abs(
                atual.pitch - proxima.pitch
            )

            if distancia_proxima <= 1:

                notas[i + 1] = NotaDetectada(
                    pitch=proxima.pitch,
                    inicio=atual.inicio,
                    fim=proxima.fim,
                )

                i += 1
                continue

        # ----------------------------------------------------
        # CASO 4
        #
        # Não temos evidência suficiente para afirmar
        # que é erro.
        #
        # Portanto PRESERVAMOS.
        # ----------------------------------------------------

        resultado.append(atual)

        i += 1

    return resultado


def juntar_notas_iguais(
    notas: List[NotaDetectada],
    gap_maximo: float,
):
    """
    Junta duas notas iguais separadas por um pequeno intervalo.

    Exemplo:

        A3 0.00 -> 0.50
        A3 0.54 -> 1.20

    vira:

        A3 0.00 -> 1.20
    """

    if not notas:
        return []

    resultado = [notas[0]]

    for atual in notas[1:]:

        anterior = resultado[-1]

        gap = atual.inicio - anterior.fim

        if (
            atual.pitch == anterior.pitch
            and gap <= gap_maximo
        ):

            resultado[-1] = NotaDetectada(
                pitch=anterior.pitch,
                inicio=anterior.inicio,
                fim=atual.fim
            )

        else:
            resultado.append(atual)

    return resultado


def corrigir_micro_notas_intermediarias(
    notas: List[NotaDetectada],
    duracao_micro_nota: float,
):
    """
    Corrige micro-notas espúrias sem criar buracos.

    Caso clássico:

        A3  0.00 -> 0.50
        A#3 0.50 -> 0.54
        A3  0.54 -> 1.20

    Em vez de simplesmente apagar A#3, reconstruímos:

        A3 0.00 -> 1.20

    Isso é muito útil contra:

    - vibrato;
    - pequenas flutuações;
    - detecção instável;
    - ataques vocais.
    """

    if len(notas) < 3:
        return notas.copy()

    resultado = notas.copy()

    alterado = True

    while alterado:

        alterado = False
        nova_lista = []

        i = 0

        while i < len(resultado):

            # Precisamos ter:
            #
            # anterior
            # atual
            # próxima
            if (
                i > 0
                and i < len(resultado) - 1
            ):

                anterior = nova_lista[-1]
                atual = resultado[i]
                proxima = resultado[i + 1]

                if (
                    atual.duracao <= duracao_micro_nota
                    and anterior.pitch == proxima.pitch
                ):

                    # Reconstrói uma única nota contínua.
                    nova_lista[-1] = NotaDetectada(
                        pitch=anterior.pitch,
                        inicio=anterior.inicio,
                        fim=proxima.fim,
                    )

                    # Pulamos:
                    #
                    # atual
                    # próxima
                    #
                    # porque já foram incorporadas.
                    i += 2

                    alterado = True
                    continue

            nova_lista.append(
                resultado[i]
            )

            i += 1

        resultado = nova_lista

    return resultado


def agrupar_notas_transitorias(
    notas: List[NotaDetectada],
    duracao_maxima_transitoria: float,
    distancia_maxima_semitons: int = 1,
    chroma_harmonico=None,
    confianca_harmonica=None,
    tempos=None,
    confianca_harmonica_minima=0.18,
    vantagem_harmonica_para_preservar=0.15,
):
    """
    Agrupa notas transitórias produzidas por:

        - ataques vocais;
        - vibrato;
        - portamento;
        - instabilidade momentânea;
        - pequenas oscilações do pYIN.

    Uma nota curta pode ser incorporada:

        - à anterior;
        - à seguinte;
        - às duas, quando estiver entre notas iguais.

    Quando anterior e próxima são possíveis, priorizamos:

        1. a nota mais próxima em pitch;
        2. em caso de empate, a nota de maior duração.

    Isso favorece a incorporação de um pequeno ataque
    existente antes da nota principal.
    """

    if len(notas) < 2:
        return notas.copy()

    resultado = notas.copy()
    alterado = True

    while alterado:
        alterado = False
        nova_lista = []
        i = 0

        while i < len(resultado):
            atual = resultado[i]

            anterior = (
                nova_lista[-1]
                if nova_lista
                else None
            )

            proxima = (
                resultado[i + 1]
                if i + 1 < len(resultado)
                else None
            )

            nota_curta = (
                atual.duracao
                <= duracao_maxima_transitoria
            )

            # ------------------------------------------------
            # CASO 1
            #
            # A3
            # A#3 curto
            # A3
            #
            # => A3 contínuo
            # ------------------------------------------------

            if (
                nota_curta
                and anterior is not None
                and proxima is not None
                and anterior.pitch == proxima.pitch
                and abs(
                    atual.pitch
                    - anterior.pitch
                ) <= distancia_maxima_semitons
            ):
                preservar = harmonia_sustenta_nota(
                    pitch_candidato=atual.pitch,
                    pitch_alvo=anterior.pitch,
                    inicio=atual.inicio,
                    fim=atual.fim,
                    chroma_harmonico=chroma_harmonico,
                    confianca_harmonica=(
                        confianca_harmonica
                    ),
                    tempos=tempos,
                    confianca_minima=(
                        confianca_harmonica_minima
                    ),
                    vantagem_minima=(
                        vantagem_harmonica_para_preservar
                    ),
                )

                if not preservar:
                    nova_lista[-1] = NotaDetectada(
                        pitch=anterior.pitch,
                        inicio=anterior.inicio,
                        fim=proxima.fim,
                    )

                    i += 2
                    alterado = True
                    continue

            # ------------------------------------------------
            # CANDIDATOS DE INCORPORAÇÃO
            # ------------------------------------------------

            if nota_curta:
                candidatos = []

                if anterior is not None:
                    distancia_anterior = abs(
                        atual.pitch
                        - anterior.pitch
                    )

                    if (
                        distancia_anterior
                        <= distancia_maxima_semitons
                    ):
                        candidatos.append(
                            (
                                "anterior",
                                anterior,
                                distancia_anterior,
                            )
                        )

                if proxima is not None:
                    distancia_proxima = abs(
                        atual.pitch
                        - proxima.pitch
                    )

                    if (
                        distancia_proxima
                        <= distancia_maxima_semitons
                    ):
                        candidatos.append(
                            (
                                "proxima",
                                proxima,
                                distancia_proxima,
                            )
                        )

                if candidatos:
                    # Menor distância primeiro.
                    # Em empate, maior duração primeiro.
                    candidatos.sort(
                        key=lambda item: (
                            item[2],
                            -item[1].duracao,
                        )
                    )

                    lado_escolhido = (
                        candidatos[0][0]
                    )

                    nota_principal = (
                        candidatos[0][1]
                    )

                    preservar = harmonia_sustenta_nota(
                        pitch_candidato=atual.pitch,
                        pitch_alvo=nota_principal.pitch,
                        inicio=atual.inicio,
                        fim=atual.fim,
                        chroma_harmonico=(
                            chroma_harmonico
                        ),
                        confianca_harmonica=(
                            confianca_harmonica
                        ),
                        tempos=tempos,
                        confianca_minima=(
                            confianca_harmonica_minima
                        ),
                        vantagem_minima=(
                            vantagem_harmonica_para_preservar
                        ),
                    )

                    if not preservar:
                        if lado_escolhido == "anterior":
                            nova_lista[-1] = NotaDetectada(
                                pitch=anterior.pitch,
                                inicio=anterior.inicio,
                                fim=atual.fim,
                            )

                            i += 1
                            alterado = True
                            continue

                        if lado_escolhido == "proxima":
                            resultado[i + 1] = NotaDetectada(
                                pitch=proxima.pitch,
                                inicio=atual.inicio,
                                fim=proxima.fim,
                            )

                            i += 1
                            alterado = True
                            continue

            nova_lista.append(
                atual
            )

            i += 1

        resultado = nova_lista

    return resultado


def juntar_notas_proximas(
    notas: List[NotaDetectada],
    gap_maximo: float,
    distancia_maxima_semitons: int = 1,
    duracao_maxima_desvio: float = 0.130,
    chroma_harmonico=None,
    confianca_harmonica=None,
    tempos=None,
    confianca_harmonica_minima=0.18,
    vantagem_harmonica_para_preservar=0.15,
):
    """
    Junta regiões próximas pertencentes provavelmente
    ao mesmo bloco vocal.

    Uma nota vizinha curta pode ser absorvida pela anterior,
    desde que:

        - esteja próxima em pitch;
        - esteja próxima no tempo;
        - não possua forte sustentação harmônica própria.
    """

    if not notas:
        return []

    resultado = [
        notas[0]
    ]

    for atual in notas[1:]:
        anterior = resultado[-1]

        gap = (
            atual.inicio
            - anterior.fim
        )

        distancia = abs(
            atual.pitch
            - anterior.pitch
        )

        # ----------------------------------------------------
        # MESMA NOTA
        # ----------------------------------------------------

        if (
            atual.pitch == anterior.pitch
            and gap <= gap_maximo
        ):
            resultado[-1] = NotaDetectada(
                pitch=anterior.pitch,
                inicio=anterior.inicio,
                fim=max(
                    anterior.fim,
                    atual.fim,
                ),
            )

            continue

        # ----------------------------------------------------
        # NOTA VIZINHA CURTA
        # ----------------------------------------------------

        if (
            distancia <= distancia_maxima_semitons
            and gap <= gap_maximo
            and atual.duracao
            <= duracao_maxima_desvio
        ):
            preservar = harmonia_sustenta_nota(
                pitch_candidato=atual.pitch,
                pitch_alvo=anterior.pitch,
                inicio=atual.inicio,
                fim=atual.fim,
                chroma_harmonico=chroma_harmonico,
                confianca_harmonica=(
                    confianca_harmonica
                ),
                tempos=tempos,
                confianca_minima=(
                    confianca_harmonica_minima
                ),
                vantagem_minima=(
                    vantagem_harmonica_para_preservar
                ),
            )

            if not preservar:
                resultado[-1] = NotaDetectada(
                    pitch=anterior.pitch,
                    inicio=anterior.inicio,
                    fim=atual.fim,
                )

                continue

        resultado.append(
            atual
        )

    return resultado

def preencher_buracos_vocais_com_energia(
    valores,
    y_voz,
    sr,
    hop_length,
    frame_length,
    gap_maximo_segundos=0.180,
    gap_borda_maximo_segundos=0.060,
    distancia_maxima_interpolacao_cents=200.0,
    percentil_energia_lacuna=70.0,
    fator_energia_local_minima=0.18,
):
    """
    Recupera pequenas regiões sem F0 somente quando o áudio
    isolado da voz ainda possui energia suficiente.

    Isso distingue:

        falha do pYIN:
            existe energia vocal, mas não existe F0 confiável

        silêncio verdadeiro:
            não existe F0 e a energia vocal também caiu

    Quando os pitches das extremidades estão próximos,
    fazemos interpolação.

    Quando estão distantes, provavelmente ocorreu uma troca
    real de nota durante a lacuna. Nesse caso:

        primeira metade -> nota da esquerda
        segunda metade  -> nota da direita

    Isso recupera a continuidade sem criar uma escada de
    notas intermediárias artificiais.
    """

    valores = np.asarray(
        valores,
        dtype=float,
    ).copy()

    y_voz = np.asarray(
        y_voz,
        dtype=float,
    )

    quantidade_frames = len(
        valores
    )

    diagnostico = {
        "lacunas_encontradas": 0,
        "lacunas_recuperadas": 0,
        "lacunas_preservadas": 0,
        "frames_recuperados": 0,
        "detalhes_preservadas": [],
    }

    if quantidade_frames == 0:
        return valores, diagnostico

    duracao_frame = (
        hop_length
        / float(sr)
    )

    max_frames_internos = max(
        1,
        int(
            round(
                gap_maximo_segundos
                / duracao_frame
            )
        ),
    )

    max_frames_borda = max(
        1,
        int(
            round(
                gap_borda_maximo_segundos
                / duracao_frame
            )
        ),
    )

    # --------------------------------------------------------
    # 1. ENERGIA RMS DA VOZ
    # --------------------------------------------------------

    rms = librosa.feature.rms(
        y=y_voz,
        frame_length=frame_length,
        hop_length=hop_length,
        center=True,
    )[0]

    tempos_valores = librosa.frames_to_time(
        np.arange(
            quantidade_frames
        ),
        sr=sr,
        hop_length=hop_length,
    )

    tempos_rms = librosa.frames_to_time(
        np.arange(
            len(rms)
        ),
        sr=sr,
        hop_length=hop_length,
    )

    if len(rms) == 0:
        energia = np.zeros(
            quantidade_frames,
            dtype=float,
        )
    else:
        energia = np.interp(
            tempos_valores,
            tempos_rms,
            rms,
            left=0.0,
            right=0.0,
        )

    energias_positivas = energia[
        energia > 0.0
    ]

    if len(energias_positivas) == 0:
        limiar_global = 0.0
    else:
        piso_energia = np.percentile(
            energias_positivas,
            10,
        )

        pico_energia = np.max(
            energias_positivas
        )

        limiar_global = max(
            piso_energia * 1.35,
            pico_energia * 0.003,
        )

    # --------------------------------------------------------
    # 2. PROCURA DAS LACUNAS
    # --------------------------------------------------------

    i = 0

    while i < quantidade_frames:
        if np.isfinite(valores[i]):
            i += 1
            continue

        inicio_gap = i

        while (
            i < quantidade_frames
            and not np.isfinite(valores[i])
        ):
            i += 1

        fim_gap = i - 1
        quantidade_gap = (
            fim_gap
            - inicio_gap
            + 1
        )

        diagnostico[
            "lacunas_encontradas"
        ] += 1

        indice_esquerda = (
            inicio_gap - 1
        )

        indice_direita = i

        possui_esquerda = (
            indice_esquerda >= 0
            and np.isfinite(
                valores[indice_esquerda]
            )
        )

        possui_direita = (
            indice_direita
            < quantidade_frames
            and np.isfinite(
                valores[indice_direita]
            )
        )

        lacuna_interna = (
            possui_esquerda
            and possui_direita
        )

        limite_frames = (
            max_frames_internos
            if lacuna_interna
            else max_frames_borda
        )

        inicio_segundos = (
            inicio_gap
            * duracao_frame
        )

        fim_segundos = (
            (fim_gap + 1)
            * duracao_frame
        )

        # Lacuna longa continua sendo silêncio.
        if quantidade_gap > limite_frames:
            diagnostico[
                "lacunas_preservadas"
            ] += 1

            diagnostico[
                "detalhes_preservadas"
            ].append(
                {
                    "inicio": inicio_segundos,
                    "fim": fim_segundos,
                    "duracao": (
                        quantidade_gap
                        * duracao_frame
                    ),
                    "motivo": "lacuna longa",
                }
            )

            continue

        # ----------------------------------------------------
        # 3. ENERGIA DENTRO E AO REDOR DA LACUNA
        # ----------------------------------------------------

        energia_gap = float(
            np.percentile(
                energia[
                    inicio_gap:
                    fim_gap + 1
                ],
                percentil_energia_lacuna,
            )
        )

        margem_contexto = max(
            3,
            quantidade_gap,
        )

        inicio_contexto_esquerdo = max(
            0,
            inicio_gap
            - margem_contexto
        )

        fim_contexto_direito = min(
            quantidade_frames,
            fim_gap
            + margem_contexto
            + 1
        )

        energias_contexto = []

        if inicio_gap > inicio_contexto_esquerdo:
            energias_contexto.extend(
                energia[
                    inicio_contexto_esquerdo:
                    inicio_gap
                ].tolist()
            )

        if fim_contexto_direito > fim_gap + 1:
            energias_contexto.extend(
                energia[
                    fim_gap + 1:
                    fim_contexto_direito
                ].tolist()
            )

        if energias_contexto:
            energia_local = float(
                np.percentile(
                    energias_contexto,
                    60,
                )
            )
        else:
            energia_local = 0.0

        limiar_local = (
            energia_local
            * fator_energia_local_minima
        )

        limiar_necessario = max(
            limiar_global,
            limiar_local,
        )

        possui_energia_vocal = (
            energia_gap
            >= limiar_necessario
            and energia_gap > 0.0
        )

        if not possui_energia_vocal:
            diagnostico[
                "lacunas_preservadas"
            ] += 1

            diagnostico[
                "detalhes_preservadas"
            ].append(
                {
                    "inicio": inicio_segundos,
                    "fim": fim_segundos,
                    "duracao": (
                        quantidade_gap
                        * duracao_frame
                    ),
                    "motivo": "energia insuficiente",
                }
            )

            continue

        # ----------------------------------------------------
        # 4. RECUPERAÇÃO COM DUAS EXTREMIDADES
        # ----------------------------------------------------

        if lacuna_interna:
            valor_esquerda = float(
                valores[indice_esquerda]
            )

            valor_direita = float(
                valores[indice_direita]
            )

            distancia_cents = abs(
                valor_direita
                - valor_esquerda
            ) * 100.0

            if (
                distancia_cents
                <= distancia_maxima_interpolacao_cents
            ):
                # Pitch semelhante:
                # interpolação gradual.
                passos = (
                    quantidade_gap + 1
                )

                for j in range(
                    1,
                    quantidade_gap + 1,
                ):
                    proporcao = (
                        j / passos
                    )

                    valores[
                        inicio_gap + j - 1
                    ] = (
                        valor_esquerda
                        + (
                            valor_direita
                            - valor_esquerda
                        )
                        * proporcao
                    )

            else:
                # Troca real de nota:
                # não criamos pitches intermediários.
                quantidade_esquerda = (
                    quantidade_gap // 2
                )

                if quantidade_gap % 2 != 0:
                    quantidade_esquerda += 1

                ponto_divisao = (
                    inicio_gap
                    + quantidade_esquerda
                )

                valores[
                    inicio_gap:
                    ponto_divisao
                ] = valor_esquerda

                valores[
                    ponto_divisao:
                    fim_gap + 1
                ] = valor_direita

        # ----------------------------------------------------
        # 5. RECUPERAÇÃO EM UMA BORDA
        # ----------------------------------------------------

        elif possui_esquerda:
            valores[
                inicio_gap:
                fim_gap + 1
            ] = valores[indice_esquerda]

        elif possui_direita:
            valores[
                inicio_gap:
                fim_gap + 1
            ] = valores[indice_direita]

        else:
            diagnostico[
                "lacunas_preservadas"
            ] += 1

            continue

        diagnostico[
            "lacunas_recuperadas"
        ] += 1

        diagnostico[
            "frames_recuperados"
        ] += quantidade_gap

    return valores, diagnostico