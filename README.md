# tata-customer-agent

Webhook-based AI customer support agent **Tata** built with:

| Component | Technology |
|-----------|-----------|
| Webhook server | [FastAPI](https://fastapi.tiangolo.com/) |
| Agent workflow | [LangGraph](https://langchain-ai.github.io/langgraph/) |
| LLM + Embeddings | [OpenAI](https://platform.openai.com/) (`gpt-4.1` / `text-embedding-3-small`) |
| Vector store (RAG) | [PostgreSQL + pgvector](https://github.com/pgvector/pgvector) |
| Conversation memory | PostgreSQL |
| Deployment | Docker Compose |

## How it works

```
Chatwoot ──webhook──▶ FastAPI /webhook
                           │
                    MessageBuffer (debounce 2 min)
                           │
                     LangGraph agent
                      ├─ retrieve  ──▶ pgvector (similarity search)
                      ├─ generate  ──▶ OpenAI chat completion
                      └─ review    ──▶ Supervisor LLM check
                           │
                        APPROVED ──▶ Chatwoot API (reply to customer)
                        NEEDS_HUMAN ──▶ Chatwoot API (escalation message)
```

1. Chatwoot sends a `message_created` webhook when a contact writes a message.
2. The FastAPI server queues the message in a per-conversation debounce buffer (default 2 min).
3. After the silence window, buffered messages are joined and forwarded to the LangGraph agent.
4. The agent retrieves relevant knowledge snippets from pgvector (RAG).
5. OpenAI generates a grounded reply using the retrieved context.
6. A supervisor LLM reviews the reply; if flagged it is replaced with a human-handoff message.
7. The reply is posted back to the conversation via the Chatwoot REST API.

## Quick start

```bash
# 1. Copy and fill in your credentials
cp .env.example .env

# 2. Start PostgreSQL + Tata agent
docker compose up --build

# 3. Expose the webhook with ngrok (development)
ngrok http 8000
# Then set the ngrok URL as the webhook in your Chatwoot inbox settings:
# https://<ngrok-id>.ngrok.io/webhook
```

## Running tests

```bash
pip install -r requirements.txt

# Run the full test suite (requires OPENAI_API_KEY and PostgreSQL with pgvector)
POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/tata_agent \
OPENAI_API_KEY=sk-... \
pytest --tb=short -v -s
```

Tests use **real services** (OpenAI + PostgreSQL/pgvector).  Only the outbound
Chatwoot HTTP client is replaced by a `MagicMock`.  Missing `OPENAI_API_KEY`
causes tests to **fail** (not skip), giving a clear error.  Put your credentials
in a `.env` file — it is loaded automatically by the test suite.

## Environment variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI secret key |
| `LLM_MODEL` | Chat model (default `gpt-4.1`) |
| `LLM_PROVIDER` | Provider (`openai` or `azure`) |
| `OPENAI_API_ENDPOINT` | Azure OpenAI endpoint (leave blank for openai.com) |
| `EMBEDDING_MODEL_SMALL` | Embedding model (default `text-embedding-3-small`) |
| `POSTGRES_DSN` | PostgreSQL DSN (pgvector extension required) |
| `PG_VECTOR_TABLE` | Knowledge table name (default `tata_knowledge`) |
| `PG_MEMORY_TABLE` | Memory table name (default `tata_conversations`) |
| `CHATWOOT_BASE_URL` | Chatwoot instance URL |
| `CHATWOOT_API_TOKEN` | Chatwoot agent bot / API token |
| `CHATWOOT_ACCOUNT_ID` | Chatwoot account ID |
| `WEBHOOK_TOKEN` | Optional secret for webhook signature validation |
| `RESPONSE_DELAY_SECONDS` | Debounce window before replying (default `120`) |
