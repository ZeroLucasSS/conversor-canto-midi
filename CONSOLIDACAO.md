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
   Não se atravessam blocos desconhecidos nem se deslocam os blocos existentes.

O SRT continua determinando a estrutura da gravação. Um TXT abreviado pode
servir de referência para várias ocorrências existentes. Texto do TXT sem
referência temporal segura é sinalizado, e não inserido arbitrariamente.

## Execução

```powershell
python consolidar_letra.py "audios/Tempo Perdido"
python consolidar_letra.py "audios/Evidencias"
python consolidar_letra.py "audios/Livre Pra Voar"
```

As entradas são `letra.srt`, `letra.txt` e `voz.*` na pasta escolhida. As saídas
são `letra_consolidada.srt` e `letra_consolidada.json` nessa pasta. Para atualizar
saídas existentes, acrescente `--atualizar`. As entradas são preservadas.
`--somente-comparar` continua disponível sem carregar o motor acústico.

## Critérios e limitações

A consulta usa similaridade mínima de 0,65, bônus de 0,02 por extremidade igual
e margem de ambiguidade de 0,025. Desempate pelo contexto anterior exige score
de pelo menos 0,85. Esses valores são heurísticos, não probabilidades.

As referências de uma lacuna precisam ter score textual de pelo menos 0,75.
O limite de busca é o menor entre `--janela-maxima` (90 s por padrão) e
`max(30 s, 2 s por palavra candidata)`. Isso permite a lacuna de Tempo Perdido
sem abrir uma busca de quase toda a música para poucas palavras.
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

## Relatório versão 5

- `auditoria_estrutura`: texto original/publicado, origem e tempos de cada bloco.
- `comparacao`: consultas ao TXT e tokens sem correspondência textual inicial.
- `recuperacoes`: candidatos, janelas, palavras retornadas e estados
  `nao_pesquisado`, `pesquisado_sem_confirmacao`, `parcialmente_recuperado`
  ou `recuperado`.
- `metricas`: separa correções textuais, inserções e tokens do TXT não associados.
- `resumo_avisos`: último campo, também exibido no terminal.

`palavras_txt_sem_tempo` conta tokens do TXT sem associação confirmada, não
necessariamente palavras ausentes do SRT publicado: um trecho ambíguo pode ter
sido preservado literalmente no SRT, sem vínculo seguro com a ocorrência no TXT.
Os índices do TXT são base zero. As inserções também identificam sua lacuna.

## Testes

```powershell
python -m unittest discover -s testes -q
```

Há regressões para repetições, palavras divididas incorretamente, tempos
inalterados, correções sem chamada acústica, silêncio, resultados fora da
janela, resultados NumPy, inserção parcial e falha do motor. A suíte do motor
regional anterior permanece isolada em `test_consolidar_letra.py`.

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
