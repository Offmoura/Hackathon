# Portal de Triagem de Chamados com IA Local

Aplicação web em Python (FastAPI + Jinja2 + Ollama) para triagem automática de chamados iniciados no **Blip** na opção **"Outros"**, com validação determinística de CNPJ, classificação e resumo via LLM local, envio de e-mail para abertura no **SysAid** e opção permanente de transferência para atendente humano.

> **Versão de entrega:** `v1.0.0` (indicar com `git tag v1.0.0` após o commit final).

---

## O que o portal faz

1. O cliente no Blip escolhe **"Outros"** e recebe um link `/triagem?token=...` assinado, de validade curta e uso único (carregando apenas o identificador da conversa/telefone, sem dados pessoais na URL).
2. O cliente informa **nome completo**, **CNPJ**, **e-mail** e **descrição do pedido**.
3. O **CNPJ é validado em código** (14 dígitos + dígitos verificadores), sem uso de IA.
4. Um **modelo local no Ollama** classifica em uma lista configurável de categorias (`config/categories.json`), define prioridade (`baixa`, `média`, `alta`), gera resumo (até 3 linhas) e retorna confiança (`0` a `1`) em JSON validado por Pydantic.
5. Se o Ollama falhar, retornar JSON inválido ou confiança abaixo do limiar, o fluxo continua com categoria **`Revisar`** e aviso explícito.
6. Na tela de confirmação, o cliente vê categoria e resumo e escolhe **"Enviar para a equipe"** ou **"Falar com atendente"** (botão presente em todas as telas; recomendado automaticamente em reclamações, contratos e urgências).
7. Ao enviar, o sistema gera um código `TRI-AAAAMMDD-XXXX`, envia (ou grava em `outbox/` no modo demo) o e-mail para `atendimento@` e consulta o módulo de confirmação do SysAid (simulado no modo demo).

---

## Como instalar

Pré-requisitos: **Python 3.11+** e (opcional para inferência real) **Ollama**.

```bash
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

Configure o arquivo de ambiente:

```bash
cp .env.example .env
```

---

## Como instalar o Ollama e baixar o modelo

1. Instale o Ollama seguindo as instruções oficiais em [https://ollama.com/download](https://ollama.com/download).
2. Baixe o modelo configurado (padrão `llama3.1:8b`, ou outro de sua preferência alterando `MODEL_NAME` no `.env`):

```bash
ollama pull llama3.1:8b
```

3. Verifique se o serviço está ativo em `http://localhost:11434`:

```bash
ollama list
```

---

## Como rodar em modo demonstração

Com `DEMO_MODE=true` no `.env` (padrão do `.env.example`):
- Os e-mails são gravados como arquivos `.eml` na pasta `outbox/`.
- A confirmação do SysAid retorna um protocolo fictício (`SYS-DEMO-...`).
- A rota `/` exibe um gerador de link de demonstração para abrir `/triagem?token=...`.

```bash
uvicorn app.main:app --reload --port 8000
```

Acesse `http://localhost:8000/` no navegador.

---

## Como rodar os testes (`pytest`)

Os testes não dependem do Ollama em execução (usam mocks para o LLM) nem de servidor SMTP:

```bash
pytest -v
```

---

## Como avaliar o modelo local

O conjunto de 40 chamados sintéticos está em [data/chamados_sinteticos.json](file:///d:/Moura/Desktop/Hackathon/data/chamados_sinteticos.json). Com o Ollama rodando e o modelo baixado, execute:

```bash
python scripts/avaliar_modelo.py
```

O script exibe: acerto da categoria (%), taxa de JSON válido sem fallback (%), tempo médio por chamado e a lista detalhada de erros.

---

## Política de retenção e privacidade

- O portal **não possui banco de dados** e **não persiste dados pessoais** em disco em modo produção.
- O controle de uso único (`jti`) e os rascunhos da etapa de confirmação ficam apenas em memória pelo tempo do `TOKEN_TTL_SECONDS` (padrão: 15 minutos) e são descartados automaticamente após expirar.
- Em modo demonstração (`DEMO_MODE=true`), os arquivos `.eml` gerados em `outbox/` devem ser limpos periodicamente.
- Os logs mascaram CNPJ, e-mail e identificador/telefone da conversa.

---

## Suposições assumidas

1. **Armazenamento em memória para uso único (`jti`)**: assumiu-se uma única instância do portal (ou sticky session), mantendo os `jti` consumidos em memória com limpeza por TTL. Para múltiplas réplicas sem afinidade de sessão, trocar pelo Redis.
2. **Abertura de chamado no SysAid por e-mail**: assumiu-se que o envio de e-mail para `EMAIL_TO` (`atendimento@`) dispara a abertura automática no SysAid; a obtenção posterior do protocolo real está isolada na interface `SysAidProvider` (`app/sysaid.py`).
3. **Configuração de categorias via JSON**: usou-se `config/categories.json` para evitar dependência extra de parser YAML.
4. **Identificador no token**: assumiu-se que o Blip assina um token contendo apenas `cid` (ID da conversa ou telefone) usando a mesma `SECRET_KEY` compartilhada, ou chama um endpoint interno gerador de link.
5. **Idioma e moeda**: interface, mensagens de validação, prompt e dataset sintético 100% em português do Brasil.
