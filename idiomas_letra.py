"""Seleção textual pt/en por linha, com contexto para linhas pouco informativas.

Não é um detector universal: as opções explícitas da CLI sempre prevalecem.
Palavras funcionais evitam depender do vocabulário de uma canção particular.
"""
import re

_PT = set('o a os as um uma uns umas de da do das dos em no na nos nas '
          'eu tu você vocês ele ela nós vós eles elas meu minha meus minhas seu sua seus suas '
          'nosso nossa nossos nossas vosso vossa vossos vossas isto isso aquilo '
          'me te se si consigo lhe lhes vos aqui ali lá cá ainda já só '
          'que não sim se mas porque para com sem por ao aos é são foi ser '
          'estou estás está estamos estão estava estavam tenho tens tem temos têm tinha tinham '
          'sou és somos sois fui fomos eram vou vai vamos vão muito mais também'.split())
_EN = set('the a an of to in on at from for with without and or but if as no so '
          'i you he she it we they my your his her our their me him us them '
          'is are was were be been being am do does did not have has had '
          'will would shall should can could may might must this that these those'.split())


def _votos(texto):
    palavras = re.findall(r"[^\W_]+", texto.casefold())
    return (sum(p in _PT - _EN or bool(re.search('[ãõç]', p)) for p in palavras),
            sum(p in _EN - _PT for p in palavras))


def idioma_predominante(texto):
    pt, en = _votos(texto)
    return 'en' if en > pt else 'pt'


def idiomas_por_linha(texto, contexto=None):
    """Empates herdam o contexto; a confiança/limitação fica no diagnóstico."""
    contexto = contexto or idioma_predominante(texto)
    resultado = []
    for linha in texto.splitlines():
        p, e = _votos(linha)
        idioma = ('en' if e > p else 'pt') if p != e else contexto
        resultado.append(dict(idioma=idioma, votos_pt=p, votos_en=e,
                              herdado=p == e))
        if p != e:
            contexto = idioma
    return resultado
