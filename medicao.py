"""Medição simples de tempo por etapa, impressa no log da conversão."""
from __future__ import annotations

import time
from contextlib import contextmanager


@contextmanager
def medir(etapa: str):
    inicio = time.perf_counter()
    try:
        yield
    finally:
        print(f"[tempo] {etapa}: {time.perf_counter() - inicio:.1f} s", flush=True)


def informar_ambiente(dispositivo: str | None = None) -> None:
    """Versões e dispositivo, para comparar medições entre máquinas."""
    import importlib.metadata as metadata
    import os
    import platform

    versoes = []
    for pacote in ("torch", "whisperx", "librosa", "numpy", "numba"):
        try:
            versoes.append(f"{pacote} {metadata.version(pacote)}")
        except metadata.PackageNotFoundError:
            pass
    texto = f"[ambiente] Python {platform.python_version()} | {os.cpu_count()} CPUs lógicas"
    if dispositivo:
        texto += f" | dispositivo {dispositivo}"
    print(texto + " | " + ", ".join(versoes), flush=True)
