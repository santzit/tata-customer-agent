"""Realistic customer message simulation tests for the Tata support agent.

Two-way approach
----------------
**Section 1 -- Mocked OpenAI** (always runs, no API key required)
    Exercises the full four-node LangGraph pipeline with a deterministic mock
    OpenAI client.  These tests verify that the pipeline logic is wired
    correctly: the vector store is queried, knowledge snippets reach the
    OpenAI prompt, the reply is returned, and the turn is persisted to memory.

**Section 2 -- Live OpenAI** (skipped when OPENAI_API_KEY is absent or a dummy)
    Makes real calls to the OpenAI API using the configured key.  The Chatwoot
    webhook trigger is simulated by calling ``run_agent()`` directly — no real
    Chatwoot instance is required.  The PostgreSQL vector store and conversation
    memory are mocked; snippets are loaded from ``docs/company_context.md`` so
    the agent reasons about realistic company knowledge.

To run the live tests locally:

    OPENAI_API_KEY=sk-... LLM_MODEL=gpt-4.1 pytest tests/test_message_simulations.py -v

For Azure OpenAI, also set OPENAI_API_ENDPOINT:

    OPENAI_API_KEY=<key> OPENAI_API_ENDPOINT=https://<resource>.cognitiveservices.azure.com/openai/v1/ LLM_MODEL=gpt-4.1 pytest tests/test_message_simulations.py -v
"""

from __future__ import annotations

import os
import pathlib
import re
from unittest.mock import MagicMock

import pytest
from openai import OpenAI

from app.agent import run_agent

# ---------------------------------------------------------------------------
# Docs helpers
# ---------------------------------------------------------------------------

_DOCS_DIR = pathlib.Path(__file__).parent.parent / "docs"


def _load_doc_section(heading: str) -> str:
    """Return the body text of a ``##``-level section from company_context.md.

    Args:
        heading: The exact section heading text (without ``## ``), e.g.
            ``"Address"`` or ``"Opening Hours"``.

    Returns:
        The section body as a single string, or an empty string if not found.
    """
    content = (_DOCS_DIR / "company_context.md").read_text(encoding="utf-8")
    pattern = rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


# ---------------------------------------------------------------------------
# Helpers shared by both sections
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
    """Return a real OpenAI client using the environment API key and optional endpoint.

    When ``OPENAI_API_ENDPOINT`` is set the client points at that base URL,
    enabling Azure OpenAI Cognitive Services endpoints.
    """
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


def _run_live(
    user_message: str,
    *,
    snippets: list[str],
    conversation_id: int = 1,
    history: list[dict] | None = None,
) -> tuple[str, MagicMock, MagicMock]:
    """Run the agent with a real OpenAI client and mocked infrastructure.

    Returns:
        (agent_reply, vector_store_mock, memory_mock)
    """
    openai_client = _real_openai_client()
    vector_store = _make_vector_store(snippets)
    memory = _make_memory(history)

    agent_reply = run_agent(
        user_message=user_message,
        vector_store=vector_store,
        conversation_memory=memory,
        conversation_id=conversation_id,
        openai_client=openai_client,
    )
    return agent_reply, vector_store, memory


# ---------------------------------------------------------------------------
# Skip guard for live-OpenAI tests
# ---------------------------------------------------------------------------

_api_key = os.environ.get("OPENAI_API_KEY", "")
_KNOWN_DUMMY_KEYS = {"sk-test-dummy", "sk-placeholder", ""}
_key_is_real = _api_key not in _KNOWN_DUMMY_KEYS

requires_openai = pytest.mark.skipif(
    not _key_is_real,
    reason="OPENAI_API_KEY is not configured -- skipping live OpenAI tests",
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
# SECTION 2 -- Live OpenAI (skipped when OPENAI_API_KEY is not configured)
# ===========================================================================


@requires_openai
class TestLiveSimulations:
    """Full pipeline tests that make real calls to the OpenAI API.

    The Chatwoot webhook trigger is simulated by calling ``run_agent()``
    directly — no real Chatwoot instance or API token is required.
    The PostgreSQL vector store and conversation memory are mocked; context
    snippets come from ``docs/company_context.md`` so the agent reasons about
    realistic academy knowledge rather than hard-coded strings.

    Assertions check structural correctness (non-empty reply, correct calls)
    rather than exact wording, since LLM output is non-deterministic.
    """

    def test_greeting(self):
        """Live: agent produces a non-empty greeting for Nova Academy."""
        user_message = "Hi there"
        snippets = [
            _load_doc_section("About Us"),
            _load_doc_section("Contact Information"),
        ]

        reply, vector_store, memory = _run_live(user_message, snippets=snippets)

        vector_store.search.assert_called_once_with(user_message)
        assert isinstance(reply, str) and len(reply) > 0
        memory.add_turn.assert_called_once_with(
            conversation_id=1, user_message=user_message, assistant_reply=reply
        )

    def test_company_address(self):
        """Live: agent responds to a company address question using docs context."""
        user_message = "What is the academy address?"
        snippets = [
            _load_doc_section("Address"),
            _load_doc_section("Contact Information"),
        ]

        reply, vector_store, memory = _run_live(user_message, snippets=snippets)

        vector_store.search.assert_called_once_with(user_message)
        assert isinstance(reply, str) and len(reply) > 0
        memory.add_turn.assert_called_once()

    def test_opening_hours(self):
        """Live: agent returns opening hours from docs context."""
        user_message = "What are the opening hours?"
        snippets = [_load_doc_section("Opening Hours")]

        reply, vector_store, memory = _run_live(user_message, snippets=snippets)

        vector_store.search.assert_called_once_with(user_message)
        assert isinstance(reply, str) and len(reply) > 0
        memory.add_turn.assert_called_once()

    def test_courses_offered(self):
        """Live: agent lists available courses from docs context."""
        user_message = "What courses does Nova Academy offer?"
        snippets = [_load_doc_section("Courses and Activities")]

        reply, vector_store, memory = _run_live(user_message, snippets=snippets)

        vector_store.search.assert_called_once_with(user_message)
        assert isinstance(reply, str) and len(reply) > 0
        memory.add_turn.assert_called_once()

    def test_pricing_plans(self):
        """Live: agent explains pricing plans from docs context."""
        user_message = "How much does a membership cost?"
        snippets = [_load_doc_section("Membership Plans and Prices")]

        reply, vector_store, memory = _run_live(user_message, snippets=snippets)

        vector_store.search.assert_called_once_with(user_message)
        assert isinstance(reply, str) and len(reply) > 0
        memory.add_turn.assert_called_once()

    def test_unknown_topic_politely_declines(self):
        """Live: agent replies gracefully for an off-topic query."""
        user_message = "Can you book a table at a restaurant for me?"
        snippets: list[str] = []

        reply, vector_store, memory = _run_live(user_message, snippets=snippets)

        vector_store.search.assert_called_once_with(user_message)
        assert isinstance(reply, str) and len(reply) > 0
        memory.add_turn.assert_called_once()

    def test_multi_turn_conversation(self):
        """Live: turn-1 history is injected and turn-2 produces a valid reply."""
        conversation_id = 201

        # Turn 1 — greeting
        reply_1, vector_store_1, memory_1 = _run_live(
            "Hi there",
            snippets=[_load_doc_section("About Us")],
            conversation_id=conversation_id,
        )
        assert isinstance(reply_1, str) and len(reply_1) > 0
        memory_1.add_turn.assert_called_once_with(
            conversation_id=conversation_id,
            user_message="Hi there",
            assistant_reply=reply_1,
        )

        # Turn 2 — follow-up with history injected (simulating memory retrieval)
        history = [
            {"role": "user", "content": "Hi there"},
            {"role": "assistant", "content": reply_1},
        ]
        reply_2, vector_store_2, memory_2 = _run_live(
            "What are your opening hours?",
            snippets=[_load_doc_section("Opening Hours")],
            conversation_id=conversation_id,
            history=history,
        )
        assert isinstance(reply_2, str) and len(reply_2) > 0
        memory_2.add_turn.assert_called_once_with(
            conversation_id=conversation_id,
            user_message="What are your opening hours?",
            assistant_reply=reply_2,
        )
