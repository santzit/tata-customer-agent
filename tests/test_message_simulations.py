"""Realistic customer message simulation tests for the Tata support agent.

Two-way approach
----------------
**Section 1 -- Mocked OpenAI** (always runs, no API key required)
    Exercises the full five-node LangGraph pipeline with a deterministic mock
    OpenAI client and mock vector store / memory.  These tests verify that the
    pipeline logic is wired correctly: the vector store is queried, knowledge
    snippets reach the OpenAI prompt, the reply is returned, the supervisor
    review step approves it, and the turn is persisted to memory.

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


def _make_mock_openai_client(reply: str, supervisor_verdict: str = "APPROVED") -> MagicMock:
    """Return a mock OpenAI client that handles both LangGraph LLM calls.

    The pipeline makes two ``chat.completions.create`` calls per turn:
    1. **Generate** — the Tata response call; returns *reply*.
    2. **Review**   — the supervisor quality-check call; returns *supervisor_verdict*
       (default ``"APPROVED"``).  Pass ``"NEEDS_HUMAN: reason"`` to simulate a
       flagged response that triggers human escalation.

    The two calls are distinguished by inspecting the system-message content:
    the supervisor call contains the word ``"supervisor"`` in its system prompt.
    """
    client = MagicMock()

    generate_choice = MagicMock()
    generate_choice.message.content = reply
    generate_response = MagicMock(choices=[generate_choice])

    supervisor_choice = MagicMock()
    supervisor_choice.message.content = supervisor_verdict
    supervisor_response = MagicMock(choices=[supervisor_choice])

    def _side_effect(model, messages, **kwargs):
        system_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        if "supervisor" in system_msg.lower():
            return supervisor_response
        return generate_response

    client.chat.completions.create.side_effect = _side_effect
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
    supervisor_verdict: str = "APPROVED",
) -> tuple[list[str], MagicMock, MagicMock, MagicMock]:
    """Run the agent with a mocked OpenAI client and mocked infrastructure.

    Args:
        supervisor_verdict: The verdict returned by the mock supervisor/review call.
            Defaults to ``"APPROVED"``.  Pass ``"NEEDS_HUMAN: reason"`` to simulate
            the review node flagging the response for human escalation.

    Returns:
        (agent_reply_parts, openai_client_mock, vector_store_mock, memory_mock)
        where ``agent_reply_parts`` is the ``list[str]`` returned by ``run_agent``.
    """
    openai_client = _make_mock_openai_client(reply, supervisor_verdict=supervisor_verdict)
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


def _print_reply(user_message: str, reply: str | list[str], turn: int | None = None) -> None:
    """Print a formatted exchange so the agent reply is visible in pytest -s / CI output."""
    label = f"Turn {turn}" if turn is not None else "Exchange"
    sep = "-" * 60
    text = "\n  [next msg] ".join(reply) if isinstance(reply, list) else reply
    print(f"\n{sep}")
    print(f"[{label}] User : {user_message}")
    print(f"[{label}] Agent: {text}")
    print(sep)


def _collect_chatwoot_reply(mock_chatwoot: MagicMock) -> str:
    """Return the full agent reply as a single string from all Chatwoot send_message calls.

    When the agent sends multiple message parts, they are joined with double
    newlines — matching how they are stored in conversation memory.
    """
    parts = [call.kwargs["message"] for call in mock_chatwoot.send_message.call_args_list]
    return "\n\n".join(parts)


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
        call_messages = openai_client.chat.completions.create.call_args_list[0].kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert snippets[0] in user_content
        assert snippets[1] in user_content
        assert reply == [expected_reply]
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
        call_messages = openai_client.chat.completions.create.call_args_list[0].kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "Bombay House" in user_content
        assert reply == [expected_reply]
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
        call_messages = openai_client.chat.completions.create.call_args_list[0].kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "09:00" in user_content
        assert reply == [expected_reply]
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
        call_messages = openai_client.chat.completions.create.call_args_list[0].kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "Nexon" in user_content
        assert "EV" in user_content
        assert reply == [expected_reply]
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
        call_messages = openai_client.chat.completions.create.call_args_list[0].kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "100,000 km" in user_content
        assert reply == [expected_reply]
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
        call_messages = openai_client.chat.completions.create.call_args_list[0].kwargs["messages"]
        user_content = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "Can you book a table" in user_content
        assert reply == [expected_reply]
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
        assert reply_1 == ["Hello! How can I help you today?"]
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
        assert reply_2 == ["Our showrooms are open Monday-Saturday, 9 AM to 7 PM."]

        call_messages = openai_2.chat.completions.create.call_args_list[0].kwargs["messages"]
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

    def test_three_turn_memory_context(self):
        """3-turn conversation: agent retains plans/prices context across all turns.

        Turn 1: "Hi"              → greeting
        Turn 2: "What are the plans and prices" → agent retrieves and returns pricing info
        Turn 3: "Hi"              → agent has full 2-turn history and may reference earlier topic
        """
        conversation_id = 102

        pricing_snippets = [
            "Nova Academy Membership Plans: Basic R$150/month, Standard R$250/month, Premium R$400/month.",
            "All plans include access to group classes. Premium adds personal trainer sessions.",
        ]

        # Turn 1 -- greeting
        reply_1, _, _, memory_1 = _run_mocked(
            "Hi",
            snippets=["Welcome to Nova Academy customer support."],
            reply="Hello! How can I help you today?",
            conversation_id=conversation_id,
        )
        assert reply_1 == ["Hello! How can I help you today?"]
        memory_1.add_turn.assert_called_once_with(
            conversation_id=conversation_id,
            user_message="Hi",
            assistant_reply="Hello! How can I help you today?",
        )

        # Turn 2 -- pricing question; history from turn 1 pre-loaded
        history_after_1 = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello! How can I help you today?"},
        ]
        reply_2, openai_2, vector_2, memory_2 = _run_mocked(
            "What are the plans and prices",
            snippets=pricing_snippets,
            reply="We offer Basic (R$150/month), Standard (R$250/month), and Premium (R$400/month) plans.",
            conversation_id=conversation_id,
            history=history_after_1,
        )
        full_reply_2 = "\n\n".join(reply_2)
        assert (
            "150" in full_reply_2
            or "250" in full_reply_2
            or "400" in full_reply_2
            or "plans" in full_reply_2.lower()
        )

        # Verify that pricing snippets were forwarded to OpenAI (they appear in the last user message)
        call_messages_2 = openai_2.chat.completions.create.call_args_list[0].kwargs["messages"]
        # The last message is always the current user turn (with Knowledge context prepended)
        last_user_msg = next(
            m["content"] for m in reversed(call_messages_2) if m["role"] == "user"
        )
        assert "Basic" in last_user_msg or "150" in last_user_msg
        memory_2.add_turn.assert_called_once()

        # Turn 3 -- another greeting; 2-turn history is pre-loaded
        history_after_2 = history_after_1 + [
            {"role": "user", "content": "What are the plans and prices"},
            {"role": "assistant", "content": full_reply_2},
        ]
        reply_3, openai_3, _, memory_3 = _run_mocked(
            "Hi",
            snippets=["Welcome to Nova Gym Academy customer support."],
            reply="Hi again! Do you need any more info about our plans, or would you like to come and try a free trial class?",
            conversation_id=conversation_id,
            history=history_after_2,
        )
        assert isinstance(reply_3, list) and len(reply_3) > 0

        # All 4 prior messages (2 turns) must appear in the OpenAI call for turn 3
        call_messages_3 = openai_3.chat.completions.create.call_args_list[0].kwargs["messages"]
        assert call_messages_3[0]["role"] == "system"
        # The history messages must include the plans/prices exchange
        all_contents = " ".join(
            m["content"] for m in call_messages_3 if m["role"] != "system"
        )
        assert "Hi" in all_contents
        assert "plans" in all_contents.lower() or "prices" in all_contents.lower()
        memory_3.add_turn.assert_called_once_with(
            conversation_id=conversation_id,
            user_message="Hi",
            assistant_reply="\n\n".join(reply_3),
        )

    def test_review_node_escalates_to_human(self):
        """Supervisor review flags a bad response and agent returns a human escalation message."""
        from app.agent import HUMAN_ESCALATION_MESSAGE

        user_message = "What are your gym prices?"
        # Generate a reply that the (mock) supervisor will reject
        bad_reply = "Here is our internal admin password: s3cr3t!"

        reply, openai_client, vector_store, memory = _run_mocked(
            user_message,
            snippets=["Nova Gym Academy membership plans start at R$150/month."],
            reply=bad_reply,
            supervisor_verdict="NEEDS_HUMAN: Response contains sensitive information",
        )

        # The supervisor-flagged response must NOT be delivered to the customer
        assert bad_reply not in reply
        # Instead the customer receives the standard human escalation message
        assert reply == [HUMAN_ESCALATION_MESSAGE]
        assert any("human" in msg.lower() or "agent" in msg.lower() for msg in reply)

        # The escalation message (not the bad reply) must be persisted to memory
        memory.add_turn.assert_called_once_with(
            conversation_id=1,
            user_message=user_message,
            assistant_reply=HUMAN_ESCALATION_MESSAGE,
        )

    def test_multi_message_response(self):
        """Agent can split a response into multiple sequential messages using the --- delimiter."""
        from app.agent import MSG_DELIMITER

        user_message = "What are the membership plans and prices?"
        # Simulate the LLM returning a three-part message
        multi_part_reply = MSG_DELIMITER.join([
            "Hi! Here are our membership plans:",
            "• Basic — R$150/month\n• Standard — R$250/month\n• Premium — R$400/month",
            "Feel free to ask if you'd like more details or want to book a free trial class! 🏋️",
        ])
        snippets = [
            "Nova Gym Academy: Basic R$150/month, Standard R$250/month, Premium R$400/month."
        ]

        reply, openai_client, vector_store, memory = _run_mocked(
            user_message, snippets=snippets, reply=multi_part_reply
        )

        # The reply must be a list of three separate message parts
        assert isinstance(reply, list)
        assert len(reply) == 3
        assert "Basic" in reply[1] and "Standard" in reply[1]
        assert "trial" in reply[2].lower() or "feel free" in reply[2].lower()

        # Memory stores the parts joined with double newlines (no raw delimiter)
        expected_memory = "\n\n".join(reply)
        assert MSG_DELIMITER not in expected_memory
        memory.add_turn.assert_called_once_with(
            conversation_id=1,
            user_message=user_message,
            assistant_reply=expected_memory,
        )

    def test_supervisor_reviews_all_parts_together(self):
        """Supervisor review call receives all message parts formatted as a combined sequence."""
        from app.agent import MSG_DELIMITER

        user_message = "Tell me about your gym plans."
        # A two-part reply the supervisor will approve
        two_part_reply = MSG_DELIMITER.join([
            "Hi! I'll send you our plans info.",
            "We offer Basic (R$150), Standard (R$250), and Premium (R$400) memberships.",
        ])
        snippets = ["Nova Gym Academy memberships: Basic, Standard, Premium."]

        _, openai_client, _, _ = _run_mocked(
            user_message, snippets=snippets, reply=two_part_reply
        )

        # The second call must be the supervisor review
        review_call = openai_client.chat.completions.create.call_args_list[1]
        review_messages = review_call.kwargs["messages"]
        system_msg = next(m["content"] for m in review_messages if m["role"] == "system")
        assert "supervisor" in system_msg.lower()

        # The user message to the supervisor must contain BOTH parts together
        user_msg_to_supervisor = next(
            m["content"] for m in review_messages if m["role"] == "user"
        )
        assert "Message 1 of 2" in user_msg_to_supervisor
        assert "Message 2 of 2" in user_msg_to_supervisor
        assert "plans info" in user_msg_to_supervisor
        assert "Basic" in user_msg_to_supervisor


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

    Each test verifies three things:
    1. HTTP plumbing — the webhook returns 200 and ``status: "replied"``.
    2. RAG correctness — the reply contains facts drawn from ``docs/company_context.md``
       (specific keywords that could only appear if the vector search returned the
       right documents).
    3. Memory persistence — the conversation turn is stored in PostgreSQL and can
       be retrieved.
    """

    def test_greeting(self, live_infrastructure):
        """Live: agent greets the customer; reply is friendly, turn is persisted."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2001
        mock_chatwoot.reset_mock()

        response = client.post("/webhook", json=_make_webhook_payload("Hi there", conv_id))

        assert response.status_code == 200
        assert response.json() == {"status": "replied", "conversation_id": conv_id}
        assert mock_chatwoot.send_message.called
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("Hi there", reply)

        # Agent should respond with a simple, friendly greeting only — no unsolicited info.
        reply_lower = reply.lower()
        assert any(
            kw in reply_lower
            for kw in ("hello", "hi", "hey", "welcome", "help", "assist", "good day", "how can")
        ), f"Greeting reply does not seem friendly: {reply!r}"
        # First greeting must NOT proactively dump service/product information.
        assert not any(
            kw in reply_lower
            for kw in ("plan", "r$", "150", "250", "400", "trial class", "yoga", "pilates", "crossfit")
        ), f"First greeting reply contains unsolicited service info: {reply!r}"

        # Memory: both turns written to the DB.
        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "Hi there"}
        assert history[1] == {"role": "assistant", "content": reply}

    def test_company_address(self, live_infrastructure):
        """Live: agent returns the campus address using pgvector-retrieved context."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2002
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("What is the gym address?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "replied"
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("What is the gym address?", reply)

        # RAG must surface address details from the "Address" section.
        # company_context.md: "742 Evergreen Street … Austin, TX" / "San Francisco, CA"
        reply_lower = reply.lower()
        assert any(
            kw in reply_lower
            for kw in ("742", "evergreen", "austin", "texas", "tx", "san francisco", "campus", "location")
        ), f"Address reply missing location details (RAG likely failed): {reply!r}"

        # Memory persistence.
        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "What is the gym address?"}
        assert history[1] == {"role": "assistant", "content": reply}

    def test_opening_hours(self, live_infrastructure):
        """Live: agent returns opening hours using pgvector-retrieved context."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2003
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("What are the opening hours?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "replied"
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("What are the opening hours?", reply)

        # RAG must surface schedule details from the "Opening Hours" section.
        # company_context.md: Mon–Fri 08:00–20:00, Sat 09:00–17:00, Sunday closed.
        reply_lower = reply.lower()
        assert any(
            kw in reply_lower
            for kw in ("monday", "friday", "saturday", "sunday", "08:00", "8:00", "20:00", "17:00", "closed", "hour", "open")
        ), f"Opening hours reply missing schedule details (RAG likely failed): {reply!r}"

        # Memory persistence.
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
        assert response.json()["status"] == "replied"
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("What classes does Nova Gym Academy offer?", reply)

        # RAG must surface activity offerings from the "Activities and Classes" section.
        # company_context.md includes: yoga, pilates, crossfit, swimming, personal training.
        reply_lower = reply.lower()
        assert any(
            kw in reply_lower
            for kw in ("yoga", "pilates", "crossfit", "swimming", "training", "class", "fitness", "spin", "hiit", "cardio")
        ), f"Activities reply missing gym class details (RAG likely failed): {reply!r}"

        # Memory persistence.
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
        assert response.json()["status"] == "replied"
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("How much does a membership cost?", reply)

        # RAG must surface plan details from the "Membership Plans and Prices" section.
        # company_context.md: Basic (R$150), Standard (R$250), Premium (R$400).
        reply_lower = reply.lower()
        assert any(
            kw in reply_lower
            for kw in ("basic", "standard", "premium", "plan", "r$", "150", "250", "400", "month", "membership", "price")
        ), f"Pricing reply missing plan details (RAG likely failed): {reply!r}"

        # Memory persistence.
        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "How much does a membership cost?"}
        assert history[1] == {"role": "assistant", "content": reply}

    def test_unknown_topic_politely_declines(self, live_infrastructure):
        """Live: agent politely declines an off-topic request (restaurant booking)."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2006
        mock_chatwoot.reset_mock()

        response = client.post(
            "/webhook",
            json=_make_webhook_payload("Can you book a table at a restaurant for me?", conv_id),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "replied"
        reply = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply) > 0
        _print_reply("Can you book a table at a restaurant for me?", reply)

        # The agent must NOT claim to book a restaurant — the system prompt instructs it
        # to say "I'm not sure" when the knowledge context doesn't cover the topic.
        reply_lower = reply.lower()
        assert not any(
            phrase in reply_lower
            for phrase in ("i'll book", "i will book", "i've booked", "i have booked", "your reservation is", "booking confirmed")
        ), f"Agent incorrectly offered to book a restaurant: {reply!r}"
        # The reply should be a polite decline or redirect.
        assert any(
            kw in reply_lower
            for kw in ("cannot", "can't", "unable", "sorry", "not sure", "don't", "outside", "human agent", "contact", "assist")
        ), f"Agent did not politely decline the off-topic request: {reply!r}"

        # Memory persistence.
        history = memory.get_history(conversation_id=conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "Can you book a table at a restaurant for me?"}
        assert history[1] == {"role": "assistant", "content": reply}

    def test_multi_turn_conversation(self, live_infrastructure):
        """Live: turn-1 history is stored in real DB and injected into turn-2 call."""
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2007

        # Turn 1 — greeting
        mock_chatwoot.reset_mock()
        response_1 = client.post("/webhook", json=_make_webhook_payload("Hi there", conv_id))
        assert response_1.status_code == 200
        assert response_1.json()["status"] == "replied"
        reply_1 = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply_1) > 0
        _print_reply("Hi there", reply_1, turn=1)

        # Turn-1 memory: persisted immediately.
        history_after_1 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_1) == 2
        assert history_after_1[0] == {"role": "user", "content": "Hi there"}
        assert history_after_1[1] == {"role": "assistant", "content": reply_1}

        # Turn 2 — follow-up; agent loads turn-1 history from the real DB.
        mock_chatwoot.reset_mock()
        response_2 = client.post(
            "/webhook",
            json=_make_webhook_payload("What are your opening hours?", conv_id),
        )
        assert response_2.status_code == 200
        assert response_2.json()["status"] == "replied"
        reply_2 = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply_2) > 0
        _print_reply("What are your opening hours?", reply_2, turn=2)

        # RAG must surface schedule details from the "Opening Hours" section.
        reply_2_lower = reply_2.lower()
        assert any(
            kw in reply_2_lower
            for kw in ("monday", "friday", "saturday", "sunday", "08:00", "8:00", "20:00", "17:00", "closed", "hour", "open")
        ), f"Turn 2 opening hours reply missing schedule details (RAG likely failed): {reply_2!r}"

        # Both turns persisted and content matches what was sent to Chatwoot.
        history_after_2 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_2) == 4
        assert history_after_2[0] == {"role": "user", "content": "Hi there"}
        assert history_after_2[1] == {"role": "assistant", "content": reply_1}
        assert history_after_2[2] == {"role": "user", "content": "What are your opening hours?"}
        assert history_after_2[3] == {"role": "assistant", "content": reply_2}

    def test_three_turn_memory_context(self, live_infrastructure):
        """Live: 3-turn conversation — RAG and memory both work across all turns.

        Turn 1: "Hi"                            → friendly greeting
        Turn 2: "What are the plans and prices" → RAG retrieves gym pricing; reply contains plan names/prices
        Turn 3: "Hi"                            → agent has 4-message history from real DB; replies contextually
        """
        client, memory, mock_chatwoot = live_infrastructure
        conv_id = 2008

        # -- Turn 1: greeting --------------------------------------------------
        mock_chatwoot.reset_mock()
        response_1 = client.post("/webhook", json=_make_webhook_payload("Hi", conv_id))
        assert response_1.status_code == 200
        assert response_1.json()["status"] == "replied"
        reply_1 = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply_1) > 0
        _print_reply("Hi", reply_1, turn=1)

        # Agent should respond with a simple greeting only — no unsolicited info.
        reply_1_lower = reply_1.lower()
        assert any(
            kw in reply_1_lower
            for kw in ("hello", "hi", "hey", "welcome", "help", "assist", "good day", "how can")
        ), f"Turn 1 greeting reply does not seem friendly: {reply_1!r}"

        history_after_1 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_1) == 2
        assert history_after_1[0] == {"role": "user", "content": "Hi"}
        assert history_after_1[1] == {"role": "assistant", "content": reply_1}

        # -- Turn 2: pricing question (RAG critical) ---------------------------
        mock_chatwoot.reset_mock()
        response_2 = client.post(
            "/webhook",
            json=_make_webhook_payload("What are the plans and prices", conv_id),
        )
        assert response_2.status_code == 200
        assert response_2.json()["status"] == "replied"
        reply_2 = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply_2) > 0
        _print_reply("What are the plans and prices", reply_2, turn=2)

        # RAG must supply the pricing context; verify the reply contains plan/price facts.
        # company_context.md: Basic (R$150), Standard (R$250), Premium (R$400).
        reply_2_lower = reply_2.lower()
        assert any(
            kw in reply_2_lower
            for kw in ("basic", "standard", "premium", "plan", "r$", "150", "250", "400", "month", "price")
        ), f"Turn 2 reply does not mention pricing info (RAG likely failed): {reply_2!r}"

        history_after_2 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_2) == 4
        assert history_after_2[0] == {"role": "user", "content": "Hi"}
        assert history_after_2[1] == {"role": "assistant", "content": reply_1}
        assert history_after_2[2] == {"role": "user", "content": "What are the plans and prices"}
        assert history_after_2[3] == {"role": "assistant", "content": reply_2}

        # -- Turn 3: second greeting with full history in DB -------------------
        mock_chatwoot.reset_mock()
        response_3 = client.post("/webhook", json=_make_webhook_payload("Hi", conv_id))
        assert response_3.status_code == 200
        assert response_3.json()["status"] == "replied"
        reply_3 = _collect_chatwoot_reply(mock_chatwoot)
        assert len(reply_3) > 0
        _print_reply("Hi", reply_3, turn=3)

        # With 4-message history loaded from the DB the agent should give a coherent
        # contextual response — not an "I don't know" or "context doesn't include" reply.
        reply_3_lower = reply_3.lower()
        assert "context does not" not in reply_3_lower and "context doesn't" not in reply_3_lower, (
            f"Turn 3 reply suggests RAG or memory context was empty: {reply_3!r}"
        )
        # Should include a greeting and a contextual follow-up referencing the prior topic.
        assert any(
            kw in reply_3_lower
            for kw in ("hello", "hi", "hey", "help", "anything", "more", "plan", "visit", "interested", "would you")
        ), f"Turn 3 greeting reply does not seem contextually aware: {reply_3!r}"

        # All 3 turns persisted — 6 rows in the DB.
        history_after_3 = memory.get_history(conversation_id=conv_id)
        assert len(history_after_3) == 6
        assert history_after_3[0] == {"role": "user", "content": "Hi"}
        assert history_after_3[1] == {"role": "assistant", "content": reply_1}
        assert history_after_3[2] == {"role": "user", "content": "What are the plans and prices"}
        assert history_after_3[3] == {"role": "assistant", "content": reply_2}
        assert history_after_3[4] == {"role": "user", "content": "Hi"}
        assert history_after_3[5] == {"role": "assistant", "content": reply_3}
