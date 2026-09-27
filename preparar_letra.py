from __future__ import annotations

import argparse
import sys

from pathlib import Path

from alinhamento import AlinhadorLetraSRT
from exportacao_final import validar_cobertura
from medicao import medir

from config_alinhamento import (
    DISPOSITIVO_ALINHAMENTO,
    EXTENSOES_AUDIO_SUPORTADAS,
    IDIOMA_ALINHAMENTO,
    IDIOMA_SILABIFICACAO,
    MODELO_ALINHAMENTO,
)

from letra import (
    gerar_silabas_alinhadas,
    ler_srt,
    salvar_json,
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


def localizar_voz(
    pasta_musica: Path,
) -> Path:
    encontrados = []

    for arquivo in pasta_musica.iterdir():
        if not arquivo.is_file():
            continue

        if (
            arquivo.stem.casefold()
            != "voz"
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
            'Não foi encontrado um arquivo chamado "voz" '
            f"na pasta:\n{pasta_musica}\n\n"
            "Exemplos aceitos:\n"
            "voz.mp3\n"
            "voz.wav\n"
            "voz.flac"
        )

    if len(encontrados) > 1:
        lista = "\n".join(
            f"- {arquivo.name}"
            for arquivo in encontrados
        )

        raise RuntimeError(
            "Foram encontrados vários arquivos de voz:\n"
            f"{lista}\n\n"
            "Mantenha apenas um arquivo chamado voz."
        )

    return encontrados[0]


def localizar_srt(
    pasta_musica: Path,
) -> Path:
    encontrados = [
        arquivo
        for arquivo in pasta_musica.iterdir()
        if (
            arquivo.is_file()
            and arquivo.name.casefold()
            == "letra.srt"
        )
    ]

    if not encontrados:
        raise FileNotFoundError(
            'Não foi encontrado o arquivo "letra.srt" '
            f"na pasta:\n{pasta_musica}"
        )

    if len(encontrados) > 1:
        raise RuntimeError(
            "Foi encontrado mais de um arquivo "
            'correspondente a "letra.srt".'
        )

    return encontrados[0]


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Executa as etapas 1, 2 e 3 do alinhamento "
            "de letra cantada: SRT, palavras e sílabas."
        )
    )

    parser.add_argument(
        "pasta_musica",
        nargs="?",
        default="audios",
        help=(
            "Pasta que contém voz.mp3 e letra.srt. "
            'O padrão é a pasta "audios".'
        ),
    )

    parser.add_argument(
        "--saida",
        default=None,
        help=(
            "Pasta dos arquivos JSON. Se não informada, "
            "será criada dentro de saida/alinhamento_<música>."
        ),
    )

    parser.add_argument(
        "--idioma-alinhamento",
        default=IDIOMA_ALINHAMENTO,
        help=(
            "Código do idioma acústico. "
            'Exemplo: "pt", "en", "es".'
        ),
    )

    parser.add_argument(
        "--idioma-silabas",
        default=IDIOMA_SILABIFICACAO,
        help=(
            "Código do dicionário silábico. "
            'Exemplo: "pt_BR".'
        ),
    )

    parser.add_argument(
        "--dispositivo",
        default=DISPOSITIVO_ALINHAMENTO,
        choices=[
            "auto",
            "cpu",
            "cuda",
        ],
        help=(
            "Dispositivo do alinhamento acústico."
        ),
    )

    parser.add_argument(
        "--modelo-alinhamento",
        default=MODELO_ALINHAMENTO,
        help=(
            "Modelo Wav2Vec2 personalizado. "
            "O padrão seleciona automaticamente."
        ),
    )

    return parser


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

    if not pasta_musica.is_dir():
        raise NotADirectoryError(
            "O caminho informado não é uma pasta:\n"
            f"{pasta_musica}"
        )

    caminho_voz = localizar_voz(
        pasta_musica
    )

    caminho_srt = localizar_srt(
        pasta_musica
    )

    if argumentos.saida:
        pasta_saida = resolver_caminho(
            pasta_projeto,
            argumentos.saida,
        )
    else:
        nome_musica = (
            pasta_musica.name
            if pasta_musica.name.casefold()
            != "audios"
            else "musica_atual"
        )

        pasta_saida = (
            pasta_projeto
            / "saida"
            / f"alinhamento_{nome_musica}"
        ).resolve()

    pasta_saida.mkdir(
        parents=True,
        exist_ok=True,
    )

    pasta_modelos = (
        pasta_projeto
        / "modelos"
        / "alinhamento"
    ).resolve()

    print()
    print("=" * 60)
    print("ETAPAS 1, 2 E 3 — LETRA CANTADA")
    print("=" * 60)

    print(
        f"Pasta da música:\n{pasta_musica}"
    )

    print()
    print(
        f"Voz:\n{caminho_voz}"
    )

    print()
    print(
        f"SRT:\n{caminho_srt}"
    )

    print()
    print(
        f"Saída:\n{pasta_saida}"
    )

    # ========================================================
    # ETAPA 1 — SRT E MODELO DE DADOS
    # ========================================================

    print()
    print("=" * 60)
    print("ETAPA 1 — LEITURA DO SRT")
    print("=" * 60)

    blocos = ler_srt(
        caminho_srt
    )

    blocos_vazios = [
        bloco
        for bloco in blocos
        if bloco.vazio
    ]

    blocos_com_texto = [
        bloco
        for bloco in blocos
        if not bloco.vazio
    ]

    estrutura_srt = {
        "arquivo_srt": str(
            caminho_srt
        ),
        "total_blocos": len(
            blocos
        ),
        "blocos_com_texto": len(
            blocos_com_texto
        ),
        "blocos_vazios": len(
            blocos_vazios
        ),
        "indices_blocos_vazios": [
            bloco.indice
            for bloco in blocos_vazios
        ],
        "blocos": [
            bloco.para_dict()
            for bloco in blocos
        ],
    }

    salvar_json(
        pasta_saida
        / "01_estrutura_srt.json",
        estrutura_srt,
    )

    print(
        f"Blocos encontrados: {len(blocos)}"
    )

    print(
        "Blocos com texto: "
        f"{len(blocos_com_texto)}"
    )

    print(
        "Blocos vazios: "
        f"{len(blocos_vazios)}"
    )

    if blocos_vazios:
        print(
            "Índices vazios: "
            + ", ".join(
                str(bloco.indice)
                for bloco in blocos_vazios
            )
        )

    # ========================================================
    # ETAPA 2 — ALINHAMENTO DAS PALAVRAS
    # ========================================================

    print()
    print("=" * 60)
    print("ETAPA 2 — ALINHAMENTO DAS PALAVRAS")
    print("=" * 60)

    alinhador = AlinhadorLetraSRT(
        caminho_voz=caminho_voz,
        idioma=(
            argumentos.idioma_alinhamento
        ),
        dispositivo=(
            argumentos.dispositivo
        ),
        modelo_alinhamento=(
            argumentos.modelo_alinhamento
        ),
        pasta_modelos=pasta_modelos,
    )

    with medir("alinhamento forçado e recuperação de sustentação"):
        (
            palavras,
            avisos_alinhamento,
        ) = alinhador.alinhar(
            blocos
        )

    resultado_palavras = {
        "arquivo_voz": str(
            caminho_voz
        ),
        "arquivo_srt": str(
            caminho_srt
        ),
        "idioma": (
            argumentos.idioma_alinhamento
        ),
        "dispositivo": (
            alinhador.dispositivo
        ),
        "duracao_audio": (
            alinhador.duracao_audio
        ),
        "total_palavras": len(
            palavras
        ),
        "avisos": avisos_alinhamento,
        "palavras": [
            palavra.para_dict()
            for palavra in palavras
        ],
    }

    salvar_json(
        pasta_saida
        / "02_palavras_alinhadas.json",
        resultado_palavras,
    )

    print()
    print(
        f"Palavras alinhadas: {len(palavras)}"
    )

    print(
        "Avisos de alinhamento: "
        f"{len(avisos_alinhamento)}"
    )

    # ========================================================
    # ETAPA 3 — ALINHAMENTO DAS SÍLABAS
    # ========================================================

    print()
    print("=" * 60)
    print("ETAPA 3 — ALINHAMENTO DAS SÍLABAS")
    print("=" * 60)

    with medir("separação e alinhamento das sílabas"):
        silabas = gerar_silabas_alinhadas(
            palavras=palavras,
            idioma=(
                argumentos.idioma_silabas
            ),
        )

    resultado_silabas = {
        "arquivo_voz": str(
            caminho_voz
        ),
        "arquivo_srt": str(
            caminho_srt
        ),
        "idioma_alinhamento": (
            argumentos.idioma_alinhamento
        ),
        "idioma_silabificacao": (
            argumentos.idioma_silabas
        ),
        "total_silabas": len(
            silabas
        ),
        "silabas": [
            silaba.para_dict()
            for silaba in silabas
        ],
    }

    salvar_json(
        pasta_saida
        / "03_silabas_alinhadas.json",
        resultado_silabas,
    )

    # ========================================================
    # ARQUIVO CONSOLIDADO
    # ========================================================

    resultado_completo = {
        "metadados": {
            "arquivo_voz": str(
                caminho_voz
            ),
            "arquivo_srt": str(
                caminho_srt
            ),
            "idioma_alinhamento": (
                argumentos.idioma_alinhamento
            ),
            "idioma_silabificacao": (
                argumentos.idioma_silabas
            ),
            "duracao_audio": (
                alinhador.duracao_audio
            ),
            "total_blocos": len(
                blocos
            ),
            "total_palavras": len(
                palavras
            ),
            "total_silabas": len(
                silabas
            ),
            "avisos": avisos_alinhamento,
        },
        "blocos": [
            bloco.para_dict()
            for bloco in blocos
        ],
        "palavras": [
            palavra.para_dict()
            for palavra in palavras
        ],
        "silabas": [
            silaba.para_dict()
            for silaba in silabas
        ],
    }

    resultado_completo["metadados"]["auditoria_cobertura"] = validar_cobertura(
        resultado_completo, blocos_fonte=blocos,
    )
    salvar_json(
        pasta_saida / "alinhamento_completo.json",
        resultado_completo,
    )

    print()
    print("=" * 60)
    print("ETAPAS 1, 2 E 3 CONCLUÍDAS")
    print("=" * 60)

    print(
        f"Blocos: {len(blocos)}"
    )

    print(
        f"Palavras: {len(palavras)}"
    )

    print(
        f"Sílabas: {len(silabas)}"
    )

    print()
    print(
        "Resultados salvos em:\n"
        f"{pasta_saida}"
    )

    print()
    print(
        "Arquivo principal:\n"
        f"{pasta_saida / 'alinhamento_completo.json'}"
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
        print("ERRO NO ALINHAMENTO")
        print("=" * 60)

        print(
            str(
                erro
            )
        )

        raise
