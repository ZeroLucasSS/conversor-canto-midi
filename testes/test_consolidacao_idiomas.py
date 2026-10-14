"""Casos independentes das músicas locais: âncoras, idiomas e lacunas longas."""
import unittest
from unittest.mock import patch

import consolidar_letra as c
from idiomas_letra import idiomas_por_linha


class Motor:
    nome = 'gravado'
    duracao_audio = 240.

    def __init__(self, palavras=()):
        self.palavras = list(palavras)
        self.chamadas = []

    def alinhar(self, texto, inicio, fim):
        self.chamadas.append((texto, inicio, fim))
        return self.palavras


class IdiomasTest(unittest.TestCase):
    def test_estrofe_portugues_refrao_ingles_e_retorno(self):
        linhas = idiomas_por_linha('Eu estou com você\nWe are on our way\n'
                                   'Golden skies\nNão vou mais\nLuz')
        self.assertEqual([x['idioma'] for x in linhas], ['pt', 'en', 'en', 'pt', 'pt'])
        self.assertTrue(linhas[2]['herdado'])

    def test_frase_curta_herda_contexto_global(self):
        self.assertEqual(idiomas_por_linha('Golden skies\nWe are on our way')[0]['idioma'], 'en')

    def test_possessivos_e_flexoes_portuguesas_em_contexto_ingles(self):
        linhas = idiomas_por_linha('Nossos sonhos\nSomos livres\nCan you see me in the sky')
        self.assertEqual([x['idioma'] for x in linhas], ['pt', 'pt', 'en'])

    def motor(self, idioma):
        motor = object.__new__(c.AlinhadorWhisperX)
        motor.idioma = idioma
        motor.historico_idiomas = []
        return motor

    def test_modelo_por_linha_sem_dividir_tempo_proporcionalmente(self):
        texto = 'Eu estou\nYou are'
        pt = [c.PalavraTemporal(w, a, a+.4, .9) for w, a in
              [('Eu', 1.), ('estou', 2.), ('You', 3.), ('are', 4.)]]
        en = [c.PalavraTemporal(w, a, a+.4, .9) for w, a in
              [('Eu', .1), ('estou', .6), ('You', 8.), ('are', 9.)]]
        motor = self.motor('bilingue')
        with patch.object(motor, '_alinhar_idioma', side_effect=lambda t,a,b,l: pt if l == 'pt' else en) as alinhar:
            resultado = motor.alinhar(texto, 0, 10)
        self.assertEqual([p.inicio for p in resultado], [1., 2., 8., 9.])
        self.assertEqual([x.args[1:3] for x in alinhar.call_args_list[:2]], [(0, 10), (0, 10)])

    def test_refina_frase_comprimida_usando_ancora_do_outro_idioma(self):
        motor = self.motor('bilingue')
        def resposta(texto, a, b, idioma):
            if texto == 'Eu estou':
                self.assertEqual((a,b), (0,8))
                return [c.PalavraTemporal('Eu',1,2,.9), c.PalavraTemporal('estou',3,7,.9)]
            return [c.PalavraTemporal(w,t,t+.2,.4) for w,t in
                    zip(texto.split(), [1.,2.,8.,9.] if texto == 'Eu estou You are' else [8.,9.])]
        with patch.object(motor, '_alinhar_idioma', side_effect=resposta):
            ps = motor.alinhar('Eu estou\nYou are',0,10)
        self.assertEqual(ps[1].fim,7)

    def test_idioma_explicito_prevalece(self):
        motor = self.motor('en')
        with patch.object(motor, '_alinhar_idioma', return_value=[]) as alinhar:
            motor.alinhar('Eu estou com você', 0, 10)
        self.assertEqual(alinhar.call_args.args[-1], 'en')

    def test_lacuna_sem_votos_herda_idioma_da_letra_completa(self):
        motor = self.motor('auto')
        motor.preparar_texto('We are on our way\nGolden skies')
        with patch.object(motor, '_alinhar_idioma', return_value=[]) as alinhar:
            motor.alinhar('Golden skies', 0, 10)
        self.assertEqual(alinhar.call_args.args[-1], 'en')

    def test_conflito_entre_modelos_nao_publica_sobreposicao(self):
        motor = self.motor('auto')
        def resposta(texto, a, b, idioma):
            return [c.PalavraTemporal(w, t, t+.8, .9) for w,t in
                    zip(texto.split(), [1., 2., 3., 4.] if idioma == 'pt' else [.1, 1., 1.9, 4.])]
        with patch.object(motor, '_alinhar_idioma', side_effect=resposta):
            ps = [p for p in motor.alinhar('Eu estou\nYou are', 0, 10) if p.inicio is not None]
        self.assertTrue(all(a.fim <= b.inicio for a,b in zip(ps, ps[1:])))


class LacunasTest(unittest.TestCase):
    def test_palavra_isolada_aproximada_nao_retrocede_no_txt(self):
        plano = c.planejar_estrutura([c.Bloco(1, 1, 2, 'We will be here'),
                                     c.Bloco(2, 8, 8.5, 'Bye')],
                                    'We will be here\nUntil the morning')
        self.assertIsNone(plano['consultas'][1]['txt_inicio'])

    def test_palavra_repetida_distante_nao_escolhe_primeira_ocorrencia(self):
        for inicio, palavra, txt in [('My home', 'you', 'My home\nI see you\nYou are free'),
                                     ('Minha casa', 'amor', 'Minha casa\nMeu amor\nAmor e paz')]:
            with self.subTest(palavra=palavra):
                qs = c.planejar_estrutura([c.Bloco(1, 1, 3, inicio),
                                          c.Bloco(2, 40, 40.5, palavra)], txt)['consultas']
                self.assertIsNone(qs[1]['txt_inicio'])

    def test_palavra_curta_continua_vizinho_proximo(self):
        qs = c.planejar_estrutura([c.Bloco(1, 1, 2, 'Where'), c.Bloco(2, 3, 3.5, 'I')],
                                 'Where I go\nI can dream')['consultas']
        self.assertEqual(qs[1]['txt_inicio'], 1)

    def test_busca_atravessa_fragmento_sem_sobrepor_original(self):
        bs = [c.Bloco(1, 1, 3, 'Open road'), c.Bloco(2, 5, 5.5, 'hmm'),
              c.Bloco(3, 15, 17, 'Morning light')]
        m = Motor([c.PalavraTemporal(w, a, b, .9) for w,a,b in
                   [('We',4,4.5), ('are',5,6), ('on',7,8), ('our',8,9), ('way',10,11)]])
        r = c.consolidar(bs, 'Open road\nWe are on our way\nMorning light', m)
        self.assertEqual(len(m.chamadas), 1)
        self.assertEqual([b['texto'] for b in r['blocos']],
                         ['Open road', 'We', 'hmm', 'on our way', 'Morning light'])
        self.assertEqual(r['metricas']['palavras_txt_pesquisadas_sem_tempo'], 1)
        self.assertTrue(r['tentativas'][0]['conflitos_originais'])

    def test_nao_reune_palavras_ao_redor_de_intervalo_ocupado(self):
        bs = [c.Bloco(1,1,3,'Open road'), c.Bloco(2,5,5.5,'hmm'),
              c.Bloco(3,15,17,'Morning light')]
        m = Motor([c.PalavraTemporal('Blue',4,4.5,.9), c.PalavraTemporal('sky',6,7,.9)])
        r = c.consolidar(bs, 'Open road\nBlue sky\nMorning light', m)
        self.assertEqual([b['texto'] for b in r['blocos']], ['Open road','Blue','hmm','sky','Morning light'])

    def test_lacuna_longa_com_texto_suficiente_e_limite_explicito(self):
        meio = '\n'.join(['We are on our way'] * 8)
        bs = [c.Bloco(1,1,3,'Open road'), c.Bloco(2,105,107,'Morning light')]
        m = Motor()
        c.consolidar(bs, 'Open road\n'+meio+'\nMorning light', m)
        self.assertEqual(len(m.chamadas), 1)
        self.assertIn('\n', m.chamadas[0][0])
        m = Motor()
        c.consolidar(bs, 'Open road\n'+meio+'\nMorning light', m, janela_maxima=90)
        self.assertEqual(m.chamadas, [])

    def test_fragmentos_sem_ancora_nao_autorizam_busca_integral(self):
        m = Motor()
        c.consolidar([c.Bloco(1,10,10.5,'hmm')], 'We are on our way', m)
        self.assertFalse(m.chamadas)


if __name__ == '__main__':
    unittest.main()
