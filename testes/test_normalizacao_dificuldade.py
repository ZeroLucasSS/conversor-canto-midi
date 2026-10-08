import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from normalizacao_legenda import normalizar_frase
from exportacao_final import avaliar_dificuldade


def evento(pitch, inicio=0., fim=1.):
    return SimpleNamespace(pitch=pitch, start=inicio, end=fim)


class DificuldadeTest(unittest.TestCase):
    def test_repetir_e_dividir_notas_nao_aumenta_dificuldade(self):
        unica = avaliar_dificuldade([evento(67)])
        dividida = avaliar_dificuldade([evento(67,i/1000,(i+1)/1000) for i in range(1000)])
        repetida = avaliar_dificuldade([evento(67,i,i+1) for i in range(1000)])
        for resultado in (dividida,repetida):
            self.assertEqual(resultado[0],unica[0])
            self.assertEqual(resultado[1]['score'],unica[1]['score'])

    def test_pico_curto_tem_peso_dominante(self):
        base = [evento(60,i,i+1) for i in range(1000)]
        self.assertEqual(avaliar_dificuldade(base)[0],'beginner')
        nivel,d = avaliar_dificuldade(base+[evento(84,1000,1000.05)])
        self.assertEqual(nivel,'advanced')
        self.assertEqual(d['pitch_pico'],84)
        self.assertEqual(d['peso_pico'],.85)

    def test_variedade_tem_peso_menor_e_conta_oitavas(self):
        _,unica = avaliar_dificuldade([evento(72)])
        _,oitavas = avaliar_dificuldade([evento(60),evento(72)])
        _,variada = avaliar_dificuldade([evento(n) for n in range(61,73)])
        self.assertEqual(oitavas['total_alturas_distintas'],2)
        self.assertGreater(variada['score'],unica['score'])
        self.assertAlmostEqual(variada['score']-unica['score'],.15)

    def test_transpor_para_agudo_aumenta_score(self):
        niveis = [avaliar_dificuldade([evento(p)]) for p in [60,72,84]]
        self.assertEqual([x[0] for x in niveis],['beginner','intermediate','advanced'])
        self.assertEqual([x[1]['score'] for x in niveis], [0.,.425,.85])

    def test_entrada_invalida(self):
        for notas in [[],[evento(60,1,1)],[evento(float('nan'))],[evento(128)]]:
            with self.assertRaises(ValueError):
                avaliar_dificuldade(notas)


class NormalizacaoTest(unittest.TestCase):
    def test_pontuacao_acentos_e_primeira_letra(self):
        for original, esperado in [('... "É ISSO, MEU Amor!"','... "É isso, meu amor!"'),
                                   ('123 eu VOU','123 Eu vou'), ('sÃO PAULO','São paulo'), ('♪...','♪...')]:
            self.assertEqual(normalizar_frase(original),esperado)
            self.assertEqual(normalizar_frase(esperado),esperado)

    def test_publicacao_consolidada_json_consistente_sem_mudar_entrada(self):
        from consolidar_letra import publicar,ler_srt
        r = dict(status='consolidado',blocos=[dict(inicio=1,fim=2,texto='eu VOU')],
                 auditoria_estrutura=[dict(texto_original='eu VOU',texto_publicado='eu VOU')])
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'letra_consolidada.srt'
            publicar(r,p)
            self.assertEqual(ler_srt(p)[0].texto,'Eu vou')
            j=json.loads(p.with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual(j['blocos'][0]['texto'],'Eu vou')
            self.assertEqual(j['auditoria_estrutura'][0]['texto_original'],'eu VOU')
            self.assertEqual(j['auditoria_estrutura'][0]['texto_publicado'],'Eu vou')
            self.assertEqual(r['blocos'][0]['texto'],'eu VOU')

    def test_validada_preserva_tempos_e_sincroniza_manifesto(self):
        from testes.test_revisao_letra import preparar_fixture
        from revisao_letra import SessaoRevisao,palavras_editor,carregar_tempos_confirmados
        from alinhamento import AlinhadorLetraSRT
        from letra import ler_srt
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            preparar_fixture(p)
            s=SessaoRevisao(p)
            ps=palavras_editor('vamos VOAR')
            ps[1].update(inicio=2.,fim=2.8,confirmado=True)
            s.aplicar('teste','corrigir',alvos=['srt:1'],novos=[dict(inicio=1,fim=3,texto='vamos VOAR',palavras=ps)])
            srt,manifesto=s.publicar()
            m=carregar_tempos_confirmados(manifesto,srt,p/'voz.wav')
            b=ler_srt(srt)[0]
            self.assertEqual(b.texto_normalizado,'Vamos voar')
            self.assertEqual(m[1][1]['texto'],'voar')
            motor=AlinhadorLetraSRT.__new__(AlinhadorLetraSRT)
            palavras=motor._construir_com_manuais(b,1.,3.,None,0,m[1])
            self.assertEqual((palavras[1].inicio,palavras[1].fim),(2.,2.8))
            self.assertEqual(s.blocos[0]['texto'],'vamos VOAR')


if __name__ == '__main__':
    unittest.main()
