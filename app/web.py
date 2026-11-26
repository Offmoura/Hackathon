"""Rotas FastAPI, validação de formulário, rate limit e renderização Jinja2."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from app.cnpj import formatar_cnpj, limpar_cnpj, validar_cnpj
from app.config import Settings, configure_logging, get_settings, mask_phone
from app.email import DadosEmailTriagem, enviar_email_triagem, gerar_codigo_solicitacao
from app.llm import ResultadoTriagem, classificar_chamado, sanitizar_texto_cliente
from app.sysaid import obter_provider_sysaid
from app.tokens import (
    TokenExpiradoError,
    TokenInvalidoError,
    TokenJaUsadoError,
    TokenManager,
)

logger = logging.getLogger("portal_triagem.web")

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RateLimiter:
    """Rate limiter simples em memória com janela deslizante por chave (IP ou token)."""

    def __init__(self, max_requests: int = 20, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def permitir(self, chave: str) -> bool:
        """Retorna True se a chave ainda está dentro do limite na janela atual."""
        now = time.monotonic()
        limite_inferior = now - self.window_seconds
        with self._lock:
            timestamps = [t for t in self._hits[chave] if t > limite_inferior]
            if len(timestamps) >= self.max_requests:
                self._hits[chave] = timestamps
                return False
            timestamps.append(now)
            self._hits[chave] = timestamps
            return True


class FormularioTriagemInput(BaseModel):
    """Validação e sanitização dos campos enviados pelo cliente."""

    nome_completo: str = Field(min_length=3, max_length=120)
    cnpj: str
    email: str = Field(min_length=5, max_length=160)
    descricao: str = Field(min_length=10, max_length=2000)

    @field_validator("nome_completo", mode="before")
    @classmethod
    def validar_nome(cls, value: object) -> str:
        texto = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(texto) < 3:
            raise ValueError("Informe seu nome completo (mínimo de 3 caracteres).")
        return texto

    @field_validator("cnpj", mode="before")
    @classmethod
    def validar_campo_cnpj(cls, value: object) -> str:
        raw = str(value or "").strip()
        if not validar_cnpj(raw):
            raise ValueError("CNPJ inválido. Verifique os 14 dígitos informados.")
        return limpar_cnpj(raw)

    @field_validator("email", mode="before")
    @classmethod
    def validar_campo_email(cls, value: object) -> str:
        texto = str(value or "").strip().lower()
        if not EMAIL_REGEX.match(texto):
            raise ValueError("Informe um endereço de e-mail válido.")
        return texto

    @field_validator("descricao", mode="before")
    @classmethod
    def validar_descricao(cls, value: object) -> str:
        texto = sanitizar_texto_cliente(str(value or ""), max_chars=2000)
        if len(texto) < 10:
            raise ValueError("Descreva seu pedido com pelo menos 10 caracteres.")
        return texto


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _verificar_rate_limit(request: Request, limiter: RateLimiter, token: str = "") -> bool:
    ip = _client_ip(request)
    if not limiter.permitir(f"ip:{ip}"):
        return False
    if token:
        if not limiter.permitir(f"tok:{token[:24]}"):
            return False
    return True


def create_app(settings: Settings | None = None) -> FastAPI:
    """Cria e configura a aplicação FastAPI."""
    configure_logging()
    cfg = settings or get_settings()
    token_manager = TokenManager(
        secret_key=cfg.resolve_secret_key(),
        ttl_seconds=cfg.token_ttl_seconds,
    )
    limiter = RateLimiter(
        max_requests=cfg.rate_limit_requests,
        window_seconds=cfg.rate_limit_window_seconds,
    )

    app = FastAPI(
        title="Portal de Triagem de Chamados",
        version="1.0.0",
        docs_url="/docs" if cfg.demo_mode else None,
        redoc_url=None,
    )
    app.state.settings = cfg
    app.state.token_manager = token_manager
    app.state.rate_limiter = limiter

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    router = APIRouter()

    def render_erro(
        request: Request,
        titulo: str,
        mensagem: str,
        status_code: int,
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="erro.html",
            context={
                "titulo": titulo,
                "mensagem": mensagem,
                "handoff_url": cfg.human_handoff_url,
                "demo_mode": cfg.demo_mode,
            },
            status_code=status_code,
        )

    @router.get("/health")
    async def health() -> dict[str, object]:
        return {"status": "ok", "demo_mode": cfg.demo_mode}

    @router.get("/", response_class=HTMLResponse)
    async def home(request: Request, conversa_id: str = "5511999990000") -> HTMLResponse:
        if not cfg.demo_mode:
            return render_erro(
                request,
                titulo="Acesso via link de atendimento",
                mensagem="Para iniciar uma triagem, acesse o link exclusivo enviado no seu atendimento.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        token_demo = token_manager.criar_token(conversa_id)
        return templates.TemplateResponse(
            request=request,
            name="demo.html",
            context={
                "token_demo": token_demo,
                "conversa_id": conversa_id,
                "handoff_url": cfg.human_handoff_url,
                "demo_mode": cfg.demo_mode,
            },
        )

    @router.get("/atendente")
    async def falar_com_atendente(request: Request) -> RedirectResponse:
        logger.info("Redirecionamento para atendente humano solicitado ip=%s", _client_ip(request))
        return RedirectResponse(url=cfg.human_handoff_url, status_code=status.HTTP_302_FOUND)

    @router.get("/triagem", response_class=HTMLResponse)
    async def exibir_formulario(request: Request, token: str = "") -> HTMLResponse:
        if not _verificar_rate_limit(request, limiter, token):
            return render_erro(
                request,
                titulo="Muitas tentativas",
                mensagem="Aguarde alguns instantes antes de tentar novamente.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            payload = token_manager.validar_token(token)
        except TokenExpiradoError as exc:
            return render_erro(request, "Link expirado", str(exc), status.HTTP_410_GONE)
        except TokenJaUsadoError as exc:
            return render_erro(request, "Link já utilizado", str(exc), status.HTTP_410_GONE)
        except TokenInvalidoError as exc:
            return render_erro(request, "Link inválido", str(exc), status.HTTP_400_BAD_REQUEST)

        logger.info("Portal aberto para conversa=%s", mask_phone(payload.conversa_id))
        return templates.TemplateResponse(
            request=request,
            name="triagem_form.html",
            context={
                "token": token,
                "handoff_url": cfg.human_handoff_url,
                "demo_mode": cfg.demo_mode,
                "erros": {},
                "valores": {
                    "nome_completo": "",
                    "cnpj": "",
                    "email": "",
                    "descricao": "",
                },
            },
        )

    @router.post("/triagem", response_class=HTMLResponse)
    async def processar_formulario(
        request: Request,
        token: str = Form(...),
        nome_completo: str = Form(""),
        cnpj: str = Form(""),
        email: str = Form(""),
        descricao: str = Form(""),
    ) -> HTMLResponse:
        if not _verificar_rate_limit(request, limiter, token):
            return render_erro(
                request,
                titulo="Muitas tentativas",
                mensagem="Aguarde alguns instantes antes de tentar novamente.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            payload = token_manager.validar_token(token)
        except TokenExpiradoError as exc:
            return render_erro(request, "Link expirado", str(exc), status.HTTP_410_GONE)
        except TokenJaUsadoError as exc:
            return render_erro(request, "Link já utilizado", str(exc), status.HTTP_410_GONE)
        except TokenInvalidoError as exc:
            return render_erro(request, "Link inválido", str(exc), status.HTTP_400_BAD_REQUEST)

        erros: dict[str, str] = {}
        dados_validos: FormularioTriagemInput | None = None
        try:
            dados_validos = FormularioTriagemInput(
                nome_completo=nome_completo,
                cnpj=cnpj,
                email=email,
                descricao=descricao,
            )
        except Exception as exc:  # pydantic.ValidationError
            if hasattr(exc, "errors"):
                for err in exc.errors():  # type: ignore[attr-defined]
                    campo = str(err["loc"][0]) if err.get("loc") else "geral"
                    msg = str(err.get("msg", "Valor inválido.")).replace("Value error, ", "")
                    erros[campo] = msg
            else:
                erros["geral"] = "Verifique os dados informados."

        if erros or dados_validos is None:
            return templates.TemplateResponse(
                request=request,
                name="triagem_form.html",
                context={
                    "token": token,
                    "handoff_url": cfg.human_handoff_url,
                    "demo_mode": cfg.demo_mode,
                    "erros": erros,
                    "valores": {
                        "nome_completo": nome_completo,
                        "cnpj": cnpj,
                        "email": email,
                        "descricao": descricao,
                    },
                },
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        resultado: ResultadoTriagem = await classificar_chamado(
            dados_validos.descricao,
            settings=cfg,
        )

        token_rascunho = token_manager.criar_token_rascunho(
            {
                "token_original": token,
                "jti": payload.jti,
                "conversa_id": payload.conversa_id,
                "nome_completo": dados_validos.nome_completo,
                "cnpj": dados_validos.cnpj,
                "email": dados_validos.email,
                "descricao": dados_validos.descricao,
                "resultado": resultado.model_dump(),
            }
        )

        return templates.TemplateResponse(
            request=request,
            name="confirmacao.html",
            context={
                "token_rascunho": token_rascunho,
                "nome_completo": dados_validos.nome_completo,
                "cnpj_formatado": formatar_cnpj(dados_validos.cnpj),
                "email": dados_validos.email,
                "descricao": dados_validos.descricao,
                "resultado": resultado,
                "handoff_url": cfg.human_handoff_url,
                "demo_mode": cfg.demo_mode,
            },
        )

    @router.post("/triagem/confirmar", response_class=HTMLResponse)
    async def confirmar_envio(
        request: Request,
        token_rascunho: str = Form(...),
    ) -> HTMLResponse:
        if not _verificar_rate_limit(request, limiter, token_rascunho):
            return render_erro(
                request,
                titulo="Muitas tentativas",
                mensagem="Aguarde alguns instantes antes de tentar novamente.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            rascunho = token_manager.ler_token_rascunho(token_rascunho)
            token_original = str(rascunho.get("token_original", ""))
            # Garante uso único consumindo o token original neste momento
            payload = token_manager.consumir_token(token_original)
        except TokenExpiradoError as exc:
            return render_erro(request, "Sessão expirada", str(exc), status.HTTP_410_GONE)
        except TokenJaUsadoError as exc:
            return render_erro(request, "Solicitação já enviada", str(exc), status.HTTP_410_GONE)
        except TokenInvalidoError as exc:
            return render_erro(request, "Sessão inválida", str(exc), status.HTTP_400_BAD_REQUEST)

        resultado = ResultadoTriagem.model_validate(rascunho["resultado"])
        codigo = gerar_codigo_solicitacao()

        dados_email = DadosEmailTriagem(
            codigo_solicitacao=codigo,
            conversa_id=payload.conversa_id,
            nome_completo=str(rascunho["nome_completo"]),
            cnpj=str(rascunho["cnpj"]),
            email_cliente=str(rascunho["email"]),
            descricao_original=str(rascunho["descricao"]),
            categoria=resultado.categoria,
            prioridade=resultado.prioridade,
            resumo=resultado.resumo,
            classificacao_automatica=resultado.classificacao_automatica,
        )
        enviar_email_triagem(dados_email, settings=cfg)

        provider = obter_provider_sysaid(cfg)
        confirmacao_sysaid = provider.confirmar_abertura(codigo)

        return templates.TemplateResponse(
            request=request,
            name="sucesso.html",
            context={
                "codigo_solicitacao": codigo,
                "categoria": resultado.categoria,
                "confirmacao_sysaid": confirmacao_sysaid,
                "handoff_url": cfg.human_handoff_url,
                "demo_mode": cfg.demo_mode,
            },
        )

    app.include_router(router)
    return app
