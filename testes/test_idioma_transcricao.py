import unittest
from unittest.mock import Mock
import numpy as np

from idioma_transcricao import identificar_idiomas, selecionar_idioma


class IdiomaTranscricaoTest(unittest.TestCase):
    def test_score_relativo_nao_transforma_audio_fraco_em_confianca(self):
        r = selecionar_idioma('Luz', [('es', .90), ('pt', .06), ('en', .04)])
        self.assertEqual(r['idioma'], 'pt')
        self.assertFalse(r['audio_local']['forte'])
        self.assertEqual(r['audio_local']['probabilidade'], .06)
        self.assertTrue(r['revisao_recomendada'])

    def test_texto_portugues_nao_recebe_alinhador_ingles_silenciosamente(self):
        r = selecionar_idioma('Eu não vou mais', [('en', .85), ('pt', .10)])
        self.assertEqual(r['idioma'], 'pt')
        self.assertEqual(r['audio_local']['idioma'], 'en')
        self.assertTrue(r['divergencia_audio_texto'])
        self.assertTrue(r['revisao_recomendada'])

    def test_pronomes_compartilhados_nao_contam_como_ingles_exclusivo(self):
        r = selecionar_idioma('Você ainda me ouve', [('en', .4), ('pt', .3)])
        self.assertEqual(r['idioma'], 'pt')
        self.assertEqual(r['texto']['votos']['en'], 0)

    def test_texto_ingles_no_contexto_portugues_preserva_troca(self):
        r = selecionar_idioma('We are on our way', [('en', .6), ('pt', .3)],
                             contexto=[('pt', .9), ('en', .05)])
        self.assertEqual(r['idioma'], 'en')
        self.assertTrue(r['revisao_recomendada'])

    def test_contexto_desempata_frase_curta_sem_pistas_textuais(self):
        r = selecionar_idioma('Golden skies', [('pt', .25), ('en', .24)],
                             contexto=[('en', .9), ('pt', .05)])
        self.assertEqual(r['idioma'], 'en')
        self.assertEqual(r['fonte'], 'audio_contextual')

    def test_recorte_curto_ganha_contexto_sem_sair_do_audio(self):
        backend = Mock()
        backend.detect_language.side_effect = [
            ('pt', .4, [('pt', .4), ('en', .3)]),
            ('en', .9, [('pt', .05), ('en', .9)])]
        r = identificar_idiomas(backend, np.zeros(10*16000),
                               [dict(start=0.,end=.4,text='Golden skies')])[0]
        self.assertEqual(r['idioma'], 'en')
        self.assertEqual(r['analise_idioma']['janela_contexto'], [0.,3.2])
        self.assertEqual((r['start'],r['end']), (0.,.4))

    def test_texto_misto_sinaliza_limitacao_de_um_alinhador(self):
        r = selecionar_idioma('Eu não vou but you can stay', [('pt', .8), ('en', .15)])
        self.assertTrue(r['texto']['misto'])
        self.assertTrue(r['revisao_recomendada'])

    def test_sem_probabilidades_validas_nao_inventa_idioma(self):
        with self.assertRaises(ValueError):
            selecionar_idioma('Palavra', [('pt', float('nan')), ('ja', .9)])


if __name__ == '__main__':
    unittest.main()
