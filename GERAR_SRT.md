O botão **Gerar SRT**, antes de **Gerar MIDI**, transcreve o arquivo de voz e
alinha as palavras com WhisperX. É independente da conversão: exige apenas um
arquivo `voz` em formato suportado. Não exige instrumental ou letra.txt, não
depende do modo silábico/palavras e não inicia a conversão automaticamente.

Ao clicar, uma janela pede o idioma: **Português** (seleção inicial), **Inglês**
ou **Bilíngue (português e inglês)**. Confirmar inicia a operação; Cancelar, Esc
ou fechar a janela não inicia nenhum processamento.

Português e inglês fixam o idioma da transcrição e do alinhador. Bilíngue usa a
detecção por trecho do backend faster-whisper fornecido pelo WhisperX, em modo
de transcrição, sem tradução. Para alinhar, estima o idioma predominante de cada
trecho entre português e inglês e carrega os modelos correspondentes. A escolha
e os idiomas estimados são registrados no relatório. Mudanças de língua dentro
da mesma frase e trechos curtos podem exigir revisão. Esta escolha se aplica à
geração do SRT; não muda a configuração dos demais módulos do conversor.

A saída é `letra.srt`, na pasta selecionada, com frases agrupadas por pausas de
650 ms, duração de até 6 s e até 72 caracteres quando os limites das palavras
permitem. Uma palavra indivisível pode exceder esses limites. Palavras sem tempo
ou cobertura incompleta fazem o segmento conservar o texto e os tempos originais
do reconhecimento, com aviso para revisão. Sobreposições e tempos inválidos que
persistam impedem a publicação.

`letra_geracao.json` registra a identidade do áudio, configuração, segmentos,
palavras alinhadas, blocos publicados e avisos. Se houver letra.txt em UTF-8,
registra também divergências textuais, sem alterar a letra de referência.
Scores de alinhamento e similaridade textual não garantem precisão musical.

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
alinhador utilizado pelo conversor. Para escolher outro modelo ou idioma:

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
