"""Realistic customer message simulation tests for the Tata support agent.

Two-way approach
----------------
**Section 1 -- Mocked OpenAI** (always runs, no API key required)
    Exercises the full four-node LangGraph pipeline with a deterministic mock
    OpenAI client and mock vector store / memory.  These tests verify that the
    pipeline logic is wired correctly: the vector store is queried, knowledge
    snippets reach the OpenAI prompt, the reply is returned, and the turn is
    persisted to memory.

**Section 2 -- Live** (skipped when OPENAI_API_KEY is absent or a dummy)
    All real services except Chatwoot:
    - OpenAI (chat completions + embeddings) — real API call
    - PostgreSQL/pgvector vector store — real DB, pre-populated from
      ``docs/company_context.md`` using real OpenAI embeddings
    - PostgreSQL conversation memory — real DB, turn persisted and verified
    - Chatwoot — simulated by POSTing Chatwoot-format JSON to the ``/webhook``
      endpoint via FastAPI's ``TestClient``; the actual Chatwoot HTTP call is
      captured by a ``MagicMock``.  No live Chatwoot instance is required.

To run the live tests locally:

    OPENAI_API_KEY=sk-... \\
    LLM_MODEL=gpt-4.1 \\
    POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/tata_agent \\
    pytest tests/test_message_simulations.py::TestLiveSimulations -v

For Azure OpenAI, also set OPENAI_API_ENDPOINT:

    OPENAI_API_KEY=<key> \\
    OPENAI_API_ENDPOINT=https://<resource>.cognitiveservices.azure.com/openai/v1/ \\
    LLM_MODEL=gpt-4.1 \\
    pytest tests/test_message_simulations.py::TestLiveSimulations -v
"""

from __future__ import annotations

import os
import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from app.agent import run_agent

# ---------------------------------------------------------------------------
# Docs helpers
# ---------------------------------------------------------------------------

_DOCS_DIR = pathlib.Path(__file__).parent.parent / "docs"


def _load_doc_section(heading: str) -> str:
    """Return the body text of a ``##``-level section from company_context.md."""
    content = (_DOCS_DIR / "company_context.md").read_text(encoding="utf-8")
    # re.MULTILINE is required so that ^ inside the lookahead matches line starts.
    pattern = rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _iter_doc_sections() -> list[tuple[str, str]]:
    """Return (section_id, full_text) pairs for every ``##`` section in company_context.md."""
    content = (_DOCS_DIR / "company_context.md").read_text(encoding="utf-8")
    parts = re.split(r"^## ", content, flags=re.MULTILINE)
    sections = []
    for part in parts[1:]:  # skip preamble before first ##
        lines = part.strip().split("\n", 1)
        heading = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        if body:
            section_id = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
            sections.append((section_id, f"{heading}\n\n{body}"))
    return sections


# ---------------------------------------------------------------------------
# Helpers shared by both test sections
# ---------------------------------------------------------------------------


def _make_vector_store(snippets: list[str]) -> MagicMock:
    """Return a mock PgVectorStore whose search returns the given text snippets."""
    store = MagicMock()
    store.search.return_value = [{"text": s} for s in snippets]
    return store


def _make_memory(history: list[dict] | None = None) -> MagicMock:
    """Return a mock ConversationMemory with optional pre-loaded history."""
    memory = MagicMock()
    memory.get_history.return_value = history or []
    memory.add_turn.return_value = None
    return memory


def _make_mock_openai_client(reply: str) -> MagicMock:
    """Return a mock OpenAI client that returns *reply* from chat completions."""
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = reply
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return client


def _real_openai_client() -> OpenAI:
    """Return a real OpenAI client (standard or Azure) from environment variables."""
    kwargs: dict = {"api_key": os.environ["OPENAI_API_KEY"]}
    endpoint = os.environ.get("OPENAI_API_ENDPOINT", "")
    if endpoint:
        kwargs["base_url"] = endpoint
    return OpenAI(**kwargs)


def _run_mocked(
    user_message: str,
    *,
    snippets: list[str],
    reply: str,
    conversation_id: int = 1,
    history: list[dict] | None = None,
) -> tuple[str, MagicMock, MagicMock, MagicMock]:
    """Run the agent with a mocked OpenAI client and mocked infrastructure.

    Returns:
        (agent_reply, openai_client_mock, vector_store_mock, memory_mock)
    """
    openai_client = _make_mock_openai_client(reply)
    vector_store = _make_vector_store(snippets)
    memory = _make_memory(history)

    agent_reply = run_agent(
        user_message=user_message,
        vector_store=vector_store,
        conversation_memory=memory,
        conversation_id=conversation_id,
        openai_client=openai_client,
    )
    return agent_reply, openai_client, vector_store, memory


def _make_webhook_payload(content: str, conversation_id: int = 1) -> dict:
    """Return a minimal Chatwoot webhook payload for an incoming customer message."""
    return {
        "event": "message_created",
        "message": {
            "id": 1,
            "content": content,
            "message_type": 0,  # 0 = incoming customer message
            "conversation_id": conversation_id,
        },
        "conversation": {"id": conversation_id},
    }


# ---------------------------------------------------------------------------
# Skip guard for live tests
# ---------------------------------------------------------------------------

_api_key = os.environ.get("OPENAI_API_KEY", "")
_KNOWN_DUMMY_KEYS = {"sk-test-dummy", "sk-placeholder", ""}
_key_is_real = _api_key not in _KNOWN_DUMMY_KEYS

requires_openai = pytest.mark.skipif(
    not _key_is_real,
    reason="OPENAI_API_KEY is not configured -- skipping live tests",
)


# ===========================================================================
# SECTION 1 -- Mocked OpenAI (always runs)
# ===========================================================================


class TestMockedSimulations:
    """Full pipeline tests with a deterministic mock OpenAI client."""

    def test_greeting(self):
        """Agent greets the customer; pipeline is exercised end-to-end."""
        user_message = "Hi there"
        expected_reply = (
            "Hello! Welcome to Tata Motors support. "
            "I'm Tata, your virtual assistant. How can I help you today?"
        )
        snippets = [
            "Tata Motors customer support is available 24/7 via phone and chat.",
            "You can reach us at support@tatamotors.com or call 1800-209-7979.",
        ]

        reply, openai_client, vector_store, memory = _run_mocked(
            user_message, snippets=snippets, reply=expected_reply
        )

        vector_store.search.assert_called_once_with(user_message)
        call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert snippets[0] in user_content
        assert snippets[1] in user_content
        assert reply == expected_reply
        memory.add_turn.assert_called_once_with(
            conversation_id=1,
            user_message=user_message,
            assistant_reply=expected_reply,
        )

    def test_company_address(self):
        """Agent responds to an address question using retrieved knowledge."""
        user_message = "What is the company address?"
        expected_reply = (
            "Our registered office is at Bombay House, 24 Homi Mody Street, "
            "Mumbai, Maharashtra 400001, India."
        )
        snippets = [
            (
                "Tata Motors Limited registered office: Bombay House, 24 Homi Mody Street, "
                "Mumbai, Maharashtra 400001, India."
            ),
            "For visit-related enquiries please call the reception at +91 22 6665 8282.",
        ]

        reply, openai_client, vector_store, memory = _run_mocked(
            user_message, snippets=snippets, reply=expected_reply
        )

        vector_store.search.assert_called_once_with(user_message)
        call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "Bombay House" in user_content
        assert reply == expected_reply
        memory.add_turn.assert_called_once()

    def test_opening_hours(self):
        """Agent returns showroom hours from retrieved context."""
        user_message = "What are the opening hours of the showroom?"
        expected_reply = (
            "Our showrooms are open Monday to Saturday, 9 AM to 7 PM, "
            "and Sunday 10 AM to 5 PM."
        )
        snippets = [
            "Tata Motors showrooms are open Monday-Saturday 09:00-19:00 IST.",
            "Sunday hours: 10:00-17:00 IST. Public holidays may vary.",
        ]

        reply, openai_client, vector_store, memory = _run_mocked(
            user_message, snippets=snippets, reply=expected_reply
        )

        vector_store.search.assert_called_once_with(user_message)
        call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "09:00" in user_content
        assert reply == expected_reply
        memory.add_turn.assert_called_once()

    def test_vehicle_lineup(self):
        """Agent lists available vehicles based on retrieved knowledge."""
        user_message = "What cars does Tata offer?"
        expected_reply = (
            "Tata Motors offers a wide range including the Nexon, Harrier, Safari, "
            "Punch, Tiago, and Altroz, plus the Nexon EV and Tiago EV."
        )
        snippets = [
            "Tata Motors passenger vehicles: Nexon, Harrier, Safari, Punch, Tiago, Altroz.",
            "Electric vehicles: Nexon EV, Tiago EV, Punch EV -- available at select dealerships.",
        ]

        reply, openai_client, vector_store, memory = _run_mocked(
            user_message, snippets=snippets, reply=expected_reply
        )

        vector_store.search.assert_called_once_with(user_message)
        call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "Nexon" in user_content
        assert "EV" in user_content
        assert reply == expected_reply
        memory.add_turn.assert_called_once()

    def test_warranty_inquiry(self):
        """Agent explains the warranty policy using retrieved context."""
        user_message = "What is the warranty on Tata vehicles?"
        expected_reply = (
            "All Tata Motors vehicles come with a standard 3-year / 100,000 km "
            "warranty, whichever comes first. Extended warranty plans are also available."
        )
        snippets = [
            "Standard warranty: 3 years or 100,000 km, whichever is earlier.",
            "Extended warranty options: up to 5 years. Contact your nearest dealer.",
        ]

        reply, openai_client, vector_store, memory = _run_mocked(
            user_message, snippets=snippets, reply=expected_reply
        )

        vector_store.search.assert_called_once_with(user_message)
        call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "100,000 km" in user_content
        assert reply == expected_reply
        memory.add_turn.assert_called_once()

    def test_unknown_topic_politely_declines(self):
        """Agent replies gracefully when no relevant context is available."""
        user_message = "Can you book a table at a restaurant for me?"
        expected_reply = (
            "I'm sorry, I don't have information about that. "
            "For assistance, please contact a human agent."
        )
        snippets: list[str] = []

        reply, openai_client, vector_store, memory = _run_mocked(
            user_message, snippets=snippets, reply=expected_reply
        )

        vector_store.search.assert_called_once_with(user_message)
        call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "Can you book a table" in user_content
        assert reply == expected_reply
        memory.add_turn.assert_called_once()

    def test_multi_turn_conversation(self):
        """History from turn 1 is injected into the OpenAI prompt for turn 2."""
        conversation_id = 101

        # Turn 1
        reply_1, _, _, memory_1 = _run_mocked(
            "Hi there",
            snippets=["Customer support available 24/7."],
            reply="Hello! How can I help you today?",
            conversation_id=conversation_id,
        )
        assert reply_1 == "Hello! How can I help you today?"
        memory_1.add_turn.assert_called_once_with(
            conversation_id=conversation_id,
            user_message="Hi there",
            assistant_reply="Hello! How can I help you today?",
        )

        # Turn 2 -- history from turn 1 pre-loaded in memory mock
        history = [
            {"role": "user", "content": "Hi there"},
            {"role": "assistant", "content": "Hello! How can I help you today?"},
        ]
        reply_2, openai_2, _, memory_2 = _run_mocked(
            "What are your opening hours?",
            snippets=["Showrooms open Mon-Sat 09:00-19:00."],
            reply="Our showrooms are open Monday-Saturday, 9 AM to 7 PM.",
            conversation_id=conversation_id,
            history=history,
        )
        assert reply_2 == "Our showrooms are open Monday-Saturday, 9 AM to 7 PM."

        call_messages = openai_2.chat.completions.create.call_args.kwargs["messages"]
        assert call_messages[0]["role"] == "system"
        user_contents = [m["content"] for m in call_messages if m["role"] == "user"]
        assert any("Hi there" in c for c in user_contents)
        assistant_contents = [m["content"] for m in call_messages if m["role"] == "assistant"]
        assert any("How can I help" in c for c in assistant_contents)
        memory_2.add_turn.assert_called_once_with(
            conversation_id=conversation_id,
            user_message="What are your opening hours?",
            assistant_reply="Our showrooms are open Monday-Saturday, 9 AM to 7 PM.",
        )


# ===========================================================================
# SECTION 2 -- Live (skipped when OPENAI_API_KEY is not configured)
# ===========================================================================


@pytest.fixture(scope="class")
def live_infrastructure(require_pg, pg_dsn, pg_test_vector_table, pg_test_memory_table):
    """Set up real services shared by all live simulation tests.

    - Builds a real OpenAI client (standard or Azure).
    - Creates a real PgVectorStore and populates it with every section from
      ``docs/company_context.md`` using real OpenAI embeddings.
    - Creates a real ConversationMemory backed by the same PostgreSQL instance.
    - Provides a FastAPI TestClient with the real services injected and Chatwoot
      simulated via a MagicMock — so each test POSTs to the real ``/webhook``
      endpoint rather than calling ``run_agent()`` directly.

    Skipped automatically when ``OPENAI_API_KEY`` is absent or a placeholder
    (the ``@requires_openai`` class decorator fires first), or when PostgreSQL
    is not reachable (``require_pg`` fires).
    """
    from app.conversation_memory import ConversationMemory
    from app.main import app
    from app.pg_vector_store import PgVectorStore

    openai_client = _real_openai_client()

    store = PgVectorStore(
        dsn=pg_dsn, table=pg_test_vector_table, openai_client=openai_client
    )
    store.ensure_table()

    # Upsert every section of the company knowledge base.
    for section_id, text in _iter_doc_sections():
        store.upsert(section_id, text, {"source": "company_context"})

    memory = ConversationMemory(dsn=pg_dsn, table=pg_test_memory_table)
    memory.ensure_table()

    mock_chatwoot = MagicMock()
    mock_chatwoot.send_message.return_value = {"id": 99, "content": "mocked reply"}

    # Inject real services and mock Chatwoot into the running app.
    # Note: TestClient(app) is instantiated here but NOT entered as a context
    # manager (i.e. not `with TestClient(app) as client:`).  This means the
    # ASGI lifespan events do not run, so the module-level singletons patched
    # above are not overwritten by the startup code in ``app/main.py``.
    with (
        patch("app.main._vector_store", store),
        patch("app.main._conversation_memory", memory),
        patch("app.main._chatwoot_client", mock_chatwoot),
    ):
        yield TestClient(app, raise_server_exceptions=True), memory, mock_chatwoot


@requires_openai
class TestLiveSimulations:
    """Full pipeline tests using real OpenAI, real pgvector, and real PostgreSQL memory.

    Chatwoot is simulated: each test POSTs a Chatwoot-format JSON payload to the
    real ``/webhook`` endpoint via FastAPI's ``TestClient``.  The full request
    handling path in ``app/main.py`` is exercised — webhook parsing, agent
    invocation, and the Chatwoot reply call — while the actual Chatwoot HTTP call
    is captured by a ``MagicMock``.

    Assertions verify structural correctness (non-empty reply, memory persistence)
    rather than exact wording, since LLM output is non-deterministic.
    """

    def test_greeting(self, live_infrastructure):
        """Live: agent greets the customer; turn is persisted to real memory."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2001
        mock_chatwoot.reset_mock()

        response = client.post("/webhook", json=_make_webhook_payload("Hi there", conv_id))

        assert response.status_code == 200
        assert response.json() == {"status": "replied", "conversation_id": conv_id}
        mock_chatwoot.send_message.assert_called_once()
        reply = mock_chatwoot.send_message.call_args.kwargs["message"]
        assert isinstance(reply, str) and len(reply) > 0

        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "Hi there"}
        assert history[1] == {"role": "assistant", "content": reply}

    def test_company_address(self, live_infrastructure):
        """Live: agent answers an address question using pgvector-retrieved context."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2002
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("What is the academy address?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "replied"
        reply = mock_chatwoot.send_message.call_args.kwargs["message"]
        assert isinstance(reply, str) and len(reply) > 0
        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "What is the academy address?"}
        assert history[1]["role"] == "assistant"

    def test_opening_hours(self, live_infrastructure):
        """Live: agent returns opening hours from pgvector-retrieved context."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2003
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("What are the opening hours?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "replied"
        reply = mock_chatwoot.send_message.call_args.kwargs["message"]
        assert isinstance(reply, str) and len(reply) > 0
        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "What are the opening hours?"}
        assert history[1]["role"] == "assistant"

    def test_courses_offered(self, live_infrastructure):
        """Live: agent lists available courses from pgvector-retrieved context."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2004
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("What courses does Nova Academy offer?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "replied"
        reply = mock_chatwoot.send_message.call_args.kwargs["message"]
        assert isinstance(reply, str) and len(reply) > 0
        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "What courses does Nova Academy offer?"}
        assert history[1]["role"] == "assistant"

    def test_pricing_plans(self, live_infrastructure):
        """Live: agent explains membership pricing from pgvector-retrieved context."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2005
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("How much does a membership cost?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "replied"
        reply = mock_chatwoot.send_message.call_args.kwargs["message"]
        assert isinstance(reply, str) and len(reply) > 0
        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "How much does a membership cost?"}
        assert history[1]["role"] == "assistant"

    def test_unknown_topic_politely_declines(self, live_infrastructure):
        """Live: agent replies gracefully when the query is off-topic."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2006
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("Can you book a table at a restaurant for me?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "replied"
        reply = mock_chatwoot.send_message.call_args.kwargs["message"]
        assert isinstance(reply, str) and len(reply) > 0
        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "Can you book a table at a restaurant for me?"}
        assert history[1]["role"] == "assistant"

    def test_multi_turn_conversation(self, live_infrastructure):
        """Live: turn-1 history is stored in real memory and injected into turn 2."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2007

        # Turn 1 — greeting
        mock_chatwoot.reset_mock()
        response_1 = client.post("/webhook", json=_make_webhook_payload("Hi there", conv_id))
        assert response_1.status_code == 200
        assert response_1.json()["status"] == "replied"
        reply_1 = mock_chatwoot.send_message.call_args.kwargs["message"]
        assert isinstance(reply_1, str) and len(reply_1) > 0

        # Verify turn 1 is persisted to the real DB
        history_after_1 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_1) == 2
        assert history_after_1[0] == {"role": "user", "content": "Hi there"}
        assert history_after_1[1] == {"role": "assistant", "content": reply_1}

        # Turn 2 — follow-up; agent will load turn-1 history from real DB
        mock_chatwoot.reset_mock()
        response_2 = client.post(
            "/webhook",
            json=_make_webhook_payload("What are your opening hours?", conv_id),
        )
        assert response_2.status_code == 200
        assert response_2.json()["status"] == "replied"
        reply_2 = mock_chatwoot.send_message.call_args.kwargs["message"]
        assert isinstance(reply_2, str) and len(reply_2) > 0

        # Verify both turns are now persisted
        history_after_2 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_2) == 4
        assert history_after_2[0] == {"role": "user", "content": "Hi there"}
        assert history_after_2[2] == {"role": "user", "content": "What are your opening hours?"}
        assert history_after_2[3] == {"role": "assistant", "content": reply_2}
