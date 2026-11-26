"""Configurações da aplicação, carregamento de categorias e utilitários de privacidade."""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configurações carregadas via variáveis de ambiente ou arquivo .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    demo_mode: bool = Field(default=True, alias="DEMO_MODE")
    secret_key: str = Field(default="", alias="SECRET_KEY")
    token_ttl_seconds: int = Field(default=900, alias="TOKEN_TTL_SECONDS")
    human_handoff_url: str = Field(
        default="https://blip.suaempresa.com.br/handoff",
        alias="HUMAN_HANDOFF_URL",
    )

    ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    model_name: str = Field(default="llama3.1:8b", alias="MODEL_NAME")
    ollama_timeout_seconds: float = Field(default=30.0, alias="OLLAMA_TIMEOUT_SECONDS")
    confidence_threshold: float = Field(default=0.60, alias="CONFIDENCE_THRESHOLD")

    email_to: str = Field(default="atendimento@suaempresa.com.br", alias="EMAIL_TO")
    email_from: str = Field(default="triagem@suaempresa.com.br", alias="EMAIL_FROM")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")

    outbox_dir: Path = Field(default=BASE_DIR / "outbox", alias="OUTBOX_DIR")
    categories_file: Path = Field(
        default=BASE_DIR / "config" / "categories.json",
        alias="CATEGORIES_FILE",
    )
    prompt_file: Path = Field(
        default=BASE_DIR / "prompts" / "triagem_prompt.txt",
        alias="PROMPT_FILE",
    )

    rate_limit_requests: int = Field(default=20, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(default=60, alias="RATE_LIMIT_WINDOW_SECONDS")

    sysaid_mode: str = Field(default="demo", alias="SYSAID_MODE")
    sysaid_api_url: str = Field(default="", alias="SYSAID_API_URL")
    sysaid_api_token: str = Field(default="", alias="SYSAID_API_TOKEN")

    def resolve_secret_key(self) -> str:
        """Retorna a chave secreta configurada ou gera uma efêmera apenas em modo demo."""
        if self.secret_key.strip():
            return self.secret_key.strip()
        if self.demo_mode:
            return "demo-secret-key-nao-usar-em-producao"
        raise RuntimeError(
            "SECRET_KEY não configurada. Defina SECRET_KEY no ambiente quando DEMO_MODE=false."
        )


class CategoriesConfig:
    """Representa as categorias configuráveis e regras de sugestão de atendente."""

    def __init__(
        self,
        categorias: list[str],
        sugerir_atendente_categorias: list[str],
        sugerir_atendente_prioridades: list[str],
    ) -> None:
        self.categorias = categorias
        self.sugerir_atendente_categorias = set(sugerir_atendente_categorias)
        self.sugerir_atendente_prioridades = {p.lower() for p in sugerir_atendente_prioridades}


def load_categories(path: Path | None = None) -> CategoriesConfig:
    """Carrega a lista de categorias a partir do arquivo JSON configurado."""
    target = path or get_settings().categories_file
    with target.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return CategoriesConfig(
        categorias=list(data.get("categorias", [])),
        sugerir_atendente_categorias=list(data.get("sugerir_atendente_categorias", [])),
        sugerir_atendente_prioridades=list(data.get("sugerir_atendente_prioridades", [])),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna instância cacheada das configurações."""
    return Settings()


def mask_cnpj(cnpj: str) -> str:
    """Mascara um CNPJ mantendo apenas os 2 primeiros e 2 últimos dígitos."""
    digits = re.sub(r"\D", "", cnpj or "")
    if len(digits) != 14:
        return "***.***.***/****-**"
    return f"{digits[:2]}.***.***/****-{digits[-2:]}"


def mask_email(email_addr: str) -> str:
    """Mascara um endereço de e-mail para logs seguros."""
    value = (email_addr or "").strip()
    if "@" not in value:
        return "***"
    local, domain = value.split("@", 1)
    prefix = local[0] if local else "*"
    return f"{prefix}***@{domain}"


def mask_phone(phone: str) -> str:
    """Mascara um telefone ou identificador de conversa para logs seguros."""
    cleaned = re.sub(r"\s+", "", phone or "")
    if len(cleaned) <= 4:
        return "****"
    return f"{cleaned[:3]}****{cleaned[-4:]}"


def configure_logging() -> logging.Logger:
    """Configura logger padrão da aplicação."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return logging.getLogger("portal_triagem")
