"""Análise de áudio que não depende da letra: pitch vocal, contexto harmônico
e evidência acústica da cauda final. Roda em paralelo com preparar_letra.py;
gerar_midi_silabico.py --analise-audio reaproveita o resultado se a identidade
(conteúdo dos áudios, parâmetros, versões e código) for a mesma.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gerar_midi_silabico import localizar_audio, resolver_caminho
from medicao import medir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pasta_musica", nargs="?", default="audios",
                        help='Pasta contendo voz e instrumental. O padrão é "audios".')
    parser.add_argument("--saida", required=True, help="Arquivo .npz da análise.")
    argumentos = parser.parse_args()

    pasta_projeto = Path(__file__).resolve().parent
    pasta_musica = resolver_caminho(pasta_projeto, argumentos.pasta_musica)
    if not pasta_musica.is_dir():
        raise FileNotFoundError(f"Pasta da música não encontrada:\n{pasta_musica}")

    from notas_silabicas import AnalisadorNotasSilabicas

    analisador = AnalisadorNotasSilabicas(
        caminho_voz=localizar_audio(pasta_musica, "voz"),
        caminho_instrumental=localizar_audio(pasta_musica, "instrumental"),
    )
    with medir("evidência acústica para a duração das notas e gravação"):
        analisador.salvar_analise(resolver_caminho(pasta_projeto, argumentos.saida))
    print("Análise de áudio concluída.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProcessamento interrompido pelo usuário.")
        sys.exit(130)
    except Exception as erro:
        print()
        print("=" * 60)
        print("ERRO NA ANÁLISE DE ÁUDIO")
        print("=" * 60)
        print(str(erro))
        raise
