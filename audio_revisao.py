"""Player PCM: posição ancorada no relógio DAC, inclusive após pausa/seek.

Não importa sounddevice até reproduzir; revisão textual funciona sem dispositivo.
"""
from __future__ import annotations

from collections import deque
import subprocess
import threading
import numpy as np


def decodificar(caminho, taxa=44100):
    p = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(caminho), '-f', 'f32le',
                        '-ac', '1', '-ar', str(taxa), 'pipe:1'], capture_output=True,
                       timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if p.returncode:
        raise RuntimeError(p.stderr.decode('utf-8', errors='replace'))
    audio = np.frombuffer(p.stdout, dtype=np.float32).copy()
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError('Áudio vazio ou inválido.')
    return audio, taxa


class PlayerVoz:
    def __init__(self, audio, taxa=44100, fabrica=None):
        self.audio = np.asarray(audio, dtype=np.float32)
        self.taxa = taxa
        self.duracao = len(self.audio) / taxa
        self.fabrica = fabrica
        self.stream = None
        self.lock = threading.RLock()
        self.cursor = 0
        self.parado = 0.
        self.marcos = deque(maxlen=128)
        self.limite = len(self.audio)
        self.loop = None
        self.esgotado = False
        self.aviso = ''

    @property
    def tocando(self):
        return self.stream is not None and self.stream.active

    @property
    def posicao(self):
        with self.lock:
            if not self.tocando or not self.marcos:
                return self.parado
            agora = self.stream.time
            marcos = list(self.marcos)
            anteriores = [m for m in marcos if m[0] <= agora]
            if not anteriores:
                return self.parado
            dac, amostra, n = anteriores[-1]
            return min(self.duracao, (amostra + min(n, max(0, (agora-dac)*self.taxa))) / self.taxa)

    def _callback(self, out, frames, relogio, status):
        out.fill(0)
        with self.lock:
            if status:
                self.aviso = str(status)
            preenchidos = 0
            while preenchidos < frames:
                if self.cursor >= self.limite:
                    if self.loop:
                        self.cursor = self.loop[0]
                    else:
                        self.esgotado = True
                        break
                n = min(frames-preenchidos, self.limite-self.cursor)
                out[preenchidos:preenchidos+n, 0] = self.audio[self.cursor:self.cursor+n]
                self.marcos.append((relogio.outputBufferDacTime + preenchidos/self.taxa, self.cursor, n))
                self.cursor += n
                preenchidos += n

    def pausar(self):
        self.parado = self.posicao
        if self.stream is not None:
            self.stream.abort()
            self.stream.close()
            self.stream = None
        self.cursor = round(self.parado*self.taxa)
        self.marcos.clear()

    def buscar(self, segundos):
        tocando = self.tocando
        self.pausar()
        self.parado = min(self.duracao, max(0., float(segundos)))
        self.cursor = round(self.parado*self.taxa)
        if tocando:
            self.reproduzir()

    def reproduzir(self, inicio=None, fim=None, repetir=False):
        self.pausar()
        if inicio is not None:
            self.parado = max(0., min(self.duracao, inicio))
        self.cursor = round(self.parado*self.taxa)
        self.limite = round(min(self.duracao, fim)*self.taxa) if fim is not None else len(self.audio)
        if self.cursor >= self.limite:
            return
        self.loop = (self.cursor, self.limite) if repetir else None
        self.esgotado = False
        fabrica = self.fabrica
        if fabrica is None:
            try:
                import sounddevice
            except ImportError as erro:
                raise RuntimeError('Instale o player: python -m pip install -r requirements_revisao.txt') from erro
            fabrica = sounddevice.OutputStream
        self.stream = fabrica(samplerate=self.taxa, channels=1, dtype='float32', callback=self._callback)
        try:
            self.stream.start()
        except Exception:
            self.stream.close()
            self.stream = None
            raise

    def atualizar(self):
        if self.esgotado and self.posicao >= self.limite/self.taxa - .001:
            self.pausar()
        return self.posicao

    def fechar(self):
        self.pausar()


def envelope(audio, pontos=1200):
    bordas = np.linspace(0, len(audio), min(pontos, len(audio))+1, dtype=int)
    return [(float(np.min(audio[a:b])), float(np.max(audio[a:b]))) for a,b in zip(bordas,bordas[1:])]
