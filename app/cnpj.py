"""Validação e formatação determinística de CNPJ (sem uso de IA)."""

from __future__ import annotations

import re


def limpar_cnpj(cnpj: str) -> str:
    """Remove qualquer caractere não numérico do CNPJ."""
    return re.sub(r"\D", "", cnpj or "")


def formatar_cnpj(cnpj: str) -> str:
    """Formata 14 dígitos no padrão 00.000.000/0000-00."""
    digitos = limpar_cnpj(cnpj)
    if len(digitos) != 14:
        return cnpj.strip()
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def _calcular_digito(base: str, pesos: list[int]) -> int:
    soma = sum(int(d) * p for d, p in zip(base, pesos, strict=True))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def validar_cnpj(cnpj: str) -> bool:
    """Valida se o CNPJ possui 14 dígitos, não é sequência repetida e tem DVs válidos."""
    digitos = limpar_cnpj(cnpj)
    if len(digitos) != 14:
        return False

    # Rejeita sequências com todos os dígitos iguais (ex.: 00000000000000, 11111111111111)
    if digitos == digitos[0] * 14:
        return False

    pesos_primeiro = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos_segundo = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    dv1 = _calcular_digito(digitos[:12], pesos_primeiro)
    dv2 = _calcular_digito(digitos[:12] + str(dv1), pesos_segundo)

    return digitos[-2:] == f"{dv1}{dv2}"
