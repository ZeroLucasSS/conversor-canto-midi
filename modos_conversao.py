"""Modos públicos e adaptação de palavras ao motor de intervalos vocais."""
from __future__ import annotations

import json
from pathlib import Path

MODOS = ("silabico", "palavras")


def validar_modo(modo):
    if modo not in MODOS:
        raise ValueError(f"Modo de conversão inválido: {modo!r}.")
    return modo


def sufixo_srt(modo):
    return "palavras" if validar_modo(modo) == "palavras" else "silabas"


def carregar_palavras_alinhadas(caminho):
    """Adapta intervalos inteiros ao contrato interno do analisador existente.

    Os campos de núcleo abrangem a palavra inteira; não há silabificação.
    A filtragem de frames vocais e a escolha do pitch continuam acústicas.
    """
    from notas_silabicas import validar_tempos_silabas

    dados = json.loads(Path(caminho).read_text(encoding="utf-8-sig"))
    palavras = dados.get("palavras")
    if not isinstance(palavras, list) or not palavras:
        raise ValueError("O alinhamento não contém palavras.")
    unidades = []
    obrigatorios = {"id", "bloco_indice", "ordem_global", "texto", "inicio", "fim"}
    for palavra in palavras:
        if not isinstance(palavra, dict) or obrigatorios - palavra.keys():
            raise ValueError("Palavra alinhada com campos obrigatórios ausentes.")
        avisos = list(palavra.get("avisos", []))
        if "fallback" in palavra.get("origem_tempos", ""):
            avisos.append("alinhamento de palavra estimado")
        unidades.append({**palavra, "palavra_id": palavra["id"], "unidade": "palavra",
                         "avisos": list(dict.fromkeys(avisos)),
                         "inicio_nucleo_vogal": palavra["inicio"],
                         "fim_nucleo_vogal": palavra["fim"]})
    unidades.sort(key=lambda p: (float(p["inicio"]), int(p["ordem_global"])))
    validar_tempos_silabas(unidades)
    return dados, unidades
