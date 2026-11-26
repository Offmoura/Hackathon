"""Testes unitários do cliente LLM (Ollama) e fallback para Revisar."""

import asyncio
import json

import httpx

from app.config import Settings
from app.llm import FALLBACK_CATEGORIA, classificar_chamado


def _settings_teste(threshold: float = 0.6) -> Settings:
    return Settings(
        DEMO_MODE=True,
        OLLAMA_URL="http://ollama.local:11434",
        MODEL_NAME="llama3.1:8b",
        CONFIDENCE_THRESHOLD=threshold,
    )


def test_llm_classificacao_valida() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "response": json.dumps(
                {
                    "categoria": "Boleto",
                    "prioridade": "média",
                    "resumo": "Cliente pede segunda via de boleto.",
                    "confianca": 0.91,
                }
            )
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    resultado = asyncio.run(
        classificar_chamado(
            "Preciso da segunda via do boleto que vence amanhã.",
            settings=_settings_teste(),
            transport=transport,
        )
    )

    assert resultado.categoria == "Boleto"
    assert resultado.prioridade == "média"
    assert resultado.classificacao_automatica is True
    assert resultado.aviso is None


def test_llm_falha_rede_cai_em_revisar() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Ollama indisponível", request=request)

    transport = httpx.MockTransport(handler)
    resultado = asyncio.run(
        classificar_chamado(
            "Preciso de ajuda com minha fatura.",
            settings=_settings_teste(),
            transport=transport,
        )
    )

    assert resultado.categoria == FALLBACK_CATEGORIA
    assert resultado.classificacao_automatica is False
    assert resultado.aviso is not None


def test_llm_json_invalido_cai_em_revisar() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "Desculpe, não entendi o pedido."})

    transport = httpx.MockTransport(handler)
    resultado = asyncio.run(
        classificar_chamado(
            "Quero falar sobre meu contrato.",
            settings=_settings_teste(),
            transport=transport,
        )
    )

    assert resultado.categoria == FALLBACK_CATEGORIA
    assert resultado.classificacao_automatica is False
    assert resultado.aviso is not None


def test_llm_baixa_confianca_cai_em_revisar() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "response": json.dumps(
                {
                    "categoria": "Outros",
                    "prioridade": "baixa",
                    "resumo": "Mensagem vaga.",
                    "confianca": 0.35,
                }
            )
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    resultado = asyncio.run(
        classificar_chamado(
            "Oi, tudo bem?",
            settings=_settings_teste(threshold=0.6),
            transport=transport,
        )
    )

    assert resultado.categoria == FALLBACK_CATEGORIA
    assert resultado.classificacao_automatica is False
    assert resultado.aviso is not None
