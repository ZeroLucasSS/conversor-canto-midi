from __future__ import annotations

import argparse
import hashlib
import sys
from exportacao_final import validar_cobertura, validar_notas, exportar_complementos

from pathlib import Path

from config_alinhamento import (
    EXTENSOES_AUDIO_SUPORTADAS,
)

from midi_silabico import (
    gerar_midi_silabico,
)

from notas_silabicas import (
    AnalisadorNotasSilabicas,
    carregar_silabas_alinhadas,
    salvar_notas_csv,
    salvar_notas_json,
)


def resolver_caminho(
    pasta_projeto: Path,
    caminho_informado: str | Path,
) -> Path:
    caminho = Path(
        caminho_informado
    ).expanduser()

    if not caminho.is_absolute():
        caminho = (
            pasta_projeto
            / caminho
        )

    return caminho.resolve()


def localizar_audio(
    pasta_musica: Path,
    nome_base: str,
) -> Path:
    encontrados = []

    for arquivo in pasta_musica.iterdir():
        if not arquivo.is_file():
            continue

        if (
            arquivo.stem.casefold()
            != nome_base.casefold()
        ):
            continue

        if (
            arquivo.suffix.lower()
            not in EXTENSOES_AUDIO_SUPORTADAS
        ):
            continue

        encontrados.append(
            arquivo
        )

    if not encontrados:
        raise FileNotFoundError(
            f'Não foi encontrado o arquivo "{nome_base}" '
            f"na pasta:\n{pasta_musica}"
        )

    if len(encontrados) > 1:
        lista = "\n".join(
            f"- {arquivo.name}"
            for arquivo in encontrados
        )

        raise RuntimeError(
            f'Foram encontrados vários arquivos "{nome_base}":\n'
            f"{lista}"
        )

    return encontrados[0]


def localizar_alinhamento_automaticamente(
    pasta_projeto: Path,
    pasta_musica: Path,
) -> Path:
    candidatos_diretos = [
        pasta_musica
        / "alinhamento_completo.json",

        pasta_projeto
        / "saida"
        / f"alinhamento_{pasta_musica.name}"
        / "alinhamento_completo.json",
    ]

    if (
        pasta_musica.name.casefold()
        == "audios"
    ):
        candidatos_diretos.append(
            pasta_projeto
            / "saida"
            / "alinhamento_musica_atual"
            / "alinhamento_completo.json"
        )

    for candidato in candidatos_diretos:
        if candidato.exists():
            return candidato.resolve()

    encontrados = list(
        (
            pasta_projeto
            / "saida"
        ).glob(
            "**/alinhamento_completo.json"
        )
    )

    if len(encontrados) == 1:
        return encontrados[0].resolve()

    if not encontrados:
        raise FileNotFoundError(
            "Não foi encontrado "
            '"alinhamento_completo.json".\n\n'
            "Execute primeiro:\n"
            "python preparar_letra.py"
        )

    lista = "\n".join(
        f"- {arquivo}"
        for arquivo in encontrados
    )

    raise RuntimeError(
        "Existem vários alinhamentos disponíveis.\n"
        "Informe o correto usando --alinhamento.\n\n"
        f"{lista}"
    )


def preparar_nome_midi(
    nome: str,
) -> str:
    nome = nome.strip()

    if not nome:
        raise ValueError(
            "O nome do MIDI não pode ficar vazio."
        )

    caminho_nome = Path(
        nome
    )

    if caminho_nome.name != nome:
        raise ValueError(
            "Informe somente o nome do arquivo MIDI, "
            "sem pastas."
        )

    if caminho_nome.suffix.lower() not in {
        ".mid",
        ".midi",
    }:
        nome += ".mid"

    return nome


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Escolhe uma nota por sílaba usando voz e "
            "instrumental e gera o MIDI."
        )
    )

    parser.add_argument(
        "nome_saida",
        help=(
            "Nome do MIDI que será gravado na "
            'pasta "saida".'
        ),
    )

    parser.add_argument(
        "--pasta-musica",
        default="audios",
        help=(
            "Pasta contendo voz e instrumental. "
            'O padrão é "audios".'
        ),
    )

    parser.add_argument(
        "--alinhamento",
        default=None,
        help=(
            "Caminho de alinhamento_completo.json. "
            "Se omitido, será procurado automaticamente."
        ),
    )

    parser.add_argument(
        "--saida",
        default="saida",
        help=(
            "Pasta onde MIDI, JSON e CSV serão gravados."
        ),
    )

    parser.add_argument(
        "--analise-audio",
        default=None,
        help=(
            "Arquivo .npz de analisar_audio.py. Só é reaproveitado se "
            "áudios, parâmetros, versões e código forem os mesmos."
        ),
    )

    return parser


def fonte_srt_alinhamento(dados, pasta_musica):
    """Audita a mesma legenda usada para alinhar, inclusive consolidações parciais."""
    meta = dados.get("metadados", {})
    informado = meta.get("arquivo_srt")
    if informado:
        caminho = Path(informado)
        if not caminho.is_absolute():
            caminho = pasta_musica / caminho
    else:
        caminho = pasta_musica / "letra.srt"  # compatibilidade com JSON antigo
    if not caminho.is_file():
        raise FileNotFoundError(f"Fonte do alinhamento não encontrada: {caminho}")
    if meta.get("sha256_srt") and hashlib.sha256(caminho.read_bytes()).hexdigest() != meta["sha256_srt"]:
        raise ValueError("O SRT mudou após o alinhamento. Execute novamente preparar_letra.py.")
    return caminho


def main():
    parser = criar_parser()
    argumentos = parser.parse_args()

    pasta_projeto = Path(
        __file__
    ).resolve().parent

    pasta_musica = resolver_caminho(
        pasta_projeto,
        argumentos.pasta_musica,
    )

    if not pasta_musica.exists():
        raise FileNotFoundError(
            "Pasta da música não encontrada:\n"
            f"{pasta_musica}"
        )

    caminho_voz = localizar_audio(
        pasta_musica,
        "voz",
    )

    caminho_instrumental = localizar_audio(
        pasta_musica,
        "instrumental",
    )

    if argumentos.alinhamento:
        caminho_alinhamento = resolver_caminho(
            pasta_projeto,
            argumentos.alinhamento,
        )
    else:
        caminho_alinhamento = (
            localizar_alinhamento_automaticamente(
                pasta_projeto,
                pasta_musica,
            )
        )

    pasta_saida = resolver_caminho(
        pasta_projeto,
        argumentos.saida,
    )

    pasta_saida.mkdir(
        parents=True,
        exist_ok=True,
    )

    nome_midi = preparar_nome_midi(
        argumentos.nome_saida
    )

    caminho_midi = (
        pasta_saida
        / nome_midi
    )

    nome_base = Path(
        nome_midi
    ).stem

    caminho_json = (
        pasta_saida
        / f"{nome_base}_notas.json"
    )

    caminho_csv = (
        pasta_saida
        / f"{nome_base}_notas.csv"
    )

    print()
    print("=" * 60)
    print("NOTAS POR SÍLABA")
    print("=" * 60)

    print(
        f"Voz:\n{caminho_voz}"
    )

    print()
    print(
        f"Instrumental:\n{caminho_instrumental}"
    )

    print()
    print(
        f"Alinhamento:\n{caminho_alinhamento}"
    )

    (
        dados_alinhamento,
        silabas,
    ) = carregar_silabas_alinhadas(
        caminho_alinhamento
    )

    palavras = dados_alinhamento.get(
        "palavras",
        [],
    )

    from letra import ler_srt
    caminho_srt = fonte_srt_alinhamento(dados_alinhamento, pasta_musica)
    auditoria = validar_cobertura(dados_alinhamento, ler_srt(caminho_srt))

    analisador = AnalisadorNotasSilabicas(
        caminho_voz=caminho_voz,
        caminho_instrumental=(
            caminho_instrumental
        ),
        analise_audio=(
            resolver_caminho(pasta_projeto, argumentos.analise_audio)
            if argumentos.analise_audio else None
        ),
    )

    notas = analisador.analisar(
        silabas=silabas,
        palavras=palavras,
    )

    metadados = {
        "arquivo_srt": str(caminho_srt),
        "consolidacao": dados_alinhamento.get("metadados", {}).get("consolidacao"),
        "arquivo_voz": str(
            caminho_voz
        ),
        "arquivo_instrumental": str(
            caminho_instrumental
        ),
        "arquivo_alinhamento": str(
            caminho_alinhamento
        ),
        "regra": (
            "exatamente uma nota por sílaba"
        ),
        "melismas": False,
        "versao_conversor": "2.4-cobertura-srt-dificuldade",
        "regra_duracao": "tempos silabicos com redistribuicao limitada e cauda final acustica",
        "total_notas_com_ajustes_duracao": sum(bool(n.ajustes_duracao) for n in notas),
        "versao_alinhamento": dados_alinhamento.get("metadados", {}).get("versao_alinhador"),
        "total_palavras_com_recuperacao": dados_alinhamento.get("metadados", {}).get("total_palavras_com_recuperacao", 0),
        "duracao_recuperada_segundos": dados_alinhamento.get("metadados", {}).get("duracao_recuperada_segundos", 0.0),

    }

    if len(notas) != len(silabas):
        raise RuntimeError("A quantidade de notas não corresponde à quantidade de sílabas.")
    validar_notas(silabas, notas)
    # Primeiro valida/exporta o MIDI. Falhas não publicam um relatório de sucesso.
    gerar_midi_silabico(notas=notas, caminho_saida=caminho_midi)
    metadados["auditoria_cobertura"] = auditoria
    metadados["avaliacao_dificuldade"] = exportar_complementos(caminho_midi, silabas, notas)
    salvar_notas_json(caminho=caminho_json, notas=notas, metadados=metadados)
    salvar_notas_csv(caminho=caminho_csv, notas=notas)

    total_revisao = sum(
        1
        for nota in notas
        if nota.revisao_recomendada
    )

    print()
    print("=" * 60)
    print("MIDI SILÁBICO CONCLUÍDO")
    print("=" * 60)

    print(
        f"Sílabas processadas: {len(silabas)}"
    )

    print(
        f"Notas MIDI geradas: {len(notas)}"
    )

    print(
        "Notas marcadas para revisão: "
        f"{total_revisao}"
    )

    print()
    print(
        f"MIDI:\n{caminho_midi}"
    )

    print()
    print(
        f"Diagnóstico JSON:\n{caminho_json}"
    )

    print()
    print(
        f"Diagnóstico CSV:\n{caminho_csv}"
    )


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print()
        print(
            "Processamento interrompido pelo usuário."
        )

        sys.exit(130)

    except Exception as erro:
        print()
        print("=" * 60)
        print("ERRO NA GERAÇÃO DO MIDI")
        print("=" * 60)

        print(
            str(
                erro
            )
        )

        raise
