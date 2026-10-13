"""Transcrição e alinhamento independentes: voz -> letra.srt + diagnóstico."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import re
import tempfile
from difflib import SequenceMatcher
from pathlib import Path


def verificar_destinos(pasta):
    reservados = {"letra.srt", "letra_geracao.json"}
    for p in Path(pasta).iterdir():
        if p.name.casefold() in reservados:
            raise FileExistsError(f"{p.name} já existe. Nenhum arquivo será sobrescrito.")


def validar_blocos(blocos, duracao):
    if not math.isfinite(duracao) or duracao <= 0 or not blocos:
        raise ValueError("Nenhum trecho de voz com tempo utilizável foi reconhecido.")
    anterior = 0
    for b in blocos:
        a, z = b['inicio'], b['fim']
        if (not all(math.isfinite(x) for x in (a, z)) or
                not 0 <= a < z <= duracao or a < anterior or not b['texto'].strip()):
            raise ValueError("A transcrição contém tempos inválidos ou sobrepostos; revise o áudio.")
        if round(z * 1000) <= round(a * 1000):
            raise ValueError("Trecho menor que a precisão do SRT.")
        anterior = z


def agrupar_segmentos(segmentos, duracao, *, pausa=.65, max_duracao=6., max_caracteres=72):
    """Agrupa palavras; sem alinhamento completo, conserva o segmento e seu texto.

    Não inventa tempos por palavra e não descarta palavras sem timestamp.
    """
    blocos, avisos = [], []
    for indice, segmento in enumerate(segmentos, 1):
        texto = ' '.join(str(segmento.get('text', '')).split())
        if not texto:
            continue
        palavras = segmento.get('words') or []
        grupo = []
        locais = []
        def fechar():
            if grupo:
                locais.append(dict(inicio=float(grupo[0]['start']), fim=float(grupo[-1]['end']),
                                   texto=' '.join(str(p['word']).strip() for p in grupo)))
                grupo.clear()
        try:
            if not palavras:
                raise ValueError('sem palavras alinhadas')
            normalizar = lambda s: re.findall(r"\w+", s.casefold())
            if normalizar(' '.join(str(p.get('word', '')) for p in palavras)) != normalizar(texto):
                raise ValueError('cobertura textual incompleta')
            fim_anterior = -1.
            for p in palavras:
                a, z = float(p['start']), float(p['end'])
                if not (math.isfinite(a) and math.isfinite(z) and 0 <= a < z <= duracao and a >= fim_anterior):
                    raise ValueError('tempos de palavras inválidos')
                if grupo and (a - float(grupo[-1]['end']) >= pausa or
                              z - float(grupo[0]['start']) > max_duracao or
                              len(' '.join(str(x['word']) for x in grupo + [p])) > max_caracteres):
                    fechar()
                grupo.append(p)
                fim_anterior = z
            fechar()
            validar_blocos(locais, duracao)
        except (KeyError, TypeError, ValueError):
            locais = [dict(inicio=float(segmento['start']), fim=float(segmento['end']), texto=texto)]
            avisos.append(f"Segmento {indice}: tempos do reconhecimento usados; alinhamento incompleto. Revisar.")
        for p in palavras:
            score = p.get('score')
            if isinstance(score, (float, int)) and score < .30:
                avisos.append(f"Segmento {indice}: alinhamento fraco em {p.get('word', '')!r}.")
        blocos.extend(locais)
    validar_blocos(blocos, duracao)
    return blocos, avisos


def texto_srt(blocos):
    def tempo(segundos):
        total = round(segundos * 1000)
        segundos, ms = divmod(total, 1000)
        minutos, segundos = divmod(segundos, 60)
        horas, minutos = divmod(minutos, 60)
        return f'{horas:02d}:{minutos:02d}:{segundos:02d},{ms:03d}'
    return '\n'.join(f"{i}\n{tempo(b['inicio'])} --> {tempo(b['fim'])}\n{b['texto']}\n"
                     for i, b in enumerate(blocos, 1))


def comparar_letra(texto, referencia):
    tokens = lambda s: re.findall(r"\w+", s.casefold())
    reconhecidas, esperadas = tokens(texto), tokens(referencia)
    comparador = SequenceMatcher(None, esperadas, reconhecidas, autojunk=False)
    return dict(similaridade_textual=comparador.ratio(), divergencias=[
        dict(tipo=tipo, referencia=' '.join(esperadas[a:b]), transcricao=' '.join(reconhecidas[c:d]))
        for tipo, a, b, c, d in comparador.get_opcodes() if tipo != 'equal'])


def publicar(srt, relatorio, pasta):
    """Links atômicos sem substituição; publica SRT completo por último."""
    pasta = Path(pasta)
    verificar_destinos(pasta)
    criados = []
    with tempfile.TemporaryDirectory(prefix='.geracao_srt_', dir=pasta) as temp:
        temp = Path(temp)
        (temp / 'letra.srt').write_text(srt, encoding='utf-8')
        (temp / 'letra_geracao.json').write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        try:
            for nome in ('letra_geracao.json', 'letra.srt'):
                os.link(temp / nome, pasta / nome)
                criados.append(pasta / nome)
        except BaseException:
            for p in criados:
                p.unlink()
            raise
    return pasta / 'letra.srt'


def reconhecer(voz, *, modelo='small', idioma='pt', dispositivo='auto', pasta_modelos=None):
    if idioma not in {'pt', 'en', 'bilingue'}:
        raise ValueError('Escolha pt, en ou bilingue para gerar o SRT.')
    if idioma != 'en' and modelo.endswith('.en'):
        raise ValueError('Português e bilíngue exigem um modelo multilíngue, como small.')
    import whisperx
    import torch
    from alinhamento import resolver_dispositivo

    device = resolver_dispositivo(dispositivo)
    pasta_modelos = Path(pasta_modelos or Path(__file__).resolve().parent / 'modelos')
    pasta_modelos.mkdir(parents=True, exist_ok=True)
    compute = 'int8' if device == 'cpu' else 'float16'
    print('1 de 3 · Carregando áudio e modelo de transcrição', flush=True)
    audio = whisperx.load_audio(str(voz))
    duracao = len(audio) / 16000
    if not duracao:
        raise ValueError('O áudio está vazio.')
    print('Na primeira execução, os modelos ausentes serão baixados para o cache.', flush=True)
    idioma_asr = None if idioma == 'bilingue' else idioma
    modelo_asr = whisperx.load_model(modelo, device, compute_type=compute, language=idioma_asr,
                                    vad_method='silero', download_root=str(pasta_modelos / 'transcricao'))
    print('2 de 3 · Reconhecendo a letra cantada', flush=True)
    if idioma == 'bilingue':
        # O wrapper WhisperX instalado detecta apenas um idioma por chamada.
        # Seu backend faster-whisper suporta detecção a cada trecho.
        trechos, _ = modelo_asr.model.transcribe(
            audio, language=None, task='transcribe', multilingual=True, vad_filter=True,
            chunk_length=10, condition_on_previous_text=False)
        originais = []
        for trecho in trechos:
            recorte = audio[max(0, int(trecho.start * 16000)):int(trecho.end * 16000)]
            _, _, probabilidades = modelo_asr.model.detect_language(audio=recorte)
            candidatas = [(lingua, prob) for lingua, prob in probabilidades if lingua in {'pt', 'en'}]
            if not candidatas:
                raise ValueError('Não foi possível identificar português ou inglês no trecho.')
            lingua, probabilidade = max(candidatas, key=lambda item: item[1])
            originais.append(dict(start=trecho.start, end=trecho.end, text=trecho.text,
                                  idioma=lingua, confianca_idioma=float(probabilidade)))
            print(f'Trecho bilíngue reconhecido: {trecho.start:.1f}s · {lingua}', flush=True)
        resultado = {'segments': originais}
    else:
        resultado = modelo_asr.transcribe(audio, batch_size=1 if device == 'cpu' else 4,
                                          language=idioma, task='transcribe', print_progress=True)
    del modelo_asr
    gc.collect()
    if device == 'cuda':
        torch.cuda.empty_cache()
    if not resultado.get('segments'):
        raise ValueError('Nenhuma voz foi reconhecida. Nenhum SRT foi publicado.')
    print('3 de 3 · Alinhando palavras ao áudio', flush=True)
    alinhadores = {}
    segmentos = []
    # align pode dividir um segmento em várias frases. Mantemos a associação
    # com o reconhecimento original, inclusive quando alguma palavra não alinha.
    for i, original in enumerate(resultado['segments'], 1):
        lingua = original.get('idioma', idioma)
        if lingua not in alinhadores:
            alinhadores[lingua] = whisperx.load_align_model(language_code=lingua, device=device,
                                                           model_dir=str(pasta_modelos / 'alinhamento'))
        alinhador, meta = alinhadores[lingua]
        alinhado = whisperx.align([original], alinhador, meta, audio, device,
                                 interpolate_method='ignore', return_char_alignments=False)
        palavras = [p for s in alinhado.get('segments', []) for p in (s.get('words') or [])]
        segmentos.append({**original, 'idioma': lingua, 'words': palavras})
        print(f'Alinhamento: {i}/{len(resultado["segments"])} segmentos', flush=True)
    return segmentos, duracao, dict(modelo=modelo, idioma=idioma, dispositivo=device,
                                   compute_type=compute, vad='silero')


def gerar(pasta, *, saida=None, modelo='small', idioma='pt', dispositivo='auto'):
    from conversao_gui import validar_pasta
    pasta = Path(pasta).resolve()
    voz = validar_pasta(pasta, requisitos=('voz',))['voz']
    verificar_destinos(pasta)
    destino = Path(saida).resolve() if saida else pasta
    destino.mkdir(parents=True, exist_ok=True)
    verificar_destinos(destino)
    cache = Path(__file__).resolve().parent / 'modelos'
    segmentos, duracao, configuracao = reconhecer(voz, modelo=modelo, idioma=idioma,
                                                  dispositivo=dispositivo, pasta_modelos=cache)
    blocos, avisos = agrupar_segmentos(segmentos, duracao)
    if idioma == 'bilingue':
        avisos.append('Modo bilíngue: idioma estimado por trecho; revise trocas de língua dentro da mesma frase.')
    relatorio = dict(versao=1, arquivo_voz=str(voz), sha256_voz=hashlib.sha256(voz.read_bytes()).hexdigest(),
                     duracao_audio=duracao, configuracao=configuracao, segmentos=segmentos,
                     blocos=blocos, avisos=avisos, revisao_recomendada=True)
    referencias = [p for p in pasta.iterdir() if p.name.casefold() == 'letra.txt' and p.is_file()]
    if len(referencias) == 1:
        try:
            relatorio['comparacao_letra'] = comparar_letra(' '.join(b['texto'] for b in blocos),
                                                          referencias[0].read_text(encoding='utf-8-sig'))
        except UnicodeError:
            avisos.append('Não foi possível comparar letra.txt: use codificação UTF-8.')
    caminho = publicar(texto_srt(blocos), relatorio, destino)
    print(f'SRT gerado: {caminho}\nRevise a letra e os tempos antes de converter.', flush=True)
    return caminho


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pasta', type=Path)
    parser.add_argument('--saida', type=Path, help='Pasta de trabalho opcional; não sobrescreve arquivos.')
    parser.add_argument('--modelo', default='small')
    parser.add_argument('--idioma', choices=('pt', 'en', 'bilingue'), default='pt')
    parser.add_argument('--dispositivo', choices=('auto', 'cpu', 'cuda'), default='auto')
    args = parser.parse_args()
    gerar(args.pasta, saida=args.saida, modelo=args.modelo, idioma=args.idioma, dispositivo=args.dispositivo)


if __name__ == '__main__':
    main()
