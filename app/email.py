"""Geração de código da solicitação e envio de e-mail (modo demo em outbox/ ou SMTP real)."""

from __future__ import annotations

import logging
import secrets
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from app.cnpj import formatar_cnpj
from app.config import Settings, get_settings, mask_cnpj, mask_email, mask_phone

logger = logging.getLogger("portal_triagem.email")


@dataclass(frozen=True)
class DadosEmailTriagem:
    """Dados necessários para compor e enviar o e-mail de triagem."""

    codigo_solicitacao: str
    conversa_id: str
    nome_completo: str
    cnpj: str
    email_cliente: str
    descricao_original: str
    categoria: str
    prioridade: str
    resumo: str
    classificacao_automatica: bool


def gerar_codigo_solicitacao(agora: datetime | None = None) -> str:
    """Gera código único no formato TRI-AAAAMMDD-XXXX."""
    dt = agora or datetime.now(timezone.utc)
    sufixo = secrets.token_hex(2).upper()
    return f"TRI-{dt.strftime('%Y%m%d')}-{sufixo}"


def montar_mensagem_email(dados: DadosEmailTriagem, remetente: str, destinatario: str) -> EmailMessage:
    """Constrói a mensagem MIME com código e CNPJ no assunto e detalhes no corpo."""
    cnpj_formatado = formatar_cnpj(dados.cnpj)
    assunto = f"[{dados.codigo_solicitacao}] Triagem ({dados.categoria}) - CNPJ {cnpj_formatado}"

    status_ia = "Automática" if dados.classificacao_automatica else "Revisão manual necessária (fallback)"
    corpo = (
        f"Código da solicitação: {dados.codigo_solicitacao}\n"
        f"ID da conversa (Blip): {dados.conversa_id}\n"
        f"Categoria sugerida: {dados.categoria}\n"
        f"Prioridade sugerida: {dados.prioridade}\n"
        f"Classificação IA: {status_ia}\n\n"
        f"--- Resumo ---\n"
        f"{dados.resumo}\n\n"
        f"--- Dados do Cliente ---\n"
        f"Nome completo: {dados.nome_completo}\n"
        f"CNPJ: {cnpj_formatado}\n"
        f"E-mail: {dados.email_cliente}\n\n"
        f"--- Mensagem Original ---\n"
        f"{dados.descricao_original}\n"
    )

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = remetente
    msg["To"] = destinatario
    msg["Reply-To"] = dados.email_cliente
    msg.set_content(corpo, charset="utf-8")
    return msg


def enviar_email_triagem(
    dados: DadosEmailTriagem,
    settings: Settings | None = None,
) -> Path | None:
    """Grava o e-mail em outbox/ quando DEMO_MODE=true ou envia via SMTP em produção."""
    cfg = settings or get_settings()
    msg = montar_mensagem_email(dados, remetente=cfg.email_from, destinatario=cfg.email_to)

    logger.info(
        "Preparando envio de triagem codigo=%s conversa=%s cnpj=%s email=%s demo=%s",
        dados.codigo_solicitacao,
        mask_phone(dados.conversa_id),
        mask_cnpj(dados.cnpj),
        mask_email(dados.email_cliente),
        cfg.demo_mode,
    )

    if cfg.demo_mode:
        cfg.outbox_dir.mkdir(parents=True, exist_ok=True)
        arquivo = cfg.outbox_dir / f"{dados.codigo_solicitacao}.eml"
        arquivo.write_bytes(msg.as_bytes())
        logger.info("E-mail salvo em modo demonstração: %s", arquivo.name)
        return arquivo

    if not cfg.smtp_host:
        raise RuntimeError("SMTP_HOST não configurado para envio em modo real.")

    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as server:
        if cfg.smtp_use_tls:
            server.starttls()
        if cfg.smtp_user:
            server.login(cfg.smtp_user, cfg.smtp_password)
        server.send_message(msg)

    logger.info("E-mail enviado via SMTP para %s (codigo=%s)", mask_email(cfg.email_to), dados.codigo_solicitacao)
    return None
