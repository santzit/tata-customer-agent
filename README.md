# tata-customer-agent

Webhook-based AI customer support agent **Tata** built with:

| Component | Technology |
|-----------|-----------|
| Webhook server | [FastAPI](https://fastapi.tiangolo.com/) |
| Agent workflow | [LangGraph](https://langchain-ai.github.io/langgraph/) |
| LLM + Embeddings | [OpenAI](https://platform.openai.com/) (`gpt-4o-mini` / `text-embedding-3-small`) |
| Vector store (RAG) | [Qdrant](https://qdrant.tech/) |
| Deployment | Docker Compose |

## How it works

```
Chatwoot ──webhook──▶ FastAPI /webhook
                          │
                    LangGraph agent
                     ├─ retrieve  ──▶ Qdrant (similarity search)
                     └─ generate  ──▶ OpenAI chat completion
                          │
                   reply  ▼
                      Chatwoot API
```

1. Chatwoot sends a `message_created` webhook when a contact writes a message.
2. The FastAPI server filters events and forwards incoming customer messages to the LangGraph agent.
3. The agent retrieves relevant knowledge snippets from Qdrant (RAG).
4. OpenAI generates a grounded reply using the retrieved context.
5. The reply is posted back to the conversation via the Chatwoot REST API.

## Quick start

```bash
# 1. Copy and fill in your credentials
cp .env.example .env

# 2. Start Qdrant + Tata agent
docker compose up --build

# 3. Expose the webhook with ngrok (development)
ngrok http 8000
# Then set the ngrok URL as the webhook in your Chatwoot inbox settings:
# https://<ngrok-id>.ngrok.io/webhook
```

## Running tests

```bash
pip install -r requirements.txt
pytest
```

## Environment variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI secret key |
| `OPENAI_MODEL` | Chat model (default `gpt-4o-mini`) |
| `OPENAI_EMBEDDING_MODEL` | Embedding model (default `text-embedding-3-small`) |
| `QDRANT_URL` | Qdrant base URL (default `http://localhost:6333`) |
| `QDRANT_API_KEY` | Qdrant API key (optional) |
| `QDRANT_COLLECTION` | Collection name (default `tata_knowledge`) |
| `CHATWOOT_BASE_URL` | Chatwoot instance URL |
| `CHATWOOT_API_TOKEN` | Chatwoot agent bot / API token |
| `CHATWOOT_ACCOUNT_ID` | Chatwoot account ID |
| `WEBHOOK_TOKEN` | Optional secret for webhook signature validation |
