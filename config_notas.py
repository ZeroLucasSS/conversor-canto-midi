# ============================================================
# ÁUDIO
# ============================================================

SAMPLE_RATE_NOTAS = 22050
MONO_NOTAS = True

FRAME_LENGTH_NOTAS = 2048
HOP_LENGTH_NOTAS = 256

NOTA_VOCAL_MINIMA = "C2"
NOTA_VOCAL_MAXIMA = "C7"


# ============================================================
# DETECÇÃO DO PITCH VOCAL
# ============================================================

# Aceitamos frames relativamente tolerantes porque a análise
# final considera todos os frames da sílaba em conjunto.
VOICED_PROB_MIN_NOTAS = 0.20

# Quantidade mínima desejada de frames vocais dentro do
# núcleo da sílaba.
FRAMES_VOCAIS_MINIMOS = 3

# Se o núcleo não possuir F0 suficiente, analisamos também
# esta margem ao redor da sílaba.
MARGEM_FALLBACK_SILABA = 0.120


# ============================================================
# PITCH PREDOMINANTE
# ============================================================

# Resolução do histograma usado para localizar o plateau
# predominante da sílaba.
RESOLUCAO_HISTOGRAMA_CENTS = 10.0

# Depois que o pico do histograma é encontrado, frames nesta
# distância participam do cálculo refinado do centro vocal.
JANELA_CENTRO_PREDOMINANTE_CENTS = 55.0

# Frames dentro desta distância do candidato contam como
# ocupação daquela nota.
RAIO_OCUPACAO_CANDIDATO_CENTS = 65.0

# Usado para medir o quanto a sílaba permaneceu estável
# próximo do centro vocal.
RAIO_ESTABILIDADE_CENTS = 55.0


# ============================================================
# CANDIDATOS MUSICAIS
# ============================================================

# Serão avaliados:
#
#     nota arredondada
#     duas notas abaixo
#     duas notas acima
#
# Isso permite corrigir desafinações moderadas sem entregar
# liberdade total ao instrumental.
RAIO_CANDIDATOS_SEMITONS = 2

# Controla a penalização pela distância da voz.
#
# Valor maior torna o sistema mais tolerante à desafinação.
ESCALA_DISTANCIA_VOCAL_CENTS = 75.0


# ============================================================
# PESOS DA DECISÃO
# ============================================================

# Os pesos somam 1.0.
#
# A voz ainda é a evidência principal, mas a harmonia possui
# peso suficiente para resolver pitches próximos da fronteira
# entre dois semitons.
PESO_PROXIMIDADE_VOZ = 0.42
PESO_OCUPACAO_VOZ = 0.23
PESO_HARMONIA = 0.30
PESO_CONTINUIDADE = 0.05


# ============================================================
# CONTINUIDADE
# ============================================================

# Depois de um silêncio maior que este valor, a nota anterior
# deixa de influenciar a decisão.
GAP_MAXIMO_CONTINUIDADE = 1.000

# Distância em semitons usada no decaimento do bônus de
# continuidade.
ESCALA_CONTINUIDADE_SEMITONS = 4.0


# ============================================================
# ANÁLISE HARMÔNICA
# ============================================================

JANELA_SUAVIZACAO_CHROMA = 9
BINS_POR_OITAVA_CQT = 36

# Se a concentração harmônica for baixa, o instrumental terá
# automaticamente menos influência.
CONFIANCA_HARMONICA_MINIMA = 0.10


# ============================================================
# NOTAS MIDI
# ============================================================

# True faz a nota começar no núcleo vocálico, evitando que
# consoantes antecipem artificialmente o pitch.
USAR_NUCLEO_COMO_INICIO_NOTA = True

DURACAO_MINIMA_NOTA_MIDI = 0.030

VELOCIDADE_MIDI = 100
INSTRUMENTO_MIDI = "Acoustic Grand Piano"
TEMPO_REFERENCIA_MIDI = 120.0


# ============================================================
# DIAGNÓSTICO
# ============================================================

# Notas abaixo desta confiança serão geradas normalmente,
# mas marcadas para revisão no JSON e no CSV.
CONFIANCA_MINIMA_SEM_REVISAO = 0.55

# Correções maiores que esta distância serão destacadas.
CORRECAO_CENTS_PARA_REVISAO = 90.0