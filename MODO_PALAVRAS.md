O conversor oferece **Silábico** (padrão) e **Por palavras**, selecionáveis antes
de iniciar a conversão. Os arquivos de entrada continuam sendo voz, instrumental,
letra.srt e letra.txt. A consolidação e a revisão manual são compartilhadas.

No modo por palavras, cada ocorrência alinhada gera exatamente uma nota MIDI e
uma legenda com a palavra inteira. A escolha da altura usa os frames vocais da
palavra, ponderados por confiança e energia, e o centro de pitch predominante.
A harmonia e a continuidade auxiliam a decisão. Não há divisão em sílabas nem
média das notas silábicas. Os limites alinhados são preservados, com a recuperação
acústica de sustentação já existente; tempos confirmados manualmente são respeitados.

Uma palavra cantada com várias alturas será simplificada. Uma região distante
do centro por pelo menos 1,5 semitom e com 20% do peso vocal é sinalizada para
revisão. Intervalos internos de mais de 150 ms sem frames vocais confiáveis também
são sinalizados. São heurísticas, não garantias de precisão musical. Sem F0 local,
o fallback de altura permanece explícito no relatório, sem emprestar frames de
palavras vizinhas.

Com o nome padrão, a interface publica `voz.mid`, `voz_metadata.json` e
`voz_silabas.srt` ou `voz_palavras.srt`. Os relatórios `voz_notas.json` e
`voz_notas.csv` acompanham a saída. Resultados anteriores são copiados para uma
subpasta exclusiva de `historico_conversoes` antes da substituição. A legenda do
modo anterior sai da pasta ativa e fica preservada no histórico. O nome escolhido
permanece estável, sem sufixo numérico. Falhas de publicação tentam restaurar o
conjunto anterior; múltiplos arquivos não constituem transação contra queda de energia.

Pela linha de comando, use `--modo palavras` nas duas etapas:

```powershell
python preparar_letra.py audios --modo palavras --saida saida/alinhamento_palavras
python gerar_midi_silabico.py voz.mid --pasta-musica audios --modo palavras --alinhamento saida/alinhamento_palavras/alinhamento_completo.json --saida saida/palavras
```

Sem `--modo`, o comportamento musical continua silábico. A publicação com histórico
é feita pela interface/controlador; o gerador de linha de comando grava diretamente
na pasta indicada. Use pastas distintas para comparar modos pela linha de comando.

O motor compartilha seu contrato interno histórico (`NotaSilabica` e campos
`silaba*`) com intervalos por palavra. No novo modo, esses campos representam a
palavra completa; `metadados.modo = "palavras"` identifica o relatório JSON.
O formato de consumo de `voz_metadata.json` permanece compatível.

Validação: `python -m unittest discover -s testes -v`. Os testes do novo modo
usam evidência vocal sintética e alinhamentos controlados. A qualidade em músicas
reais deve ser avaliada comparando sincronismo, pitch e perda de movimentos internos.
