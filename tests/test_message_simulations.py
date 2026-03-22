"""Realistic customer message simulation tests for the Tata support agent.

These tests exercise the full four-node LangGraph pipeline
(load_history → retrieve → generate → save_turn) using realistic customer
messages — greeting, address inquiry, opening-hours inquiry, product inquiry,
warranty inquiry, complaint, and a two-turn multi-message conversation.

All external services (OpenAI, Qdrant, Chatwoot) are mocked so the suite
runs offline with no real API keys.  The mocks simulate what each service
would actually return, making the tests serve as living documentation of
expected agent behaviour.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from app.agent import run_agent


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_openai_client(reply: str) -> MagicMock:
    """Return a mock OpenAI client whose chat completion returns *reply*."""
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = reply
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return client


def _make_qdrant_store(snippets: list[str]) -> MagicMock:
    """Return a mock QdrantStore whose search returns the given text snippets."""
    store = MagicMock()
    store.search.return_value = [{"text": s} for s in snippets]
    return store


def _make_memory(history: list[dict] | None = None) -> MagicMock:
    """Return a mock ConversationMemory with optional pre-loaded history."""
    memory = MagicMock()
    memory.get_history.return_value = history or []
    memory.add_turn.return_value = None
    return memory


def _run(
    user_message: str,
    *,
    snippets: list[str],
    reply: str,
    conversation_id: int = 1,
    history: list[dict] | None = None,
) -> tuple[str, MagicMock, MagicMock, MagicMock]:
    """Run the agent with mocked dependencies.

    Returns:
        (agent_reply, openai_client_mock, qdrant_store_mock, memory_mock)
    """
    openai_client = _make_openai_client(reply)
    qdrant_store = _make_qdrant_store(snippets)
    memory = _make_memory(history)

    agent_reply = run_agent(
        user_message=user_message,
        qdrant_store=qdrant_store,
        conversation_memory=memory,
        conversation_id=conversation_id,
        openai_client=openai_client,
    )
    return agent_reply, openai_client, qdrant_store, memory


# ---------------------------------------------------------------------------
# Scenario 1 — Customer greeting
# ---------------------------------------------------------------------------


def test_simulation_greeting():
    """Agent greets the customer and Qdrant is queried for relevant context."""
    user_message = "Hi there"
    expected_reply = (
        "Hello! Welcome to Tata Motors support. "
        "I'm Tata, your virtual assistant. How can I help you today?"
    )
    snippets = [
        "Tata Motors customer support is available 24/7 via phone and chat.",
        "You can reach us at support@tatamotors.com or call 1800-209-7979.",
    ]

    reply, openai_client, qdrant_store, memory = _run(
        user_message, snippets=snippets, reply=expected_reply
    )

    # The agent must have queried Qdrant with the user's exact message
    qdrant_store.search.assert_called_once_with(user_message)

    # The knowledge snippets must appear in the OpenAI prompt
    call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in call_messages if m["role"] == "user")
    assert snippets[0] in user_content
    assert snippets[1] in user_content

    # The reply is returned verbatim from the mock
    assert reply == expected_reply

    # The turn must be saved to conversation memory
    memory.add_turn.assert_called_once_with(
        conversation_id=1,
        user_message=user_message,
        assistant_reply=expected_reply,
    )


# ---------------------------------------------------------------------------
# Scenario 2 — Company address inquiry
# ---------------------------------------------------------------------------


def test_simulation_company_address():
    """Agent responds to a company address question using retrieved knowledge."""
    user_message = "What is the company address?"
    expected_reply = (
        "Our registered office is at Bombay House, 24 Homi Mody Street, "
        "Mumbai, Maharashtra 400001, India."
    )
    snippets = [
        "Tata Motors Limited registered office: Bombay House, 24 Homi Mody Street, "
        "Mumbai, Maharashtra 400001, India.",
        "For visit-related enquiries please call the reception at +91 22 6665 8282.",
    ]

    reply, openai_client, qdrant_store, memory = _run(
        user_message, snippets=snippets, reply=expected_reply
    )

    qdrant_store.search.assert_called_once_with(user_message)

    call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in call_messages if m["role"] == "user")
    assert "Bombay House" in user_content

    assert reply == expected_reply
    memory.add_turn.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario 3 — Opening-hours inquiry
# ---------------------------------------------------------------------------


def test_simulation_opening_hours():
    """Agent returns office / showroom opening hours from retrieved context."""
    user_message = "What are the opening hours of the showroom?"
    expected_reply = (
        "Our showrooms are open Monday to Saturday, 9 AM – 7 PM, "
        "and Sunday 10 AM – 5 PM."
    )
    snippets = [
        "Tata Motors showrooms are open Monday–Saturday 09:00–19:00 IST.",
        "Sunday hours: 10:00–17:00 IST. Public holidays may vary.",
    ]

    reply, openai_client, qdrant_store, memory = _run(
        user_message, snippets=snippets, reply=expected_reply
    )

    qdrant_store.search.assert_called_once_with(user_message)

    call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in call_messages if m["role"] == "user")
    assert "09:00" in user_content

    assert reply == expected_reply
    memory.add_turn.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario 4 — Product / vehicle lineup inquiry
# ---------------------------------------------------------------------------


def test_simulation_vehicle_lineup():
    """Agent lists available vehicles based on retrieved knowledge."""
    user_message = "What cars does Tata offer?"
    expected_reply = (
        "Tata Motors offers a wide range including the Nexon, Harrier, Safari, "
        "Punch, Tiago, and Altroz. We also have the Nexon EV and Tiago EV in "
        "our electric lineup."
    )
    snippets = [
        "Tata Motors passenger vehicles: Nexon, Harrier, Safari, Punch, Tiago, Altroz.",
        "Electric vehicles: Nexon EV, Tiago EV, Punch EV — available at select dealerships.",
    ]

    reply, openai_client, qdrant_store, memory = _run(
        user_message, snippets=snippets, reply=expected_reply
    )

    qdrant_store.search.assert_called_once_with(user_message)

    call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in call_messages if m["role"] == "user")
    assert "Nexon" in user_content
    assert "EV" in user_content

    assert reply == expected_reply
    memory.add_turn.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario 5 — Warranty inquiry
# ---------------------------------------------------------------------------


def test_simulation_warranty_inquiry():
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

    reply, openai_client, qdrant_store, memory = _run(
        user_message, snippets=snippets, reply=expected_reply
    )

    qdrant_store.search.assert_called_once_with(user_message)

    call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in call_messages if m["role"] == "user")
    assert "100,000 km" in user_content

    assert reply == expected_reply
    memory.add_turn.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario 6 — Unknown topic (knowledge not in context)
# ---------------------------------------------------------------------------


def test_simulation_unknown_topic_politely_declines():
    """When Qdrant returns no relevant context the agent should say it's unsure."""
    user_message = "Can you book a table at a restaurant for me?"
    expected_reply = (
        "I'm sorry, I don't have information about that. "
        "For assistance, please contact a human agent."
    )
    # Qdrant returns unrelated snippets — agent should still respond gracefully
    snippets: list[str] = []

    reply, openai_client, qdrant_store, memory = _run(
        user_message, snippets=snippets, reply=expected_reply
    )

    qdrant_store.search.assert_called_once_with(user_message)

    # Even with no context, the OpenAI call must still be made (with empty context)
    call_messages = openai_client.chat.completions.create.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in call_messages if m["role"] == "user")
    assert "Can you book a table" in user_content

    assert reply == expected_reply
    memory.add_turn.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario 7 — Multi-turn conversation (two sequential messages)
# ---------------------------------------------------------------------------


def test_simulation_multi_turn_conversation():
    """Simulate a two-message conversation; second message sees first turn in history."""
    conversation_id = 101

    # ── Turn 1: greeting ──────────────────────────────────────────────────
    reply_1, _, qdrant_1, memory_1 = _run(
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

    # ── Turn 2: follow-up with history loaded ─────────────────────────────
    history_after_turn_1 = [
        {"role": "user", "content": "Hi there"},
        {"role": "assistant", "content": "Hello! How can I help you today?"},
    ]
    reply_2, openai_2, qdrant_2, memory_2 = _run(
        "What are your opening hours?",
        snippets=["Showrooms open Mon–Sat 09:00–19:00."],
        reply="Our showrooms are open Monday–Saturday, 9 AM to 7 PM.",
        conversation_id=conversation_id,
        history=history_after_turn_1,
    )

    assert reply_2 == "Our showrooms are open Monday–Saturday, 9 AM to 7 PM."

    # History from turn 1 must appear in the OpenAI messages for turn 2
    call_messages = openai_2.chat.completions.create.call_args.kwargs["messages"]
    roles = [m["role"] for m in call_messages]
    assert roles[0] == "system"
    # history user + history assistant should be present
    user_contents = [m["content"] for m in call_messages if m["role"] == "user"]
    assert any("Hi there" in c for c in user_contents)
    assistant_contents = [m["content"] for m in call_messages if m["role"] == "assistant"]
    assert any("How can I help" in c for c in assistant_contents)

    memory_2.add_turn.assert_called_once_with(
        conversation_id=conversation_id,
        user_message="What are your opening hours?",
        assistant_reply="Our showrooms are open Monday–Saturday, 9 AM to 7 PM.",
    )
