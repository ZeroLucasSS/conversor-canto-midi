# Consolidação em três etapas

`consolidar_letra.py` mantém a CLI e a interface `AlinhadorLocal`.
`etapas_consolidacao.py` executa as etapas independentes:

1. Preservar texto exclusivo ou ambíguo do SRT, com seus tempos e um aviso.
2. Corrigir texto correspondente pelo TXT, sem modificar os tempos existentes.
   As palavras das extremidades são preferências, permitindo, por exemplo,
   "Diz antes de tudo" virar "Distantes de tudo". Um vizinho reconhecido pode
   desempatar variantes semelhantes. Exclusões de texto exclusivo preservam
   conservadoramente o bloco inteiro; falas extras não são removidas por não
   constarem do TXT.
3. Procurar trechos ainda não associados nas lacunas livres entre referências
   adjacentes, ou nas extremidades do áudio quando há referência suficiente.
   Repetições são ocorrências distintas, indexadas pelos tokens do TXT.
   Fragmentos desconhecidos de até duas palavras e um segundo podem ficar
   dentro da janela de pesquisa, mas seus intervalos permanecem ocupados:
   palavras novas que os sobrepõem são omitidas e sinalizadas. Blocos
   desconhecidos maiores continuam interrompendo a busca. Nenhum bloco
   existente é deslocado.

O SRT continua determinando a estrutura da gravação. Um TXT abreviado pode
servir de referência para várias ocorrências existentes. Texto do TXT sem
referência temporal segura é sinalizado, e não inserido arbitrariamente.

## Execução

```powershell
python consolidar_letra.py "audios/Tempo Perdido"
python consolidar_letra.py "audios/Evidencias"
python consolidar_letra.py "audios/Livre Pra Voar"
python consolidar_letra.py "audios/minha musica" --idioma en
python consolidar_letra.py "audios/minha musica" --idioma bilingue
```

As entradas são `letra.srt`, `letra.txt` e `voz.*` na pasta escolhida. As saídas
são `letra_consolidada.srt` e `letra_consolidada.json` nessa pasta. Para atualizar
saídas existentes, acrescente `--atualizar`. As entradas são preservadas.
`--somente-comparar` continua disponível sem carregar o motor acústico.

O padrão de `--idioma` agora é `auto`, inclusive na conversão pela interface.
`auto` e `bilingue` selecionam modelos pt/en por linha do TXT, usando palavras
funcionais, flexões e marcas ortográficas. Linhas sem evidência própria herdam
o contexto; lacunas curtas também recebem o idioma predominante da letra
completa. `pt` e `en` forçam o modelo escolhido. Modelos personalizados exigem
um idioma explícito.
Na entrada `preparar_letra.py`, a opção correspondente é
`--idioma-consolidacao` (padrão `auto`). O idioma do alinhamento posterior de
palavras/sílabas permanece uma configuração separada. Outros códigos de idioma
explícitos continuam sendo repassados ao WhisperX, como antes; a seleção
automática desta melhoria é somente pt/en.

Essa seleção é heurística, limitada a português/inglês, e pode errar em linhas
curtas, empréstimos ou mudanças de idioma dentro da mesma linha. O JSON registra
os votos, o idioma escolhido e quando houve herança de contexto. Não depende
de nomes de músicas, artistas ou frases específicas.

Em uma janela bilíngue, os modelos recebem primeiro o contexto completo. As
palavras são selecionadas pelo idioma de sua linha e pela compatibilidade
temporal. Uma segunda passagem refina cada grupo de idioma entre palavras
vizinhas com suporte acústico; as alternativas são combinadas preservando ordem
e ausência de sobreposição. Nenhuma divisão temporal é estimada pelo tamanho
da letra. Os modelos são carregados sob demanda e reutilizados.

## Critérios e limitações

A consulta usa similaridade mínima de 0,65, bônus de 0,02 por extremidade igual
e margem de ambiguidade de 0,025. Desempate pelo contexto anterior exige score
de pelo menos 0,85. Esses valores são heurísticos, não probabilidades.
Palavras isoladas exigem igualdade textual normalizada. Quando a palavra aparece
em vários lugares do TXT, só serve como âncora se continuar a referência do
bloco anterior, separado por até três segundos. Caso contrário, o original é
preservado com aviso; a primeira ocorrência não é escolhida arbitrariamente.

As referências de uma lacuna precisam ter score textual de pelo menos 0,75.
O limite de busca é o menor entre `--janela-maxima` (180 s por padrão) e
`max(30 s, 3 s por palavra candidata)`. A tolerância acomoda canto sustentado e
omissões de várias estrofes, mas continua rejeitando intervalos muito longos
para poucas palavras. Uma busca exige ao menos uma referência textual; apenas
fragmentos desconhecidos não autorizam alinhar a música inteira. Janelas longas
consomem mais memória/CPU; é possível reduzir o limite explicitamente.
`--margem` é mantido por compatibilidade, mas a etapa nova não o aplica para
invadir intervalos dos blocos originais.

Inserções usam exclusivamente os tempos retornados pelo alinhador. A sequência,
os limites, a ordem e a duração positiva são conferidos. Um trecho precisa ter
algum suporte do modelo (ao menos um score de 0,10) e, quando o motor disponibiliza
o áudio mono de 16 kHz, atividade em pelo menos 20% dos quadros de 20 ms
(RMS acima de 0,0001). Esses critérios rejeitam silêncio e resultados sem suporte,
mas energia, instrumentos e ruído não certificam a presença de uma frase.
Uma inspeção auditiva continua necessária para avaliar a precisão musical.

Palavras de baixa confiança com tempos utilizáveis podem ser publicadas com
avisos. Recuperação parcial é explicitada. Falha do motor não impede publicar
os blocos originais e as correções textuais. Não se interpolam timestamps.

## Relatório versão 6

- `auditoria_estrutura`: texto original/publicado, origem e tempos de cada bloco.
- `comparacao`: consultas ao TXT e tokens sem correspondência textual inicial.
- `recuperacoes`: candidatos, janelas, palavras retornadas e estados
  `nao_pesquisado`, `pesquisado_sem_confirmacao`, `parcialmente_recuperado`
  ou `recuperado`.
- `metricas`: separa correções textuais, inserções e tokens do TXT não associados.
- `palavras_conflito_original`, dentro de `metricas`: tokens cuja inserção foi
  impedida por sobreposição com um fragmento preservado. Os detalhes aparecem
  em `tentativas[].conflitos_originais` e nas pendências.
- `configuracao_motor.selecao_por_trecho`: escolhas de idioma e falhas de
  refinamento, quando executado pela CLI.
- `resumo_avisos`: último campo, também exibido no terminal.

`palavras_txt_sem_tempo` conta tokens do TXT sem associação confirmada, não
necessariamente palavras ausentes do SRT publicado: um trecho ambíguo pode ter
sido preservado literalmente no SRT, sem vínculo seguro com a ocorrência no TXT.
Os índices do TXT são base zero. As inserções também identificam sua lacuna.

## Testes

```powershell
python -m unittest discover -s testes -q
```

Em ambientes que restringem escrita no cache das dependências, use no PowerShell
`$env:NUMBA_CACHE_DIR = Join-Path (Get-Location) 'saida/numba_cache'` antes da suíte.

Há regressões para repetições, palavras divididas incorretamente, tempos
inalterados, correções sem chamada acústica, silêncio, resultados fora da
janela, resultados NumPy, inserção parcial e falha do motor. A suíte do motor
regional anterior permanece isolada em `test_consolidar_letra.py`.
`test_consolidacao_idiomas.py` cobre idiomas alternados, herança de contexto,
refinamento acústico, palavras repetidas isoladas, fragmentos ocupados e limites
de busca. Os testes não dependem da letra da Whitney.

Resultados do teste com as três gravações fornecidas:

| Música | Blocos originais preservados | Blocos novos | Resultado |
|---|---:|---:|---|
| Tempo Perdido | 26 | 3 | Três ocorrências recuperadas; 144 palavras publicadas |
| Evidencias | 56 | 0 | Refrões em 01:42,900 e 03:34,880 preservados |
| Livre Pra Voar | 39 | 0 | Publicação com avisos: 74 tokens do TXT sem associação confirmada |

Em Livre Pra Voar, as ambiguidades e intervalos ocupados impedem algumas buscas
seguras; isso não é uma falha do WhisperX, pois não houve chamada acústica nessa
música. O transcritor inclui falas extras e uma mensagem promocional, preservadas
para revisão. Não foi alterada a geração MIDI ou a sustentação das notas.

## Avaliação de 14/10/2026

O relatório anterior de `I Will Aways Love You` usava `idioma=pt`. Além disso,
uma palavra isolada aproximada voltava para um ponto anterior do TXT, e uma
palavra repetida era associada à primeira ocorrência disponível. Isso deslocava
o texto candidato e bloqueava buscas. Portanto, cobertura textual sozinha não
era uma medida suficiente de qualidade.

| Medida nessa gravação | Antes | Depois |
|---|---:|---:|
| Tokens do TXT sem associação temporal | 44 | 3 |
| Tokens pendentes que nem foram pesquisados | 44 | 0 |
| Palavras inseridas com baixa confiança | 44 | 7 |
| Blocos inseridos | 13 | 24 |

Os três tokens restantes conflitam com dois fragmentos preservados do SRT,
incluindo uma palavra já visível nele. Eles permanecem pendentes de revisão;
não significam necessariamente três palavras ausentes da legenda publicada.
Os 12 blocos originais mantiveram seus tempos e nenhuma inserção os sobrepôs.
As métricas de cobertura das outras três gravações permaneceram iguais às da
tabela anterior; as 74 pendências de Livre Pra Voar continuam existindo.

Também foi preparado um experimento com recortes reais em português e inglês
concatenados, com fronteira conhecida, para verificar a seleção de modelos e a
ordem temporal. É uma amostra controlada, não uma avaliação ampla de repertório
bilíngue. Não houve validação auditiva humana dos novos tempos. O status continua
`pendente` onde há baixa confiança ou conflitos.

Artefatos locais: `saida/melhoria_consolidacao/`, incluindo `comparacao.json`,
`bilingue.json`, o script reproduzível `avaliar.py` e os pares SRT/JSON por música.
