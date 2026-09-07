# config.py

# ============================================================
# CONFIGURAÇÕES DO CONVERSOR DE VOZ EM MIDI
# ============================================================


# ------------------------------------------------------------
# ÁUDIO
# ------------------------------------------------------------

SAMPLE_RATE = 22050

# Trabalhamos em mono porque o objetivo é detectar
# uma única linha melódica vocal.
MONO = True


# ------------------------------------------------------------
# FAIXA VOCAL
# ------------------------------------------------------------

# Frequências aproximadas:
#
# C2 = 65.41 Hz
# C6 = 1046.50 Hz
#
# Essa faixa cobre praticamente todas as situações
# normais de canto que encontraremos.

NOTA_MINIMA = "C2"
NOTA_MAXIMA = "C6"


# ============================================================
# PYIN
# ============================================================

FRAME_LENGTH = 2048
HOP_LENGTH = 256

# Confiança normal para aceitar imediatamente um frame.
VOICED_PROB_MIN = 0.45


# ============================================================
# MEMÓRIA DE SUSTENTAÇÃO VOCAL
# ============================================================

# Durante uma nota já estabilizada, frames com probabilidade
# menor ainda podem ser preservados quando o F0 continuar
# próximo da nota sustentada.
VOICED_PROB_MIN_SUSTENTACAO = 0.18


# Quantidade de frames válidos necessária para considerar
# que uma nota entrou em estado de sustentação.
#
# 8 frames representam aproximadamente 93 ms.
FRAMES_ESTABILIDADE_SUSTENTACAO = 8


# Quantos frames sem pitch confiável a memória da nota
# sustentada poderá conservar.
FRAMES_MEMORIA_SUSTENTACAO = 16


# Um F0 de baixa confiança só será preservado quando estiver
# próximo do pitch sustentado.
DISTANCIA_MAXIMA_SUSTENTACAO_CENTS = 120.0


# Uma região precisa ter pelo menos esta duração para receber
# a tolerância ampliada de sustentação.
DURACAO_MINIMA_SUSTENTACAO = 0.300


# Pequenas falhas dentro de uma nota sustentada poderão ser
# recuperadas até esta duração.
GAP_MAXIMO_SUSTENTACAO = 0.300


# Se a lacuna estiver entre notas distantes, só preencheremos
# toda a transição quando ela for menor que este valor.
GAP_MAXIMO_TRANSICAO_SUSTENTADA = 0.180


# No final de uma nota sustentada, permite prolongar a nota
# por um curto período quando ainda não existe pitch válido
# do outro lado.
EXTENSAO_MAXIMA_FINAL_SUSTENTADO = 0.120


# ============================================================
# RECUPERAÇÃO NORMAL DE BURACOS
# ============================================================

# Recuperação normal usada para ataques, consoantes e falhas
# curtas do pYIN.
GAP_F0_MAXIMO = 0.120

DISTANCIA_MAXIMA_INTERPOLACAO_CENTS = 200.0


# ------------------------------------------------------------
# ESTABILIZAÇÃO DA AFINAÇÃO
# ------------------------------------------------------------

# Antes: 5
#
# Aumentamos um pouco a suavização da curva de pitch.
#
# 7 frames ~= 81 ms com hop_length=256.
JANELA_MEDIANA = 7


# ============================================================
# DETECÇÃO E AGRUPAMENTO
# ============================================================

DURACAO_MINIMA_NOTA = 0.070

GAP_MAXIMO = 0.150

LIMIAR_TROCA_CENTS = 65.0

FRAMES_CONFIRMACAO_NOTA = 3


# ============================================================
# RECUPERAÇÃO DE LACUNAS VOCAIS
# ============================================================

# Lacuna interna máxima que poderá ser recuperada quando
# o áudio ainda apresentar energia vocal.
#
# 180 ms cobre ataques, consoantes, finais de sílabas
# e pequenas falhas do pYIN.
GAP_VOCAL_MAXIMO_COM_ENERGIA = 0.180


# Nas extremidades de uma região vocal, onde existe pitch
# válido somente de um lado, somos mais conservadores.
GAP_VOCAL_BORDA_MAXIMO = 0.060


# Percentil da energia dentro da lacuna utilizado para
# verificar se ainda existe sinal vocal.
#
# Usar o percentil 70 evita que um único frame silencioso
# invalide toda a região.
PERCENTIL_ENERGIA_LACUNA = 70.0


# A energia da lacuna precisa representar pelo menos esta
# fração da energia vocal ao redor dela.
FATOR_ENERGIA_LOCAL_MINIMA = 0.18


# Limite para interpolar gradualmente entre os pitches
# das duas extremidades.
#
# Quando a distância for maior, dividiremos a lacuna:
# primeira metade recebe a nota da esquerda;
# segunda metade recebe a nota da direita.
DISTANCIA_MAXIMA_INTERPOLACAO_CENTS = 200.0


# ============================================================
# AGRUPAMENTO MUSICAL
# ============================================================

DISTANCIA_MAXIMA_AGRUPAMENTO_SEMITONS = 1

# Retorna ao valor mais tolerante da versão anterior.
DURACAO_MAXIMA_NOTA_TRANSITORIA = 0.130

# Retorna à tolerância anterior.
GAP_MAXIMO_AGRUPAMENTO = 0.100


# ------------------------------------------------------------
# VELOCITY MIDI
# ------------------------------------------------------------

VELOCITY_PADRAO = 100


# ------------------------------------------------------------
# MIDI
# ------------------------------------------------------------

NOME_INSTRUMENTO = "Voz convertida"

# Acoustic Grand Piano
PROGRAMA_MIDI = 0


# ------------------------------------------------------------
# DEBUG
# ------------------------------------------------------------

MOSTRAR_DETALHES = True

# ============================================================
# FUSÃO VOZ + INSTRUMENTAL
# ============================================================

# Quantidade de frames usada para suavizar o chroma.
#
# Com HOP_LENGTH = 256:
# 9 frames representam aproximadamente 104 ms.
JANELA_SUAVIZACAO_HARMONICA = 9


# Quantas subdivisões da oitava serão usadas internamente
# pelo CQT.
#
# O chroma final continuará possuindo 12 classes:
#
# C, C#, D, D#, E, F, F#, G, G#, A, A#, B
BINS_POR_OITAVA_CQT = 36


# Peso máximo da harmonia na escolha de uma nota.
#
# A voz permanece como evidência principal.
PESO_HARMONIA = 0.85


# Pequeno bônus para manter continuidade com a nota
# escolhida no frame anterior.
PESO_CONTINUIDADE = 0.12


# Escala usada para transformar a distância em cents
# em uma pontuação vocal.
#
# Quanto menor, mais autoridade damos ao F0 vocal.
ESCALA_DISTANCIA_VOZ_CENTS = 55.0


# A harmonia só poderá influenciar a decisão quando
# sua confiança ultrapassar este valor.
CONFIANCA_HARMONICA_MINIMA = 0.18


# Para trocar a nota arredondada naturalmente pela voz,
# a nota alternativa precisa possuir esta vantagem
# harmônica mínima.
VANTAGEM_HARMONICA_MINIMA = 0.12


# Mesmo depois da vantagem harmônica, o score total
# precisa superar o candidato original por esta margem.
MARGEM_SCORE_TROCA = 0.08


# A harmonia nunca poderá deslocar um pitch vocal
# por mais que esta distância.
#
# Isso impede que o instrumental "invente" notas.
DISTANCIA_MAXIMA_CORRECAO_CENTS = 70.0


# Durante o agrupamento, uma nota curta será preservada
# quando o instrumental a favorecer em relação à nota
# que tentaria absorvê-la.
VANTAGEM_HARMONICA_PARA_PRESERVAR = 0.15


# Os dois stems já estão naturalmente sincronizados.
#
# Se futuramente for detectado um pequeno desalinhamento,
# este parâmetro permitirá compensá-lo.
#
# Valor positivo:
# consulta o instrumental um pouco mais à frente.
#
# Valor negativo:
# consulta o instrumental um pouco mais atrás.
DESLOCAMENTO_INSTRUMENTAL_SEGUNDOS = 0.0


# Diferenças pequenas podem surgir apenas por exportação
# ou arredondamento dos arquivos.
TOLERANCIA_DURACAO_ARQUIVOS = 0.500