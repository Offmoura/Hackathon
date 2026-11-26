"""Testes unitários de tokens assinados, expiração, uso único e adulteração."""

import time

import pytest

from app.tokens import (
    TokenExpiradoError,
    TokenInvalidoError,
    TokenJaUsadoError,
    TokenManager,
)


def test_token_valido_e_uso_unico() -> None:
    manager = TokenManager(secret_key="segredo-teste", ttl_seconds=60)
    token = manager.criar_token("5511999990000")

    payload = manager.validar_token(token)
    assert payload.conversa_id == "5511999990000"

    consumido = manager.consumir_token(token)
    assert consumido.jti == payload.jti

    with pytest.raises(TokenJaUsadoError):
        manager.validar_token(token)

    with pytest.raises(TokenJaUsadoError):
        manager.consumir_token(token)


def test_token_expirado() -> None:
    manager = TokenManager(secret_key="segredo-teste", ttl_seconds=0)
    token = manager.criar_token("5511999990000")
    time.sleep(1.1)

    with pytest.raises(TokenExpiradoError):
        manager.validar_token(token)


def test_token_adulterado() -> None:
    manager = TokenManager(secret_key="segredo-teste", ttl_seconds=60)
    token = manager.criar_token("5511999990000")
    # Altera o primeiro caractere do payload para garantir corrupção determinística
    adulterado = ("A" if token[0] != "A" else "B") + token[1:]

    with pytest.raises(TokenInvalidoError):
        manager.validar_token(adulterado)
