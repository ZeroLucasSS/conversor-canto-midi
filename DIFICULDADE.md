# Dificuldade estimada do MIDI

A heurística `heuristica_v2_pico_e_variedade`, em `exportacao_final.py`, usa:

- **85%: altura de pico**, a maior nota MIDI presente na música.
- **15%: variedade**, o número de alturas MIDI distintas. Notas em oitavas
  diferentes contam como alturas diferentes.

A quantidade de sílabas, o número total de eventos, a duração da música e a
densidade de notas não entram no score. Subdividir uma nota em várias sílabas
ou repetir a mesma sequência de alturas mantém o resultado.

Referências configuráveis no início do módulo:

```text
pico = limitar((maior_pitch - 60) / (84 - 60), 0, 1)
variedade = limitar((alturas_distintas - 1) / (12 - 1), 0, 1)
score = 0.85 * pico + 0.15 * variedade
```

O score abaixo de 0,35 recebe `beginner`; de 0,35 até menos de 0,65,
`intermediate`; a partir de 0,65, `advanced`. Por exemplo, uma única altura
C4 (MIDI 60) resulta em 0, C5 (72) em 0,425 e C6 (84) em 0,85, independentemente
de quantas vezes apareça.

O pico inclui notas breves: não é mais o percentil de altura ponderado pela
duração. A estimativa usa as alturas exportadas, portanto depende da qualidade
da detecção de pitch; é uma referência absoluta, não uma avaliação da tessitura
individual de quem canta.

O diagnóstico registra alturas distintas, pico, componentes, pesos e limiares.
O arquivo `_metadata.json` mantém o mesmo formato e os três níveis compatíveis
com o aplicativo leitor. Reexporte o MIDI para recalcular os arquivos existentes.
