"""Testes unitários de geração de e-mail e mascaramento de dados em logs."""

from pathlib import Path

from app.config import Settings, mask_cnpj, mask_email, mask_phone
from app.email import DadosEmailTriagem, enviar_email_triagem, gerar_codigo_solicitacao


def test_geracao_email_com_codigo_e_cnpj_no_assunto(tmp_path: Path) -> None:
    cfg = Settings(
        DEMO_MODE=True,
        OUTBOX_DIR=tmp_path,
        EMAIL_TO="atendimento@empresa.com.br",
        EMAIL_FROM="triagem@empresa.com.br",
    )
    codigo = gerar_codigo_solicitacao()
    assert codigo.startswith("TRI-")

    dados = DadosEmailTriagem(
        codigo_solicitacao=codigo,
        conversa_id="5511999990000",
        nome_completo="Maria Silva",
        cnpj="11222333000181",
        email_cliente="maria@empresa.com.br",
        descricao_original="Solicito segunda via do boleto.",
        categoria="Boleto",
        prioridade="média",
        resumo="Cliente pede segunda via de boleto.",
        classificacao_automatica=True,
    )

    arquivo = enviar_email_triagem(dados, settings=cfg)
    assert arquivo is not None
    assert arquivo.exists()

    conteudo = arquivo.read_text(encoding="utf-8")
    assert codigo in conteudo
    assert "11.222.333/0001-81" in conteudo
    assert "Subject: [" in conteudo
    assert "Solicito segunda via do boleto." in conteudo


def test_mascaramento_dados_sensiveis() -> None:
    assert mask_cnpj("11.222.333/0001-81") == "11.***.***/****-81"
    assert mask_email("maria.silva@empresa.com.br") == "m***@empresa.com.br"
    assert mask_phone("5511999990000") == "551****0000"
