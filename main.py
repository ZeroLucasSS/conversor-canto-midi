import argparse
from pathlib import Path

from conversor import converter_audio_para_midi


EXTENSOES_AUDIO_SUPORTADAS = {
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".m4a",
    ".aac",
    ".wma",
}


def localizar_audio(
    pasta_audios: Path,
    nome_base: str,
) -> Path:
    """
    Procura um arquivo de áudio pelo nome-base.

    Exemplos encontrados:

        audios/voz.mp3
        audios/voz.wav
        audios/instrumental.mp3

    A extensão não precisa ser informada.
    """

    arquivos_encontrados = []

    for arquivo in pasta_audios.iterdir():
        if not arquivo.is_file():
            continue

        if arquivo.suffix.lower() not in EXTENSOES_AUDIO_SUPORTADAS:
            continue

        if arquivo.stem.lower() == nome_base.lower():
            arquivos_encontrados.append(
                arquivo
            )

    if not arquivos_encontrados:
        extensoes = ", ".join(
            sorted(
                EXTENSOES_AUDIO_SUPORTADAS
            )
        )

        raise FileNotFoundError(
            f'Não foi encontrado o arquivo "{nome_base}" '
            f"na pasta:\n"
            f"{pasta_audios}\n\n"
            f'Exemplo esperado: "{nome_base}.mp3"\n'
            f"Extensões aceitas: {extensoes}"
        )

    if len(arquivos_encontrados) > 1:
        lista = "\n".join(
            f"- {arquivo.name}"
            for arquivo in arquivos_encontrados
        )

        raise RuntimeError(
            f'Foram encontrados vários arquivos chamados '
            f'"{nome_base}" na pasta de áudios:\n\n'
            f"{lista}\n\n"
            f"Mantenha apenas um deles."
        )

    return arquivos_encontrados[0]


def preparar_nome_midi(
    nome_informado: str,
) -> str:
    """
    Garante que o nome de saída possua extensão MIDI.

    Exemplos:

        resultado       -> resultado.mid
        resultado.mid   -> resultado.mid
        resultado.midi  -> resultado.midi
    """

    nome_informado = nome_informado.strip()

    if not nome_informado:
        raise ValueError(
            "O nome do arquivo de saída não pode ficar vazio."
        )

    caminho_informado = Path(
        nome_informado
    )

    if caminho_informado.name != nome_informado:
        raise ValueError(
            "Informe somente o nome do arquivo de saída, "
            "sem indicar pastas."
        )

    extensao = caminho_informado.suffix.lower()

    if extensao not in {
        ".mid",
        ".midi",
    }:
        nome_informado += ".mid"

    return nome_informado


def criar_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Converte a voz isolada em MIDI usando "
            "o instrumental como evidência harmônica."
        )
    )

    parser.add_argument(
        "nome_saida",
        help=(
            "Nome do arquivo MIDI que será criado "
            'dentro da pasta "saida".'
        ),
    )

    return parser


def main():
    # --------------------------------------------------------
    # 1. PASTA PRINCIPAL DO PROJETO
    # --------------------------------------------------------

    pasta_projeto = Path(
        __file__
    ).resolve().parent

    pasta_audios = (
        pasta_projeto
        / "audios"
    )

    pasta_saida = (
        pasta_projeto
        / "saida"
    )

    # --------------------------------------------------------
    # 2. ARGUMENTOS DO TERMINAL
    # --------------------------------------------------------

    parser = criar_parser()
    argumentos = parser.parse_args()

    nome_midi = preparar_nome_midi(
        argumentos.nome_saida
    )

    # --------------------------------------------------------
    # 3. VERIFICAÇÃO DA PASTA DE ÁUDIOS
    # --------------------------------------------------------

    if not pasta_audios.exists():
        raise FileNotFoundError(
            "A pasta de áudios não foi encontrada:\n"
            f"{pasta_audios}\n\n"
            'Crie a pasta "audios" dentro da pasta '
            "principal do projeto."
        )

    if not pasta_audios.is_dir():
        raise NotADirectoryError(
            "O caminho esperado para os áudios "
            "não é uma pasta:\n"
            f"{pasta_audios}"
        )

    # --------------------------------------------------------
    # 4. LOCALIZAÇÃO AUTOMÁTICA DOS ARQUIVOS
    # --------------------------------------------------------

    caminho_voz = localizar_audio(
        pasta_audios=pasta_audios,
        nome_base="voz",
    )

    caminho_instrumental = localizar_audio(
        pasta_audios=pasta_audios,
        nome_base="instrumental",
    )

    # --------------------------------------------------------
    # 5. PREPARAÇÃO DA PASTA DE SAÍDA
    # --------------------------------------------------------

    pasta_saida.mkdir(
        parents=True,
        exist_ok=True,
    )

    caminho_midi = (
        pasta_saida
        / nome_midi
    )

    # --------------------------------------------------------
    # 6. RESUMO
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("ARQUIVOS DO PROJETO")
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
        f"Saída MIDI:\n{caminho_midi}"
    )

    # --------------------------------------------------------
    # 7. CONVERSÃO
    # --------------------------------------------------------

    converter_audio_para_midi(
        caminho_voz=str(
            caminho_voz
        ),
        caminho_instrumental=str(
            caminho_instrumental
        ),
        caminho_midi=str(
            caminho_midi
        ),
    )


if __name__ == "__main__":
    main()