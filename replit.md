# Portal de Triagem — execução no Replit

## Estrutura e execução

- Manter Python 3.12, FastAPI, Jinja2 e a estrutura importada.
- Dependências em `requirements.txt`, instaladas no ambiente Python gerenciado pelo Replit, sem virtualenv.
- Workflow `Start application`: `python -m uvicorn app.main:app --host 0.0.0.0 --port 5000`.
- Clique em Run e abra o Preview. A página `/` gera um link de demonstração para o formulário.
- Verificação de saúde: `GET /health`.
- Testes: `python -m pytest -q`.

## Configuração atual

- `DEMO_MODE=true` e `SYSAID_MODE=demo`: e-mails são gravados em `outbox/`, sem envio real, e protocolos SysAid são simulados.
- Não é necessário criar `.env` para executar a demonstração. Os padrões ficam em `app/config.py`; `.env.example` é apenas referência.
- A assinatura dos tokens usa `SECRET_KEY`, quando definida, ou o segredo `SESSION_SECRET` já disponível no Replit. Nunca registrar seus valores.
- Ollama não está instalado nem conectado. Sem serviço em `OLLAMA_URL`, a aplicação continua com categoria `Revisar` e aviso explícito, sem classificação por IA.
- O botão de atendente ainda aponta para o endereço de exemplo do projeto. Configure `HUMAN_HANDOFF_URL` com a fila real antes de usar com clientes.
- Para classificação real, conectar um serviço Ollama acessível e configurar `OLLAMA_URL` e `MODEL_NAME`.
- Para uso real, configurar SMTP, destinatários e integração SysAid antes de desativar `DEMO_MODE`. O Blip deve compartilhar a chave de assinatura configurada em `SECRET_KEY`.
- Tokens e rascunhos ficam em memória: manter uma única instância; reiniciar o processo invalida o estado de uso único e os rascunhos.
- Não utilizar dados pessoais reais nos testes de demonstração. Arquivos `.eml` da pasta `outbox/` devem ser removidos periodicamente e não entram no Git.
