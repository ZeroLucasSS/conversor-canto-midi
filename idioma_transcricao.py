"""Evidência acústica e textual de idioma para transcrições pt/en.

O texto reconhecido não é uma prova da língua cantada (pode estar errado ou
traduzido). A escolha do alinhador precisa, contudo, ser compatível com esse
texto. Divergências são registradas, nunca tratadas como confirmação automática.
"""
import math

from idiomas_letra import idiomas_por_linha


def evidencia_textual(texto):
    linhas = idiomas_por_linha(texto)
    votos = {l: sum(x['votos_' + l] for x in linhas) for l in ('pt', 'en')}
    idioma = max(votos, key=votos.get)
    forte = votos[idioma] >= 2 and abs(votos['pt'] - votos['en']) >= 2
    return dict(votos=votos, idioma=idioma if forte else None,
                misto=min(votos.values()) >= 2)


def evidencia_acustica(probabilidades):
    probs = {l: float(p) for l, p in probabilidades
             if math.isfinite(float(p)) and 0 <= float(p) <= 1}
    if not any(l in probs for l in ('pt', 'en')):
        raise ValueError('O detector não retornou evidência de português ou inglês.')
    idioma = max(('pt', 'en'), key=lambda l: probs.get(l, 0.))
    outro = 'en' if idioma == 'pt' else 'pt'
    prob = probs.get(idioma, 0.)
    global_ = max(probs, key=probs.get)
    return dict(idioma=idioma, probabilidade=prob,
                probabilidades={l: probs.get(l, 0.) for l in ('pt', 'en')},
                melhor_global=global_, probabilidade_global=probs[global_],
                forte=prob >= .65 and prob - probs.get(outro, 0.) >= .20
                      and global_ == idioma)


def selecionar_idioma(texto, probabilidades, *, contexto=None):
    local = evidencia_acustica(probabilidades)
    textual = evidencia_textual(texto)
    ampla = evidencia_acustica(contexto) if contexto is not None else None
    # Contexto só desempata áudio fraco. Texto claro impede que um recorte
    # vizinho de outra língua escolha um alinhador incompatível com a frase.
    acustica = ampla if ampla and ampla['forte'] and not local['forte'] else local
    idioma = textual['idioma'] or acustica['idioma']
    divergencia = bool(textual['idioma'] and textual['idioma'] != local['idioma'])
    return dict(idioma=idioma, fonte='texto_reconhecido' if textual['idioma'] else
                ('audio_contextual' if acustica is ampla else 'audio_local'),
                audio_local=local, audio_contextual=ampla, texto=textual,
                divergencia_audio_texto=divergencia,
                revisao_recomendada=divergencia or not acustica['forte'] or textual['misto']
                    or bool(ampla and ampla['idioma'] != local['idioma']))


def identificar_idiomas(backend, audio, originais):
    """Conserva os tempos/textos do ASR e audita a escolha de alinhador.

    Não consulta letra.txt nem usa vocabulário de músicas específicas.
    Recortes curtos/fracos/divergentes ganham contexto acústico de até 6 s.
    """
    duracao = len(audio) / 16000
    saida = []
    for original in originais:
        a, b = original['start'], original['end']
        if not (math.isfinite(a) and math.isfinite(b) and 0 <= a < b <= duracao + .005):
            raise ValueError(f'Reconhecimento com intervalo inválido: {a!r}–{b!r} s.')
        recorte = audio[int(a * 16000):min(len(audio), int(b * 16000))]
        _, _, probs = backend.detect_language(audio=recorte)
        inicial = selecionar_idioma(original['text'], probs)
        contexto, janela = None, None
        if b-a < 2.5 or not inicial['audio_local']['forte'] or inicial['divergencia_audio_texto']:
            # Não reduzimos recortes já longos a seus primeiros segundos.
            centro = (a+b)/2
            x, y = max(0., min(a, centro-3.)), min(duracao, max(b, centro+3.))
            if y-x > b-a + .01:
                _, _, contexto = backend.detect_language(audio=audio[int(x*16000):int(y*16000)])
                janela = [x,y]
        decisao = selecionar_idioma(original['text'], probs, contexto=contexto)
        decisao['janela_contexto'] = janela
        lingua = decisao['idioma']
        saida.append(dict(original, idioma=lingua,
                          confianca_idioma=decisao['audio_local']['probabilidades'][lingua],
                          analise_idioma=decisao))
        print(f'Trecho bilíngue: {a:.1f}s · alinhador {lingua}'
              + (' · revisar idioma' if decisao['revisao_recomendada'] else ''), flush=True)
    return saida
