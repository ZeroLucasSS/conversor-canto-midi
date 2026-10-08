"""Consolidação de TXT + SRT + voz, também executável isoladamente.

Uso (no Python que contém WhisperX):
    python -m pip install rapidfuzz
    python consolidar_letra.py audios
    python consolidar_letra.py audios --somente-comparar
    python consolidar_letra.py audios --saida saida/experimento/letra_consolidada.srt

O SRT determina a estrutura e as ocorrências da gravação. O TXT fornece a
grafia e frases de referência, reutilizáveis em repetições; não use rótulos
como [Refrão]. Linhas orientam a divisão dos novos blocos, não seus tempos.
Sem --atualizar, saídas não sobrescrevem arquivos existentes. O fluxo integrado
regenera letra_consolidada.srt e seu JSON, preservando TXT e SRT originais.
Pendências não impedem o SRT:
tempos disponíveis são publicados com avisos no terminal e ao final do JSON.
Palavras sem tempos utilizáveis são omitidas e identificadas para revisão.
Publicação retorna 0, mesmo com avisos; erros de entrada/ambiente retornam 1.

Dependências: RapidFuzz; WhisperX e seus modelos apenas na etapa acústica.
Scores são heurísticos, não probabilidades de acerto. Mesmo um resultado sem
pendências exige audição para avaliar canto, sustentação e qualidade musical.
Para testar outro motor, implemente AlinhadorLocal e passe-o a consolidar().
"""
from __future__ import annotations

import argparse
from array import array
from dataclasses import asdict, dataclass
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Callable, Protocol
import unicodedata


PALAVRA = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)
TEMPO = re.compile(r"^(\d+):(\d{2}):(\d{2})[,.](\d{3})$")


def chave(texto: str) -> str:
    """Somente para comparação; a saída mantém a grafia do TXT."""
    return "".join(c for c in unicodedata.normalize("NFD", texto.casefold())
                   if c.isalnum())


@dataclass(frozen=True)
class Token:
    texto: str
    unidade: int  # linha TXT ou posição do bloco SRT, começando em zero
    inicio: int
    fim: int


@dataclass(frozen=True)
class Bloco:
    indice: int
    inicio: float
    fim: float
    texto: str


@dataclass(frozen=True)
class PalavraTemporal:
    texto: str
    inicio: float | None
    fim: float | None
    score: float | None


class AlinhadorLocal(Protocol):
    """Tempos absolutos no áudio; uma resposta por palavra, sem interpolação.

    O motor pode devolver palavras sem tempos/score; elas serão rejeitadas.
    A ordem e o texto retornados são conferidos antes de qualquer associação.
    """
    duracao_audio: float
    nome: str

    def alinhar(self, texto: str, inicio: float, fim: float) -> list[PalavraTemporal]: ...


class AlinhadorWhisperX:
    nome = "whisperx"

    def __init__(self, voz: Path, idioma="pt", dispositivo="auto",
                 modelo=None, pasta_modelos=None):
        import torch
        import whisperx

        self.wx = whisperx
        self.dispositivo = ("cuda" if torch.cuda.is_available() else "cpu") if dispositivo == "auto" else dispositivo
        if self.dispositivo == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA solicitada, mas indisponível.")
        self.audio = whisperx.load_audio(str(voz))
        self.duracao_audio = len(self.audio) / 16000
        kwargs = dict(language_code=idioma, device=self.dispositivo, model_name=modelo)
        if pasta_modelos:
            kwargs["model_dir"] = str(pasta_modelos)
        # Mesmo cache do projeto; tenta primeiro sem acesso à rede.
        try:
            self.modelo, self.meta = whisperx.load_align_model(**kwargs, model_cache_only=True)
        except (TypeError, OSError, ValueError):
            self.modelo, self.meta = whisperx.load_align_model(**kwargs)

    def alinhar(self, texto, inicio, fim):
        resultado = self.wx.align(
            [{"text": texto, "start": inicio, "end": fim}], self.modelo,
            self.meta, self.audio, self.dispositivo, interpolate_method="ignore",
            return_char_alignments=True, print_progress=False,
        )
        palavras = resultado.get("word_segments")
        if palavras is None:
            palavras = [p for s in resultado.get("segments", []) for p in s.get("words", [])]
        return [PalavraTemporal(p.get("word", ""), p.get("start"),
                                p.get("end"), p.get("score")) for p in palavras]


def _segundos(texto):
    m = TEMPO.fullmatch(texto.strip())
    if not m:
        raise ValueError(f"Timestamp inválido: {texto!r}")
    h, minuto, segundo, ms = map(int, m.groups())
    if minuto >= 60 or segundo >= 60:
        raise ValueError(f"Timestamp inválido: {texto!r}")
    return h * 3600 + minuto * 60 + segundo + ms / 1000


def ler_srt(caminho: Path) -> list[Bloco]:
    conteudo = caminho.read_text(encoding="utf-8-sig").strip()
    blocos, indices = [], set()
    for trecho in re.split(r"\n\s*\n", conteudo):
        linhas = trecho.splitlines()
        if len(linhas) < 3 or not linhas[0].strip().isdigit() or "-->" not in linhas[1]:
            raise ValueError("SRT exige índice, timestamps e texto em cada bloco.")
        indice = int(linhas[0].strip())
        tempos = linhas[1].split("-->")
        if len(tempos) != 2:
            raise ValueError(f"Bloco {indice}: timestamps inválidos.")
        tempo_final = tempos[1].strip().split()
        if not tempo_final:
            raise ValueError(f"Bloco {indice}: timestamp final ausente.")
        inicio, fim = _segundos(tempos[0]), _segundos(tempo_final[0])
        if indice in indices or fim <= inicio:
            raise ValueError(f"Bloco {indice}: índice repetido ou duração inválida.")
        texto = html.unescape(" ".join(linhas[2:]))
        texto = re.sub(r"<[^>]*>|\{\\[^}]*\}", "", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        blocos.append(Bloco(indice, inicio, fim, texto))
        indices.add(indice)
    blocos.sort(key=lambda b: b.inicio)
    if any(b.inicio < a.fim for a, b in zip(blocos, blocos[1:])):
        raise ValueError("SRT contém blocos sobrepostos; revise antes de consolidar.")
    return blocos


def ler_txt(caminho: Path) -> str:
    texto = unicodedata.normalize("NFC", caminho.read_text(encoding="utf-8-sig")).strip()
    for linha in texto.splitlines():
        if re.fullmatch(r"\s*\[.*\]\s*", linha) or re.search(r"\b\d+\s*[x×]\s*$", linha, re.I):
            raise ValueError("TXT deve conter somente a letra cantada e repetições explícitas, sem [rótulos] ou '2x'.")
    if not PALAVRA.search(texto):
        raise ValueError("TXT sem palavras.")
    return texto


def tokenizar(texto: str) -> list[Token]:
    tokens, offset = [], 0
    for linha, trecho in enumerate(texto.splitlines(keepends=True)):
        tokens.extend(Token(m.group(), linha, offset + m.start(), offset + m.end())
                      for m in PALAVRA.finditer(trecho))
        offset += len(trecho)
    return tokens


def trecho_txt(texto, tokens, a, b):
    """Preserva pontuação até a próxima palavra, sem carregar linhas seguintes."""
    fim = tokens[b].inicio if b < len(tokens) else len(texto)
    inicio = tokens[a].inicio
    if a == 0:
        inicio = 0
    return " ".join(texto[inicio:fim].split()).strip()


def comparar(tokens_srt: list[Token], tokens_txt: list[Token]) -> dict:
    """Alinhamento global monotônico com custo de substituição do RapidFuzz.

    A matriz de caminhos registra TODOS os empates ótimos. Assim, uma mesma
    ocorrência de refrão não é escolhida silenciosamente em caso de empate.
    Não usa token_set_ratio, que apagaria repetições.
    """
    from rapidfuzz.fuzz import ratio

    fonte, alvo = [chave(t.texto) for t in tokens_srt], [chave(t.texto) for t in tokens_txt]
    n, m = len(fonte), len(alvo)
    if not n or not m:
        raise ValueError("As duas fontes precisam conter palavras.")
    if (n + 1) * (m + 1) > 4_000_000:
        raise ValueError("Letra muito grande para a comparação global (limite de 4 milhões de células).")
    caminhos = [bytearray(m + 1) for _ in range(n + 1)]
    caminhos[0][1:] = bytes([4]) * m
    anterior = array("d", range(m + 1))
    for i in range(1, n + 1):
        atual = array("d", [float(i)] + [0.0] * m)
        caminhos[i][0] = 2
        for j in range(1, m + 1):
            custo = 0.0 if fonte[i - 1] == alvo[j - 1] else 1.0 + (1.0 - ratio(fonte[i - 1], alvo[j - 1]) / 100) * 0.5
            valores = (anterior[j - 1] + custo, anterior[j] + 1, atual[j - 1] + 1)
            minimo = min(valores)
            atual[j] = minimo
            caminhos[i][j] = sum(bit for bit, v in zip((1, 2, 4), valores) if abs(v - minimo) < 1e-8)
        anterior = atual
    # Percorre o grafo de caminhos ótimos, sem enumerar todas as combinações.
    possibilidades = [set() for _ in alvo]
    visitados, pilha = set(), [(n, m)]
    while pilha:
        i, j = pilha.pop()
        if (i, j) in visitados:
            continue
        visitados.add((i, j))
        bits = caminhos[i][j]
        if bits & 1:
            possibilidades[j - 1].add(i - 1)
            pilha.append((i - 1, j - 1))
        if bits & 2:
            pilha.append((i - 1, j))
        if bits & 4:
            possibilidades[j - 1].add(None)
            pilha.append((i, j - 1))
    operacoes, i, j = [], n, m
    while i or j:
        bits = caminhos[i][j]
        if bits & 1:
            tipo = "igual" if tokens_srt[i - 1].texto == tokens_txt[j - 1].texto else (
                "grafia" if fonte[i - 1] == alvo[j - 1] else "substituicao")
            operacoes.append({"tipo": tipo, "srt": i - 1, "txt": j - 1})
            i, j = i - 1, j - 1
        elif bits & 2:
            operacoes.append({"tipo": "somente_srt", "srt": i - 1, "txt": None})
            i -= 1
        else:
            operacoes.append({"tipo": "ausente_srt", "srt": None, "txt": j - 1})
            j -= 1
    operacoes.reverse()
    ambiguos = [i for i, ps in enumerate(possibilidades) if len(ps) > 1]
    return {"operacoes": operacoes, "txt_ambiguos": ambiguos,
            "custo": anterior[m], "indices_tokens_base_zero": True}


def preparar_comparacao(blocos, texto):
    ref = tokenizar(texto)
    fonte = [Token(m.group(), i, m.start(), m.end())
             for i, b in enumerate(blocos) for m in PALAVRA.finditer(b.texto)]
    comparacao = comparar(fonte, ref)
    for op in comparacao["operacoes"]:
        op["texto_srt"] = fonte[op["srt"]].texto if op["srt"] is not None else None
        op["texto_txt"] = ref[op["txt"]].texto if op["txt"] is not None else None
        op["bloco_srt"] = blocos[fonte[op["srt"]].unidade].indice if op["srt"] is not None else None
    # Uma troca pode ter quantidades diferentes de palavras (ex.: 'diz antes'
    # por 'distantes'). Só exclusões SEM texto substituto exigem revisão extra.
    grupos, grupo = [], []
    for op in comparacao["operacoes"] + [{"tipo": "igual"}]:
        if op["tipo"] in ("igual", "grafia"):
            if grupo:
                s = [o for o in grupo if o["srt"] is not None]
                t = [o for o in grupo if o["txt"] is not None]
                grupos.append({"tipo": "substituicao" if s and t else (
                    "ausente_srt" if t else "somente_srt"),
                    "texto_srt": " ".join(o["texto_srt"] for o in s),
                    "texto_txt": " ".join(o["texto_txt"] for o in t),
                    "tokens_srt": [o["srt"] for o in s],
                    "tokens_txt": [o["txt"] for o in t]})
                grupo = []
        else:
            grupo.append(op)
    comparacao["divergencias"] = grupos
    return fonte, ref, comparacao


def _ancoras(blocos, fonte, ref, comparacao):
    mapa = {op["srt"]: op["txt"] for op in comparacao["operacoes"]
            if op["tipo"] in ("igual", "grafia")}
    ambiguos = set(comparacao["txt_ambiguos"])
    ancoras = []
    for ib, bloco in enumerate(blocos):
        ids = [i for i, t in enumerate(fonte) if t.unidade == ib]
        alvos = [mapa.get(i) for i in ids]
        if (alvos and all(j is not None and j not in ambiguos for j in alvos)
                and alvos == list(range(alvos[0], alvos[0] + len(alvos)))):
            ancoras.append({"a": alvos[0], "b": alvos[-1] + 1, "bloco": ib})
    return ancoras


def _numero(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def dividir_regioes(regioes, ancoras, blocos, alvo_segundos=18.0):
    """Divide cadeias longas em âncoras textuais, com contexto compartilhado.

    a/b incluem contexto; alvo_a/alvo_b delimitam a propriedade dos tokens.
    O tempo do SRT define somente a busca, nunca um tempo interpolado de palavra.
    """
    resultado = []
    for r in regioes:
        a, b = r["a"], r["b"]
        internas = [x for x in ancoras if a <= x["a"] and x["b"] <= b]
        inicio = a
        while True:
            restantes = [x for x in internas if x["a"] >= inicio]
            if len(restantes) < 2:
                break
            t0 = blocos[restantes[0]["bloco"]].inicio
            if blocos[restantes[-1]["bloco"]].fim - t0 <= alvo_segundos:
                break
            cortes = [x for x in restantes[1:-1]
                      if blocos[x["bloco"]].fim - t0 <= alvo_segundos]
            if not cortes:
                cortes = restantes[1:2]
            corte = cortes[-1]
            resultado.append({"a": inicio, "b": corte["b"],
                              "alvo_a": inicio, "alvo_b": corte["a"]})
            inicio = corte["a"]
        resultado.append({"a": inicio, "b": b, "alvo_a": inicio, "alvo_b": b})
    return resultado


def referencias_busca(fonte, comparacao):
    """Correspondências aproximadas só delimitam buscas, não certificam tempos."""
    por_bloco = {}
    for op in comparacao["operacoes"]:
        if op["srt"] is not None and op["txt"] is not None:
            por_bloco.setdefault(fonte[op["srt"]].unidade, []).append(op["txt"])
    return [{"a": min(ids), "b": max(ids) + 1, "bloco": ib}
            for ib, ids in por_bloco.items()]


def escolher_tempos(opcoes, inicio, fim):
    """Busca limitada a 64 caminhos: cobertura, depois score, sem interpolação.

    Cada nó guarda o predecessor; tempos vêm exclusivamente das tentativas.
    Mantém alternativas de fim diferente para não escolher avidamente uma
    palavra longa que impediria as próximas. None representa omissão explícita.
    """
    # predecessor, palavra, cobertura, score acumulado, último fim
    estados = [(None, None, 0, 0.0, inicio)]
    for alternativas in opcoes:
        unicas = {}
        for p in alternativas:
            if p.inicio < inicio or p.fim > fim:
                continue
            k = (p.inicio, p.fim)
            score = p.score if _numero(p.score) else 0.0
            if k not in unicas or score > (unicas[k].score or 0):
                unicas[k] = p
        novos = {}
        for anterior in estados:
            propostas = [(anterior, None, anterior[2], anterior[3], anterior[4])]
            for p in unicas.values():
                if round(p.inicio * 1000) >= round(anterior[4] * 1000):
                    propostas.append((anterior, p, anterior[2] + 1,
                        anterior[3] + (p.score if _numero(p.score) else 0.0), p.fim))
            for node in propostas:
                k = round(node[4] * 1000)
                if k not in novos or node[2:4] > novos[k][2:4]:
                    novos[k] = node
        estados = sorted(novos.values(), key=lambda n: n[2:4], reverse=True)[:64]
    melhor = max(estados, key=lambda n: n[2:4])
    palavras = []
    while melhor[0] is not None:
        palavras.append(melhor[1])
        melhor = melhor[0]
    return list(reversed(palavras))


def validar_alinhamento(palavras, esperadas, inicio, fim, score_minimo):
    if [chave(p.texto) for p in palavras] != [chave(p) for p in esperadas]:
        return "palavras_retornadas_diferem_do_texto_solicitado"
    ultimo = inicio
    for p in palavras:
        if not all(_numero(v) for v in (p.inicio, p.fim, p.score)):
            return "palavra_sem_tempo_ou_score_finito"
        if not inicio <= p.inicio < p.fim <= fim or p.inicio < ultimo - 1e-6:
            return "tempos_invalidos_ou_sobrepostos"
        if not score_minimo <= p.score <= 1:
            return "score_insuficiente"
        if round(p.fim * 1000) <= round(p.inicio * 1000):
            return "duracao_inferior_a_precisao_srt"
        ultimo = p.fim
    return None


def aproveitar_palavras(palavras, esperadas, inicio, fim):
    """Recupera correspondências exatas, incluindo scores baixos, sem criar tempos."""
    resultado = [None] * len(esperadas)
    if not palavras:
        return resultado
    obtidas = [Token(p.texto, 0, 0, 0) for p in palavras]
    alvo = [Token(t, 0, 0, 0) for t in esperadas]
    comp = comparar(obtidas, alvo)
    ambiguos = set(comp["txt_ambiguos"])
    ultimo = inicio
    for op in comp["operacoes"]:
        j = op["txt"]
        if op["tipo"] not in ("igual", "grafia") or j in ambiguos:
            continue
        p = palavras[op["srt"]]
        if (all(_numero(v) for v in (p.inicio, p.fim))
                and inicio <= p.inicio < p.fim <= fim and p.inicio >= ultimo
                and round(p.fim * 1000) > round(p.inicio * 1000)):
            resultado[j] = p
            ultimo = p.fim
    return resultado


def _consolidar_sequencia(blocos: list[Bloco], texto: str, alinhador: AlinhadorLocal, *,
               score_minimo=0.30, margem=0.40, janela_maxima=90.0,
               progresso: Callable[[str], None] | None = None, inicio_regiao=0.0) -> dict:
    """Retorna relatório completo; nunca escreve arquivos nem inventa tempos.

    Blocos textualmente correspondentes preservam os tempos fornecidos, exceto
    os usados como contexto de uma região reparada. Isto não certifica seus
    tempos acusticamente. Regiões ambíguas continuam pendentes mesmo com score
    alto: alinhamento forçado não comprova a presença do texto no canto.
    """
    if not _numero(score_minimo) or not 0 <= score_minimo <= 1:
        raise ValueError("Score mínimo deve estar entre 0 e 1.")
    if not _numero(margem) or margem < 0 or not _numero(janela_maxima) or janela_maxima <= 0:
        raise ValueError("Margem e janela máxima inválidas.")
    duracao = alinhador.duracao_audio
    if not _numero(duracao) or duracao <= 0:
        raise ValueError("Duração do áudio inválida.")
    if any(not 0 <= b.inicio < b.fim <= duracao for b in blocos):
        raise ValueError("SRT contém tempos fora do áudio.")
    if any(b.inicio < a.fim for a, b in zip(blocos, blocos[1:])):
        raise ValueError("Blocos fora de ordem ou sobrepostos.")
    fonte, ref, comparacao = preparar_comparacao(blocos, texto)
    ancoras = _ancoras(blocos, fonte, ref, comparacao)
    pendencias = []
    if comparacao["txt_ambiguos"]:
        pendencias.append({"motivo": "correspondencia_textual_ambigua",
                           "tokens_txt": comparacao["txt_ambiguos"]})
    extras = [g for g in comparacao["divergencias"] if g["tipo"] == "somente_srt"]
    if extras:
        pendencias.append({"motivo": "texto_exclusivo_srt_exige_revisao", "divergencias": extras})
    # Cada lacuna inclui um bloco de contexto de cada lado. Isso permite
    # recuperar texto omitido DENTRO do tempo de blocos contíguos.
    regioes = []
    limites = [None] + ancoras + [None]
    for esquerda, direita in zip(limites, limites[1:]):
        a = esquerda["b"] if esquerda else 0
        b = direita["a"] if direita else len(ref)
        if a < b:
            regioes.append({"a": esquerda["a"] if esquerda else 0,
                            "b": direita["b"] if direita else len(ref)})
    fundidas = []
    for regiao in regioes:
        if fundidas and regiao["a"] < fundidas[-1]["b"]:
            fundidas[-1]["b"] = max(fundidas[-1]["b"], regiao["b"])
        else:
            fundidas.append(dict(regiao))
    buscas = referencias_busca(fonte, comparacao)
    locais = dividir_regioes(fundidas, buscas, blocos)
    # Mantém a hipótese ampla: recortar sozinho pode perder o contexto musical.
    # A reconciliação compara ambas, em vez de substituir uma pela outra.
    amplas = [dict(r, alvo_a=r["a"], alvo_b=r["b"], ampla=True) for r in fundidas]
    chaves_amplas = {(r["a"], r["b"]) for r in amplas}
    fundidas = amplas + [r for r in locais if (r["a"], r["b"]) not in chaves_amplas]
    usadas = {i for i, a in enumerate(ancoras)
              if any(r["a"] <= a["a"] and a["b"] <= r["b"] for r in fundidas)}
    candidatos = []
    for i, ancora in enumerate(ancoras):
        if i not in usadas:
            bloco = blocos[ancora["bloco"]]
            candidatos.append(dict(inicio=bloco.inicio, fim=bloco.fim,
                texto=trecho_txt(texto, ref, ancora["a"], ancora["b"]),
                token_inicio=ancora["a"], token_fim=ancora["b"],
                origem="tempos_srt_preservados", bloco_original=bloco.indice))
    tentativas = []
    estimativas = {}
    for numero_regiao, regiao in enumerate(fundidas, 1):
        a, b = regiao["a"], regiao["b"]
        alvo_a, alvo_b = regiao["alvo_a"], regiao["alvo_b"]
        dentro = [x for x in ancoras if a <= x["a"] and x["b"] <= b]
        referencias = [x for x in buscas if a <= x["a"] and x["b"] <= b]
        if regiao.get("ampla"):
            referencias = dentro
        antes = [x for x in ancoras if x["b"] <= a]
        depois = [x for x in ancoras if x["a"] >= b]
        piso = blocos[antes[-1]["bloco"]].fim if antes else inicio_regiao
        teto = blocos[depois[0]["bloco"]].inicio if depois else duracao
        inicio_base = blocos[referencias[0]["bloco"]].inicio if referencias and referencias[0]["a"] == a else piso
        fim_base = blocos[referencias[-1]["bloco"]].fim if referencias and referencias[-1]["b"] == b else teto
        esperado = [t.texto for t in ref[a:b]]
        aceitas = None
        parciais = []
        for fator in (1, 3):
            inicio, fim = max(piso, inicio_base - margem * fator), min(teto, fim_base + margem * fator)
            if fator == 3 and tentativas and tentativas[-1].get("janela") == [inicio, fim]:
                break
            registro = {"token_inicio": a, "token_fim": b, "janela": [inicio, fim],
                        "alvo_inicio": alvo_a, "alvo_fim": alvo_b}
            tentativas.append(registro)
            if fim <= inicio or fim - inicio > janela_maxima:
                registro["erro"] = "janela_vazia_ou_excede_limite"
                break
            if progresso:
                progresso(f"Região {numero_regiao}/{len(fundidas)}: {inicio:.2f}–{fim:.2f} s, "
                          f"{len(esperado)} palavras; tentativa {1 if fator == 1 else 2}.")
            try:
                palavras = alinhador.alinhar(" ".join(esperado), inicio, fim)
                erro = validar_alinhamento(palavras, esperado, inicio, fim, score_minimo)
                if erro is None:
                    # O alinhamento não pode deslocar livremente o contexto
                    # conhecido para outra repetição dentro da mesma janela.
                    for ancora in dentro:
                        bloco = blocos[ancora["bloco"]]
                        contexto = palavras[ancora["a"] - a:ancora["b"] - a]
                        tolerancia = max(2.0, margem * 3)
                        if (contexto[0].inicio < bloco.inicio - tolerancia
                                or contexto[-1].fim > bloco.fim + tolerancia):
                            erro = "contexto_deslocado_da_referencia_srt"
                            break
                registro["palavras"] = [_palavra_json(p) for p in palavras]
                recuperadas = aproveitar_palavras(palavras, esperado, inicio, fim)
                parciais.append((recuperadas, registro))
                for k, p in enumerate(recuperadas):
                    if p is not None:
                        estimativas.setdefault(a + k, []).append(p)
                if erro:
                    registro["erro"] = erro
                else:
                    registro["aceita"] = True
                    aceitas = palavras
                    break
            except Exception as erro:
                registro["erro"] = f"{type(erro).__name__}: {erro}"
        if aceitas is None:
            if parciais:
                aceitas, escolhido = max(parciais, key=lambda item: (
                    sum(p is not None for p in item[0]),
                    sum(p.score for p in item[0] if p is not None and _numero(p.score))))
                escolhido["aproveitada_com_avisos"] = True
                if escolhido.get("erro") == "contexto_deslocado_da_referencia_srt":
                    pendencias.append({"motivo": escolhido["erro"], "token_inicio": a,
                                       "token_fim": b, "janela": escolhido["janela"]})
            if not aceitas or not any(p is not None for p in aceitas):
                pendencias.append({"motivo": "regiao_sem_alinhamento_aceito", "token_inicio": a,
                                   "token_fim": b, "texto": trecho_txt(texto, ref, a, b)})
                # Os blocos de contexto continuam úteis mesmo se a reparação falhar.
                for ancora in dentro:
                    if not alvo_a <= ancora["a"] < ancora["b"] <= alvo_b:
                        continue
                    bloco = blocos[ancora["bloco"]]
                    candidatos.append(dict(inicio=bloco.inicio, fim=bloco.fim,
                        texto=trecho_txt(texto, ref, ancora["a"], ancora["b"]),
                        token_inicio=ancora["a"], token_fim=ancora["b"],
                        origem="tempos_srt_preservados", bloco_original=bloco.indice))
                continue
    # Reconcilia contexto e tentativas antes de formar frases. Uma borda
    # divergente não pode eliminar todas as palavras de uma linha do TXT.
    preservados = list({(c["token_inicio"], c["token_fim"]): c for c in candidatos
                        if c["origem"] == "tempos_srt_preservados"}.values())
    reservados = {i for c in preservados for i in range(c["token_inicio"], c["token_fim"])}
    candidatos = list(preservados)
    pendencias = [p for p in pendencias if p["motivo"] != "palavra_com_baixa_confianca"]
    i = 0
    while i < len(ref):
        if i in reservados:
            i += 1
            continue
        j = i + 1
        while j < len(ref) and j not in reservados:
            j += 1
        anteriores = [c["fim"] for c in preservados if c["token_fim"] <= i]
        posteriores = [c["inicio"] for c in preservados if c["token_inicio"] >= j]
        escolhidas = escolher_tempos([estimativas.get(k, []) for k in range(i, j)],
                                    max(anteriores, default=inicio_regiao), min(posteriores, default=duracao))
        k = i
        while k < j:
            if escolhidas[k - i] is None:
                k += 1
                continue
            l = k + 1
            while l < j and escolhidas[l - i] is not None and ref[l].unidade == ref[k].unidade:
                l += 1
            ps = escolhidas[k - i:l - i]
            candidatos.append(dict(inicio=ps[0].inicio, fim=ps[-1].fim,
                texto=trecho_txt(texto, ref, k, l), token_inicio=k, token_fim=l,
                origem="alinhamento_local", score_minimo=min(
                    (p.score for p in ps if _numero(p.score)), default=None)))
            for idx, p in enumerate(ps, k):
                if not _numero(p.score) or p.score < score_minimo:
                    pendencias.append(dict(motivo="palavra_com_baixa_confianca", token_txt=idx,
                        texto=ref[idx].texto, inicio=p.inicio, fim=p.fim,
                        score=p.score if _numero(p.score) else None))
            k = l
        i = j
    candidatos.sort(key=lambda c: c["token_inicio"])
    exportaveis = []
    for c in candidatos:
        motivo = None
        if round(c["fim"] * 1000) <= round(c["inicio"] * 1000):
            motivo = "bloco_sem_duracao_em_milissegundos"
        elif exportaveis and round(exportaveis[-1]["fim"] * 1000) > round(c["inicio"] * 1000):
            motivo = "sobreposicao_entre_blocos"
        if motivo:
            pendencias.append({"motivo": motivo, "bloco_omitido": c})
        else:
            exportaveis.append(c)
    candidatos = exportaveis
    cobertos = [i for c in candidatos for i in range(c["token_inicio"], c["token_fim"])]
    if cobertos != list(range(len(ref))):
        pendencias.append({"motivo": "cobertura_textual_incompleta",
                           "tokens_txt_sem_tempo": sorted(set(range(len(ref))) - set(cobertos))})
    resumo = []
    for p in pendencias:
        if p["motivo"] == "palavra_com_baixa_confianca":
            resumo.append(f"Baixa confiança: '{p['texto']}' em {timestamp(p['inicio'])} "
                          f"(score {p['score']}); mantida no SRT.")
        elif p["motivo"] == "cobertura_textual_incompleta":
            for i in p["tokens_txt_sem_tempo"]:
                resumo.append(f"Omitida do SRT: '{ref[i].texto}' (palavra {i + 1}, "
                              f"linha {ref[i].unidade + 1} do TXT), sem tempo utilizável.")
        else:
            resumo.append("Revisar: " + p["motivo"].replace("_", " ") + ".")
    return {"versao": 3, "status": "pendente" if pendencias else "consolidado",
            "estrategia": "janelas_amplas_e_locais_com_reconciliacao_temporal",
            "metricas": {"palavras_publicadas": len(cobertos),
                         "palavras_omitidas": len(ref) - len(set(cobertos)),
                         "palavras_baixa_confianca": sum(p["motivo"] == "palavra_com_baixa_confianca" for p in pendencias),
                         "tentativas_acusticas": len(tentativas)},
            "motor": alinhador.nome, "duracao_audio": duracao,
            "parametros": dict(score_minimo=score_minimo, margem=margem, janela_maxima=janela_maxima),
            "scores_sao_probabilidades": False, "aprovacao_musical_automatica": False,
            "total_palavras_txt": len(ref), "total_palavras_srt": len(fonte),
            "comparacao": comparacao, "tentativas": tentativas, "pendencias": pendencias,
            "blocos": candidatos, "resumo_avisos": resumo}


def planejar_estrutura(blocos, texto):
    """Consulta trechos CONTÍGUOS do TXT para cada ocorrência temporal do SRT.

    A posição no TXT desempata ocorrências idênticas, mas nunca apaga um bloco
    da gravação. Candidatos quase empatados com textos distintos são mantidos
    como pendência. Limiares são heurísticos, expostos no relatório.
    """
    from rapidfuzz.fuzz import ratio
    ref = tokenizar(texto)
    normalizados = [chave(t.texto) for t in ref]
    cursor, consultas = 0, []
    for bloco in blocos:
        palavras = [chave(t.texto) for t in tokenizar(bloco.texto)]
        n = len(palavras)
        fonte = " ".join(palavras)
        candidatos = []
        for a in range(len(ref)):
            for b in range(a + max(1, n // 2), min(len(ref), a + n + max(6, n)) + 1):
                score = ratio(fonte, " ".join(normalizados[a:b])) / 100
                if palavras and score >= .65:
                    # Extremidades são preferências, nunca vetos a erros como
                    # "Diz antes" -> "Distantes".
                    bonus = .02 * (normalizados[a] == palavras[0]) + .02 * (normalizados[b-1] == palavras[-1])
                    candidatos.append((score + bonus, a, b))
        aviso = None
        escolhido = None
        if candidatos:
            melhor = max(x[0] for x in candidatos)
            proximos = [x for x in candidatos if x[0] >= melhor - .025]
            versoes = {tuple(normalizados[a:b]) for _, a, b in proximos}
            # Um vizinho reconhecido pode distinguir variantes textuais de
            # refrões semelhantes, sem saltar para outra parte da letra.
            if len(versoes) > 1 and consultas and (consultas[-1]['score'] or 0) >= .85:
                continuacoes = [x for x in proximos if x[1] == cursor]
                if len({tuple(normalizados[a:b]) for _, a, b in continuacoes}) == 1:
                    proximos = continuacoes
                    versoes = {tuple(normalizados[a:b]) for _, a, b in proximos}
            if len(versoes) == 1:
                escolhido = min(proximos, key=lambda x: (x[1] < cursor, abs(x[1] - cursor), -x[0]))
            else:
                aviso = "consulta_txt_ambigua_original_preservado"
        else:
            aviso = "texto_exclusivo_srt_exige_revisao"
        if escolhido:
            _, a, b = escolhido
            score = ratio(fonte, " ".join(normalizados[a:b])) / 100
            cursor = b
            consultas.append(dict(bloco_srt=bloco.indice, inicio=bloco.inicio, fim=bloco.fim,
                                  txt_inicio=a, txt_fim=b, score=score,
                                  texto=trecho_txt(texto, ref, a, b), aviso=None))
        else:
            consultas.append(dict(bloco_srt=bloco.indice, inicio=bloco.inicio, fim=bloco.fim,
                                  txt_inicio=None, txt_fim=None, score=None,
                                  texto=bloco.texto, aviso=aviso))
    usados = {i for q in consultas if q["txt_inicio"] is not None
              for i in range(q["txt_inicio"], q["txt_fim"])}
    regioes = [dict(indices=[i], inicio=q["inicio"], fim=q["fim"],
                    txt_inicio=q["txt_inicio"], txt_fim=q["txt_fim"], texto=q["texto"])
               for i, q in enumerate(consultas)]
    return dict(consultas=consultas, regioes=regioes,
                tokens_txt_sem_correspondencia=sorted(set(range(len(ref))) - usados),
                parametros=dict(score_consulta_minimo=.65, margem_ambiguidade=.025,
                                bonus_por_extremidade=.02, score_contexto_minimo=.85))


def consolidar(blocos, texto, alinhador, *, score_minimo=.30, margem=.40,
               janela_maxima=90., progresso=None):
    from etapas_consolidacao import consolidar_etapas
    return consolidar_etapas(blocos, texto, alinhador, score_minimo=score_minimo,
                             margem=margem, janela_maxima=janela_maxima, progresso=progresso)


def _palavra_json(p):
    d = asdict(p)
    for campo in ("inicio", "fim", "score"):
        if not _numero(d[campo]):
            d[campo] = None
        else:
            d[campo] = float(d[campo])
    return d


def timestamp(segundos):
    ms = round(segundos * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def publicar(relatorio, saida: Path, *, atualizar=False):
    """Criação exclusiva por padrão; atualizar regenera somente o par consolidado."""
    diagnostico = saida.with_suffix(".json")
    if atualizar:
        if saida.name != "letra_consolidada.srt" or relatorio["status"] == "somente_comparacao":
            raise ValueError("Atualização permitida somente para letra_consolidada.srt com análise acústica.")
        saida.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="consolidacao_", dir=saida.parent) as temp:
            novo = Path(temp) / saida.name
            publicar(relatorio, novo)
            os.replace(novo, saida)
            os.replace(novo.with_suffix(".json"), diagnostico)
        return diagnostico
    if saida.exists() or diagnostico.exists():
        raise FileExistsError(f"Saída já existe. Escolha outro --saida: {saida}")
    saida.parent.mkdir(parents=True, exist_ok=True)
    # Mantém o resumo como último campo, inclusive após metadados da CLI.
    relatorio = dict(relatorio)
    relatorio["resumo_avisos"] = relatorio.pop("resumo_avisos", [])
    json_texto = json.dumps(relatorio, ensure_ascii=False, indent=2, allow_nan=False)
    with diagnostico.open("x", encoding="utf-8") as f:
        f.write(json_texto + "\n")
    if relatorio["status"] != "somente_comparacao":
        linhas = [f"{i}\n{timestamp(b['inicio'])} --> {timestamp(b['fim'])}\n{b['texto']}\n"
                  for i, b in enumerate(relatorio["blocos"], 1)]
        with saida.open("x", encoding="utf-8") as f:
            f.write("\n".join(linhas))
    return diagnostico


def _identidade(caminho):
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for trecho in iter(lambda: f.read(1024 * 1024), b""):
            h.update(trecho)
    return {"caminho": str(caminho), "sha256": h.hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pasta", nargs="?", type=Path, default=Path("audios"))
    parser.add_argument("--txt", type=Path, help="Padrão: PASTA/letra.txt")
    parser.add_argument("--srt", type=Path, help="Padrão: PASTA/letra.srt")
    parser.add_argument("--voz", type=Path, help="Padrão: único arquivo voz.* de áudio na pasta")
    parser.add_argument("--saida", type=Path, help="Padrão: PASTA/letra_consolidada.srt; não sobrescreve")
    parser.add_argument("--atualizar", action="store_true", help="Regenera letra_consolidada.srt e seu JSON; preserva as fontes.")
    parser.add_argument("--somente-comparar", action="store_true", help="Gera apenas diagnóstico textual, sem carregar WhisperX")
    parser.add_argument("--idioma", default="pt")
    parser.add_argument("--dispositivo", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--modelo-alinhamento")
    parser.add_argument("--pasta-modelos", type=Path, default=Path(__file__).resolve().parent / "modelos" / "alinhamento")
    parser.add_argument("--score-minimo", type=float, default=0.30)
    parser.add_argument("--margem", type=float, default=0.40)
    parser.add_argument("--janela-maxima", type=float, default=90.0)
    args = parser.parse_args(argv)
    try:
        txt = (args.txt or args.pasta / "letra.txt").resolve()
        srt = (args.srt or args.pasta / "letra.srt").resolve()
        saida = (args.saida or args.pasta / "letra_consolidada.srt").resolve()
        if saida.suffix.lower() != ".srt":
            raise ValueError("--saida deve ter extensão .srt; o relatório usa o mesmo nome com .json.")
        if saida in (txt, srt) or saida.with_suffix(".json") in (txt, srt):
            raise ValueError("A saída não pode substituir uma fonte.")
        if args.atualizar and (saida.name != "letra_consolidada.srt" or args.somente_comparar):
            raise ValueError("--atualizar exige letra_consolidada.srt e análise acústica.")
        if not args.atualizar and (saida.exists() or saida.with_suffix(".json").exists()):
            raise FileExistsError("Saída já existe; informe outro --saida.")
        texto, blocos = ler_txt(txt), ler_srt(srt)
        fonte = [t for b in blocos for t in tokenizar(b.texto)]
        ref = tokenizar(texto)
        fontes = {"txt": _identidade(txt), "srt": _identidade(srt)}
        if args.somente_comparar:
            relatorio = {"versao": 5, "status": "somente_comparacao", "comparacao": planejar_estrutura(blocos, texto),
                         "total_palavras_txt": len(ref), "total_palavras_srt": len(fonte),
                         "blocos": [], "pendencias": [{"motivo": "analise_acustica_nao_executada"}]}
        else:
            voz = args.voz
            if voz is None:
                extensoes = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma"}
                vozes = [p for p in args.pasta.iterdir() if p.is_file() and p.stem.casefold() == "voz" and p.suffix.lower() in extensoes]
                if len(vozes) != 1:
                    raise ValueError("Informe --voz ou mantenha exatamente um arquivo voz.* na pasta.")
                voz = vozes[0]
            voz = voz.resolve()
            fontes["voz"] = _identidade(voz)
            print("Carregando voz e alinhador local...", flush=True)
            alinhador = AlinhadorWhisperX(voz, args.idioma, args.dispositivo,
                                        args.modelo_alinhamento, args.pasta_modelos)
            print("Consolidando regiões com divergências...", flush=True)
            relatorio = consolidar(blocos, texto, alinhador, score_minimo=args.score_minimo,
                                   margem=args.margem, janela_maxima=args.janela_maxima,
                                   progresso=lambda mensagem: print(mensagem, flush=True))
            relatorio["configuracao_motor"] = {"idioma": args.idioma, "dispositivo": alinhador.dispositivo,
                                              "modelo_solicitado": args.modelo_alinhamento}
        relatorio["fontes"] = fontes
        diagnostico = publicar(relatorio, saida, atualizar=args.atualizar)
        print(f"Status: {relatorio['status']}\nRelatório: {diagnostico}")
        if not args.somente_comparar:
            print(f"SRT publicado: {saida} ({len(relatorio['blocos'])} blocos)")
            for aviso in relatorio["resumo_avisos"]:
                print(f"AVISO: {aviso}")
        return 0
    except (OSError, ValueError, ImportError, RuntimeError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
