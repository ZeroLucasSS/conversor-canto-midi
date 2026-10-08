"""Contrato público: SRT determina ocorrências; TXT é referência reutilizável."""
import unittest

import consolidar_letra as c


class Motor:
    nome = 'teste_estrutura'
    duracao_audio = 300.

    def __init__(self, resposta=None):
        self.chamadas = []
        self.resposta = resposta or []

    def alinhar(self, texto, inicio, fim):
        self.chamadas.append((texto, inicio, fim))
        return self.resposta


class EstruturaTest(unittest.TestCase):
    def test_txt_sem_repeticao_preserva_dois_refroes(self):
        bs = [c.Bloco(17, 102.9, 106.28, 'E nessa loucura'),
              c.Bloco(40, 214.88, 218.88, 'E nessa loucura')]
        m = Motor()
        r = c.consolidar(bs, 'E nessa loucura', m)
        self.assertEqual([(b['inicio'], b['fim']) for b in r['blocos']],
                         [(102.9, 106.28), (214.88, 218.88)])
        self.assertEqual(len(r['auditoria_estrutura']), 2)
        self.assertEqual(m.chamadas, [])

    def test_txt_completo_e_abreviado_produzem_mesma_estrutura(self):
        bs = [c.Bloco(1, 1, 3, 'Minha vida'), c.Bloco(2, 4, 6, 'Meu amor'),
              c.Bloco(3, 21, 23, 'Minha vida'), c.Bloco(4, 24, 26, 'Meu amor')]
        curto = 'Minha vida\nMeu amor'
        a = c.consolidar(bs, curto, Motor())
        b = c.consolidar(bs, curto + '\n' + curto, Motor())
        resumir = lambda r: [(x['texto'], x['inicio'], x['fim']) for x in r['blocos']]
        self.assertEqual(resumir(a), resumir(b))
        self.assertEqual(len(a['blocos']), 4)

    def test_corrige_frase_contigua_sem_costurar_refroes(self):
        texto = 'Eu preciso aceitar que não dá mais\nPra separar as nossas vidas\nE nessa loucura'
        bs = [c.Bloco(16, 92.54, 100.32, 'Eu preciso aceitar para separar as nossas vidas'),
              c.Bloco(17, 102.9, 106.28, 'E nessa loucura'),
              c.Bloco(39, 203.95, 213.5, 'Eu preciso aceitar separar as nossas vidas'),
              c.Bloco(40, 214.88, 218.88, 'E nessa loucura')]
        p = c.planejar_estrutura(bs, texto)
        for i in (0, 2):
            self.assertEqual(p['consultas'][i]['texto'],
                'Eu preciso aceitar que não dá mais Pra separar as nossas vidas')
        self.assertTrue(all(g['fim'] - g['inicio'] <= 18 for g in p['regioes']))

    def test_correcao_textual_nao_chama_motor_acustico(self):
        bs = [c.Bloco(1, 100, 104, 'vida com amor'), c.Bloco(2, 200, 204, 'vida com amor')]
        m = Motor()
        r = c.consolidar(bs, 'vida e amor', m)
        self.assertEqual(m.chamadas, [])
        self.assertEqual([x['texto'] for x in r['blocos']], ['vida e amor'] * 2)
        self.assertEqual([(x['inicio'],x['fim']) for x in r['blocos']], [(100,104),(200,204)])
        self.assertEqual(r['metricas']['blocos_srt_descartados'], 0)

    def test_motor_nao_pode_devolver_outra_ocorrencia(self):
        bs = [c.Bloco(1, 100, 104, 'Bom dia'), c.Bloco(2, 110, 113, 'Até logo')]
        m = Motor([c.PalavraTemporal(w, 200+i, 200.5+i, .99)
                   for i, w in enumerate(['vida', 'e', 'amor'])])
        r = c.consolidar(bs, 'Bom dia\nvida e amor\nAté logo', m)
        self.assertEqual(r['blocos'][0]['inicio'], 100)
        self.assertEqual(r['blocos'][0]['texto'], 'Bom dia')
        self.assertEqual(len(r['blocos']), 2)
        self.assertEqual(m.chamadas[0][1:], (104,110))
        self.assertEqual(r['status'], 'pendente')

    def test_texto_srt_exclusivo_e_preservado_com_aviso(self):
        bs = [c.Bloco(1, 1, 3, 'Bom dia'), c.Bloco(2, 5, 7, 'Trecho desconhecido')]
        r = c.consolidar(bs, 'Bom dia', Motor())
        self.assertEqual([x['texto'] for x in r['blocos']], ['Bom dia', 'Trecho desconhecido'])
        self.assertTrue(any(p['motivo'] == 'texto_exclusivo_srt_exige_revisao' for p in r['pendencias']))

    def test_txt_excedente_e_diagnosticado_sem_criar_repeticao(self):
        r = c.consolidar([c.Bloco(1, 1, 3, 'Meu amor')], 'Meu amor\nMeu amor', Motor())
        self.assertEqual(len(r['blocos']), 1)
        self.assertTrue(r['comparacao']['tokens_txt_sem_correspondencia'])

    def test_repeticao_dentro_do_mesmo_bloco_nao_desaparece(self):
        bs = [c.Bloco(1, 1, 8, 'Meu amor Meu amor')]
        m = Motor([c.PalavraTemporal('Meu', 1, 2, .9), c.PalavraTemporal('amor', 3, 4, .9)])
        r = c.consolidar(bs, 'Meu amor', m)
        self.assertEqual(r['blocos'][0]['texto'], 'Meu amor Meu amor')
        self.assertEqual(r['blocos'][0]['fim'], 8)

    def test_recupera_omissao_entre_vizinhos(self):
        bs = [c.Bloco(1, 1, 3, 'Bom dia'), c.Bloco(2, 9, 11, 'Até logo')]
        m = Motor([c.PalavraTemporal(w, a, b, .9) for w,a,b in
                   [('Bom',1,1.4),('dia',2,3),('Muito',5,5.5),('amor',6,7),('Até',9,9.5),('logo',10,11)]])
        r = c.consolidar(bs, 'Bom dia\nMuito amor\nAté logo', m)
        self.assertEqual([x['texto'] for x in r['blocos']], ['Bom dia', 'Muito amor', 'Até logo'])

    def test_nao_reune_blocos_distantes_por_texto_semelhante(self):
        bs = [c.Bloco(1, 1, 3, 'Bom dia'), c.Bloco(2, 90, 92, 'Até logo')]
        m = Motor()
        r = c.consolidar(bs, 'Bom dia\nMuito amor\nAté logo', m)
        self.assertEqual(len(r['blocos']), 2)
        self.assertEqual(m.chamadas, [])
        self.assertTrue(r['comparacao']['tokens_txt_sem_correspondencia'])

    def test_grafia_nao_altera_tempos(self):
        r = c.consolidar([c.Bloco(1, 1, 3, 'nao tenho medo')], 'Não tenho medo!', Motor())
        self.assertEqual(r['blocos'][0]['texto'], 'Não tenho medo!')
        self.assertEqual((r['blocos'][0]['inicio'], r['blocos'][0]['fim']), (1, 3))

    def test_correcao_vizinha_nao_desloca_bloco_correto(self):
        bs = [c.Bloco(1, 1, 4, 'vida com amor'), c.Bloco(2, 4, 7, 'Bom dia')]
        m = Motor([c.PalavraTemporal(w, a, b, .9) for w,a,b in
                   [('vida',1,2),('e',2,2.2),('amor',2.3,3.5)]])
        r = c.consolidar(bs, 'vida e amor\nBom dia', m)
        self.assertEqual((r['blocos'][-1]['inicio'], r['blocos'][-1]['fim']), (4, 7))
        self.assertTrue(all(b <= 4 for _,a,b in m.chamadas))

    def test_consultas_ambiguas_preservam_original(self):
        r = c.consolidar([c.Bloco(1, 1, 4, 'vida bela')], 'vida nova\nvida pura', Motor())
        self.assertEqual(r['blocos'][0]['texto'], 'vida bela')
        self.assertTrue(any(p['motivo'] == 'consulta_txt_ambigua_original_preservado' for p in r['pendencias']))

    def test_palavra_repetida_na_fronteira_nao_e_apagada(self):
        bs = [c.Bloco(1, 1, 3, 'Meu amor'), c.Bloco(2, 3, 5, 'amor vive')]
        m = Motor([c.PalavraTemporal(w,a,b,.9) for w,a,b in
                   [('Meu',1,2),('amor',2,3),('vive',4,5)]])
        r = c.consolidar(bs, 'Meu amor vive', m)
        self.assertEqual(' '.join(b['texto'] for b in r['blocos']), 'Meu amor amor vive')


if __name__ == '__main__':
    unittest.main()
