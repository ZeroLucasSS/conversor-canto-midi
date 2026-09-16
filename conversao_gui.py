"""Controlador da interface. Usa os scripts existentes em processos separados."""
from __future__ import annotations

import codecs
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable


class ConversaoCancelada(Exception):
    """Cancelamento solicitado pelo usuário."""


@dataclass(frozen=True)
class ResultadoConversao:
    midi: Path
    srt: Path
    metadata: Path
    dificuldade: str


def validar_pasta(pasta: Path) -> dict[str, Path]:
    from config_alinhamento import EXTENSOES_AUDIO_SUPORTADAS

    pasta = Path(pasta).expanduser().resolve()
    if not pasta.is_dir():
        raise ValueError("Selecione uma pasta existente.")
    extensoes = {str(e).lower() for e in EXTENSOES_AUDIO_SUPORTADAS}
    arquivos = [p for p in pasta.iterdir() if p.is_file()]
    resultado = {}
    for nome in ("voz", "instrumental", "letra"):
        candidatos = [p for p in arquivos if p.stem.casefold() == nome
                      and (p.suffix.lower() == ".srt" if nome == "letra"
                           else p.suffix.lower() in extensoes)]
        if not candidatos:
            esperado = "letra.srt" if nome == "letra" else f"{nome} (áudio)"
            raise ValueError(f"Arquivo não encontrado: {esperado}.")
        if len(candidatos) > 1:
            raise ValueError(f"Há mais de um arquivo para {nome}: "
                             + ", ".join(p.name for p in candidatos))
        if candidatos[0].stat().st_size == 0:
            raise ValueError(f"O arquivo {candidatos[0].name} está vazio.")
        resultado[nome] = candidatos[0]
    return resultado


def normalizar_nome(nome: str) -> str:
    nome = nome.strip()
    if not nome or nome in {".", ".."} or nome.endswith("."):
        raise ValueError("Informe um nome de MIDI válido.")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', nome):
        raise ValueError("O nome do MIDI não pode conter pastas ou caracteres especiais.")
    if nome.split(".")[0].upper() in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        raise ValueError("Esse nome é reservado pelo Windows. Escolha outro.")
    if Path(nome).suffix.lower() not in {".mid", ".midi"}:
        nome += ".mid"
    if len(nome) > 180:
        raise ValueError("Use um nome com até 180 caracteres.")
    return nome


def _python() -> str:
    # Permite abrir a interface por pythonw mantendo a saída dos processos.
    executavel = Path(sys.executable)
    if executavel.name.lower() == "pythonw.exe":
        executavel = executavel.with_name("python.exe")
    return str(executavel)


def _parar(processo: subprocess.Popen) -> None:
    if processo.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(processo.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10,
        )
    else:
        try:
            os.killpg(processo.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        processo.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            processo.kill()
        else:
            try:
                os.killpg(processo.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        processo.wait(timeout=5)


def _executar(script: Path, args: list[str], projeto: Path, log: Path,
              cancelar: Event, emitir: Callable[[str, str], None]) -> None:
    if cancelar.is_set():
        raise ConversaoCancelada()
    ambiente = os.environ.copy()
    ambiente.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                    PYTHONUTF8="1", MPLBACKEND="Agg")
    opcoes = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {
        "start_new_session": True
    }
    # Arquivo temporário evita bloqueios de pipe e permite cancelar mesmo
    # quando o modelo passa muito tempo sem imprimir nenhuma mensagem.
    with log.open("wb") as saida, log.open("rb") as leitura:
        processo = subprocess.Popen(
            [_python(), "-u", str(script), *args], cwd=str(projeto),
            env=ambiente, stdin=subprocess.DEVNULL, stdout=saida,
            stderr=subprocess.STDOUT, **opcoes,
        )
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while True:
                if cancelar.is_set():
                    _parar(processo)
                    raise ConversaoCancelada()
                trecho = decoder.decode(leitura.read(65536))
                if trecho:
                    emitir("log", trecho)
                if processo.poll() is not None:
                    while dados := leitura.read(65536):
                        emitir("log", decoder.decode(dados))
                    final = decoder.decode(b"", final=True)
                    if final:
                        emitir("log", final)
                    if processo.returncode != 0:
                        raise RuntimeError(f"{script.name} terminou com erro "
                                           f"(código {processo.returncode}). "
                                           "Consulte os detalhes da execução.")
                    return
                cancelar.wait(0.10)
        finally:
            if processo.poll() is None:
                _parar(processo)


def _salvar_conjunto(origens: tuple[Path, Path, Path], pasta: Path, nome: str,
                     cancelar: Event) -> ResultadoConversao:
    """Reserva nomes exclusivos e desfaz a própria cópia se falhar/cancelar.

    Não é uma transação atômica contra queda de energia. Nenhum arquivo
    preexistente é removido, inclusive quando só um dos complementos existe.
    """
    base = Path(normalizar_nome(nome))
    for origem in origens:
        if not origem.is_file() or origem.stat().st_size == 0:
            raise RuntimeError(f"Resultado ausente ou vazio: {origem.name}.")
    with origens[0].open("rb") as arquivo:
        if arquivo.read(4) != b"MThd" or origens[0].stat().st_size < 14:
            raise RuntimeError("O conversor não produziu um arquivo MIDI reconhecível.")
    dados = json.loads(origens[2].read_text(encoding="utf-8"))
    dificuldade = dados.get("difficulty")
    if (set(dados) != {"title", "artist", "difficulty", "language", "offset", "lyricsOffset"}
            or dificuldade not in {"beginner", "intermediate", "advanced"}):
        raise RuntimeError("Metadados da música inválidos.")
    for numero in range(10000):
        if cancelar.is_set():
            raise ConversaoCancelada()
        stem = base.stem if numero == 0 else f"{base.stem}_{numero}"
        destinos = (pasta / f"{stem}{base.suffix}", pasta / f"{stem}_silabas.srt",
                    pasta / f"{stem}_metadata.json")
        criados = []
        conflito = False
        try:
            with ExitStack() as pilha:
                arquivos = []
                for destino in destinos:
                    try:
                        arquivo = destino.open("xb")
                    except FileExistsError:
                        conflito = True
                        break
                    criados.append(destino)
                    arquivos.append(pilha.enter_context(arquivo))
                if not conflito:
                    for origem, saida in zip(origens, arquivos):
                        with origem.open("rb") as entrada:
                            while trecho := entrada.read(1024 * 1024):
                                if cancelar.is_set():
                                    raise ConversaoCancelada()
                                saida.write(trecho)
                        saida.flush()
                    if cancelar.is_set():
                        raise ConversaoCancelada()
            if not conflito:
                return ResultadoConversao(*destinos, dificuldade)
        except BaseException:
            for destino in criados:
                destino.unlink(missing_ok=True)
            raise
        for destino in criados:
            destino.unlink(missing_ok=True)
    raise RuntimeError("Há muitos arquivos com esse nome. Escolha outro nome.")


def converter(pasta: Path, nome: str, cancelar: Event,
              emitir: Callable[[str, str], None], *, projeto: Path | None = None) -> ResultadoConversao:
    """Retorna após as duas etapas concluírem e os três arquivos serem copiados.

    emitir recebe ('etapa', texto) ou ('log', texto). Não acessa widgets.
    """
    projeto = (projeto or Path(__file__).resolve().parent).resolve()
    pasta = Path(pasta).expanduser().resolve()
    validar_pasta(pasta)
    nome = normalizar_nome(nome)
    for script in ("preparar_letra.py", "gerar_midi_silabico.py", "exportacao_final.py"):
        if not (projeto / script).is_file():
            raise FileNotFoundError(f"Falta {script} na pasta principal do projeto.")
    with tempfile.TemporaryDirectory(prefix="canto_midi_", ignore_cleanup_errors=True) as temp:
        trabalho = Path(temp)
        alinhamento = trabalho / "alinhamento"
        notas = trabalho / "notas"
        emitir("etapa", "1 de 2 · Preparando a letra e alinhando as sílabas")
        _executar(projeto / "preparar_letra.py",
                  [str(pasta), "--saida", str(alinhamento)], projeto,
                  trabalho / "alinhamento.log", cancelar, emitir)
        json_alinhamento = alinhamento / "alinhamento_completo.json"
        if not json_alinhamento.is_file():
            raise RuntimeError("A preparação não gerou alinhamento_completo.json.")
        emitir("etapa", "2 de 2 · Analisando voz, harmonia e gerando o MIDI")
        _executar(projeto / "gerar_midi_silabico.py",
                  ["resultado.mid", "--pasta-musica", str(pasta),
                   "--alinhamento", str(json_alinhamento), "--saida", str(notas)],
                  projeto, trabalho / "midi.log", cancelar, emitir)
        emitir("etapa", "Salvando MIDI, SRT silábico e metadados")
        destino = _salvar_conjunto((notas / "resultado.mid", notas / "resultado_silabas.srt",
                                   notas / "resultado_metadata.json"), pasta, nome, cancelar)
        emitir("log", f"\nDificuldade estimada: {destino.dificuldade}\n")
    return destino
