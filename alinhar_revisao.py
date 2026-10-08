"""Worker cancelável de alinhamento local, sem acesso à interface."""
import argparse
import json
from pathlib import Path
from consolidar_letra import AlinhadorWhisperX
from revisao_letra import propor_tempos, gravar_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('pedido', type=Path)
    parser.add_argument('saida', type=Path)
    args = parser.parse_args()
    pedido = json.loads(args.pedido.read_text(encoding='utf-8'))
    motor = AlinhadorWhisperX(Path(pedido['voz']), pasta_modelos=Path(__file__).parent / 'modelos' / 'alinhamento')
    palavras = propor_tempos(motor, pedido['texto'], pedido['inicio'], pedido['fim'])
    gravar_json(args.saida, palavras)


if __name__ == '__main__':
    main()
