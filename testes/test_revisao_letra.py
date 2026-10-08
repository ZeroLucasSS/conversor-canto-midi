import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from revisao_letra import (SessaoRevisao, hash_arquivo, palavras_editor, validar_blocos,
                          carregar_tempos_confirmados, propor_tempos, tempo, MARCA_MANUAL)


def preparar_fixture(pasta):
    (pasta/'letra.srt').write_text('1\n00:00:01,000 --> 00:00:03,000\nVamos voar\n\n'
                                 '2\n00:00:07,000 --> 00:00:09,000\nVamos voar\n',encoding='utf-8')
    (pasta/'letra_consolidada.srt').write_bytes((pasta/'letra.srt').read_bytes())
    (pasta/'letra.txt').write_text('Vamos voar\nLivre para voar\nVamos voar\n',encoding='utf-8')
    (pasta/'voz.wav').write_bytes(b'audio de teste')
    fontes = {k:dict(caminho=str(pasta/nome),sha256=hash_arquivo(pasta/nome))
              for k,nome in [('txt','letra.txt'),('srt','letra.srt'),('voz','voz.wav')]}
    report = dict(versao=5,duracao_audio=12.,fontes=fontes,
                  pendencias=[dict(motivo='texto_txt_sem_tempo',tokens_txt=[2,3,4])],
                  blocos=[dict(inicio=1.,fim=3.,texto='Vamos voar',bloco_original=1),
                          dict(inicio=7.,fim=9.,texto='Vamos voar',bloco_original=2)])
    (pasta/'letra_consolidada.json').write_text(json.dumps(report),encoding='utf-8')


class RevisaoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pasta = Path(self.temp.name)
        preparar_fixture(self.pasta)
        self.s = SessaoRevisao(self.pasta)
        self.id = self.s.itens[0]['id']

    def test_agrupar_ocorrencia_sem_assumir_ausencia(self):
        self.assertEqual(self.s.itens[0]['texto'],'Livre para voar')
        self.assertEqual(len(self.s.itens),1)
        candidatos = self.s.candidatos(dict(texto='Vamos voar'))
        self.assertEqual([c['inicio'] for c in candidatos[:2]],[1.,7.])

    def test_associar_repeticao_correta_sem_duplicar_e_retomar(self):
        self.s.aplicar(self.id,'associar',alvos=['srt:2'])
        nova = SessaoRevisao(self.pasta)
        self.assertEqual(len(nova.blocos),2)
        self.assertEqual(nova.dados['decisoes'][self.id]['alvos'],['srt:2'])
        self.assertFalse(nova.pendentes)
        nova.publicar()
        self.assertEqual((self.pasta/'letra_consolidada.srt').read_text(encoding='utf-8'),
                         (self.pasta/'letra_validada.srt').read_text(encoding='utf-8'))

    def test_descartar_nao_remove_srt(self):
        self.s.aplicar(self.id,'descartar')
        self.assertEqual(self.s.blocos,self.s.base)

    def test_inserir_sem_sobrepor(self):
        self.s.aplicar(self.id,'inserir',novos=[dict(inicio=4.,fim=6.,texto='Livre para voar')])
        self.assertEqual([b['inicio'] for b in self.s.blocos],[1.,4.,7.])

    def test_edicao_invalida_nao_muda_memoria_nem_disco(self):
        self.s.salvar()
        antes = self.s.caminho.read_bytes()
        for a,b in [(2,4),(4,4),(float('nan'),6),(-1,0),(10,13)]:
            with self.assertRaises(ValueError):
                self.s.aplicar(self.id,'inserir',novos=[dict(inicio=a,fim=b,texto='Livre')])
            self.assertEqual(self.s.blocos,self.s.base)
            self.assertEqual(self.s.caminho.read_bytes(),antes)

    def test_corrigir_preserva_tempos_e_desfaz(self):
        self.s.aplicar(self.id,'corrigir',alvos=['srt:1'],novos=[dict(inicio=1,fim=3,texto='Podemos voar')])
        self.assertEqual(self.s.blocos[0]['texto'],'Podemos voar')
        self.s.desfazer()
        self.assertEqual(self.s.blocos,self.s.base)
        self.assertEqual(len(SessaoRevisao(self.pasta).pendentes),1)

    def test_divisao_explicita(self):
        self.s.aplicar(self.id,'substituir',alvos=['srt:1'],novos=[dict(inicio=1,fim=2,texto='Vamos'),
                                                                  dict(inicio=2,fim=3,texto='voar')])
        self.assertEqual(len(self.s.blocos),3)

    def test_remocao_invalida_associacao_anterior(self):
        self.s.aplicar(self.id,'associar',alvos=['srt:1'])
        self.s.aplicar('outra','remover',alvos=['srt:1'])
        self.assertEqual(self.s.dados['decisoes'][self.id]['acao'],'depois')

    def test_rascunho_sem_tempo_nao_publica_insercao(self):
        self.s.dados['rascunhos'][self.id] = dict(texto='Livre',inicio='',fim='')
        self.s.publicar()
        self.assertEqual(len(self.s.blocos),2)
        self.assertEqual(SessaoRevisao(self.pasta).dados['rascunhos'][self.id]['inicio'],'')

    def test_fontes_alteradas_arquiva_e_exige_reconfirmacao(self):
        self.s.aplicar(self.id,'descartar')
        p = self.pasta/'letra_consolidada.srt'
        p.write_text(p.read_text(encoding='utf-8').replace('Vamos','Podemos'),encoding='utf-8')
        nova = SessaoRevisao(self.pasta)
        self.assertTrue(nova.reconciliar)
        self.assertTrue(nova.pendentes)
        self.assertEqual(len(nova.dados['revisoes_anteriores']),1)
        nova.salvar()
        self.assertEqual(len(SessaoRevisao(self.pasta).dados['revisoes_anteriores']),1)

    def test_txt_alterado_sem_reconsolidar_rejeitado(self):
        (self.pasta/'letra.txt').write_text('Nova letra',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Consolide novamente'):
            SessaoRevisao(self.pasta)
        with self.assertRaisesRegex(ValueError,'fontes mudaram'):
            self.s.publicar()

    def test_tempo_confirmado_publicado_e_hash_verificado(self):
        ps = palavras_editor('Livre para voar')
        ps[0].update(inicio=4.1,fim=4.5,confirmado=True)
        self.s.aplicar(self.id,'inserir',novos=[dict(inicio=4,fim=6,texto='Livre para voar',palavras=ps)])
        srt,manifesto = self.s.publicar()
        tempos = carregar_tempos_confirmados(manifesto,srt,self.pasta/'voz.wav')
        self.assertEqual(tempos[2][0]['inicio'],4.1)
        srt.write_text('alterado',encoding='utf-8')
        with self.assertRaises(ValueError):
            carregar_tempos_confirmados(manifesto,srt,self.pasta/'voz.wav')

    def test_excluir_palavra_da_insercao(self):
        ps = palavras_editor('Livre para voar')
        ps[1]['incluir'] = False
        self.s.aplicar(self.id,'inserir',novos=[dict(inicio=4,fim=6,texto='Livre para voar',palavras=ps)])
        self.assertEqual(self.s.blocos[1]['texto'],'Livre voar')

    def test_falta_espaco_para_palavra_automatica(self):
        ps = palavras_editor('Vamos voar')
        ps[0].update(inicio=1,fim=3,confirmado=True)
        with self.assertRaises(ValueError):
            validar_blocos([dict(id='1',inicio=1,fim=3,texto='Vamos voar',palavras=ps)],10)

    def test_alinhador_alternativo_nao_confirma_sugestoes(self):
        class Motor:
            def alinhar(self,texto,inicio,fim):
                return [SimpleNamespace(texto='Livre',inicio=4.1,fim=4.5,score=.7)]
        ps = propor_tempos(Motor(),'Livre para voar',4,6)
        self.assertEqual(ps[0]['inicio'],4.1)
        self.assertFalse(ps[0]['confirmado'])
        self.assertIsNone(ps[1]['inicio'])

    def test_tempos_formatados(self):
        self.assertEqual(tempo('01:42,900'),102.9)
        self.assertEqual(tempo('1:01:42.900'),3702.9)
        for invalido in ['NaN','-2','1:61','1:2:3:4']:
            with self.assertRaises(ValueError):
                tempo(invalido)


class TemposManuaisTest(unittest.TestCase):
    def test_limites_manuais_sobrevivem_fallback_silabas_e_midi(self):
        from alinhamento import AlinhadorLetraSRT
        from letra import BlocoSRT, gerar_silabas_alinhadas
        from tempos_midi import ajustar_tempos_midi
        from dataclasses import dataclass,field
        b = BlocoSRT(1,1,0.,5.,'Eu vou voar','Eu vou voar',False)
        ps = palavras_editor(b.texto_normalizado)
        ps[1].update(inicio=1.4,fim=1.8,confirmado=True)
        ps[2].update(inicio=2.,fim=4.2,confirmado=True)
        motor = AlinhadorLetraSRT.__new__(AlinhadorLetraSRT)
        palavras = motor._construir_com_manuais(b,0.,5.,None,0,ps)
        self.assertEqual([(p.inicio,p.fim) for p in palavras],[(0.,1.4),(1.4,1.8),(2.,4.2)])
        self.assertIsNone(palavras[1].score_modelo)
        silabas = gerar_silabas_alinhadas(palavras)
        @dataclass
        class Nota:
            inicio_nota:float
            fim_nota:float
            palavra_id:str
            bloco_indice:int=1
            motivos_revisao:list=field(default_factory=list)
            ajustes_duracao:list=field(default_factory=list)
            revisao_recomendada:bool=False
        notas = [Nota(s.inicio,s.fim,s.palavra_id,motivos_revisao=list(s.avisos)) for s in silabas]
        with patch('tempos_midi._estender') as estender:
            ajustadas = ajustar_tempos_midi(notas,{},6.)
        estender.assert_not_called()
        self.assertEqual(ajustadas[-1].fim_nota,4.2)
        self.assertIn(MARCA_MANUAL,ajustadas[-1].motivos_revisao)
        self.assertEqual(min(n.inicio_nota for n in ajustadas if n.palavra_id=='b1_p2'),1.4)

    def test_palavra_nao_manual_continua_com_tratamento_original(self):
        from tempos_midi import ajustar_tempos_midi
        from dataclasses import dataclass,field
        @dataclass
        class Nota:
            inicio_nota:float=1.
            fim_nota:float=2.
            palavra_id:str='p1'
            bloco_indice:int=1
            motivos_revisao:list=field(default_factory=list)
            ajustes_duracao:list=field(default_factory=list)
        with patch('tempos_midi._estender') as estender:
            ajustar_tempos_midi([Nota()],{},5.)
        estender.assert_called_once()


class PlayerTest(unittest.TestCase):
    class Stream:
        def __init__(self,**kwargs):
            self.callback=kwargs['callback']
            self.active=False
            self.time=100.
        def start(self): self.active=True
        def abort(self): self.active=False
        def close(self): pass

    def test_relogio_dac_pausa_seek_e_loop(self):
        import numpy as np
        from audio_revisao import PlayerVoz
        p = PlayerVoz(np.arange(1000,dtype=np.float32),100,self.Stream)
        p.reproduzir(2.,4.)
        out = np.zeros((10,1),np.float32)
        p._callback(out,10,SimpleNamespace(outputBufferDacTime=100.2),None)
        self.assertEqual(p.posicao,2.)  # buffer ainda não saiu
        p.stream.time=100.25
        self.assertAlmostEqual(p.posicao,2.05)
        p.pausar()
        self.assertAlmostEqual(p.posicao,2.05)
        p.buscar(5.)
        self.assertEqual(p.posicao,5.)
        p.reproduzir(1.,1.1,True)
        out = np.zeros((25,1),np.float32)
        p._callback(out,25,SimpleNamespace(outputBufferDacTime=100.),None)
        self.assertEqual(list(out[:,0]),list(range(100,110))*2+list(range(100,105)))
        p.stream.time=100.23
        self.assertAlmostEqual(p.posicao,1.03)
        p.fechar()


class FixturesReaisTest(unittest.TestCase):
    def test_tres_musicas_sem_mudar_fontes(self):
        raiz = Path(__file__).resolve().parents[1]/'audios'
        for nome,total,pendentes in [('Evidencias',56,0),('Tempo Perdido',29,0),('Livre Pra Voar',39,74)]:
            pasta=raiz/nome
            if not (pasta/'letra_consolidada.json').exists():
                continue
            with self.subTest(musica=nome):
                s = SessaoRevisao(pasta)
                self.assertEqual(len(s.base),total)
                self.assertEqual(sum(len(i.get('tokens',[])) for i in s.itens),pendentes)
                # Em Livre Pra Voar, as 74 palavras são 19 ocorrências, não
                # 74 novas inserções automáticas.
                if pendentes:
                    self.assertEqual(sum(i['tipo']=='txt' for i in s.itens),19)


class FluxoTest(unittest.TestCase):
    def test_conversor_aguarda_revisao_e_entrega_manifesto(self):
        from conversao_gui import converter
        from threading import Event
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            preparar_fixture(p)
            (p/'instrumental.wav').write_bytes(b'fake')
            chamadas=[]
            def revisar(s):
                chamadas.append('revisao')
                s.aplicar(s.itens[0]['id'],'descartar')
                return s.publicar()
            def tarefas(ts,*args):
                chamadas.append('alinhamento')
                a=ts[0].args
                self.assertIn('--revisao',a)
                self.assertEqual(Path(a[a.index('--srt')+1]).name,'letra_validada.srt')
                saida=Path(a[a.index('--saida')+1])
                saida.mkdir()
                (saida/'alinhamento_completo.json').write_text('{}')
            with patch('conversao_gui._executar'), patch('conversao_gui._executar_tarefas',side_effect=tarefas), \
                 patch('conversao_gui._salvar_conjunto',return_value=SimpleNamespace(dificuldade='beginner')), \
                 patch('conversao_gui._memoria_disponivel',return_value=0):
                converter(p,'teste.mid',Event(),lambda *args:None,revisar=revisar)
            self.assertEqual(chamadas,['revisao','alinhamento'])

    def test_salvar_para_depois_nao_inicia_midi(self):
        from conversao_gui import converter,ConversaoCancelada
        from threading import Event
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            preparar_fixture(p)
            (p/'instrumental.wav').write_bytes(b'fake')
            with patch('conversao_gui._executar'),patch('conversao_gui._executar_tarefas') as tarefas:
                with self.assertRaises(ConversaoCancelada):
                    converter(p,'teste.mid',Event(),lambda *args:None,revisar=lambda s:None)
                tarefas.assert_not_called()


class InterfaceTest(unittest.TestCase):
    def test_janela_rascunho_e_associacao(self):
        import tkinter as tk
        import customtkinter as ctk
        from revisao_interface import JanelaRevisao
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            preparar_fixture(p)
            try:
                root=tk.Tk()
            except tk.TclError as erro:
                self.skipTest(f'Tk indisponível neste ambiente: {erro}')
            root.withdraw()
            aparencia = ctk.get_appearance_mode()
            ctk.set_appearance_mode('Dark')
            try:
                with patch('revisao_interface.threading.Thread.start'):
                    j=JanelaRevisao(root,SessaoRevisao(p))
                j.withdraw()
                root.update_idletasks()
                item=j.sessao.itens[0]['id']
                j.lista.selection_set(item)
                j.selecionar_item()
                j.avancado.set(True)
                j.mostrar_avancado()
                # A tabela deve ser filha do frame que a contém. Um frame
                # irmão criado depois cobre a tabela, embora os dados e até
                # a geometria pareçam corretos em testes sem renderização.
                root.update_idletasks()
                for tabela in (j.lista, j.trechos, j.tabela):
                    self.assertIs(tabela.master, tabela.pack_info()['in'])
                    self.assertTrue(tabela.get_children())
                # Renderizar sem mostrar a janela ao usuário e exercitar a
                # seleção por clique, não apenas alterar dados do Treeview.
                j.attributes('-alpha', 0)
                j.deiconify()
                root.update()
                self.assertEqual(ctk.get_appearance_mode(), 'Dark')
                self.assertEqual(j.cget('fg_color'), '#ffffff')
                self.assertEqual(j.texto.cget('background'), '#ffffff')
                self.assertEqual(set(j.botoes_decisao), {'associar', 'corrigir', 'inserir', 'descartar', 'depois', 'remover'})
                for tabela in (j.lista, j.trechos, j.tabela):
                    self.assertTrue(tabela.winfo_ismapped())
                    primeira = tabela.get_children()[0]
                    self.assertTrue(tabela.bbox(primeira))
                j.lista.selection_remove(*j.lista.selection())
                x,y,w,h = j.lista.bbox(item)
                j.lista.event_generate('<Button-1>', x=x+40, y=y+h//2)
                j.lista.event_generate('<ButtonRelease-1>', x=x+40, y=y+h//2)
                root.update()
                self.assertEqual(j.lista.selection(), (item,))
                self.assertIn('Livre para voar', j.contexto.get('1.0', 'end'))
                # Trocar para a legenda completa mantém o rascunho da frase.
                j.texto.delete('1.0', 'end')
                j.texto.insert('1.0', 'Rascunho preservado')
                j.filtro.set('Legenda completa')
                j.filtrar_lista()
                root.update()
                self.assertEqual(len(j.lista.get_children()), 2)
                j.proxima_pendencia()
                root.update()
                self.assertEqual(j.item['id'], item)
                self.assertEqual(j.texto.get('1.0', 'end-1c'), 'Rascunho preservado')
                j.geometry('1000x720')
                j.ir_para(j.acoes)
                root.update()
                for b in j.botoes_decisao.values():
                    self.assertGreater(b.winfo_width(), 100)
                    self.assertLessEqual(b.winfo_rootx()+b.winfo_width(), j.winfo_rootx()+j.winfo_width())
                j.trechos.selection_set('srt:2')
                j.aplicar('associar')
                self.assertFalse(j.sessao.pendentes)
                j.salvar_sair()
                nova=SessaoRevisao(p)
                self.assertIn(item,nova.dados['rascunhos'])
            finally:
                root.destroy()
                ctk.set_appearance_mode(aparencia)


if __name__ == '__main__':
    unittest.main()
