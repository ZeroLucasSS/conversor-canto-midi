import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

import gerar_srt as srt
import conversao_gui as gui


def segmento():
    return dict(start=0., end=3., text='Bom dia amor', words=[
        dict(word='Bom', start=.1, end=.4, score=.9),
        dict(word='dia', start=.4, end=1., score=.9),
        dict(word='amor', start=2., end=3., score=.9)])


class GerarSRTTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pasta = Path(self.temp.name)
        (self.pasta / 'voz.wav').write_bytes(b'audio')

    def test_voz_sozinha_habilita_srt(self):
        estado = gui.estado_pasta(self.pasta)
        self.assertIsNone(estado['srt'])
        self.assertIsNotNone(estado['midi'])
        (self.pasta / 'voz.wav').unlink()
        self.assertIsNotNone(gui.estado_pasta(self.pasta)['srt'])

    def test_existente_vazio_invalido_e_diretorio_nao_sao_sobrescritos(self):
        alvo = self.pasta / 'letra.srt'
        for conteudo in ('', 'invalido'):
            alvo.write_text(conteudo)
            self.assertIsNotNone(gui.estado_pasta(self.pasta)['srt'])
            with self.assertRaises(FileExistsError):
                srt.publicar('novo', {}, self.pasta)
            self.assertEqual(alvo.read_text(), conteudo)
        alvo.unlink()
        alvo.mkdir()
        self.assertIsNotNone(gui.estado_pasta(self.pasta)['srt'])

    def test_agrupamento_por_pausa(self):
        blocos, avisos = srt.agrupar_segmentos([segmento()], 3.)
        self.assertEqual([b['texto'] for b in blocos], ['Bom dia', 'amor'])
        self.assertEqual(avisos, [])
        self.assertIn('00:00:00,100 --> 00:00:01,000', srt.texto_srt(blocos))

    def test_palavra_sem_tempo_nao_desaparece(self):
        seg = segmento()
        del seg['words'][1]['start']
        blocos, avisos = srt.agrupar_segmentos([seg], 3.)
        self.assertEqual(blocos, [dict(inicio=0., fim=3., texto='Bom dia amor')])
        self.assertTrue(avisos)

    def test_alinhamento_perde_palavra_preserva_texto_original(self):
        seg = segmento()
        seg['words'].pop()
        blocos, avisos = srt.agrupar_segmentos([seg], 3.)
        self.assertEqual(blocos[0]['texto'], 'Bom dia amor')
        self.assertTrue(avisos)

    def test_silencio_tempos_invalidos_e_sobreposicao_rejeitados(self):
        for segmentos in ([], [dict(start=2., end=1., text='amor')],
                          [dict(start=0., end=float('nan'), text='amor')],
                          [segmento(), segmento()]):
            with self.assertRaises(ValueError):
                srt.agrupar_segmentos(segmentos, 3.)

    def test_publicacao_completa_e_comparacao_opcional(self):
        (self.pasta / 'letra.txt').write_text('Bom dia meu amor', encoding='utf-8')
        with patch.object(srt, 'reconhecer', return_value=([segmento()], 3., {'modelo': 'teste'})):
            destino = srt.gerar(self.pasta)
        self.assertEqual(destino.name, 'letra.srt')
        dados = json.loads((self.pasta / 'letra_geracao.json').read_text(encoding='utf-8'))
        self.assertTrue(dados['comparacao_letra']['divergencias'])
        self.assertEqual((self.pasta / 'letra.txt').read_text(encoding='utf-8'), 'Bom dia meu amor')
        self.assertIn('amor', destino.read_text(encoding='utf-8'))

    def test_falha_na_publicacao_reverte_apenas_arquivos_proprios(self):
        link = srt.os.link
        def falhar(origem, destino):
            if Path(destino).name == 'letra.srt':
                Path(destino).write_text('criado por outro processo')
                raise FileExistsError('conflito')
            link(origem, destino)
        with patch.object(srt.os, 'link', side_effect=falhar), self.assertRaises(FileExistsError):
            srt.publicar('novo', {}, self.pasta)
        self.assertEqual((self.pasta / 'letra.srt').read_text(), 'criado por outro processo')
        self.assertFalse((self.pasta / 'letra_geracao.json').exists())

    def test_cancelamento_antes_da_publicacao(self):
        cancelar = Event()
        def executar(script, args, projeto, log, evento, emitir):
            destino = Path(args[args.index('--saida') + 1])
            blocos, _ = srt.agrupar_segmentos([segmento()], 3.)
            srt.publicar(srt.texto_srt(blocos), dict(blocos=blocos, duracao_audio=3.), destino)
            cancelar.set()
        with patch.object(gui, '_executar', side_effect=executar), self.assertRaises(gui.ConversaoCancelada):
            gui.gerar_srt_independente(self.pasta, cancelar, lambda *a: None)
        self.assertFalse((self.pasta / 'letra.srt').exists())

    def test_controlador_publica_sem_iniciar_midi(self):
        def executar(script, args, projeto, log, evento, emitir):
            self.assertEqual(script.name, 'gerar_srt.py')
            destino = Path(args[args.index('--saida') + 1])
            blocos, _ = srt.agrupar_segmentos([segmento()], 3.)
            srt.publicar(srt.texto_srt(blocos), dict(blocos=blocos, duracao_audio=3.), destino)
        with patch.object(gui, '_executar', side_effect=executar), patch.object(gui, 'converter') as midi:
            destino = gui.gerar_srt_independente(self.pasta, Event(), lambda *a: None)
        self.assertEqual(destino, self.pasta / 'letra.srt')
        midi.assert_not_called()
        self.assertIsNotNone(gui.estado_pasta(self.pasta)['srt'])

    def test_reconhecedor_alinha_frases_divididas_sem_perder_palavras(self):
        wx = MagicMock()
        wx.load_audio.return_value = [0.] * 48000
        wx.load_model.return_value.transcribe.return_value = {'segments': [segmento()]}
        wx.load_align_model.return_value = ('modelo', {})
        wx.align.return_value = {'segments': [{'words': segmento()['words'][:2]},
                                             {'words': segmento()['words'][2:]}]}
        with patch.dict('sys.modules', {'whisperx': wx, 'torch': MagicMock(),
                                        'alinhamento': SimpleNamespace(resolver_dispositivo=lambda x: 'cpu')}):
            segmentos, duracao, config = srt.reconhecer(self.pasta / 'voz.wav', pasta_modelos=self.pasta)
        self.assertEqual(len(segmentos[0]['words']), 3)
        self.assertEqual(config['compute_type'], 'int8')
        self.assertEqual(duracao, 3.)
        self.assertEqual(wx.load_model.call_args.kwargs['vad_method'], 'silero')

    def test_ingles_e_passado_para_transcricao_e_alinhamento(self):
        wx = MagicMock()
        wx.load_audio.return_value = [0.] * 48000
        wx.load_model.return_value.transcribe.return_value = {'segments': [segmento()]}
        wx.load_align_model.return_value = ('modelo', {})
        wx.align.return_value = {'segments': []}
        with patch.dict('sys.modules', {'whisperx': wx, 'torch': MagicMock(),
                                        'alinhamento': SimpleNamespace(resolver_dispositivo=lambda x: 'cpu')}):
            _, _, config = srt.reconhecer(self.pasta / 'voz.wav', idioma='en', pasta_modelos=self.pasta)
        self.assertEqual(config['idioma'], 'en')
        self.assertEqual(wx.load_model.call_args.kwargs['language'], 'en')
        self.assertEqual(wx.load_model.return_value.transcribe.call_args.kwargs['language'], 'en')
        self.assertEqual(wx.load_align_model.call_args.kwargs['language_code'], 'en')

    def test_bilingue_detecta_trechos_e_carrega_dois_alinhadores(self):
        wx = MagicMock()
        wx.load_audio.return_value = [0.] * 64000
        backend = wx.load_model.return_value.model
        backend.transcribe.return_value = (iter([
            SimpleNamespace(start=0., end=2., text='Bom dia'),
            SimpleNamespace(start=2., end=4., text='Good morning')]), None)
        backend.detect_language.side_effect = [('pt', .9, [('pt', .9), ('en', .1)]),
                                                ('en', .9, [('en', .9), ('pt', .1)])]
        wx.load_align_model.side_effect = lambda **kw: (kw['language_code'], {})
        wx.align.return_value = {'segments': []}
        with patch.dict('sys.modules', {'whisperx': wx, 'torch': MagicMock(),
                                        'alinhamento': SimpleNamespace(resolver_dispositivo=lambda x: 'cpu')}):
            segmentos, _, config = srt.reconhecer(self.pasta / 'voz.wav', idioma='bilingue', pasta_modelos=self.pasta)
        self.assertEqual([s['idioma'] for s in segmentos], ['pt', 'en'])
        self.assertEqual([s['text'] for s in segmentos], ['Bom dia', 'Good morning'])
        self.assertEqual([c.kwargs['language_code'] for c in wx.load_align_model.call_args_list], ['pt', 'en'])
        self.assertTrue(backend.transcribe.call_args.kwargs['multilingual'])
        self.assertEqual(backend.transcribe.call_args.kwargs['task'], 'transcribe')
        self.assertEqual(config['idioma'], 'bilingue')

    def test_cancelar_dialogo_nao_inicia_trabalho(self):
        from interface import Interface
        ui = Interface.__new__(Interface)
        ui.ocupado, ui.pasta, ui.janela_revisao = False, self.pasta, None
        ui.janela = MagicMock()
        with patch('interface.escolher_idioma', return_value=None), patch('interface.threading.Thread') as thread:
            ui.iniciar_srt()
        thread.assert_not_called()
        self.assertFalse(ui.ocupado)

    def test_controlador_transmite_idioma_ao_processo(self):
        def executar(script, args, projeto, log, evento, emitir):
            self.assertEqual(args[args.index('--idioma') + 1], 'en')
            raise gui.ConversaoCancelada()
        with patch.object(gui, '_executar', side_effect=executar), self.assertRaises(gui.ConversaoCancelada):
            gui.gerar_srt_independente(self.pasta, Event(), lambda *a: None, idioma='en')

    def test_idioma_invalido_rejeitado_antes_de_carregar_modelos(self):
        with self.assertRaises(ValueError):
            srt.reconhecer(self.pasta / 'voz.wav', idioma='invalido')
        with self.assertRaises(ValueError):
            srt.reconhecer(self.pasta / 'voz.wav', idioma='bilingue', modelo='small.en')

    def test_interface_atualiza_botoes_sem_iniciar_midi(self):
        from interface import Interface
        ui = Interface.__new__(Interface)
        ui.pasta, ui.ocupado = self.pasta, False
        for nome in ('botao_srt', 'gerar', 'botao_revisar', 'arquivos', 'barra', 'escolher',
                     'entrada', 'seletor_modo', 'botao_cancelar', 'status', 'abrir'):
            setattr(ui, nome, MagicMock())
        ui.registrar = MagicMock()
        ui.iniciar = MagicMock()
        ui.atualizar_disponibilidade()
        ui.botao_srt.configure.assert_called_with(state='normal')
        ui.gerar.configure.assert_called_with(state='disabled')
        blocos, _ = srt.agrupar_segmentos([segmento()], 3.)
        destino = srt.publicar(srt.texto_srt(blocos), {}, self.pasta)
        (self.pasta / 'instrumental.wav').write_bytes(b'audio')
        (self.pasta / 'letra.txt').write_text('Bom dia amor')
        ui.finalizar('srt_concluido', destino)
        ui.botao_srt.configure.assert_called_with(state='disabled')
        ui.gerar.configure.assert_called_with(state='normal')
        ui.iniciar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
