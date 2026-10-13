"""Modo por palavras: evidência acústica, cobertura, exportação e publicação."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

import numpy as np
import pretty_midi

import conversao_gui as gui
import preparar_letra
import gerar_midi_silabico as cli
from exportacao_final import validar_cobertura, exportar_complementos
from letra import PalavraAlinhada, ler_srt
from midi_silabico import gerar_midi_silabico
from modos_conversao import carregar_palavras_alinhadas
from notas_silabicas import AnalisadorNotasSilabicas


def palavra(i, inicio, fim):
    return dict(id=f"p{i}", bloco_indice=1, ordem_no_bloco=i, ordem_global=i,
                texto="amor", inicio=inicio, fim=fim, avisos=[])


def motor(pitches):
    a = AnalisadorNotasSilabicas.__new__(AnalisadorNotasSilabicas)
    a.tempos = np.arange(len(pitches)) * .01
    a.duracao_voz = len(pitches) * .01
    a.midi_decimal = np.array(pitches, dtype=float)
    a.voiced_prob = np.where(np.isfinite(a.midi_decimal), .99, 0.)
    a.energia_voz = np.ones(len(pitches))
    a.centro_vocal_global = 60.
    a._suporte_harmonico = lambda **kwargs: (0., 0.)
    return a


class PalavrasTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pasta = Path(self.temp.name)
        self.srt = self.pasta / 'letra.srt'
        self.srt.write_text('1\n00:00:00,000 --> 00:00:02,000\namor amor\n', encoding='utf-8')
        self.palavras = [palavra(1, 0., 1.), palavra(2, 1., 2.)]
        self.dados = dict(palavras=self.palavras,
                          blocos=[b.para_dict() for b in ler_srt(self.srt)])
        self.alinhamento = self.pasta / 'alinhamento.json'

    def carregar(self):
        self.alinhamento.write_text(json.dumps(self.dados), encoding='utf-8')
        return carregar_palavras_alinhadas(self.alinhamento)[1]

    def analisar(self, pitches=None):
        a = motor(pitches if pitches is not None else [60.] * 100 + [64.] * 100)
        with patch('config_alinhamento.ALONGAR_FINAL_FRASE_MIDI', False), contextlib.redirect_stdout(io.StringIO()):
            return a.analisar(self.carregar(), self.palavras, modo='palavras')

    def exportar(self, modo='palavras'):
        notas = self.analisar()
        destino = self.pasta / 'resultado.mid'
        gerar_midi_silabico(notas, destino, modo=modo)
        with contextlib.redirect_stdout(io.StringIO()):
            exportar_complementos(destino, self.carregar(), notas, modo=modo)
        return (destino, destino.with_name('resultado_' + ('palavras' if modo == 'palavras' else 'silabas') + '.srt'),
                destino.with_name('resultado_metadata.json'))

    def test_cobertura_sem_silabas_e_palavras_repetidas(self):
        with patch('letra.Silabificador', side_effect=AssertionError('Não silabificar')):
            self.assertEqual(validar_cobertura(self.dados, ler_srt(self.srt), modo='palavras'),
                             {'palavras_verificadas': 2})
        self.dados['palavras'] = self.palavras[:1]
        with self.assertRaises(ValueError):
            validar_cobertura(self.dados, ler_srt(self.srt), modo='palavras')

    def test_limites_invalidos_rejeitados(self):
        for inicio, fim in [(0.5, 2.), (1., float('nan')), (2., 2.)]:
            self.palavras[1].update(inicio=inicio, fim=fim)
            with self.assertRaises(ValueError):
                self.carregar()

    def test_predominante_na_palavra_nao_media_das_alturas(self):
        notas = self.analisar([60.] * 30 + [67.] * 70 + [64.] * 100)
        self.assertEqual([n.pitch_midi for n in notas], [67, 64])
        self.assertIn('palavra com múltiplas alturas relevantes', notas[0].motivos_revisao)
        self.assertEqual([n.silaba for n in notas], ['amor', 'amor'])

    def test_sem_f0_nao_empresta_frames_da_palavra_seguinte(self):
        notas = self.analisar([float('nan')] * 100 + [72.] * 100)
        self.assertEqual(notas[0].frames_vocais, 0)
        self.assertIn('palavra sem F0 vocal confiável', notas[0].motivos_revisao)

    def test_pausa_interna_sinalizada(self):
        notas = self.analisar([60.] * 35 + [float('nan')] * 30 + [60.] * 35 + [64.] * 100)
        self.assertTrue(any('intervalo interno' in m for m in notas[0].motivos_revisao))

    def test_midi_srt_e_lyrics_uma_ocorrencia_por_palavra(self):
        midi, srt, _ = self.exportar()
        m = pretty_midi.PrettyMIDI(str(midi))
        blocos = ler_srt(srt)
        self.assertEqual(len(m.instruments[0].notes), 2)
        self.assertEqual([l.text for l in m.lyrics], ['amor', 'amor'])
        for n, b in zip(m.instruments[0].notes, blocos):
            self.assertAlmostEqual(n.start, b.inicio, places=3)
            self.assertAlmostEqual(n.end, b.fim, places=3)
            self.assertEqual(b.texto_original, 'amor')
        self.assertFalse((self.pasta / 'resultado_silabas.srt').exists())

    def test_padrao_continua_silabico(self):
        self.assertEqual(cli.criar_parser().parse_args(['voz.mid']).modo, 'silabico')
        self.assertEqual(preparar_letra.criar_parser().parse_args([]).modo, 'silabico')
        notas = self.analisar()
        midi = self.pasta / 'padrao.mid'
        gerar_midi_silabico(notas, midi)
        with contextlib.redirect_stdout(io.StringIO()):
            exportar_complementos(midi, self.carregar(), notas)
        self.assertTrue((self.pasta / 'padrao_silabas.srt').is_file())

    def test_silabico_preserva_mudancas_internas(self):
        unidades = []
        for p in self.palavras:
            for i, texto in enumerate(['a', 'mor']):
                a, b = p['inicio'] + i * .5, p['inicio'] + (i + 1) * .5
                unidades.append({**p, 'id': f"{p['id']}_s{i}", 'palavra_id': p['id'],
                                 'ordem_global': len(unidades) + 1, 'texto': texto,
                                 'inicio': a, 'fim': b, 'inicio_nucleo_vogal': a,
                                 'fim_nucleo_vogal': b})
        analisador = motor([60.] * 50 + [67.] * 50 + [64.] * 50 + [65.] * 50)
        with patch('config_alinhamento.ALONGAR_FINAL_FRASE_MIDI', False), contextlib.redirect_stdout(io.StringIO()):
            notas = analisador.analisar(unidades, self.palavras)
        self.assertEqual([n.pitch_midi for n in notas], [60, 67, 64, 65])
        self.assertEqual([n.silaba for n in notas], ['a', 'mor', 'a', 'mor'])

    def test_controlador_propaga_modo_para_ambas_etapas_e_publicacao(self):
        for nome in ('voz.wav', 'instrumental.wav', 'letra.txt'):
            (self.pasta / nome).write_text('amor amor')
        modos = []
        def executar(tarefas, projeto, cancelar, emitir):
            for tarefa in tarefas:
                if tarefa.script.name == 'consolidar_letra.py':
                    (self.pasta / 'letra_consolidada.srt').write_bytes(self.srt.read_bytes())
                else:
                    modos.append(tarefa.args[tarefa.args.index('--modo') + 1])
                    if tarefa.script.name == 'preparar_letra.py':
                        saida = Path(tarefa.args[tarefa.args.index('--saida') + 1])
                        saida.mkdir()
                        (saida / 'alinhamento_completo.json').write_text('{}')
        with patch.object(gui, '_executar_tarefas', side_effect=executar), \
             patch.object(gui, '_memoria_disponivel', return_value=None), \
             patch.object(gui, '_salvar_conjunto') as salvar:
            gui.converter(self.pasta, 'voz.mid', Event(), lambda *args: None, modo='palavras')
        self.assertEqual(modos, ['palavras', 'palavras'])
        self.assertEqual(salvar.call_args.kwargs['modo'], 'palavras')
        self.assertEqual(salvar.call_args.args[0][1].name, 'resultado_palavras.srt')

    def test_publicacao_nome_estavel_e_historico_ao_trocar_modo(self):
        antigas = self.exportar('silabico')
        resultado = gui._salvar_conjunto(antigas, self.pasta, 'voz.mid', Event())
        conteudo = resultado.srt.read_bytes()
        novas = self.exportar()
        resultado = gui._salvar_conjunto(novas, self.pasta, 'voz.mid', Event(), modo='palavras')
        self.assertEqual(resultado.midi.name, 'voz.mid')
        self.assertEqual(resultado.srt.name, 'voz_palavras.srt')
        self.assertFalse((self.pasta / 'voz_silabas.srt').exists())
        self.assertFalse((self.pasta / 'voz_1.mid').exists())
        historico = list((self.pasta / 'historico_conversoes').glob('*/voz_silabas.srt'))
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0].read_bytes(), conteudo)

    def test_publicacao_falha_restaura_conjunto_anterior(self):
        antigas = self.exportar('silabico')
        resultado = gui._salvar_conjunto(antigas, self.pasta, 'voz.mid', Event())
        snapshot = {p: p.read_bytes() for p in (resultado.midi, resultado.srt, resultado.metadata)}
        novas = self.exportar()
        substituir = gui.os.replace
        def falhar(origem, destino):
            if Path(destino).name == 'voz_metadata.json':
                raise OSError('falha simulada')
            substituir(origem, destino)
        with patch.object(gui.os, 'replace', side_effect=falhar), self.assertRaises(OSError):
            gui._salvar_conjunto(novas, self.pasta, 'voz.mid', Event(), modo='palavras')
        self.assertEqual({p: p.read_bytes() for p in snapshot}, snapshot)
        self.assertFalse((self.pasta / 'voz_palavras.srt').exists())

    def test_cancelamento_preserva_resultado(self):
        fontes = self.exportar()
        (self.pasta / 'voz.mid').write_bytes(b'anterior')
        cancelar = Event()
        cancelar.set()
        with self.assertRaises(gui.ConversaoCancelada):
            gui._salvar_conjunto(fontes, self.pasta, 'voz.mid', cancelar, modo='palavras')
        self.assertEqual((self.pasta / 'voz.mid').read_bytes(), b'anterior')

    def test_preparacao_por_palavras_nao_chama_silabificador(self):
        (self.pasta / 'voz.wav').write_bytes(b'audio simulado')
        saida = self.pasta / 'preparacao'
        palavras = [PalavraAlinhada(**p, texto_normalizado=p['texto'], score=1.,
                                   origem_tempos='confirmado_manualmente') for p in self.palavras]
        args = ['preparar_letra.py', str(self.pasta), '--srt', str(self.srt),
                '--saida', str(saida), '--modo', 'palavras']
        with patch('sys.argv', args), patch.object(preparar_letra, 'AlinhadorLetraSRT') as cls, \
             patch.object(preparar_letra, 'gerar_silabas_alinhadas', side_effect=AssertionError('Não silabificar')), \
             contextlib.redirect_stdout(io.StringIO()):
            cls.return_value.duracao_audio = 2.
            cls.return_value.dispositivo = 'cpu'
            cls.return_value.alinhar.return_value = (palavras, [])
            preparar_letra.main()
        dados = json.loads((saida / 'alinhamento_completo.json').read_text(encoding='utf-8'))
        self.assertEqual(len(dados['palavras']), 2)
        self.assertEqual(dados['silabas'], [])
        self.assertEqual(dados['metadados']['modo'], 'palavras')

    def test_cli_por_palavras_exporta_conjunto(self):
        self.carregar()
        (self.pasta / 'voz.wav').write_bytes(b'audio simulado')
        (self.pasta / 'instrumental.wav').write_bytes(b'audio simulado')
        saida = self.pasta / 'cli'
        args = ['gerar_midi_silabico.py', 'voz.mid', '--pasta-musica', str(self.pasta),
                '--alinhamento', str(self.alinhamento), '--saida', str(saida), '--modo', 'palavras']
        with patch('sys.argv', args), patch.object(cli, 'AnalisadorNotasSilabicas', return_value=motor([60.] * 200)), \
             patch('config_alinhamento.ALONGAR_FINAL_FRASE_MIDI', False), contextlib.redirect_stdout(io.StringIO()):
            cli.main()
        self.assertTrue((saida / 'voz.mid').is_file())
        self.assertTrue((saida / 'voz_palavras.srt').is_file())
        diagnostico = json.loads((saida / 'voz_notas.json').read_text(encoding='utf-8'))
        self.assertEqual(diagnostico['metadados']['modo'], 'palavras')
        self.assertEqual(diagnostico['total_notas'], 2)


if __name__ == '__main__':
    unittest.main()
