"""Módulo de confirmação do SysAid (simulação em modo demo e interface extensível)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from app.config import Settings, get_settings


@dataclass(frozen=True)
class ConfirmacaoSysAid:
    """Resultado da confirmação de abertura de chamado no SysAid."""

    status: str  # "simulado", "confirmado" ou "pendente"
    protocolo_sysaid: str | None
    mensagem: str


class SysAidProvider(Protocol):
    """Interface para provedores de confirmação do SysAid."""

    def confirmar_abertura(self, codigo_solicitacao: str) -> ConfirmacaoSysAid:
        """Obtém ou consulta o número de protocolo gerado pelo SysAid."""


class DemoSysAidProvider:
    """Simula a resposta do SysAid com um número fictício determinístico."""

    def confirmar_abertura(self, codigo_solicitacao: str) -> ConfirmacaoSysAid:
        digest = hashlib.sha256(codigo_solicitacao.encode("utf-8")).hexdigest()[:6].upper()
        numero_ficticio = f"SYS-DEMO-{digest}"
        return ConfirmacaoSysAid(
            status="simulado",
            protocolo_sysaid=numero_ficticio,
            mensagem=(
                f"Modo demonstração: protocolo fictício {numero_ficticio} simulado. "
                "Em produção, o protocolo será gerado pelo SysAid após leitura do e-mail."
            ),
        )


class EmailConfirmationSysAidProvider:
    """Stub preparado para leitura real do e-mail de confirmação retornado pelo SysAid."""

    def confirmar_abertura(self, codigo_solicitacao: str) -> ConfirmacaoSysAid:
        # Ponto de extensão: conectar via IMAP/POP3 ou webhook de entrada buscando
        # o código_solicitacao no assunto/corpo da resposta automática do SysAid.
        return ConfirmacaoSysAid(
            status="pendente",
            protocolo_sysaid=None,
            mensagem=(
                f"Solicitação {codigo_solicitacao} enviada para atendimento. "
                "O protocolo oficial do SysAid será enviado para o seu e-mail assim que processado."
            ),
        )


class ApiSysAidProvider:
    """Stub preparado para consulta direta via API REST do SysAid."""

    def __init__(self, api_url: str, api_token: str) -> None:
        self.api_url = api_url
        self.api_token = api_token

    def confirmar_abertura(self, codigo_solicitacao: str) -> ConfirmacaoSysAid:
        # Ponto de extensão: consultar GET {self.api_url}/api/v1/sr?search={codigo_solicitacao}
        return ConfirmacaoSysAid(
            status="pendente",
            protocolo_sysaid=None,
            mensagem=(
                f"Solicitação {codigo_solicitacao} encaminhada. "
                "Aguardando confirmação automática via API do SysAid."
            ),
        )


def obter_provider_sysaid(settings: Settings | None = None) -> SysAidProvider:
    """Seleciona o provedor de confirmação SysAid conforme configuração."""
    cfg = settings or get_settings()
    if cfg.demo_mode or cfg.sysaid_mode == "demo":
        return DemoSysAidProvider()
    if cfg.sysaid_mode == "api" and cfg.sysaid_api_url:
        return ApiSysAidProvider(api_url=cfg.sysaid_api_url, api_token=cfg.sysaid_api_token)
    return EmailConfirmationSysAidProvider()
