import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import transcricao_bilingue as tb


def hipotese(idioma, texto, score=-.3, silencio=.01, compressao=1.):
    return dict(idioma=idioma, texto=texto, avg_logprob=score,
                no_speech_prob=silencio, compression_ratio=compressao)


class BilingueTest(unittest.TestCase):
    def test_janelas_cobrem_audio_sem_lacunas_nem_repeticao(self):
        audio=np.ones(65*16000, dtype=np.float32)
        audio[18*16000:19*16000]=0
        janelas=list(tb.janelas_audio(audio))
        self.assertEqual(janelas[0][0],0)
        self.assertEqual(janelas[-1][1],len(audio))
        self.assertTrue(18*16000 <= janelas[0][1] <= 19*16000)
        self.assertTrue(all(0 < b-a <= 20*16000 for a,b in janelas))
        self.assertTrue(all(x[1]==y[0] for x,y in zip(janelas,janelas[1:])))
        self.assertEqual(list(tb.janelas_audio(np.array([]))), [])

    def test_limites_invalidos(self):
        with self.assertRaises(ValueError):
            list(tb.janelas_audio(np.ones(100),minimo=21,maximo=20))

    def test_melhor_reconhecimento_pode_contrariar_detector(self):
        hs=[hipotese('pt','Eu ainda estou aqui',-.2),hipotese('en','I am here',-.7)]
        h,d=tb.escolher_hipotese(hs,[('en',.5),('pt',.3)])
        self.assertEqual(h['idioma'],'pt')
        self.assertTrue(d['revisao_recomendada'])

    def test_audio_forte_desempata_sem_fixar_idioma_da_musica(self):
        hs=[hipotese('pt','Eu vou',-.2),hipotese('en','I will',-.25)]
        h,d=tb.escolher_hipotese(hs,[('en',.8),('pt',.1)])
        self.assertEqual(h['idioma'],'en')
        self.assertEqual(d['motivo'],'idioma_acustico_forte')

    def test_traducao_fluente_nao_supera_audio_forte(self):
        hs=[hipotese('pt','Nós vamos continuar',-.7),hipotese('en','We will continue',-.2)]
        h,d=tb.escolher_hipotese(hs,[('pt',.95),('en',.02)])
        self.assertEqual(h['idioma'],'pt')
        self.assertEqual(d['motivo'],'idioma_acustico_forte')

    def test_probabilidades_baixas_nao_viram_certeza(self):
        hs=[hipotese('pt','Eu vou',-.2),hipotese('en','I will',-.25)]
        h,d=tb.escolher_hipotese(hs,[('fr',.8),('en',.1),('pt',.01)])
        self.assertEqual(h['idioma'],'pt')
        self.assertTrue(d['revisao_recomendada'])

    def test_silencio_com_texto_inventado_e_score_alto(self):
        hs=[hipotese('pt','O que é '*60,-.05,.9,8.),hipotese('en','You',-.7,.9)]
        h,d=tb.escolher_hipotese(hs,[('en',.3),('pt',.01)],tem_voz=False)
        self.assertIsNone(h)
        self.assertEqual(d['motivo'],'silencio_confirmado')

    def test_loop_artificial_nao_ganha_apenas_pelo_logprob(self):
        hs=[hipotese('pt','e '*200,-.1,.05,10.),hipotese('en','We keep singing',-.4)]
        h,d=tb.escolher_hipotese(hs,[('en',.6),('pt',.03)])
        self.assertEqual(h['idioma'],'en')
        self.assertLess(d['scores_comparacao']['pt'],d['scores_comparacao']['en'])

    def test_vad_sozinho_nao_descarta_canto_e_repeticao_nao_apaga_refrao(self):
        hs=[hipotese('pt','Eu vou '*10,-.2,.05,3.),hipotese('en','I will',-.8)]
        h,d=tb.escolher_hipotese(hs,[('pt',.9),('en',.01)],tem_voz=False)
        self.assertEqual(h['texto'],hs[0]['texto'])
        self.assertTrue(d['revisao_recomendada'])

    def test_hipotese_vazia_nao_derrota_texto(self):
        hs=[hipotese('pt','',0),hipotese('en','We are here',-.3)]
        h,d=tb.escolher_hipotese(hs,[('en',.9),('pt',.01)])
        self.assertEqual(h['idioma'],'en')
        self.assertIsNone(tb.escolher_hipotese([], [('en',.9)])[0])

    def test_voz_detectada_conserva_hipotese_fraca_para_revisao(self):
        hs=[hipotese('pt','Vou continuar',-1.2,.9),hipotese('en','I go',-1.4,.9)]
        h,d=tb.escolher_hipotese(hs,[('pt',.6),('en',.3)],tem_voz=True)
        self.assertIsNotNone(h)
        self.assertTrue(d['revisao_recomendada'])

    def test_transicao_redecodifica_partes_sem_publicar_texto_do_pai(self):
        self.conferir_refinamento([('en',.5),('pt',.4)],-.4)

    def test_conflito_com_audio_forte_tambem_redecodifica_partes(self):
        self.conferir_refinamento([('pt',.95),('en',.02)],-1.3)

    def conferir_refinamento(self,probs,score_pt):
        def h(l,t,score):
            return dict(hipotese(l,t,score),segmentos=[dict(start=0.,end=9.,text=t)])
        hs=[h('pt','Eu estou aqui',score_pt),h('en','We are here',-.3),
            h('pt','Eu estou aqui',-.2),h('en','We are here',-.6),
            h('pt','Eu vou ficar',-.7),h('en','We will stay',-.2)]
        backend=Mock()
        backend.detect_language.side_effect=[('en',.5,probs),
            ('pt',.9,[('pt',.9),('en',.01)]),('en',.9,[('en',.9),('pt',.01)])]
        with patch.object(tb,'janelas_audio',side_effect=[iter([(0,320000)]),iter([(0,160000)])]), \
             patch.object(tb,'reconhecer_hipotese',side_effect=hs) as reconhecer, \
             patch('faster_whisper.vad.get_speech_timestamps',return_value=[dict(start=0,end=320000)]):
            segs,reg=tb.transcrever_bilingue(backend,np.zeros(320000,dtype=np.float32))
        self.assertEqual(reconhecer.call_count,6)
        self.assertEqual([r['usada'] for r in reg],[False,True,True])
        self.assertEqual([s['text'] for s in segs],['Eu estou aqui','We will stay'])
        self.assertEqual([s['janela_bilingue'] for s in segs],[1,2])
        self.assertEqual(segs[1]['start'],10.)

    def test_timestamp_degenerado_preserva_todas_as_palavras(self):
        backend=Mock()
        backend.detect_language.return_value=('pt',.9,[('pt',.9),('en',.01)])
        hp=dict(hipotese('pt','Eu vou ficar'),segmentos=[
            dict(start=0.,end=1.,text='Eu vou'),dict(start=1.,end=1.,text='ficar')])
        he=dict(hipotese('en','I stay',-.8),segmentos=[dict(start=0.,end=2.,text='I stay')])
        with patch.object(tb,'reconhecer_hipotese',side_effect=[hp,he]), \
             patch('faster_whisper.vad.get_speech_timestamps',return_value=[dict(start=0,end=32000)]):
            segs,reg=tb.transcrever_bilingue(backend,np.zeros(32000,dtype=np.float32))
        self.assertEqual([s['text'] for s in segs],['Eu vou ficar'])
        self.assertEqual(segs[0]['end'],2.)
        self.assertTrue(reg[0]['decisao']['tempos_aproximados'])

    def test_duas_decodificacoes_do_mesmo_audio_preservam_alternativas_e_offsets(self):
        backend=Mock()
        def transcribe(audio,**kw):
            en=kw['language']=='en'
            # Segunda janela é inglesa; forçar PT produz uma hipótese traduzida.
            inglesa=audio[0]==2
            texto='We will stay' if en else 'Nós vamos ficar'
            score=-.2 if en==inglesa else -.7
            return iter([SimpleNamespace(start=.1,end=1.9,text=texto,avg_logprob=score,
                        no_speech_prob=.01,compression_ratio=1.,tokens=list(range(8)))]),None
        backend.transcribe.side_effect=transcribe
        backend.detect_language.side_effect=[('pt',.9,[('pt',.9),('en',.01)]),
                                             ('en',.9,[('en',.9),('pt',.01)])]
        audio=np.repeat([1.,2.],32000).astype(np.float32)
        with patch.object(tb,'janelas_audio',return_value=[(0,32000),(32000,64000)]), \
             patch('faster_whisper.vad.get_speech_timestamps',return_value=[dict(start=0,end=64000)]):
            segmentos,auditoria=tb.transcrever_bilingue(backend,audio)
        self.assertEqual([s['idioma'] for s in segmentos],['pt','en'])
        self.assertAlmostEqual(segmentos[1]['start'],2.1)
        self.assertEqual([len(r['hipoteses']) for r in auditoria],[2,2])
        chamadas=backend.transcribe.call_args_list
        for pt,en in zip(chamadas[::2],chamadas[1::2]):
            np.testing.assert_array_equal(pt.args[0],en.args[0])
            self.assertEqual(pt.kwargs['language'],'pt')
            self.assertEqual(en.kwargs['language'],'en')
            self.assertFalse(pt.kwargs['vad_filter'])
            self.assertFalse(pt.kwargs['condition_on_previous_text'])
            self.assertEqual(en.kwargs['task'],'transcribe')
            self.assertNotIn('initial_prompt',pt.kwargs)


if __name__=='__main__':
    unittest.main()
