"""Cliente do Ollama para classificação e resumo local de chamados."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import Settings, get_settings, load_categories

logger = logging.getLogger("portal_triagem.llm")

FALLBACK_CATEGORIA = "Revisar"
FALLBACK_AVISO = (
    "Não foi possível classificar automaticamente com segurança. "
    "O chamado seguirá marcado para revisão humana."
)


class ClassificacaoLLM(BaseModel):
    """Esquema validado da resposta JSON do modelo local."""

    categoria: str
    prioridade: Literal["baixa", "média", "alta"]
    resumo: str = Field(min_length=1, max_length=400)
    confianca: float = Field(ge=0.0, le=1.0)

    @field_validator("prioridade", mode="before")
    @classmethod
    def normalizar_prioridade(cls, value: object) -> str:
        texto = str(value or "").strip().lower()
        if texto == "media":
            return "média"
        return texto

    @field_validator("resumo", mode="before")
    @classmethod
    def limpar_resumo(cls, value: object) -> str:
        texto = re.sub(r"\s+", " ", str(value or "")).strip()
        return texto[:400]


class ResultadoTriagem(BaseModel):
    """Resultado final da triagem retornado para a camada web."""

    categoria: str
    prioridade: Literal["baixa", "média", "alta"]
    resumo: str
    confianca: float
    classificacao_automatica: bool
    aviso: str | None = None
    sugerir_atendente: bool = False


def sanitizar_texto_cliente(texto: str, max_chars: int = 2000) -> str:
    """Remove caracteres de controle e neutraliza delimitadores XML usados no prompt."""
    limpo = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", texto or "")
    limpo = limpo.replace("<mensagem_cliente>", "[mensagem_cliente]")
    limpo = limpo.replace("</mensagem_cliente>", "[/mensagem_cliente]")
    limpo = re.sub(r"\s+", " ", limpo).strip()
    return limpo[:max_chars]


def _resumo_fallback(descricao: str) -> str:
    texto = sanitizar_texto_cliente(descricao, max_chars=240)
    if len(texto) > 200:
        return texto[:197] + "..."
    return texto or "Solicitação registrada sem resumo automático."


def _fallback_resultado(descricao: str, sugerir_atendente: bool = False) -> ResultadoTriagem:
    return ResultadoTriagem(
        categoria=FALLBACK_CATEGORIA,
        prioridade="média",
        resumo=_resumo_fallback(descricao),
        confianca=0.0,
        classificacao_automatica=False,
        aviso=FALLBACK_AVISO,
        sugerir_atendente=sugerir_atendente,
    )


def _extrair_json_bruto(texto: str) -> str:
    """Extrai objeto JSON mesmo se o modelo envolver em bloco markdown."""
    limpo = texto.strip()
    if limpo.startswith("```"):
        limpo = re.sub(r"^```(?:json)?\s*", "", limpo)
        limpo = re.sub(r"\s*```$", "", limpo)
    inicio = limpo.find("{")
    fim = limpo.rfind("}")
    if inicio != -1 and fim != -1 and fim >= inicio:
        return limpo[inicio : fim + 1]
    return limpo


def carregar_prompt(prompt_file: Path | None = None) -> str:
    """Lê o template de prompt do arquivo externo."""
    target = prompt_file or get_settings().prompt_file
    return target.read_text(encoding="utf-8")


def _deve_sugerir_atendente(
    categoria: str,
    prioridade: str,
    descricao: str,
    categorias_sugeridas: set[str],
    prioridades_sugeridas: set[str],
) -> bool:
    if categoria in categorias_sugeridas:
        return True
    if prioridade.lower() in prioridades_sugeridas:
        return True
    texto_lower = descricao.lower()
    gatilhos = (
        "urgente",
        "urgência",
        "reclamação formal",
        "reclamacao formal",
        "procon",
        "advogado",
        "processo",
        "cancelar contrato",
        "rescisão",
    )
    return any(g in texto_lower for g in gatilhos)


async def classificar_chamado(
    descricao: str,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ResultadoTriagem:
    """Envia a descrição sanitizada ao Ollama e valida o JSON retornado."""
    cfg = settings or get_settings()
    cats_cfg = load_categories(cfg.categories_file)
    mensagem_sanitizada = sanitizar_texto_cliente(descricao)

    template = carregar_prompt(cfg.prompt_file)
    prompt = template.format(
        categorias=", ".join(cats_cfg.categorias),
        mensagem_sanitizada=mensagem_sanitizada,
    )

    sugerir_por_texto = _deve_sugerir_atendente(
        categoria="",
        prioridade="",
        descricao=mensagem_sanitizada,
        categorias_sugeridas=cats_cfg.sugerir_atendente_categorias,
        prioridades_sugeridas=cats_cfg.sugerir_atendente_prioridades,
    )

    payload = {
        "model": cfg.model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_predict": 256,
        },
    }

    url = f"{cfg.ollama_url.rstrip('/')}/api/generate"

    try:
        async with httpx.AsyncClient(
            timeout=cfg.ollama_timeout_seconds,
            transport=transport,
        ) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Falha ao consultar Ollama (%s). Aplicando fallback Revisar.", type(exc).__name__)
        return _fallback_resultado(descricao, sugerir_atendente=sugerir_por_texto)

    raw_response = str(body.get("response", ""))
    try:
        parsed_json = json.loads(_extrair_json_bruto(raw_response))
        classificado = ClassificacaoLLM.model_validate(parsed_json)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.warning("JSON inválido retornado pelo modelo (%s). Aplicando fallback Revisar.", type(exc).__name__)
        return _fallback_resultado(descricao, sugerir_atendente=sugerir_por_texto)

    # Normaliza categoria comparando case-insensitive com a lista configurada
    mapa_categorias = {c.lower(): c for c in cats_cfg.categorias}
    categoria_oficial = mapa_categorias.get(classificado.categoria.strip().lower())

    if not categoria_oficial or classificado.confianca < cfg.confidence_threshold:
        logger.info(
            "Classificação com baixa confiança (%.2f) ou categoria desconhecida. Marcando como Revisar.",
            classificado.confianca,
        )
        return ResultadoTriagem(
            categoria=FALLBACK_CATEGORIA,
            prioridade=classificado.prioridade,
            resumo=classificado.resumo or _resumo_fallback(descricao),
            confianca=classificado.confianca,
            classificacao_automatica=False,
            aviso=FALLBACK_AVISO,
            sugerir_atendente=sugerir_por_texto
            or (classificado.prioridade in cats_cfg.sugerir_atendente_prioridades),
        )

    sugerir = _deve_sugerir_atendente(
        categoria=categoria_oficial,
        prioridade=classificado.prioridade,
        descricao=mensagem_sanitizada,
        categorias_sugeridas=cats_cfg.sugerir_atendente_categorias,
        prioridades_sugeridas=cats_cfg.sugerir_atendente_prioridades,
    )

    return ResultadoTriagem(
        categoria=categoria_oficial,
        prioridade=classificado.prioridade,
        resumo=classificado.resumo,
        confianca=classificado.confianca,
        classificacao_automatica=True,
        aviso=None,
        sugerir_atendente=sugerir,
    )
