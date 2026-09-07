"""Executa a preparação da letra e a geração do MIDI em sequência."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def listar_alinhamentos(projeto: Path) -> dict:
    encontrados = {}
    for pasta in (projeto / "saida", projeto / "audios"):
        if pasta.is_dir():
            for arquivo in pasta.rglob("alinhamento_completo.json"):
                if arquivo.is_file():
                    info = arquivo.stat()
                    encontrados[arquivo.resolve()] = (
                        info.st_mtime_ns, info.st_ctime_ns, info.st_size
                    )
    return encontrados


def executar(script: Path, argumentos: list[str], projeto: Path) -> None:
    subprocess.run(
        [sys.executable, "-u", str(script), *argumentos],
        cwd=str(projeto),
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepara a letra e gera o MIDI com um único comando."
    )
    parser.add_argument("nome_saida", help="Nome do MIDI, sem pastas.")
    args = parser.parse_args()
    nome = args.nome_saida.strip()
    if not nome or nome in {".", ".."} or any(c in nome for c in '/\\:*?"<>|'):
        parser.error("Informe um nome de arquivo válido, sem pastas.")
    if Path(nome).suffix.lower() not in {".mid", ".midi"}:
        nome += ".mid"

    projeto = Path(__file__).resolve().parent
    preparar = projeto / "preparar_letra.py"
    gerar = projeto / "gerar_midi_silabico.py"

    try:
        for script in (preparar, gerar):
            if not script.is_file():
                raise FileNotFoundError(f"Script não encontrado: {script}")

        antes = listar_alinhamentos(projeto)
        print("\n[1/2] Preparando a letra...", flush=True)
        executar(preparar, [], projeto)

        depois = listar_alinhamentos(projeto)
        atualizados = [p for p, estado in depois.items() if antes.get(p) != estado]
        if len(atualizados) != 1:
            raise RuntimeError(
                "A preparação terminou, mas não foi possível identificar um único "
                "alinhamento_completo.json novo ou atualizado em audios/ ou saida/. "
                f"Foram encontrados {len(atualizados)}. Confira a saída da preparação."
            )

        print("\n[2/2] Gerando o MIDI...", flush=True)
        executar(gerar, [
            nome,
            "--pasta-musica", str(projeto / "audios"),
            "--alinhamento", str(atualizados[0]),
            "--saida", str(projeto / "saida"),
        ], projeto)

        print(f"\nProcesso concluído. MIDI: {projeto / 'saida' / nome}")
        return 0
    except subprocess.CalledProcessError as erro:
        print(
            f"\nProcesso interrompido: uma etapa falhou (código {erro.returncode}). "
            "Consulte a mensagem exibida acima.", file=sys.stderr,
        )
        return 1
    except (OSError, RuntimeError) as erro:
        print(f"\nErro: {erro}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nProcesso interrompido pelo usuário.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
