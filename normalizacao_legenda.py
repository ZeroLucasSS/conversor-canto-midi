"""Capitalização visual dos blocos publicados, sem alterar as fontes."""


def normalizar_frase(texto: str) -> str:
    """Primeira letra maiúscula; todas as demais minúsculas.

    Pontuação, números e espaços são preservados. Aspas ou reticências
    iniciais não impedem a capitalização da primeira letra da frase.
    """
    texto = texto.lower()
    for i, caractere in enumerate(texto):
        if caractere.isalpha():
            return texto[:i] + caractere.upper() + texto[i + 1:]
    return texto
