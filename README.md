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
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install frontend dependencies and build
cd frontend
npm install
npm run build
cd ..

# 3. Start PostgreSQL with pgvector (Docker — recommended for local dev)
docker run -d \
  --name tata-pgvector \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=tata_agent \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# 4. Create your .env file and set credentials
cp .env.example .env
# Open .env and set OPENAI_API_KEY=sk-...
# POSTGRES_DSN is pre-filled to match the Docker command above

# 5. Run the full test suite
pytest --tb=short -v -s
```

Tests use **real services** (OpenAI + PostgreSQL/pgvector).  Only the outbound
Chatwoot HTTP client is replaced by a `MagicMock`.

- `OPENAI_API_KEY` must be set in `.env` — the test suite loads it automatically
  via `load_dotenv()`.  In CI it comes from the repository secret
  `OPENAI_API_KEY` (Settings → Secrets and variables → Actions).  Never pass
  the key inline on the command line or commit it to source control.
- A missing or invalid `OPENAI_API_KEY` causes tests to **fail** (not skip)
  with an `APIConnectionError`.
- To run the suite without OpenAI calls, skip OpenAI-marked tests:
  `pytest -m "not openai"`.
- PostgreSQL/pgvector must be running; DB-dependent tests fail fast when the
  database is unreachable.
- The pgvector Docker image (`pgvector/pgvector:pg16`) ships with the
  `vector` extension pre-installed.  Plain PostgreSQL will not work.

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
