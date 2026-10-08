"""Integração do fluxo sem carregar modelos acústicos."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import consolidar_letra as c
import conversao_gui as gui


SRT = "1\n00:00:01,000 --> 00:00:02,000\nBom dia\n"


class IntegracaoTest(unittest.TestCase):
    def test_auditoria_segue_fonte_consolidada_e_rejeita_alteracao(self):
        from gerar_midi_silabico import fonte_srt_alinhamento
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            self.preparar(pasta)
            consolidada = pasta / "letra_consolidada.srt"
            consolidada.write_text(SRT + "\n", encoding="utf-8")
            dados = {"metadados": {"arquivo_srt": str(consolidada),
                     "sha256_srt": hashlib.sha256(consolidada.read_bytes()).hexdigest()}}
            self.assertEqual(fonte_srt_alinhamento(dados, pasta), consolidada)
            consolidada.write_text("alterada")
            with self.assertRaisesRegex(ValueError, "mudou"):
                fonte_srt_alinhamento(dados, pasta)
            self.assertEqual(fonte_srt_alinhamento({}, pasta), pasta / "letra.srt")

    def preparar(self, pasta):
        for nome in ("voz.wav", "instrumental.wav", "letra.txt"):
            (pasta / nome).write_text("Bom dia", encoding="utf-8")
        (pasta / "letra.srt").write_text(SRT, encoding="utf-8")

    def test_txt_obrigatorio(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            self.preparar(pasta)
            self.assertIn("letra_txt", gui.validar_pasta(pasta))
            (pasta / "letra.txt").unlink()
            with self.assertRaisesRegex(ValueError, "letra.txt"):
                gui.validar_pasta(pasta)

    def test_fluxo_usa_consolidada_apos_consolidacao_com_avisos(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            self.preparar(pasta)
            chamadas = []
            def executar(tarefas, projeto, cancelar, emitir):
                for t in tarefas:
                    chamadas.append(t.script.name)
                    if t.script.name == "consolidar_letra.py":
                        self.assertIn("--atualizar", t.args)
                        (pasta / "letra_consolidada.srt").write_text(SRT, encoding="utf-8")
                        (pasta / "letra_consolidada.json").write_text('{"status":"pendente"}')
                    elif t.script.name == "preparar_letra.py":
                        self.assertEqual(Path(t.args[t.args.index("--srt") + 1]), pasta / "letra_consolidada.srt")
                        destino = Path(t.args[t.args.index("--saida") + 1])
                        destino.mkdir()
                        (destino / "alinhamento_completo.json").write_text("{}")
            with patch.object(gui, "_executar_tarefas", side_effect=executar), \
                 patch.object(gui, "_memoria_disponivel", return_value=None), \
                 patch.object(gui, "_salvar_conjunto", return_value=gui.ResultadoConversao(pasta / "teste.mid", pasta / "teste.srt", pasta / "teste.json", "beginner")):
                gui.converter(pasta, "teste.mid", Event(), lambda *args: None)
            self.assertEqual(chamadas, ["consolidar_letra.py", "preparar_letra.py", "gerar_midi_silabico.py"])

    def test_atualizacao_substitui_apenas_derivados(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            self.preparar(pasta)
            destino = pasta / "letra_consolidada.srt"
            destino.write_text("antigo")
            destino.with_suffix(".json").write_text("antigo")
            r = {"status": "pendente", "blocos": [{"inicio": 1, "fim": 2, "texto": "novo"}], "resumo_avisos": ["aviso"]}
            c.publicar(r, destino, atualizar=True)
            self.assertEqual(c.ler_srt(destino)[0].texto, "Novo")
            self.assertEqual((pasta / "letra.srt").read_text(encoding="utf-8"), SRT)
            with self.assertRaises(ValueError):
                c.publicar(r, pasta / "letra.srt", atualizar=True)

    def test_falha_de_consolidacao_nao_usa_resultado_antigo(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            self.preparar(pasta)
            (pasta / "letra_consolidada.srt").write_text(SRT)
            with patch.object(gui, "_executar_tarefas", side_effect=RuntimeError("falha")) as executar:
                with self.assertRaises(RuntimeError):
                    gui.converter(pasta, "teste.mid", Event(), lambda *args: None)
                self.assertEqual(executar.call_count, 1)


if __name__ == "__main__":
    unittest.main()
