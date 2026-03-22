"""Realistic customer message simulation tests for the Tata support agent.

All tests use real services:
- OpenAI (chat completions + embeddings) — real API call
- PostgreSQL/pgvector vector store — real DB, pre-populated from
  ``docs/company_context.md`` using real OpenAI embeddings
- PostgreSQL conversation memory — real DB, turn persisted and verified
- Chatwoot — simulated by POSTing Chatwoot-format JSON to the ``/webhook``
  endpoint via FastAPI\'s ``TestClient``; the actual Chatwoot HTTP call is
  captured by a ``MagicMock``.  No live Chatwoot instance is required.

The :class:`~app.message_buffer.MessageBuffer` is initialised with
``delay_seconds=0`` (synchronous mode) in all test fixtures.  This means the
webhook handler blocks until the full agent pipeline has finished and Chatwoot
has been notified — no ``time.sleep`` is needed.
"""

from __future__ import annotations

import os
import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Docs helpers
# ---------------------------------------------------------------------------

_DOCS_DIR = pathlib.Path(__file__).parent.parent / "docs"


def _iter_doc_sections() -> list[tuple[str, str]]:
    """Return (section_id, full_text) pairs for every ## section in company_context.md."""
    content = (_DOCS_DIR / "company_context.md").read_text(encoding="utf-8")
    parts = re.split(r"^## ", content, flags=re.MULTILINE)
    sections = []
    for part in parts[1:]:
        lines = part.strip().split("\n", 1)
        heading = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        if body:
            section_id = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
            sections.append((section_id, f"{heading}\n\n{body}"))
    return sections


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _print_reply(user_message: str, reply, turn=None) -> None:
    label = f"Turn {turn}" if turn is not None else "Exchange"
    sep = "-" * 60
    text = "\n  [next msg] ".join(reply) if isinstance(reply, list) else reply
    print(f"\n{sep}")
    print(f"[{label}] User : {user_message}")
    print(f"[{label}] Agent: {text}")
    print(sep)


def _collect_chatwoot_reply(mock_chatwoot: MagicMock) -> str:
    parts = [call.kwargs["message"] for call in mock_chatwoot.send_message.call_args_list]
    return "\n\n".join(parts)


def _make_webhook_payload(content: str, conversation_id: int = 1) -> dict:
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
# Skip guard
# ---------------------------------------------------------------------------

_api_key = os.environ.get("OPENAI_API_KEY", "")
_KNOWN_DUMMY_KEYS = {"sk-test-dummy", "sk-placeholder", ""}
_key_is_real = _api_key not in _KNOWN_DUMMY_KEYS

requires_openai = pytest.mark.skipif(
    not _key_is_real,
    reason="OPENAI_API_KEY is not configured -- skipping live tests",
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def live_infrastructure(require_pg, pg_dsn, pg_test_vector_table, pg_test_memory_table):
    """Set up real services shared by all live simulation tests.

    Uses a synchronous MessageBuffer (delay_seconds=0) so each POST blocks
    until the full agent pipeline finishes — no time.sleep required.
    """
    from app.config import settings
    from app.conversation_memory import ConversationMemory
    from app.main import _process_buffered_messages, app
    from app.message_buffer import MessageBuffer
    from app.pg_vector_store import PgVectorStore

    openai_client = settings.make_openai_client()
    store = PgVectorStore(dsn=pg_dsn, table=pg_test_vector_table, openai_client=openai_client)
    store.ensure_table()
    for section_id, text in _iter_doc_sections():
        store.upsert(section_id, text, {"source": "company_context"})

    memory = ConversationMemory(dsn=pg_dsn, table=pg_test_memory_table)
    memory.ensure_table()

    mock_chatwoot = MagicMock()
    mock_chatwoot.send_message.return_value = {"id": 99, "content": "mocked reply"}

    buffer = MessageBuffer(delay_seconds=0, on_flush=_process_buffered_messages)

    with (
        patch("app.main._vector_store", store),
        patch("app.main._conversation_memory", memory),
        patch("app.main._chatwoot_client", mock_chatwoot),
        patch("app.main._message_buffer", buffer),
    ):
        yield TestClient(app, raise_server_exceptions=True), memory, mock_chatwoot


# ===========================================================================
# Live tests
# ===========================================================================


@requires_openai
class TestLiveSimulations:
    """Full pipeline tests: real OpenAI + real pgvector + real memory + mock Chatwoot.

    The MessageBuffer uses delay_seconds=0 so POST /webhook blocks until
    the agent has finished and Chatwoot has been notified — no time.sleep needed.
    """

    def test_greeting(self, live_infrastructure):
        """Live: agent greets the customer; reply is friendly, turn is persisted."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2001
        mock_chatwoot.reset_mock()

        response = client.post("/webhook", json=_make_webhook_payload("Hi there", conv_id))

        assert response.status_code == 200
        assert response.json() == {"status": "queued", "conversation_id": conv_id}
        assert mock_chatwoot.send_message.called
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("Hi there", reply)

        reply_lower = reply.lower()
        assert any(kw in reply_lower for kw in (
            "hello", "hi", "hey", "welcome", "help", "assist", "good day", "how can"
        )), f"Greeting reply not friendly: {reply!r}"
        assert not any(kw in reply_lower for kw in (
            "plan", "r$", "150", "250", "400", "trial class", "yoga", "pilates", "crossfit"
        )), f"First greeting has unsolicited service info: {reply!r}"

        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "Hi there"}
        assert history[1] == {"role": "assistant", "content": reply}

    def test_company_address(self, live_infrastructure):
        """Live: agent returns the campus address using pgvector-retrieved context."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2002
        mock_chatwoot.reset_mock()

        response = client.post("/webhook", json=_make_webhook_payload("What is the gym address?", conv_id))

        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("What is the gym address?", reply)

        assert any(kw in reply.lower() for kw in (
            "742", "evergreen", "austin", "texas", "tx", "san francisco", "campus", "location"
        )), f"Address reply missing location details: {reply!r}"

        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "What is the gym address?"}
        assert history[1] == {"role": "assistant", "content": reply}

    def test_opening_hours(self, live_infrastructure):
        """Live: agent returns opening hours using pgvector-retrieved context."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2003
        mock_chatwoot.reset_mock()

        response = client.post("/webhook", json=_make_webhook_payload("What are the opening hours?", conv_id))

        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("What are the opening hours?", reply)

        assert any(kw in reply.lower() for kw in (
            "monday", "friday", "saturday", "sunday", "08:00", "8:00", "20:00", "17:00", "closed", "hour", "open"
        )), f"Opening hours reply missing schedule details: {reply!r}"

        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "What are the opening hours?"}
        assert history[1] == {"role": "assistant", "content": reply}

    def test_activities_offered(self, live_infrastructure):
        """Live: agent lists available gym activities using pgvector-retrieved context."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2004
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("What classes does Nova Gym Academy offer?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("What classes does Nova Gym Academy offer?", reply)

        assert any(kw in reply.lower() for kw in (
            "yoga", "pilates", "crossfit", "swimming", "training", "class", "fitness", "spin", "hiit", "cardio"
        )), f"Activities reply missing gym class details: {reply!r}"

        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "What classes does Nova Gym Academy offer?"}
        assert history[1] == {"role": "assistant", "content": reply}

    def test_pricing_plans(self, live_infrastructure):
        """Live: agent explains membership pricing using pgvector-retrieved context."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2005
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("How much does a membership cost?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("How much does a membership cost?", reply)

        assert any(kw in reply.lower() for kw in (
            "basic", "standard", "premium", "plan", "r$", "150", "250", "400", "month", "membership", "price"
        )), f"Pricing reply missing plan details: {reply!r}"

        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "How much does a membership cost?"}
        assert history[1] == {"role": "assistant", "content": reply}

    def test_unknown_topic_politely_declines(self, live_infrastructure):
        """Live: agent politely declines an off-topic request."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2006
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("Can you book a table at a restaurant for me?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("Can you book a table at a restaurant for me?", reply)

        reply_lower = reply.lower()
        assert not any(phrase in reply_lower for phrase in (
            "i\'ll book", "i will book", "i\'ve booked", "i have booked",
            "your reservation is", "booking confirmed"
        )), f"Agent incorrectly offered to book a restaurant: {reply!r}"
        assert any(kw in reply_lower for kw in (
            "cannot", "can\'t", "unable", "sorry", "not sure", "don\'t", "outside", "human agent", "contact", "assist"
        )), f"Agent did not politely decline the off-topic request: {reply!r}"

        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2

    def test_multi_turn_conversation(self, live_infrastructure):
        """Live: turn-1 history is stored in real DB and injected into turn-2 call."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2007

        mock_chatwoot.reset_mock()
        response_1 = client.post("/webhook", json=_make_webhook_payload("Hi there", conv_id))
        assert response_1.status_code == 200
        assert response_1.json()["status"] == "queued"
        reply_1 = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply_1) > 0
        _print_reply("Hi there", reply_1, turn=1)

        history_after_1 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_1) == 2
        assert history_after_1[0] == {"role": "user", "content": "Hi there"}
        assert history_after_1[1] == {"role": "assistant", "content": reply_1}

        mock_chatwoot.reset_mock()
        response_2 = client.post(
            "/webhook",
            json=_make_webhook_payload("What are your opening hours?", conv_id),
        )
        assert response_2.status_code == 200
        assert response_2.json()["status"] == "queued"
        reply_2 = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply_2) > 0
        _print_reply("What are your opening hours?", reply_2, turn=2)

        assert any(kw in reply_2.lower() for kw in (
            "monday", "friday", "saturday", "sunday", "08:00", "8:00", "20:00", "17:00", "closed", "hour", "open"
        )), f"Turn 2 opening hours reply missing schedule details: {reply_2!r}"

        history_after_2 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_2) == 4
        assert history_after_2[2] == {"role": "user", "content": "What are your opening hours?"}
        assert history_after_2[3] == {"role": "assistant", "content": reply_2}

    def test_three_turn_memory_context(self, live_infrastructure):
        """Live: 3-turn conversation — agent is contextually aware in turn 3.

        Turn 1: "Hi"                            → friendly greeting only
        Turn 2: "What are the plans and prices" → RAG pricing info in reply
        Turn 3: "Hi"                            → brief greeting + contextual follow-up
        """
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2008

        # Turn 1
        mock_chatwoot.reset_mock()
        r1 = client.post("/webhook", json=_make_webhook_payload("Hi", conv_id))
        assert r1.json()["status"] == "queued"
        reply_1 = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply_1) > 0
        _print_reply("Hi", reply_1, turn=1)

        assert any(kw in reply_1.lower() for kw in (
            "hello", "hi", "hey", "welcome", "help", "assist", "good day", "how can"
        )), f"Turn 1 greeting not friendly: {reply_1!r}"

        history_after_1 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_1) == 2

        # Turn 2
        mock_chatwoot.reset_mock()
        r2 = client.post("/webhook", json=_make_webhook_payload("What are the plans and prices", conv_id))
        assert r2.json()["status"] == "queued"
        reply_2 = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply_2) > 0
        _print_reply("What are the plans and prices", reply_2, turn=2)

        assert any(kw in reply_2.lower() for kw in (
            "basic", "standard", "premium", "plan", "r$", "150", "250", "400", "month", "price"
        )), f"Turn 2 reply missing pricing info: {reply_2!r}"

        history_after_2 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_2) == 4

        # Turn 3
        mock_chatwoot.reset_mock()
        r3 = client.post("/webhook", json=_make_webhook_payload("Hi", conv_id))
        assert r3.json()["status"] == "queued"
        reply_3 = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply_3) > 0
        _print_reply("Hi", reply_3, turn=3)

        reply_3_lower = reply_3.lower()
        assert "context does not" not in reply_3_lower and "context doesn\'t" not in reply_3_lower
        assert any(kw in reply_3_lower for kw in (
            "hello", "hi", "hey", "help", "anything", "more", "plan",
            "visit", "interested", "would you", "sign"
        )), f"Turn 3 not contextually aware: {reply_3!r}"
        assert "welcome to" not in reply_3_lower or any(kw in reply_3_lower for kw in (
            "plan", "visit", "interested", "would you", "sign", "anything"
        )), f"Turn 3 ignores conversation history: {reply_3!r}"

        history_after_3 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_3) == 6
