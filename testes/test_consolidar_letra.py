"""Contrato do consolidador; não carrega modelos nem usa a rede.

python -m unittest discover -s testes -p test_consolidar_letra.py -v
"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import consolidar_letra as c


class MotorGravado:
    """Respostas temporais explícitas, independentes da janela solicitada."""
    nome = "teste"
    duracao_audio = 20.0

    def __init__(self, palavras):
        self.palavras = palavras
        self.chamadas = []

    def alinhar(self, texto, inicio, fim):
        self.chamadas.append((texto, inicio, fim))
        return self.palavras


def palavra(texto, a, b, score=0.9):
    return c.PalavraTemporal(texto, a, b, score)


class ConsolidacaoTest(unittest.TestCase):
    def test_uniao_escolhe_alternativa_que_preserva_proxima_palavra(self):
        opcoes = [[palavra("vida", 1, 3, .95), palavra("vida", 1, 2, .8)],
                  [palavra("nova", 2.1, 2.9, .9)]]
        escolhidas = c.escolher_tempos(opcoes, 0, 4)
        self.assertEqual([p.texto for p in escolhidas], ["vida", "nova"])
        self.assertEqual(escolhidas[0].fim, 2)

    def test_uniao_nao_inventa_tempo_para_palavra_ausente(self):
        escolhidas = c.escolher_tempos([[palavra("vida", 1, 2)], [], [palavra("nova", 3, 4)]], 0, 5)
        self.assertIsNone(escolhidas[1])
        self.assertEqual(escolhidas[2].inicio, 3)

    def test_janelas_menores_tem_contexto_sem_duplicar_tokens(self):
        blocos = [c.Bloco(i, i * 5, i * 5 + 5, "exemplo") for i in range(10)]
        ancoras = [{"a": i * 10, "b": i * 10 + 10, "bloco": i} for i in range(10)]
        partes = c.dividir_regioes([{"a": 0, "b": 100}], ancoras, blocos)
        self.assertGreater(len(partes), 1)
        self.assertEqual([i for p in partes for i in range(p['alvo_a'], p['alvo_b'])], list(range(100)))
        self.assertTrue(all(p['b'] > p['alvo_b'] for p in partes[:-1]))
        self.assertTrue(all(blocos[p['b'] // 10 - 1].fim - blocos[p['a'] // 10].inicio <= 18 for p in partes))

    def test_grafia_pontuacao_e_quebras_preservam_tempos(self):
        blocos = [c.Bloco(1, 1, 4, "nao tenho"), c.Bloco(2, 5, 7, "medo")]
        motor = MotorGravado([])
        r = c.consolidar(blocos, "Não\ntenho medo!", motor)
        self.assertEqual(r["status"], "consolidado")
        self.assertEqual(motor.chamadas, [])
        self.assertEqual([(b["inicio"], b["fim"]) for b in r["blocos"]], [(1, 4), (5, 7)])
        self.assertEqual(" ".join(b["texto"] for b in r["blocos"]), "Não tenho medo!")

    def test_recupera_frase_inteira_sem_inventar_tempos(self):
        blocos = [c.Bloco(1, 1, 3, "Bom dia"), c.Bloco(2, 9, 11, "Até logo")]
        ps = [palavra("Bom", 1, 1.4), palavra("dia", 2, 3),
              palavra("Muito", 5, 5.5), palavra("amor", 6, 7),
              palavra("Até", 9, 9.5), palavra("logo", 10, 11)]
        r = c.consolidar(blocos, "Bom dia\nMuito amor\nAté logo", MotorGravado(ps))
        self.assertEqual(r["status"], "consolidado")
        self.assertEqual((r["blocos"][1]["inicio"], r["blocos"][1]["fim"]), (5, 7))
        self.assertEqual(sum(op["tipo"] == "ausente_srt" for op in r["comparacao"]["operacoes"]), 2)

    def test_omissao_dentro_de_blocos_contiguos_reconstroi_vizinhos(self):
        blocos = [c.Bloco(1, 1, 6, "Bom dia"), c.Bloco(2, 6, 11, "Até logo")]
        ps = [palavra("Bom", 1, 1.4), palavra("dia", 2, 3), palavra("amor", 4, 5),
              palavra("Até", 6, 7), palavra("logo", 10, 11)]
        motor = MotorGravado(ps)
        r = c.consolidar(blocos, "Bom dia\namor\nAté logo", motor)
        self.assertEqual(r["status"], "consolidado")
        self.assertEqual(r["blocos"][0]["fim"], 3)
        self.assertEqual(r["blocos"][1]["inicio"], 4)
        self.assertIn("Bom dia amor Até logo", motor.chamadas[0])

    def test_erros_e_pausas_nao_recebem_fallback(self):
        blocos = [c.Bloco(1, 1, 3, "Bom dia"), c.Bloco(2, 9, 11, "Até logo")]
        r = c.consolidar(blocos, "Bom dia\namor\nAté logo", MotorGravado([]))
        self.assertEqual(r["status"], "pendente")
        self.assertEqual([b["texto"] for b in r["blocos"]], ["Bom dia", "Até logo"])
        self.assertTrue(any(p["motivo"] == "cobertura_textual_incompleta" for p in r["pendencias"]))

    def test_substituicao_exige_alinhamento(self):
        blocos = [c.Bloco(1, 1, 4, "vida bela")]
        motor = MotorGravado([palavra("vida", 1, 2), palavra("nova", 3, 4)])
        r = c.consolidar(blocos, "vida nova", motor)
        self.assertEqual(r["status"], "consolidado")
        self.assertEqual(r["blocos"][0]["texto"], "vida nova")
        self.assertEqual(len(motor.chamadas), 1)

    def test_substituicao_de_duas_palavras_por_uma(self):
        blocos = [c.Bloco(1, 1, 4, "diz antes de tudo")]
        motor = MotorGravado([palavra("distantes", 1, 2), palavra("de", 2.5, 3),
                              palavra("tudo", 3, 4)])
        r = c.consolidar(blocos, "distantes de tudo", motor)
        self.assertEqual(r["status"], "consolidado")
        self.assertEqual(r["comparacao"]["divergencias"][0]["texto_srt"], "diz antes")

    def test_refrão_omitido_nao_escolhe_ocorrencia_arbitraria(self):
        _, _, comp = c.preparar_comparacao([c.Bloco(1, 1, 4, "Meu amor")], "Meu amor\nMeu amor")
        self.assertTrue(comp["txt_ambiguos"])
        motor = MotorGravado([palavra("Meu", 1, 2), palavra("amor", 3, 4),
                              palavra("Meu", 6, 7), palavra("amor", 8, 9)])
        r = c.consolidar([c.Bloco(1, 1, 4, "Meu amor")], "Meu amor\nMeu amor", motor)
        self.assertEqual(r["status"], "pendente")

    def test_repeticoes_completas_mantem_ocorrencias(self):
        blocos = [c.Bloco(1, 1, 3, "Meu amor"), c.Bloco(2, 6, 8, "Meu amor")]
        r = c.consolidar(blocos, "Meu amor\nMeu amor", MotorGravado([]))
        self.assertEqual(r["status"], "consolidado")
        self.assertEqual(len(r["blocos"]), 2)

    def test_texto_exclusivo_srt_nao_e_descartado_silenciosamente(self):
        blocos = [c.Bloco(1, 1, 3, "Bom dia"), c.Bloco(2, 5, 6, "extra")]
        r = c.consolidar(blocos, "Bom dia", MotorGravado([]))
        self.assertEqual(r["status"], "pendente")
        self.assertEqual(r["pendencias"][0]["motivo"], "texto_exclusivo_srt_exige_revisao")

    def test_inicio_e_final_sem_ancora_temporal(self):
        for txt, ps in [
            ("Olá\nBom dia", [palavra("Olá", .5, 1), palavra("Bom", 5, 6), palavra("dia", 7, 8)]),
            ("Bom dia\nAdeus", [palavra("Bom", 5, 6), palavra("dia", 7, 8), palavra("Adeus", 12, 13)])]:
            with self.subTest(txt=txt):
                r = c.consolidar([c.Bloco(1, 5, 8, "Bom dia")], txt, MotorGravado(ps))
                self.assertEqual(r["status"], "consolidado")

    def test_janela_maxima_nao_forca_musica_inteira(self):
        motor = MotorGravado([])
        motor.duracao_audio = 300
        r = c.consolidar([c.Bloco(1, 1, 4, "velho")], "novo", motor, janela_maxima=2)
        self.assertEqual(motor.chamadas, [])
        self.assertEqual(r["status"], "pendente")

    def test_motor_falha_relatorio_preserva_pendencia(self):
        motor = MotorGravado([])
        with patch.object(motor, "alinhar", side_effect=RuntimeError("falha de teste")):
            r = c.consolidar([c.Bloco(1, 1, 4, "velho")], "novo", motor)
        self.assertEqual(r["status"], "pendente")
        self.assertIn("falha de teste", r["tentativas"][0]["erro"])

    def test_contexto_nao_pode_migrar_para_outra_regiao(self):
        blocos = [c.Bloco(1, 1, 3, "Bom dia"), c.Bloco(2, 15, 17, "Até logo")]
        motor = MotorGravado([palavra("Bom", 7, 8), palavra("dia", 8, 9),
                              palavra("amor", 10, 11), palavra("Até", 15, 16),
                              palavra("logo", 16, 17)])
        r = c.consolidar(blocos, "Bom dia\namor\nAté logo", motor)
        self.assertEqual(r["status"], "pendente")
        self.assertEqual(r["tentativas"][0]["erro"], "contexto_deslocado_da_referencia_srt")

    def test_rejeita_palavras_omitidas_nan_score_baixo_e_sobreposicao(self):
        base = [palavra("Bom", 1, 2), palavra("dia", 3, 4)]
        invalidos = [base[:1], [replace(base[0], inicio=None), base[1]],
                     [replace(base[0], score=float("nan")), base[1]],
                     [replace(base[0], score=.1), base[1]],
                     [base[0], replace(base[1], inicio=1.5)],
                     [base[0], replace(base[1], fim=6)],
                     [replace(base[0], texto="outro"), base[1]]]
        for ps in invalidos:
            with self.subTest(ps=ps):
                self.assertIsNotNone(c.validar_alinhamento(ps, ["Bom", "dia"], 0, 5, .3))
        self.assertIsNone(c.validar_alinhamento(base, ["Bom", "dia"], 0, 5, .3))

    def test_entrada_e_saida_preservadas_e_srt_relegivel(self):
        with tempfile.TemporaryDirectory() as pasta:
            p = Path(pasta)
            srt = p / "letra.srt"
            srt.write_text("1\n00:00:01,000 --> 00:00:04,000\nBom dia\n", encoding="utf-8")
            original = srt.read_bytes()
            r = c.consolidar(c.ler_srt(srt), "Bom dia!", MotorGravado([]))
            saida = p / "letra_consolidada.srt"
            c.publicar(r, saida)
            self.assertEqual(c.ler_srt(saida)[0].texto, "Bom dia!")
            self.assertEqual(srt.read_bytes(), original)
            with self.assertRaises(FileExistsError):
                c.publicar(r, saida)
            self.assertEqual(json.loads(saida.with_suffix(".json").read_text(encoding="utf-8"))["status"], "consolidado")

    def test_pendente_publica_srt_e_json(self):
        with tempfile.TemporaryDirectory() as pasta:
            saida = Path(pasta) / "letra_consolidada.srt"
            r = c.consolidar([c.Bloco(1, 1, 4, "Bom dia")], "Bom dia\namor", MotorGravado([]))
            c.publicar(r, saida)
            self.assertTrue(saida.exists())
            self.assertEqual(c.ler_srt(saida)[0].texto, "Bom dia")
            self.assertTrue(saida.with_suffix(".json").exists())

    def test_score_baixo_mantem_palavra_e_frase_no_srt(self):
        motor = MotorGravado([palavra("vida", 1, 2), palavra("e", 2, 2.1, 0.0),
                              palavra("amor", 3, 4)])
        r = c.consolidar([c.Bloco(1, 1, 4, "vida com amor")], "vida e amor", motor)
        self.assertEqual(r["status"], "pendente")
        self.assertEqual(r["blocos"][0]["texto"], "vida e amor")
        self.assertEqual(len(r["resumo_avisos"]), 1)
        self.assertIn("'e'", r["resumo_avisos"][0])
        with tempfile.TemporaryDirectory() as pasta:
            saida = Path(pasta) / "teste.srt"
            r["fontes"] = {}
            c.publicar(r, saida)
            self.assertEqual(c.ler_srt(saida)[0].texto, "vida e amor")
            dados = json.loads(saida.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(list(dados)[-1], "resumo_avisos")

    def test_palavra_sem_tempo_nao_descarta_as_demais(self):
        for ps in ([palavra("vida", 1, 2), palavra("e", None, None), palavra("amor", 3, 4)],
                   [palavra("vida", 1, 2), palavra("amor", 3, 4)]):
            with self.subTest(ps=ps):
                r = c.consolidar([c.Bloco(1, 1, 4, "vida com amor")], "vida e amor", MotorGravado(ps))
                self.assertEqual([b["texto"] for b in r["blocos"]], ["vida", "amor"])
                self.assertTrue(any("Omitida" in a and "'e'" in a for a in r["resumo_avisos"]))

    def test_cli_pendencias_publicam_com_codigo_zero(self):
        with tempfile.TemporaryDirectory() as pasta:
            p = Path(pasta)
            (p / "letra.srt").write_text("1\n00:00:01,000 --> 00:00:04,000\nvida com amor", encoding="utf-8")
            (p / "letra.txt").write_text("vida e amor", encoding="utf-8")
            (p / "voz.wav").write_bytes(b"teste")
            motor = MotorGravado([palavra("vida", 1, 2), palavra("e", 2, 2.1, .1), palavra("amor", 3, 4)])
            motor.dispositivo = "teste"
            with patch.object(c, "AlinhadorWhisperX", return_value=motor):
                self.assertEqual(c.main([str(p)]), 0)
            self.assertTrue((p / "letra_consolidada.srt").exists())

    def test_srt_sobreposto_e_txt_com_rotulos_rejeitados(self):
        with tempfile.TemporaryDirectory() as pasta:
            p = Path(pasta)
            srt = p / "letra.srt"
            srt.write_text("1\n00:00:01,000 --> 00:00:04,000\nBom\n\n2\n00:00:03,000 --> 00:00:05,000\ndia", encoding="utf-8")
            with self.assertRaises(ValueError):
                c.ler_srt(srt)
            txt = p / "letra.txt"
            txt.write_text("[Refrão]\nBom dia", encoding="utf-8")
            with self.assertRaises(ValueError):
                c.ler_txt(txt)

    def test_cli_comparacao_nao_carrega_whisperx(self):
        with tempfile.TemporaryDirectory() as pasta:
            p = Path(pasta)
            (p / "letra.srt").write_text("1\n00:00:01,000 --> 00:00:04,000\nBom dia", encoding="utf-8")
            (p / "letra.txt").write_text("Bom dia\nAmor", encoding="utf-8")
            with patch.object(c, "AlinhadorWhisperX", side_effect=AssertionError("não carregar")):
                self.assertEqual(c.main([str(p), "--somente-comparar"]), 0)
            self.assertFalse((p / "letra_consolidada.srt").exists())

    def test_cli_srt_sem_tempo_final_falha_sem_publicar(self):
        with tempfile.TemporaryDirectory() as pasta:
            p = Path(pasta)
            (p / "letra.srt").write_text("1\n00:00:01,000 -->\nBom dia", encoding="utf-8")
            (p / "letra.txt").write_text("Bom dia", encoding="utf-8")
            with patch.object(c, "AlinhadorWhisperX", side_effect=AssertionError("não carregar")):
                self.assertEqual(c.main([str(p), "--somente-comparar"]), 1)
            self.assertFalse((p / "letra_consolidada.json").exists())

    def test_adaptador_whisperx_pede_tempos_sem_interpolacao(self):
        from unittest.mock import Mock
        motor = c.AlinhadorWhisperX.__new__(c.AlinhadorWhisperX)
        motor.wx = Mock()
        motor.modelo, motor.meta, motor.audio, motor.dispositivo = object(), {}, object(), "cpu"
        motor.wx.align.return_value = {"word_segments": [
            {"word": "Bom", "start": 10.2, "end": 10.8, "score": .9},
            {"word": "dia"}]}
        palavras = motor.alinhar("Bom dia", 10, 15)
        args, kwargs = motor.wx.align.call_args
        self.assertEqual(args[0], [{"text": "Bom dia", "start": 10, "end": 15}])
        self.assertEqual(kwargs["interpolate_method"], "ignore")
        self.assertEqual(palavras[0].inicio, 10.2)
        self.assertIsNone(palavras[1].inicio)
        self.assertIsNotNone(c.validar_alinhamento(palavras, ["Bom", "dia"], 10, 15, .3))


if __name__ == "__main__":
    unittest.main()
