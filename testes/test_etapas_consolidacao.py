"""Regressões das três etapas, sem depender de gravações ou modelos."""
import unittest
import json
import numpy as np
import consolidar_letra as c


class Motor:
    nome = 'teste'
    duracao_audio = 200.

    def __init__(self, palavras=()):
        self.palavras = list(palavras)
        self.chamadas = []

    def alinhar(self, texto, inicio, fim):
        self.chamadas.append((texto, inicio, fim))
        return self.palavras


class EtapasTest(unittest.TestCase):
    def test_contexto_anterior_distingue_variantes_proximas(self):
        bs=[c.Bloco(1,1,3,'Entrada'),c.Bloco(2,4,6,'vida bela')]
        plano=c.planejar_estrutura(bs,'Entrada\nvida nova\nFim\nvida pura')
        self.assertEqual(plano['consultas'][1]['texto'],'vida nova')

    def test_resultados_numpy_sao_publicaveis_em_json(self):
        m=Motor([c.PalavraTemporal('amor',np.float64(4),np.float64(5),np.float64(.25))])
        r=c.consolidar([c.Bloco(1,1,3,'Bom dia'),c.Bloco(2,9,11,'Até logo')],
                      'Bom dia\namor\nAté logo',m)
        json.dumps(r,allow_nan=False)
        self.assertEqual(r['metricas']['palavras_baixa_confianca'],1)

    def test_corrige_palavra_dividida_sem_alterar_tempo(self):
        bs = [c.Bloco(15,129.35,133.21,'Me diz mais uma vez que já estamos'),
              c.Bloco(16,133.21,138.39,'Diz antes de tudo')]
        m = Motor()
        r = c.consolidar(bs,'Me diz mais uma vez que já estamos\nDistantes de tudo',m)
        self.assertEqual(r['blocos'][1]['texto'],'Distantes de tudo')
        self.assertEqual((r['blocos'][1]['inicio'],r['blocos'][1]['fim']),(133.21,138.39))
        self.assertFalse(m.chamadas)

    def test_tres_repeticoes_na_lacuna_maior_que_doze_segundos(self):
        bs = [c.Bloco(1,133.21,138.39,'Diz antes de tudo'),
              c.Bloco(2,154.93,160.29,'Não tenho medo do escuro')]
        frase = 'Temos nosso próprio tempo'
        txt = 'Distantes de tudo\n' + (frase+'\n')*3 + 'Não tenho medo do escuro'
        ps = [c.PalavraTemporal(w,139+grupo*4+j*.6,139.4+grupo*4+j*.6,.9)
              for grupo in range(3) for j,w in enumerate(frase.split())]
        m = Motor(ps)
        r = c.consolidar(bs,txt,m)
        novos = [b for b in r['blocos'] if b['origem']=='insercao_acustica']
        self.assertEqual([b['texto'] for b in novos],[frase]*3)
        self.assertEqual(len(m.chamadas),1)
        self.assertEqual(m.chamadas[0][1:],(138.39,154.93))
        self.assertEqual(r['metricas']['palavras_txt_sem_tempo'],0)
        self.assertEqual(r['recuperacoes'][0]['estado'],'recuperado')

    def test_publica_parcial_sem_inventar_palavra_ausente(self):
        bs=[c.Bloco(1,1,3,'Bom dia'),c.Bloco(2,9,11,'Até logo')]
        m=Motor([c.PalavraTemporal('vida',4,5,.9),c.PalavraTemporal('e',None,None,None),
                 c.PalavraTemporal('amor',6,7,.1)])
        r=c.consolidar(bs,'Bom dia\nvida e amor\nAté logo',m)
        self.assertEqual([b['texto'] for b in r['blocos']],['Bom dia','vida','amor','Até logo'])
        self.assertEqual(r['recuperacoes'][0]['estado'],'parcialmente_recuperado')
        self.assertEqual(r['metricas']['palavras_txt_pesquisadas_sem_tempo'],1)
        self.assertTrue(any('baixa confiança' in a for a in r['resumo_avisos']))

    def test_falha_motor_nao_impede_originais(self):
        bs=[c.Bloco(1,1,3,'Bom dia'),c.Bloco(2,9,11,'Até logo')]
        class Falha(Motor):
            def alinhar(self,*args):raise RuntimeError('falha')
        r=c.consolidar(bs,'Bom dia\namor\nAté logo',Falha())
        self.assertEqual(len(r['blocos']),2)
        self.assertEqual(r['recuperacoes'][0]['estado'],'pesquisado_sem_confirmacao')

    def test_blocos_contiguos_nao_recebem_tempo_inventado(self):
        bs=[c.Bloco(1,1,3,'Bom dia'),c.Bloco(2,3,5,'Até logo')]
        m=Motor()
        r=c.consolidar(bs,'Bom dia\namor\nAté logo',m)
        self.assertFalse(m.chamadas)
        self.assertEqual(r['recuperacoes'][0]['estado'],'nao_pesquisado')
        self.assertEqual(r['metricas']['palavras_txt_nao_pesquisadas'],1)

    def test_silencio_nao_confirma_alinhamento_forcado(self):
        bs=[c.Bloco(1,1,3,'Bom dia'),c.Bloco(2,9,11,'Até logo')]
        m=Motor([c.PalavraTemporal('amor',4,5,.9)])
        m.audio=np.zeros(12*16000,dtype=np.float32)
        r=c.consolidar(bs,'Bom dia\namor\nAté logo',m)
        self.assertEqual(r['metricas']['blocos_inseridos'],0)
        self.assertEqual(r['recuperacoes'][0]['estado'],'pesquisado_sem_confirmacao')

    def test_nao_estica_nem_apaga_original_quando_txt_tem_frase_extra(self):
        bs=[c.Bloco(1,1,3,'Bom dia'),c.Bloco(2,9,11,'Até logo')]
        r=c.consolidar(bs,'Bom dia\namor\nAté logo',Motor())
        self.assertEqual([(b['inicio'],b['fim']) for b in r['blocos']],[(1,3),(9,11)])

    def test_trecho_exclusivo_srt_nao_e_atravessado(self):
        bs=[c.Bloco(1,1,3,'Bom dia'),c.Bloco(2,4,8,'fala improvisada'),c.Bloco(3,9,11,'Até logo')]
        m=Motor()
        r=c.consolidar(bs,'Bom dia\namor\nAté logo',m)
        self.assertFalse(m.chamadas)
        self.assertEqual([b['texto'] for b in r['blocos']],['Bom dia','fala improvisada','Até logo'])


if __name__ == '__main__':unittest.main()
