"""Testes unitários de validação e formatação de CNPJ."""

from app.cnpj import formatar_cnpj, limpar_cnpj, validar_cnpj


def test_cnpj_valido_com_e_sem_pontuacao() -> None:
    assert validar_cnpj("11.222.333/0001-81") is True
    assert validar_cnpj("11222333000181") is True
    assert validar_cnpj("11.444.777/0001-61") is True
    assert validar_cnpj("11444777000161") is True
    assert validar_cnpj("12.345.678/0001-95") is True


def test_cnpj_invalido_digito_verificador() -> None:
    assert validar_cnpj("11.222.333/0001-82") is False
    assert validar_cnpj("11222333000180") is False
    assert validar_cnpj("11.444.777/0001-60") is False


def test_cnpj_invalido_sequencia_repetida_ou_tamanho() -> None:
    assert validar_cnpj("00.000.000/0000-00") is False
    assert validar_cnpj("11111111111111") is False
    assert validar_cnpj("123456") is False
    assert validar_cnpj("") is False
    assert validar_cnpj("abcdefghijklmn") is False


def test_limpar_e_formatar_cnpj() -> None:
    assert limpar_cnpj("11.222.333/0001-81") == "11222333000181"
    assert formatar_cnpj("11222333000181") == "11.222.333/0001-81"
