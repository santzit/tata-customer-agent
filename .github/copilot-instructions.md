# Copilot instructions for tata-customer-agent

## Local development prerequisites

Before running tests or the agent locally you need two real services:

### 1. PostgreSQL with pgvector

Plain PostgreSQL will **not** work — the `vector` extension must be present.
Use the official pgvector Docker image:

```bash
docker run -d \
  --name tata-pgvector \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=tata_agent \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

The test suite (`conftest.py`) creates the extension and tables automatically
the first time it runs.

### 2. OpenAI API key

Set `OPENAI_API_KEY` in a `.env` file at the repository root:

```bash
cp .env.example .env
# Open .env and fill in OPENAI_API_KEY=sk-...
```

`conftest.py` loads `.env` via `python-dotenv` at session start, so the key is
picked up without any shell export. In CI it comes from the repository secret
`OPENAI_API_KEY` (Settings → Secrets and variables → Actions) — never
hard-code or commit the key.

### 3. Running tests

```bash
pip install -r requirements.txt
pytest --tb=short -v -s
```

## Architecture notes

- The webhook returns `{"status": "queued"}` immediately.
- `MessageBuffer` debounces messages per `conversation_id`; after
  `RESPONSE_DELAY_SECONDS` (default 120 s) of silence all buffered messages
  are joined and sent to the LangGraph agent in a background thread.
- In tests `MessageBuffer(delay_seconds=0)` flushes synchronously so
  `client.post("/webhook", …)` blocks until the full pipeline finishes.
- Only Chatwoot outbound HTTP is mocked (`MagicMock`). PostgreSQL/pgvector
  and OpenAI are always real in both unit and integration tests.
- A missing `OPENAI_API_KEY` causes tests to **fail** (not skip).
