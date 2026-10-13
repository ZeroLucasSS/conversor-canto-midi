"""Controlador da interface. Usa os scripts existentes em processos separados."""
from __future__ import annotations

import codecs
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable
from modos_conversao import validar_modo, sufixo_srt


class ConversaoCancelada(Exception):
    """Cancelamento solicitado pelo usuário."""


@dataclass(frozen=True)
class ResultadoConversao:
    midi: Path
    srt: Path
    metadata: Path
    dificuldade: str


def validar_pasta(pasta: Path, *, requisitos=("voz", "instrumental", "letra", "letra_txt")) -> dict[str, Path]:
    from config_alinhamento import EXTENSOES_AUDIO_SUPORTADAS

    pasta = Path(pasta).expanduser().resolve()
    if not pasta.is_dir():
        raise ValueError("Selecione uma pasta existente.")
    extensoes = {str(e).lower() for e in EXTENSOES_AUDIO_SUPORTADAS}
    arquivos = [p for p in pasta.iterdir() if p.is_file()]
    resultado = {}
    for nome in requisitos:
        candidatos = [p for p in arquivos if p.stem.casefold() == ("letra" if nome == "letra_txt" else nome)
                      and (p.suffix.lower() == (".txt" if nome == "letra_txt" else ".srt") if nome in {"letra", "letra_txt"}
                           else p.suffix.lower() in extensoes)]
        if not candidatos:
            esperado = "letra.txt" if nome == "letra_txt" else ("letra.srt" if nome == "letra" else f"{nome} (áudio)")
            raise ValueError(f"Arquivo não encontrado: {esperado}.")
        if len(candidatos) > 1:
            raise ValueError(f"Há mais de um arquivo para {nome}: "
                             + ", ".join(p.name for p in candidatos))
        if candidatos[0].stat().st_size == 0:
            raise ValueError(f"O arquivo {candidatos[0].name} está vazio.")
        resultado[nome] = candidatos[0]
    return resultado


def estado_pasta(pasta):
    """Valida cada operação separadamente, aceitando pastas ainda incompletas."""
    from gerar_srt import verificar_destinos
    erros = {}
    for operacao, requisitos in [('srt', ('voz',)), ('midi', ('voz', 'instrumental', 'letra', 'letra_txt'))]:
        try:
            fontes = validar_pasta(pasta, requisitos=requisitos)
            if operacao == 'srt':
                verificar_destinos(pasta)
            else:
                from consolidar_letra import ler_srt
                blocos = ler_srt(fontes['letra'])
                if not blocos:
                    raise ValueError('letra.srt não contém blocos de legenda.')
                if any(b.inicio < a.fim for a, b in zip(blocos, blocos[1:])):
                    raise ValueError('letra.srt contém blocos sobrepostos ou fora de ordem.')
            erros[operacao] = None
        except (ValueError, OSError) as erro:
            erros[operacao] = str(erro)
    return erros


def gerar_srt_independente(pasta, cancelar, emitir, *, projeto=None, idioma='pt'):
    from gerar_srt import verificar_destinos, publicar, validar_blocos, texto_srt
    if idioma not in {'pt', 'en', 'bilingue'}:
        raise ValueError('Idioma de geração de SRT inválido.')
    pasta = Path(pasta).resolve()
    validar_pasta(pasta, requisitos=('voz',))
    verificar_destinos(pasta)
    projeto = Path(projeto or Path(__file__).resolve().parent)
    with tempfile.TemporaryDirectory(prefix='srt_whisperx_') as temp:
        trabalho = Path(temp)
        emitir('etapa', 'Gerando SRT com WhisperX · transcrição e alinhamento')
        _executar(projeto / 'gerar_srt.py', [str(pasta), '--saida', str(trabalho), '--idioma', idioma],
                  projeto, trabalho / 'geracao.log', cancelar, emitir)
        relatorio = json.loads((trabalho / 'letra_geracao.json').read_text(encoding='utf-8'))
        validar_blocos(relatorio['blocos'], relatorio['duracao_audio'])
        conteudo = (trabalho / 'letra.srt').read_text(encoding='utf-8')
        if conteudo != texto_srt(relatorio['blocos']):
            raise ValueError('SRT gerado diverge dos tempos e textos do relatório.')
        if cancelar.is_set():
            raise ConversaoCancelada()
        caminho = publicar(conteudo, relatorio, pasta)
    return caminho


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


@dataclass
class _Tarefa:
    script: Path
    args: list[str]
    log: Path
    ao_vivo: bool = True  # False: o log é mostrado quando o processo termina
    ambiente: dict[str, str] | None = None


def _executar(script: Path, args: list[str], projeto: Path, log: Path,
              cancelar: Event, emitir: Callable[[str, str], None]) -> None:
    _executar_tarefas([_Tarefa(script, args, log)], projeto, cancelar, emitir)


def _executar_tarefas(tarefas: list[_Tarefa], projeto: Path, cancelar: Event,
                      emitir: Callable[[str, str], None]) -> None:
    """Executa os scripts ao mesmo tempo e retorna quando todos terminarem.

    Um erro ou cancelamento encerra todos os processos ainda em execução.
    """
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
    with ExitStack() as pilha:
        ativos = []
        try:
            for tarefa in tarefas:
                saida = pilha.enter_context(tarefa.log.open("wb"))
                leitura = pilha.enter_context(tarefa.log.open("rb"))
                processo = subprocess.Popen(
                    [_python(), "-u", str(tarefa.script), *tarefa.args], cwd=str(projeto),
                    env={**ambiente, **(tarefa.ambiente or {})}, stdin=subprocess.DEVNULL, stdout=saida,
                    stderr=subprocess.STDOUT, **opcoes,
                )
                ativos.append((tarefa, processo, leitura,
                               codecs.getincrementaldecoder("utf-8")("replace")))
            pendentes = list(ativos)
            while pendentes:
                if cancelar.is_set():
                    raise ConversaoCancelada()
                for item in list(pendentes):
                    tarefa, processo, leitura, decoder = item
                    if tarefa.ao_vivo:
                        trecho = decoder.decode(leitura.read(65536))
                        if trecho:
                            emitir("log", trecho)
                    if processo.poll() is None:
                        continue
                    pendentes.remove(item)
                    if not tarefa.ao_vivo:
                        emitir("log", f"\n--- {tarefa.script.name} (executado em paralelo) ---\n")
                    while dados := leitura.read(65536):
                        emitir("log", decoder.decode(dados))
                    final = decoder.decode(b"", final=True)
                    if final:
                        emitir("log", final)
                    if processo.returncode != 0:
                        raise RuntimeError(f"{tarefa.script.name} terminou com erro "
                                           f"(código {processo.returncode}). "
                                           "Consulte os detalhes da execução.")
                cancelar.wait(0.10)
        finally:
            for _, processo, _, _ in ativos:
                if processo.poll() is None:
                    _parar(processo)


def _memoria_disponivel() -> int | None:
    """Memória física disponível em bytes (None se não for possível medir)."""
    if os.name != "nt":
        try:
            return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError, AttributeError):
            return None
    import ctypes

    class _Estado(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    estado = _Estado()
    estado.dwLength = ctypes.sizeof(estado)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
        return None
    return int(estado.ullAvailPhys)


# Picos medidos numa música de 5 min: ~2,2–2,6 GB (alinhamento, só durante a
# carga do modelo) + ~1,3 GB (análise de áudio). Em teste com ~3 GB livres a
# conversão levou 100–110 s em paralelo e 161 s em sequência. Abaixo deste limite, as
# etapas rodam em sequência para evitar paginação.
MEMORIA_MINIMA_PARALELO = int(2.5 * 1024 ** 3)

# A análise de áudio é quase toda sequencial (pYIN, filtro de mediana). Com
# uma thread, ela não disputa os núcleos usados pelo PyTorch no alinhamento.
AMBIENTE_ANALISE_PARALELA = {
    "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "NUMBA_NUM_THREADS": "1",
}


def _salvar_conjunto(origens: tuple[Path, Path, Path], pasta: Path, nome: str,
                     cancelar: Event, *, modo="silabico") -> ResultadoConversao:
    """Publica com nome estável e histórico; desfaz falhas durante a publicação.

    O conjunto de arquivos não é atômico contra queda de energia.
    """
    sufixo = sufixo_srt(modo)
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
    destinos = (pasta / base.name, pasta / f"{base.stem}_{sufixo}.srt",
                pasta / f"{base.stem}_metadata.json")
    # Relatórios acústicos acompanham o resultado quando disponíveis.
    pares = list(zip(origens, destinos))
    for extensao in ("json", "csv"):
        origem = origens[0].with_name(f"{origens[0].stem}_notas.{extensao}")
        if origem.is_file():
            pares.append((origem, pasta / f"{base.stem}_notas.{extensao}"))
    anteriores = list(dict.fromkeys([d for _, d in pares] + [
        pasta / f"{base.stem}_silabas.srt", pasta / f"{base.stem}_palavras.srt",
        pasta / f"{base.stem}_notas.json", pasta / f"{base.stem}_notas.csv"]))
    trava = pasta / f".{base.stem}.conversao.lock"
    try:
        arquivo_trava = trava.open("x")
    except FileExistsError:
        raise RuntimeError("Já existe uma publicação em andamento para este MIDI.") from None
    try:
        with arquivo_trava, tempfile.TemporaryDirectory(prefix=".publicacao_", dir=pasta) as temp:
            trabalho = Path(temp)
            for origem, destino in pares:
                if cancelar.is_set():
                    raise ConversaoCancelada()
                shutil.copy2(origem, trabalho / destino.name)
            existentes = [p for p in anteriores if p.exists()]
            if any(not p.is_file() for p in existentes):
                raise RuntimeError("Um destino de saída é uma pasta, não um arquivo.")
            historico = None
            if existentes:
                raiz = pasta / "historico_conversoes"
                raiz.mkdir(exist_ok=True)
                historico = Path(tempfile.mkdtemp(prefix=f"{base.stem}_", dir=raiz))
                for anterior in existentes:
                    shutil.copy2(anterior, historico / anterior.name)
            if cancelar.is_set():
                raise ConversaoCancelada()
            publicados, removidos = [], []
            try:
                for _, destino in pares:
                    os.replace(trabalho / destino.name, destino)
                    publicados.append(destino)
                for anterior in existentes:
                    if anterior not in publicados:
                        anterior.unlink()
                        removidos.append(anterior)
            except BaseException:
                for destino in publicados + removidos:
                    if destino in existentes:
                        shutil.copy2(historico / destino.name, destino)
                    else:
                        destino.unlink(missing_ok=True)
                raise
    finally:
        trava.unlink(missing_ok=True)
    return ResultadoConversao(*destinos, dificuldade)


def converter(pasta: Path, nome: str, cancelar: Event,
              emitir: Callable[[str, str], None], *, projeto: Path | None = None,
              revisar=None, modo="silabico") -> ResultadoConversao:
    """Consolida a letra, alinha unidades vocais e gera o conjunto MIDI.

    emitir recebe ('etapa', texto) ou ('log', texto). Não acessa widgets.
    """
    validar_modo(modo)
    unidade = sufixo_srt(modo)
    projeto = (projeto or Path(__file__).resolve().parent).resolve()
    pasta = Path(pasta).expanduser().resolve()
    fontes = validar_pasta(pasta)
    nome = normalizar_nome(nome)
    for script in ("consolidar_letra.py", "preparar_letra.py", "gerar_midi_silabico.py", "exportacao_final.py"):
        if not (projeto / script).is_file():
            raise FileNotFoundError(f"Falta {script} na pasta principal do projeto.")
    with tempfile.TemporaryDirectory(prefix="canto_midi_", ignore_cleanup_errors=True) as temp:
        trabalho = Path(temp)
        alinhamento = trabalho / "alinhamento"
        notas = trabalho / "notas"
        consolidada = pasta / "letra_consolidada.srt"
        emitir("etapa", "1 de 3 · Consolidando a letra")
        _executar(projeto / "consolidar_letra.py",
                  [str(pasta), "--txt", str(fontes["letra_txt"]),
                   "--srt", str(fontes["letra"]), "--voz", str(fontes["voz"]),
                   "--saida", str(consolidada), "--atualizar"],
                  projeto, trabalho / "consolidacao.log", cancelar, emitir)
        if not consolidada.is_file() or not consolidada.stat().st_size:
            raise RuntimeError("A consolidação não produziu nenhum trecho com tempo utilizável.")
        emitir("log", f"\nLetra consolidada: {consolidada}\nAvisos: {consolidada.with_suffix('.json')}\n")
        fonte_srt, manifesto = consolidada, None
        if revisar is not None:
            from revisao_letra import SessaoRevisao
            sessao = SessaoRevisao(pasta, fontes['voz'])
            if sessao.pendentes or sessao.reconciliar:
                emitir('etapa', 'Revisão da letra · aguardando validação manual')
                resposta = revisar(sessao)
                if resposta is None or cancelar.is_set():
                    raise ConversaoCancelada()
                fonte_srt, manifesto = resposta
            else:
                fonte_srt, manifesto = sessao.publicar()
            emitir('log', f'Letra validada: {fonte_srt}\nPendências mantidas: {len(sessao.pendentes)}\n')
        elif (pasta / 'revisao_letra.json').exists():
            from revisao_letra import SessaoRevisao
            sessao = SessaoRevisao(pasta, fontes['voz'])
            if sessao.reconciliar:
                raise RuntimeError('As fontes da revisão mudaram. Abra a janela de revisão antes de converter.')
            fonte_srt, manifesto = sessao.publicar()
        tarefas = [_Tarefa(projeto / "preparar_letra.py",
                           [str(pasta), "--srt", str(fonte_srt), "--saida", str(alinhamento),
                            "--modo", modo,
                            *(['--revisao', str(manifesto)] if manifesto else [])],
                           trabalho / "alinhamento.log")]
        # A análise de pitch/harmonia não depende da letra: roda junto com o
        # alinhamento quando há memória suficiente. O resultado só é usado se
        # a identidade (áudios, parâmetros, versões e código) conferir.
        analise = trabalho / "analise_audio.npz"
        memoria = _memoria_disponivel()
        paralelo = ((projeto / "analisar_audio.py").is_file()
                    and memoria is not None and memoria >= MEMORIA_MINIMA_PARALELO)
        if paralelo:
            tarefas.append(_Tarefa(projeto / "analisar_audio.py",
                                   [str(pasta), "--saida", str(analise)],
                                   trabalho / "analise_audio.log", ao_vivo=False,
                                   ambiente=AMBIENTE_ANALISE_PARALELA))
            emitir("etapa", "2 de 3 · Alinhando a letra e analisando voz e harmonia")
        else:
            emitir("etapa", f"2 de 3 · Preparando a letra e alinhando {unidade}")
            if memoria is not None:
                emitir("log", f"Memória livre ({memoria / 1024 ** 3:.1f} GB) insuficiente "
                              "para processar em paralelo; etapas em sequência.\n")
        _executar_tarefas(tarefas, projeto, cancelar, emitir)
        json_alinhamento = alinhamento / "alinhamento_completo.json"
        if not json_alinhamento.is_file():
            raise RuntimeError("A preparação não gerou alinhamento_completo.json.")
        emitir("etapa", "3 de 3 · Escolhendo as notas e gerando o MIDI" if paralelo
               else "3 de 3 · Analisando voz, harmonia e gerando o MIDI")
        _executar(projeto / "gerar_midi_silabico.py",
                  ["resultado.mid", "--pasta-musica", str(pasta),
                   "--modo", modo,
                   "--alinhamento", str(json_alinhamento), "--saida", str(notas),
                   *(["--analise-audio", str(analise)] if paralelo else [])],
                  projeto, trabalho / "midi.log", cancelar, emitir)
        emitir("etapa", f"Salvando MIDI, SRT ({unidade}) e metadados")
        destino = _salvar_conjunto((notas / "resultado.mid", notas / f"resultado_{unidade}.srt",
                                   notas / "resultado_metadata.json"), pasta, nome, cancelar, modo=modo)
        emitir("log", f"\nDificuldade estimada: {destino.dificuldade}\n")
    return destino
