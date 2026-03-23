# Copilot instructions for tata-customer-agent

## Constraints 
- Do not change the tests (/tests/*), unless specifically instructed to do so.
- Always run local tests (using pgvector/openai) before committing a new code, to ensure nothing is break

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

Get OPENAI_API_KEY from secrets.OPENAI_API_KEY (repository key)


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
