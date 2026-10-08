# Revisão manual da letra

Depois da consolidação, **Gerar MIDI** abre a revisão quando há ocorrências
pendentes. A conversão fica pausada antes do alinhamento silábico. **Revisar
letra** abre a mesma janela a qualquer momento, depois de existir uma consolidação.

Para usar separadamente:

```powershell
python -m pip install -r requirements_revisao.txt
python revisao_interface.py "audios/Livre Pra Voar"
```

## Decisões por ocorrência

A lista à esquerda mostra as frases pendentes do TXT, os avisos do SRT e todos
os trechos disponíveis para edição. Em “Livre Pra Voar”, as 74 palavras sem
associação se tornam 19 ocorrências do TXT. Muitas já podem estar na legenda:
as sugestões textuais servem para localizar candidatos, não para decidir qual
repetição foi cantada. Confira a posição e os trechos vizinhos na lista da legenda.

- **Já está na legenda**: selecione um ou mais trechos (Ctrl/Shift). Registra
  a associação, sem duplicar texto nem alterar tempos. Se outra ocorrência já
  usa o mesmo trecho, a janela pede para conferir a repetição.
- **Corrigir / substituir seleção**: duplo clique no trecho para carregar seus
  tempos e texto. Edite e aplique. Se o intervalo mudar, a janela pede confirmação.
  Selecionar vários trechos permite substituí-los por uma frase única.
- **Inserir trecho**: informe texto e intervalo. Sobreposição com a legenda é
  rejeitada e identifica o conflito; não se deslocam automaticamente os vizinhos.
- **Descartar pendência**: ignora aquela consulta do TXT; não apaga nenhum SRT.
- **Revisar depois**: conserva a pendência e o rascunho.
- **Remover trechos selecionados**: exclusão explícita da versão validada,
  separada do descarte e com confirmação.

**Desfazer última decisão** restaura texto, tempos e associações da operação
anterior. Se um trecho associado for removido/substituído, sua associação antiga
volta a ser pendente.

## Ouvir e marcar

O player usa a voz informada ao consolidador, decodificada pelo FFmpeg. Exibe
minutos, segundos e milissegundos; permite pausa, saltos de três segundos, clique
na forma de onda para buscar e arraste para selecionar. Há zoom do intervalo,
repetição e botões para marcar início/fim na posição atual. O cursor usa o relógio
de saída do dispositivo, com compensação do buffer, não o tempo de abertura da janela.

Os campos aceitam segundos (`102.9`), `mm:ss,mmm` ou `hh:mm:ss,mmm`.
**Sugerir tempos neste intervalo** executa o WhisperX em um processo separado,
cancelável. Os resultados aparecem para conferência; falhas e palavras sem tempo
permanecem visíveis. Pontuação do modelo não representa aprovação humana.

Em **Tempos por palavra**, use duplo clique nas células para incluir/excluir,
editar início/fim ou confirmar. É possível selecionar várias palavras para
ouvi-las com contexto e confirmar seus tempos. **Marcar grupo no intervalo**
distribui tempos aproximados para facilitar a edição: esses tempos precisam ser
conferidos, e não são confirmação acústica. Alterar o texto exige recriar a tabela
quando já houver tempos confirmados.

Para resolver um conflito dividindo um trecho: carregue-o, selecione a primeira
palavra da segunda parte, posicione o áudio no corte e escolha **Dividir trecho
aqui**. As duas partes continuam editáveis. Nenhuma parte é removida implicitamente.

## Arquivos e continuidade

- `letra_consolidada.srt` e seu JSON continuam sendo a saída automática.
- `revisao_letra.json` guarda decisões, rascunhos, histórico, hashes das fontes,
  palavras confirmadas e resumo das pendências. Cada decisão válida é salva.
- **Publicar e continuar** gera `letra_validada.srt` e `letra_validada.json`.
  O segundo é o manifesto consumido pelo alinhamento; não o remova ao usar tempos
  por palavra. Esses arquivos ficam na pasta da música, fora dos temporários.
- **Salvar e continuar depois** encerra a conversão atual. Ao retomar, as decisões
  reaparecem. Fechar a janela tem o mesmo efeito.
- É permitido continuar com pendências. Rascunhos ainda não aplicados não entram
  no SRT. Uma edição inválida não impede usar os trechos válidos existentes.

Se TXT, SRT, voz ou consolidação mudarem, a revisão antiga é arquivada no JSON.
A janela inicia sobre as fontes atuais, sem reaplicar decisões antigas. Consulte
**Histórico / versões anteriores** e reaplique explicitamente o que continuar
correto. Se as fontes mudarem durante a edição, a publicação pede reabertura.

O manifesto vincula os tempos ao hash do SRT publicado e ao áudio. Uma gravação
interrompida entre os arquivos é detectada na leitura, em vez de misturar versões.

## Integração dos tempos

Palavras confirmadas delimitam as regiões onde as demais palavras podem ser
alinhadas. O fallback e a recuperação de sustentação não sobrescrevem essas
âncoras. A separação silábica continua estimando fronteiras **dentro** da palavra;
os ajustes MIDI conservam os limites externos confirmados e não prolongam sua
cauda. A origem humana é registrada sem inventar score do modelo. A escolha de
pitch continua sendo responsabilidade do conversor, não da revisão textual.

Uso explícito pela linha de comando:

```powershell
python preparar_letra.py "audios/Livre Pra Voar" --srt "audios/Livre Pra Voar/letra_validada.srt" --revisao "audios/Livre Pra Voar/letra_validada.json"
```

Na interface principal, esses argumentos são transmitidos automaticamente. O
controlador também reaplica uma revisão salva compatível quando usado sem callback
gráfico; se as fontes mudarem, exige reconciliação pela janela.
`preparar_letra.py` também reaplica uma revisão compatível no fluxo padrão e
carrega o manifesto adjacente ao receber `--srt letra_validada.srt`.

## Organização e verificação

`revisao_letra.py` contém validação e persistência, sem widgets. `audio_revisao.py`
contém o player. `revisao_interface.py` contém a janela, e `alinhar_revisao.py` é
o worker acústico. A função `propor_tempos(alinhador, texto, inicio, fim)` aceita
outro motor com a interface `AlinhadorLocal` existente no consolidador.

Os testes cobrem associação de repetição, descarte sem exclusão, conflitos,
divisão, retomada, mudança de fontes, integridade do manifesto, relógio de áudio,
integração com a conversão e proteção dos tempos até os ajustes MIDI:

```powershell
python -m unittest discover -s testes -q
```

O teste de widgets usa janela oculta e é pulado se Tk/Tcl estiver indisponível.
Os testes de áudio usam um dispositivo simulado para não tocar som durante a
suíte. A confirmação da pronúncia e dos tempos é uma decisão do usuário ao ouvir.
