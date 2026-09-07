"""Configuração do alinhamento SRT/voz. Tempos em segundos."""

IDIOMA_ALINHAMENTO = "pt"
IDIOMA_SILABIFICACAO = "pt_BR"
MODELO_ALINHAMENTO = None
DISPOSITIVO_ALINHAMENTO = "auto"
MARGEM_ANALISE_SRT = 0.200
ANCORAR_EXTREMIDADES_NO_SRT = True
DURACAO_MINIMA_UNIDADE = 0.005
EXTENSOES_AUDIO_SUPORTADAS = {
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma",
}

# Piso ADAPTATIVO: reduzido quando a palavra é rápida demais.
# Não alonga palavras nem invade a palavra seguinte.
DURACAO_MINIMA_SILABA = 0.060
FRACAO_PISO_SILABA = 0.45
SCORE_MINIMO_CARACTERE = 0.30
SCORE_MINIMO_PALAVRA = 0.30
RAIO_REFINAMENTO = 0.100
LIMIAR_EVENTO_FRONTEIRA = 0.45

# Evidência acústica auxiliar, não um reconhecedor de fonemas.
JANELA_ACUSTICA = 0.040
PASSO_ACUSTICO = 0.010
FREQUENCIA_MINIMA_VOZ = 65.0
FREQUENCIA_MAXIMA_VOZ = 1100.0
PERIODICIDADE_MINIMA = 0.55
ENERGIA_RELATIVA_MINIMA = 0.04
ENERGIA_ABSOLUTA_MINIMA = 0.0001
GAP_PERIODICIDADE_MAXIMO = 0.040
PAUSA_INTERNA_AVISO = 0.150
DURACAO_MINIMA_NUCLEO = 0.030

# Pyphen continua sendo apenas uma hipótese ortográfica.
# Personalize por idioma/palavra; não depende de uma música específica.
# Para outra pronúncia cantada de "ainda", pode-se usar ["ain", "da"].
EXCECOES_SILABICAS = {
    "pt_BR": {"ainda": ["a", "in", "da"]},
}

# Recuperação entre palavras. Não atravessa limites de blocos SRT.
RECUPERAR_SUSTENTACOES = True
GAP_MINIMO_ANALISAR = 0.080
RECUPERACAO_MINIMA = 0.080
JANELA_REFERENCIA_SUSTENTACAO = 0.150
FALHA_CONTINUIDADE_MAXIMA = 0.250
DISTANCIA_TIMBRE_MAXIMA = 0.35
COBERTURA_REFERENCIA_MINIMA = 0.50
COBERTURA_SUSTENTACAO_MINIMA = 0.60
GAP_COM_VOZ_AVISO = 0.200

# Controles exclusivos da recuperação. Confirmar silêncio por 120 ms;
# terminar no último frame aceito, e não no instante de confirmação.
SILENCIO_CONFIRMADO_SEGUNDOS = 0.120
SILENCIO_RMS_ABSOLUTO = 0.0000001
SILENCIO_FRACAO_REFERENCIA = 0.002
SILENCIO_MULTIPLICADOR_RUIDO = 2.5
PERIODICIDADE_MINIMA_SUSTENTACAO = 0.30
# A potência pesa na decisão do pitch, mas não encerra a nota MIDI.
PESO_MINIMO_ENERGIA_PITCH = 0.35
RESOLUCAO_MIDI_TICKS = 1920

# Experimento 2.3: ajustes de duração no MIDI, sem alterar o JSON de letra.
AJUSTAR_DURACOES_MIDI = True
DURACAO_ALVO_MINIMA_MIDI = 0.100
# Não desloca uma fronteira interna mais que isto para atender ao piso.
DESLOCAMENTO_MAXIMO_FRONTEIRA_MIDI = 0.120
ALONGAR_FINAL_FRASE_MIDI = True
EXTENSAO_MAXIMA_FINAL_FRASE = 1.200
SILENCIO_FINAL_FRASE_CONFIRMADO = 0.140
FALHA_FINAL_FRASE_MAXIMA = 0.300
RAIO_REFERENCIA_FINAL_FRASE = 0.200
