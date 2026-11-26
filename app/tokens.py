"""Geração e validação de tokens assinados, com validade curta e uso único."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class TokenError(Exception):
    """Erro base para falhas de validação de token."""


class TokenInvalidoError(TokenError):
    """Token malformado ou com assinatura adulterada."""


class TokenExpiradoError(TokenError):
    """Token ultrapassou o tempo de validade."""


class TokenJaUsadoError(TokenError):
    """Token de uso único já foi consumido."""


@dataclass(frozen=True)
class TokenPayload:
    """Dados mínimos carregados pelo token (apenas identificador da conversa/telefone)."""

    conversa_id: str
    jti: str


class TokenManager:
    """Gerencia assinatura, expiração e controle de uso único (jti) em memória."""

    def __init__(self, secret_key: str, ttl_seconds: int = 900, salt: str = "triagem-blip") -> None:
        self._serializer = URLSafeTimedSerializer(secret_key=secret_key, salt=salt)
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        # Mapeia jti -> timestamp de expiração para limpeza periódica sem retenção prolongada
        self._used_jtis: dict[str, float] = {}

    def _limpar_expirados(self, now: float) -> None:
        expirados = [jti for jti, exp in self._used_jtis.items() if exp <= now]
        for jti in expirados:
            del self._used_jtis[jti]

    def criar_token(self, conversa_id: str) -> str:
        """Cria um token assinado contendo apenas o identificador da conversa e um jti."""
        identificador = conversa_id.strip()
        if not identificador:
            raise ValueError("conversa_id não pode ser vazio")
        payload = {
            "cid": identificador,
            "jti": uuid.uuid4().hex,
        }
        return self._serializer.dumps(payload)

    def validar_token(self, token: str) -> TokenPayload:
        """Valida assinatura, expiração e verifica se o token ainda não foi usado."""
        if not token or not token.strip():
            raise TokenInvalidoError("Token ausente.")

        try:
            data = self._serializer.loads(token, max_age=self._ttl_seconds)
        except SignatureExpired as exc:
            raise TokenExpiradoError("Este link expirou. Solicite um novo atendimento.") from exc
        except BadSignature as exc:
            raise TokenInvalidoError("Link inválido ou adulterado.") from exc

        if not isinstance(data, dict) or "cid" not in data or "jti" not in data:
            raise TokenInvalidoError("Estrutura do token inválida.")

        jti = str(data["jti"])
        cid = str(data["cid"])
        now = time.time()

        with self._lock:
            self._limpar_expirados(now)
            if jti in self._used_jtis:
                raise TokenJaUsadoError("Este link já foi utilizado.")

        return TokenPayload(conversa_id=cid, jti=jti)

    def consumir_token(self, token: str) -> TokenPayload:
        """Valida e marca o token como utilizado (uso único)."""
        payload = self.validar_token(token)
        now = time.time()
        with self._lock:
            self._limpar_expirados(now)
            if payload.jti in self._used_jtis:
                raise TokenJaUsadoError("Este link já foi utilizado.")
            self._used_jtis[payload.jti] = now + self._ttl_seconds + 60
        return payload

    def marcar_jti_usado(self, jti: str) -> None:
        """Marca explicitamente um jti como usado."""
        now = time.time()
        with self._lock:
            self._limpar_expirados(now)
            self._used_jtis[jti] = now + self._ttl_seconds + 60

    def criar_token_rascunho(self, dados: dict) -> str:
        """Assina dados temporários da etapa de confirmação sem persistir em banco."""
        return self._serializer.dumps(dados, salt="triagem-rascunho")

    def ler_token_rascunho(self, token_rascunho: str) -> dict:
        """Valida e recupera os dados temporários da etapa de confirmação."""
        try:
            data = self._serializer.loads(
                token_rascunho,
                max_age=self._ttl_seconds,
                salt="triagem-rascunho",
            )
        except SignatureExpired as exc:
            raise TokenExpiradoError("A sessão de confirmação expirou.") from exc
        except BadSignature as exc:
            raise TokenInvalidoError("Dados de confirmação inválidos.") from exc

        if not isinstance(data, dict):
            raise TokenInvalidoError("Formato de rascunho inválido.")
        return data
