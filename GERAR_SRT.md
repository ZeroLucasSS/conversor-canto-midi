O botão **Gerar SRT**, antes de **Gerar MIDI**, transcreve o arquivo de voz e
alinha as palavras com WhisperX. É independente da conversão: exige apenas um
arquivo `voz` em formato suportado. Não exige instrumental ou letra.txt, não
depende do modo silábico/palavras e não inicia a conversão automaticamente.

Ao clicar, uma janela pede o idioma: **Português** (seleção inicial), **Inglês**
ou **Bilíngue (português e inglês)**. Confirmar inicia a operação; Cancelar, Esc
ou fechar a janela não inicia nenhum processamento.

Português e inglês fixam o idioma da transcrição e do alinhador. Bilíngue usa a
detecção por trecho do backend faster-whisper fornecido pelo WhisperX, em modo
de transcrição, sem tradução solicitada. O reconhecedor ainda pode errar palavras
ou traduzir involuntariamente um trecho. Para escolher o alinhador, o módulo
agora confronta a evidência acústica com palavras funcionais do texto reconhecido.
Recortes menores que 2,5 s, com detecção fraca ou divergente recebem uma segunda
análise com contexto de até 6 s (recortes maiores não são encurtados).

Uma frase com evidência textual clara usa o alinhador compatível com seu texto;
isso não certifica que a transcrição esteja correta. Quando não há evidência
textual suficiente, usa-se o áudio local e, se fraco, o contexto acústico forte.
A evidência acústica é considerada forte com probabilidade absoluta de ao menos
0,65, diferença de 0,20 entre pt/en e vencedor global no mesmo idioma. As
probabilidades não são renormalizadas descartando outras línguas.

`segmentos[].analise_idioma` registra votos textuais, probabilidades pt/en,
vencedor global, contexto usado, fonte da decisão e necessidade de revisão.
Texto e áudio divergentes, texto potencialmente misto e evidência fraca geram
avisos explícitos. `confianca_idioma` continua sendo a probabilidade acústica
local do idioma escolhido, não a certeza da decisão combinada.
Mudanças de língua dentro
da mesma frase e trechos curtos podem exigir revisão. Esta escolha se aplica à
geração do SRT; não muda a configuração dos demais módulos do conversor.

A saída é `letra.srt`, na pasta selecionada, com frases agrupadas por pausas de
650 ms, duração de até 6 s e até 72 caracteres quando os limites das palavras
permitem. Uma palavra indivisível pode exceder esses limites. Palavras sem tempo
ou cobertura incompleta fazem o segmento conservar o texto e os tempos originais
do reconhecimento, com aviso para revisão.

Os limites são validados na precisão de milissegundos do SRT. Sobreposições de
até 100 ms podem ser corrigidas quando uma fronteira usa um tempo aproximado
do reconhecedor, ou quando a palavra de fronteira tem score menor que 0,30 (ou
ausente) e a vizinha tem score de pelo menos 0,30. Usa-se o limite existente
mais confiável, sem calcular médias ou criar tempos por palavra; a palavra
afetada deve continuar com duração positiva. O texto permanece inteiro.
`blocos[].ajustes_temporais` registra campo, valor anterior, valor novo e motivo,
inclusive quando as duas extremidades do mesmo bloco são ajustadas.
Avisos identificam cada ajuste. O limite pode ser reduzido ou desligado pelo
parâmetro `tolerancia_sobreposicao` de `agrupar_segmentos`.

Conflitos maiores, duas fronteiras acústicas fortes, duas fronteiras acústicas fracas sem
referência e ajustes que apagariam uma palavra continuam impedindo a publicação.
A mensagem identifica o bloco e os tempos exatos, facilitando o diagnóstico.

`letra_geracao.json` (versão 2) registra a identidade do áudio, configuração, segmentos,
palavras alinhadas, blocos publicados e avisos. Se houver letra.txt em UTF-8,
registra também divergências textuais, sem alterar a letra de referência.
Scores de alinhamento e similaridade textual não garantem precisão musical.
`metricas` resume os ajustes temporais, as divergências áudio/texto e os segmentos
com idioma a revisar; esses avisos não são uma medição de acurácia do detector.

Arquivos existentes (inclusive vazios) não são substituídos. Para gerar outra
amostra, use outra pasta ou preserve/remova explicitamente o resultado anterior
e seu relatório. O botão fica desabilitado quando letra.srt ou letra_geracao.json
já existe. A interface explica requisitos ausentes e verifica novamente os
arquivos após a geração. Resultados anteriores da conversão MIDI não são alterados.

A execução ocorre em processo separado, com logs e cancelamento. Na interface,
os resultados só são publicados após a conclusão e a verificação do cancelamento.
SRT e relatório são preparados em arquivos temporários; o SRT completo é publicado
por último com link sem substituição. A pasta precisa suportar hard links
(por exemplo, NTFS). O par de arquivos não é transacional contra queda de energia;
nesse caso pode restar apenas o relatório, que deve ser preservado ou removido
explicitamente antes de repetir a operação.

Padrão inicial: modelo multilíngue `small`, idioma português, dispositivo automático,
CPU com int8 ou CUDA com float16, VAD Silero, sem identificação de locutores.
Modelos ausentes são baixados na primeira execução; transcrição e alinhamento
utilizam o cache `modelos` do projeto. O modelo de transcrição é adicional ao
alinhador utilizado pelo conversor. Alinhadores presentes no cache são carregados
primeiro sem consulta de rede. Para escolher outro modelo ou idioma:

```powershell
python gerar_srt.py "C:\Musicas\Minha musica" --modelo small --idioma pt --dispositivo cpu
```

Use `--idioma en` para inglês ou `--idioma bilingue` para as duas línguas.

Não há garantia de melhoria sobre uma legenda revisada. Vozes sobrepostas,
melismas, ditado incorreto e sustentações podem exigir correção. Compare a legenda
com o áudio antes de usar a consolidação/revisão e gerar MIDI.

Testes: `python -m unittest discover -s testes -v`. Os testes do módulo usam
respostas controladas do reconhecedor, sem baixar modelos. Precisão em canto real
deve ser avaliada comparando texto e tempos com referências revisadas.

Avaliação local em 17/10/2026: a gravação Desaguar reproduziu uma falha entre
57,320 s e 57,280 s. Os segmentos do próprio reconhecedor se sobrepunham em
40 ms; a última palavra do primeiro tinha score 0,258, e a primeira do segundo,
0,548. A correção conserva o início de 57,280 s do segundo bloco e reduz o fim
do primeiro para esse instante, com auditoria e sem eliminar texto.

A detecção antiga também encaminhava frases portuguesas ao alinhador inglês
com probabilidades baixas, como 0,052 e 0,070. A avaliação nova mantém separados
o idioma acústico e o do texto reconhecido. O teste usa os 63 segmentos reais
capturados pelo ASR original, repetindo a detecção no áudio e realinhando os
trechos cuja escolha de modelo mudou. Isso isola as mudanças do módulo sem
confundi-las com outra amostra estocástica da transcrição. Artefatos, diagnóstico
anterior e scripts de reprodução ficam em `saida/diagnostico_desaguar/`.

Resultado validado: 71 blocos, zero sobreposições e todo o texto reconhecido
preservado. Cinco segmentos com texto português passaram do alinhador inglês
para o português; a distribuição final foi de 48 segmentos pt e 15 en. Foram
auditados dois ajustes de 40 ms. Dezesseis segmentos continuam com indicação
de revisão de idioma. O SRT final do experimento está em
`saida/diagnostico_desaguar/validado/letra.srt`, acompanhado do relatório JSON.
A transcrição ainda contém erros de palavras e lacunas: a troca de alinhador
não corrige o texto do ASR e scores de modelos diferentes não medem melhoria
musical diretamente. A validação automática conferiu integridade textual,
publicação e ordem temporal, sem revisão auditiva humana.

Suíte após a correção: 154 testes executados, 153 aprovados e um ignorado por
indisponibilidade de Tk. Inclui regressões para sobreposições curtas, conflitos
fortes preservados, duração positiva das palavras, duas extremidades ajustadas,
precisão de milissegundos, probabilidades baixas e discordância de idioma.
