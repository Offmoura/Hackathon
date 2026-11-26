"""Compatibilidade da configuração com os segredos do Replit."""

from app.config import Settings


def test_session_secret_assina_tokens_quando_secret_key_ausente(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("SESSION_SECRET", "segredo-sintetico-de-teste")
    cfg = Settings(_env_file=None, DEMO_MODE=False)
    assert cfg.resolve_secret_key() == "segredo-sintetico-de-teste"


def test_secret_key_explicita_tem_precedencia(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "chave-sintetica-blip")
    monkeypatch.setenv("SESSION_SECRET", "chave-sintetica-replit")
    cfg = Settings(_env_file=None, DEMO_MODE=False)
    assert cfg.resolve_secret_key() == "chave-sintetica-blip"
