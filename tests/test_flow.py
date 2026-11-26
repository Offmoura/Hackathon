"""Testes de integração do fluxo completo em modo demonstração."""

from pathlib import Path

from fastapi.testclient import TestClient

import app.web as web_module
from app.config import Settings
from app.llm import ResultadoTriagem


def _criar_client_teste(tmp_path: Path) -> tuple[TestClient, Settings]:
    cfg = Settings(
        DEMO_MODE=True,
        SECRET_KEY="chave-teste-integracao",
        OUTBOX_DIR=tmp_path,
        HUMAN_HANDOFF_URL="https://blip.exemplo.com/fila-humana",
        EMAIL_TO="atendimento@exemplo.com.br",
        EMAIL_FROM="triagem@exemplo.com.br",
    )
    app = web_module.create_app(settings=cfg)
    return TestClient(app), cfg


def test_fluxo_completo_modo_demo(tmp_path: Path, monkeypatch) -> None:
    async def fake_classificar(descricao: str, settings=None, transport=None) -> ResultadoTriagem:
        return ResultadoTriagem(
            categoria="Boleto",
            prioridade="média",
            resumo="Cliente solicita segunda via de boleto.",
            confianca=0.95,
            classificacao_automatica=True,
            aviso=None,
            sugerir_atendente=False,
        )

    monkeypatch.setattr(web_module, "classificar_chamado", fake_classificar)
    client, cfg = _criar_client_teste(tmp_path)

    token = client.app.state.token_manager.criar_token("5511988887777")

    # 1. Abre o formulário com token válido
    resp_get = client.get(f"/triagem?token={token}")
    assert resp_get.status_code == 200
    assert "Falar com atendente" in resp_get.text

    # 2. Envia formulário com CNPJ inválido -> erro 422
    resp_invalido = client.post(
        "/triagem",
        data={
            "token": token,
            "nome_completo": "João Silva",
            "cnpj": "11.222.333/0001-99",
            "email": "joao@exemplo.com.br",
            "descricao": "Preciso da segunda via do boleto.",
        },
    )
    assert resp_invalido.status_code == 422
    assert "CNPJ inválido" in resp_invalido.text

    # 3. Envia formulário válido -> tela de confirmação
    resp_post = client.post(
        "/triagem",
        data={
            "token": token,
            "nome_completo": "João Silva",
            "cnpj": "11.222.333/0001-81",
            "email": "joao@exemplo.com.br",
            "descricao": "Preciso da segunda via do boleto que vence amanhã.",
        },
    )
    assert resp_post.status_code == 200
    assert "Boleto" in resp_post.text
    assert "Enviar para a equipe" in resp_post.text
    assert "Falar com atendente" in resp_post.text

    # Extrai token_rascunho do HTML
    marker = 'name="token_rascunho" value="'
    start = resp_post.text.index(marker) + len(marker)
    end = resp_post.text.index('"', start)
    token_rascunho = resp_post.text[start:end]

    # 4. Confirma envio -> gera código, grava e-mail na outbox/ e simula SysAid
    resp_conf = client.post(
        "/triagem/confirmar",
        data={"token_rascunho": token_rascunho},
    )
    assert resp_conf.status_code == 200
    assert "TRI-" in resp_conf.text
    assert "SYS-DEMO-" in resp_conf.text
    assert "Falar com atendente" in resp_conf.text

    arquivos_outbox = list(cfg.outbox_dir.glob("TRI-*.eml"))
    assert len(arquivos_outbox) == 1
    conteudo_email = arquivos_outbox[0].read_text(encoding="utf-8")
    assert "11.222.333/0001-81" in conteudo_email

    # 5. Reutilizar o mesmo token após envio deve ser bloqueado (uso único)
    resp_reuso = client.get(f"/triagem?token={token}")
    assert resp_reuso.status_code == 410
    assert "Link já utilizado" in resp_reuso.text


def test_reclamacao_sugere_atendente_e_handoff_redireciona(tmp_path: Path, monkeypatch) -> None:
    async def fake_reclamacao(descricao: str, settings=None, transport=None) -> ResultadoTriagem:
        return ResultadoTriagem(
            categoria="Reclamação",
            prioridade="alta",
            resumo="Cliente registra reclamação formal urgente.",
            confianca=0.92,
            classificacao_automatica=True,
            aviso=None,
            sugerir_atendente=True,
        )

    monkeypatch.setattr(web_module, "classificar_chamado", fake_reclamacao)
    client, _ = _criar_client_teste(tmp_path)
    token = client.app.state.token_manager.criar_token("5511977776666")

    resp = client.post(
        "/triagem",
        data={
            "token": token,
            "nome_completo": "Maria Souza",
            "cnpj": "11444777000161",
            "email": "maria@exemplo.com.br",
            "descricao": "Quero registrar uma reclamação formal pelo atendimento.",
        },
    )
    assert resp.status_code == 200
    assert "recomendamos falar diretamente com um atendente humano" in resp.text

    resp_handoff = client.get("/atendente", follow_redirects=False)
    assert resp_handoff.status_code == 302
    assert resp_handoff.headers["location"] == "https://blip.exemplo.com/fila-humana"
