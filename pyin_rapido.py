"""pYIN do librosa com decodificação Viterbi esparsa e exata.

O librosa.pyin decodifica com uma matriz de transição densa (2 × 601 estados
para C2–C7), embora mais de 90% das transições sejam zero. O Viterbi denso faz
~1,4 milhão de operações e aloca ~11 MB por frame. Aqui percorremos apenas as
transições não nulas e tratamos as nulas de forma equivalente:

- transições nulas valem log(0 + epsilon), uma constante; o melhor antecessor
  "fora da banda" é o estado anterior de maior valor que não pertence à banda;
- empates seguem np.argmax (menor índice vence).

As operações de ponto flutuante são as mesmas do librosa (valor + log_trans),
portanto os estados decodificados são idênticos, não apenas próximos.
A função librosa.pyin continua sendo usada para todo o restante do cálculo;
só a chamada a librosa.sequence.viterbi é substituída durante a execução.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

import numpy as np
from numba import njit

_trava = threading.Lock()


@njit(cache=True)
def _viterbi_esparso(log_prob, log_p_init, inicio_coluna, linhas, valores,
                     nao_nulo, log_zero):  # pragma: no cover - compilado
    n_passos, n_estados = log_prob.shape
    estado = np.zeros(n_passos, dtype=np.uint16)
    ptr = np.zeros((n_passos, n_estados), dtype=np.uint16)
    anterior = log_prob[0] + log_p_init
    atual = np.empty(n_estados, dtype=np.float64)
    for t in range(1, n_passos):
        # Ordenação estável: em empate, o menor índice aparece primeiro.
        ordem = np.argsort(-anterior, kind="mergesort")
        for j in range(n_estados):
            melhor = 0.0
            indice = -1
            for p in range(inicio_coluna[j], inicio_coluna[j + 1]):
                k = linhas[p]
                v = anterior[k] + valores[p]
                if indice < 0 or v > melhor or (v == melhor and k < indice):
                    melhor = v
                    indice = k
            for q in range(n_estados):
                k = ordem[q]
                if not nao_nulo[k, j]:
                    v = anterior[k] + log_zero
                    if indice < 0 or v > melhor or (v == melhor and k < indice):
                        melhor = v
                        indice = k
                    break
            ptr[t, j] = indice
            atual[j] = log_prob[t, j] + melhor
        anterior, atual = atual, anterior
    estado[-1] = np.argmax(anterior)
    for t in range(n_passos - 2, -1, -1):
        estado[t] = ptr[t + 1, estado[t + 1]]
    logp = np.empty(1, dtype=np.float64)
    logp[0] = anterior[estado[-1]]
    return estado, logp


def viterbi_esparso(prob, transition, *, p_init=None, return_logp=False):
    """Mesma interface e validações de librosa.sequence.viterbi."""
    from librosa.util import tiny
    from librosa.util.exceptions import ParameterError

    n_estados, _ = prob.shape[-2:]
    if transition.shape != (n_estados, n_estados):
        raise ParameterError(f"transition.shape={transition.shape}, must be "
                             f"(n_states, n_states)={n_estados, n_estados}")
    if np.any(transition < 0) or not np.allclose(transition.sum(axis=1), 1):
        raise ParameterError("Invalid transition matrix: must be non-negative "
                             "and sum to 1 on each row.")
    if np.any(prob < 0) or np.any(prob > 1):
        raise ParameterError("Invalid probability values: must be between 0 and 1.")
    epsilon = tiny(prob)
    if p_init is None:
        p_init = np.empty(n_estados)
        p_init.fill(1.0 / n_estados)
    elif (np.any(p_init < 0) or not np.allclose(p_init.sum(), 1)
          or p_init.shape != (n_estados,)):
        raise ParameterError(f"Invalid initial state distribution: p_init={p_init}")

    log_trans = np.log(transition + epsilon)
    log_prob = np.log(prob + epsilon)
    log_p_init = np.log(p_init + epsilon)
    log_zero = float(np.log(np.zeros(1, dtype=transition.dtype) + epsilon)[0])

    # Estrutura por coluna (destino j): antecessores k com transição não nula.
    nao_nulo = np.ascontiguousarray(transition != 0)
    linhas_por_coluna = [np.flatnonzero(nao_nulo[:, j]) for j in range(n_estados)]
    inicio_coluna = np.zeros(n_estados + 1, dtype=np.int64)
    inicio_coluna[1:] = np.cumsum([len(x) for x in linhas_por_coluna])
    linhas = np.concatenate(linhas_por_coluna).astype(np.int64)
    colunas = np.repeat(np.arange(n_estados), np.diff(inicio_coluna))
    valores = np.ascontiguousarray(log_trans[linhas, colunas], dtype=np.float64)

    def _helper(lp):
        s, logp = _viterbi_esparso(np.ascontiguousarray(lp.T, dtype=np.float64),
                                   np.ascontiguousarray(log_p_init, dtype=np.float64),
                                   inicio_coluna, linhas, valores, nao_nulo, log_zero)
        return s.T, logp

    if log_prob.ndim == 2:
        estados, logp = _helper(log_prob)
    else:
        vetorizado = np.vectorize(_helper, otypes=[np.uint16, np.float64],
                                  signature="(s,t)->(t),(1)")
        estados, logp = vetorizado(log_prob)
        logp = logp[..., 0]
    return (estados, logp) if return_logp else estados


@contextmanager
def _viterbi_substituido():
    import librosa.sequence as sequencia
    with _trava:
        original = sequencia.viterbi
        sequencia.viterbi = viterbi_esparso
        try:
            yield
        finally:
            sequencia.viterbi = original


def pyin(y, **kwargs):
    """librosa.pyin com o Viterbi esparso; argumentos e saída inalterados."""
    import librosa
    with _viterbi_substituido():
        return librosa.pyin(y, **kwargs)
