"""CI tests that simulate Chatwoot webhook messages sent to the Tata agent.

All external dependencies (OpenAI, Qdrant, Chatwoot) are mocked so the tests
run offline with no real API keys.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chatwoot_payload(
    content: str = "Hello, I need help!",
    conversation_id: int = 42,
    message_type: int = 0,
    event: str = "message_created",
) -> dict:
    """Return a minimal Chatwoot webhook payload for a new incoming message."""
    return {
        "event": event,
        "message": {
            "id": 1,
            "content": content,
            "message_type": message_type,
            "conversation_id": conversation_id,
        },
        "conversation": {
            "id": conversation_id,
        },
    }


@pytest.fixture()
def mock_qdrant_store():
    """Return a mock QdrantStore that always returns two knowledge snippets."""
    store = MagicMock()
    store.search.return_value = [
        {"text": "Tata Motors offers a 3-year warranty on all vehicles."},
        {"text": "Customer support is available 24/7 via phone and chat."},
    ]
    store.ensure_collection.return_value = None
    return store


@pytest.fixture()
def mock_conversation_memory():
    """Return a mock ConversationMemory."""
    memory = MagicMock()
    memory.get_history.return_value = []
    memory.add_turn.return_value = None
    memory.ensure_collection.return_value = None
    return memory


@pytest.fixture()
def mock_openai_client():
    """Return a mock OpenAI client that returns a canned chat completion."""
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = "Thank you for reaching out! How can I assist you today?"
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return client


@pytest.fixture()
def mock_chatwoot_client():
    """Return a mock ChatwootClient."""
    client = MagicMock()
    client.send_message.return_value = {"id": 99, "content": "mocked reply"}
    return client


@pytest.fixture()
def test_client(mock_qdrant_store, mock_conversation_memory, mock_openai_client, mock_chatwoot_client):
    """Build a FastAPI TestClient with all external services mocked."""
    with (
        patch("app.main._qdrant_store", mock_qdrant_store),
        patch("app.main._conversation_memory", mock_conversation_memory),
        patch("app.main._chatwoot_client", mock_chatwoot_client),
        patch("app.agent.OpenAI", return_value=mock_openai_client),
    ):
        from app.main import app

        # Patch run_agent so the whole flow is exercised but uses our mocks
        with patch(
            "app.main.run_agent",
            side_effect=lambda user_message, qdrant_store, conversation_memory, conversation_id=0, **kw: (
                mock_openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": user_message}],
                ).choices[0].message.content
            ),
        ):
            yield TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def test_health_check(test_client):
    """GET /health should return 200 with status ok."""
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Webhook — ignored events
# ---------------------------------------------------------------------------


def test_webhook_ignores_non_message_created_event(test_client):
    """Events other than message_created should be silently ignored."""
    payload = _make_chatwoot_payload(event="conversation_updated")
    response = test_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webhook_ignores_outgoing_messages(test_client):
    """Outgoing messages (sent by the agent) must not trigger a reply loop."""
    payload = _make_chatwoot_payload(message_type=1)  # 1 = outgoing
    response = test_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webhook_ignores_activity_messages(test_client):
    """Activity messages (system events) should be ignored."""
    payload = _make_chatwoot_payload(message_type=2)
    response = test_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webhook_ignores_empty_content(test_client):
    """Messages with no text content should be ignored."""
    payload = _make_chatwoot_payload(content="")
    response = test_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


# ---------------------------------------------------------------------------
# Webhook — happy path
# ---------------------------------------------------------------------------


def test_webhook_processes_incoming_message(
    test_client, mock_chatwoot_client
):
    """A valid incoming customer message should trigger a Chatwoot reply."""
    payload = _make_chatwoot_payload(
        content="What is the warranty period for Tata vehicles?",
        conversation_id=42,
    )
    response = test_client.post("/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "replied"
    assert data["conversation_id"] == 42
    mock_chatwoot_client.send_message.assert_called_once()
    call_kwargs = mock_chatwoot_client.send_message.call_args
    assert call_kwargs.kwargs["conversation_id"] == 42
    assert isinstance(call_kwargs.kwargs["message"], str)
    assert len(call_kwargs.kwargs["message"]) > 0


def test_webhook_processes_different_conversations(
    test_client, mock_chatwoot_client
):
    """Each conversation ID is passed correctly to the Chatwoot client."""
    for conv_id in (1, 100, 9999):
        mock_chatwoot_client.reset_mock()
        payload = _make_chatwoot_payload(content="Help!", conversation_id=conv_id)
        response = test_client.post("/webhook", json=payload)
        assert response.status_code == 200
        assert response.json()["conversation_id"] == conv_id
        mock_chatwoot_client.send_message.assert_called_once()
        actual_conv_id = mock_chatwoot_client.send_message.call_args.kwargs["conversation_id"]
        assert actual_conv_id == conv_id


# ---------------------------------------------------------------------------
# Webhook — token validation
# ---------------------------------------------------------------------------


def test_webhook_rejects_invalid_token(test_client):
    """When WEBHOOK_TOKEN is set, invalid tokens must be rejected with 401."""
    with patch("app.main.settings") as mock_settings:
        mock_settings.webhook_token = "secret-token"
        payload = _make_chatwoot_payload()
        response = test_client.post(
            "/webhook",
            json=payload,
            headers={"X-Chatwoot-Signature": "wrong-token"},
        )
    assert response.status_code == 401


def test_webhook_accepts_valid_token(test_client, mock_chatwoot_client):
    """Requests with the correct token should be processed normally."""
    with patch("app.main.settings") as mock_settings:
        mock_settings.webhook_token = "secret-token"
        payload = _make_chatwoot_payload()
        response = test_client.post(
            "/webhook",
            json=payload,
            headers={"X-Chatwoot-Signature": "secret-token"},
        )
    # The status may be 200 "replied" or 200 "ignored" depending on mocked settings;
    # the important thing is it's not 401.
    assert response.status_code != 401


# ---------------------------------------------------------------------------
# Agent unit tests
# ---------------------------------------------------------------------------


def test_agent_run_agent_calls_qdrant_and_openai(
    mock_qdrant_store, mock_conversation_memory, mock_openai_client
):
    """run_agent should query Qdrant then call OpenAI and return a string."""
    from app.agent import run_agent

    with patch("app.agent.OpenAI", return_value=mock_openai_client):
        reply = run_agent(
            user_message="Tell me about warranty",
            qdrant_store=mock_qdrant_store,
            conversation_memory=mock_conversation_memory,
            conversation_id=42,
            openai_client=mock_openai_client,
        )

    mock_qdrant_store.search.assert_called_once_with("Tell me about warranty")
    assert isinstance(reply, str)
    assert len(reply) > 0


def test_agent_uses_retrieved_context(
    mock_qdrant_store, mock_conversation_memory, mock_openai_client
):
    """The context from Qdrant must be forwarded to the OpenAI call."""
    from app.agent import run_agent

    mock_qdrant_store.search.return_value = [{"text": "Tata Nexon has a 5-star safety rating."}]

    with patch("app.agent.OpenAI", return_value=mock_openai_client):
        run_agent(
            user_message="Is Tata Nexon safe?",
            qdrant_store=mock_qdrant_store,
            conversation_memory=mock_conversation_memory,
            conversation_id=42,
            openai_client=mock_openai_client,
        )

    call_args = mock_openai_client.chat.completions.create.call_args
    messages = call_args.kwargs.get("messages") or call_args.args[0]
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "Tata Nexon has a 5-star safety rating." in user_content


def test_agent_includes_history_in_prompt(
    mock_qdrant_store, mock_conversation_memory, mock_openai_client
):
    """Previous conversation turns must appear in the OpenAI messages array."""
    from app.agent import run_agent

    mock_conversation_memory.get_history.return_value = [
        {"role": "user", "content": "What is your name?"},
        {"role": "assistant", "content": "I am Tata, your support agent."},
    ]

    with patch("app.agent.OpenAI", return_value=mock_openai_client):
        run_agent(
            user_message="Tell me more",
            qdrant_store=mock_qdrant_store,
            conversation_memory=mock_conversation_memory,
            conversation_id=7,
            openai_client=mock_openai_client,
        )

    call_args = mock_openai_client.chat.completions.create.call_args
    messages = call_args.kwargs.get("messages") or call_args.args[0]
    roles = [m["role"] for m in messages]
    assert "system" in roles
    assert roles.count("user") >= 2  # history user turn + current user message
    assert "assistant" in roles


def test_agent_saves_turn_to_memory(
    mock_qdrant_store, mock_conversation_memory, mock_openai_client
):
    """After generating a reply, the agent must persist the turn to memory."""
    from app.agent import run_agent

    with patch("app.agent.OpenAI", return_value=mock_openai_client):
        run_agent(
            user_message="Hello!",
            qdrant_store=mock_qdrant_store,
            conversation_memory=mock_conversation_memory,
            conversation_id=55,
            openai_client=mock_openai_client,
        )

    mock_conversation_memory.add_turn.assert_called_once()
    call_kwargs = mock_conversation_memory.add_turn.call_args.kwargs
    assert call_kwargs["conversation_id"] == 55
    assert call_kwargs["user_message"] == "Hello!"
    assert isinstance(call_kwargs["assistant_reply"], str)


# ---------------------------------------------------------------------------
# Conversation memory unit tests
# ---------------------------------------------------------------------------


def test_conversation_memory_get_history_returns_messages():
    """ConversationMemory.get_history should return messages in order."""
    mock_qdrant = MagicMock()
    mock_openai = MagicMock()

    # Simulate two scroll results ordered oldest→newest (reversed by impl)
    p1 = MagicMock()
    p1.payload = {"role": "user", "content": "Hi", "timestamp_ms": 1000}
    p2 = MagicMock()
    p2.payload = {"role": "assistant", "content": "Hello!", "timestamp_ms": 1001}
    mock_qdrant.scroll.return_value = ([p2, p1], None)  # desc order from Qdrant

    with patch("app.conversation_memory.QdrantClient", return_value=mock_qdrant):
        from app.conversation_memory import ConversationMemory

        memory = ConversationMemory(qdrant_client=mock_qdrant)
        history = memory.get_history(conversation_id=42)

    # After reversal, oldest message should be first
    assert history[0]["content"] == "Hi"
    assert history[1]["content"] == "Hello!"


def test_conversation_memory_add_turn_upserts_two_points():
    """add_turn should upsert exactly two points (user + assistant)."""
    mock_qdrant = MagicMock()

    with patch("app.conversation_memory.QdrantClient", return_value=mock_qdrant):
        from app.conversation_memory import ConversationMemory

        memory = ConversationMemory(qdrant_client=mock_qdrant)
        memory.add_turn(
            conversation_id=10,
            user_message="What is the price?",
            assistant_reply="The price is X.",
        )

    mock_qdrant.upsert.assert_called_once()
    points = mock_qdrant.upsert.call_args.kwargs["points"]
    assert len(points) == 2
    roles = {p.payload["role"] for p in points}
    assert roles == {"user", "assistant"}


def test_conversation_memory_history_filters_by_conversation():
    """get_history must filter by conversation_id."""
    mock_qdrant = MagicMock()
    mock_qdrant.scroll.return_value = ([], None)

    with patch("app.conversation_memory.QdrantClient", return_value=mock_qdrant):
        from app.conversation_memory import ConversationMemory

        memory = ConversationMemory(qdrant_client=mock_qdrant)
        memory.get_history(conversation_id=99)

    scroll_call = mock_qdrant.scroll.call_args
    scroll_filter = scroll_call.kwargs.get("scroll_filter") or scroll_call.args[0]
    condition = scroll_filter.must[0]
    assert condition.key == "conversation_id"
    assert condition.match.value == 99


# ---------------------------------------------------------------------------
# Qdrant store unit tests
# ---------------------------------------------------------------------------


def test_qdrant_store_search_returns_payloads():
    """QdrantStore.search should return payload dicts from Qdrant hits."""
    mock_qdrant = MagicMock()
    mock_openai = MagicMock()

    # Fake embedding response
    embedding_resp = MagicMock()
    embedding_resp.data = [MagicMock(embedding=[0.1] * 1536)]
    mock_openai.embeddings.create.return_value = embedding_resp

    # Fake Qdrant search results
    hit1 = MagicMock()
    hit1.payload = {"text": "Knowledge snippet A"}
    hit2 = MagicMock()
    hit2.payload = {"text": "Knowledge snippet B"}
    mock_qdrant.search.return_value = [hit1, hit2]

    with patch("app.qdrant_store.QdrantClient", return_value=mock_qdrant):
        from app.qdrant_store import QdrantStore

        store = QdrantStore(openai_client=mock_openai)
        results = store.search("test query")

    assert results == [{"text": "Knowledge snippet A"}, {"text": "Knowledge snippet B"}]


# ---------------------------------------------------------------------------
# Chatwoot client unit tests
# ---------------------------------------------------------------------------


def test_chatwoot_client_sends_post_request():
    """ChatwootClient.send_message should POST to the correct Chatwoot endpoint."""
    import httpx
    import respx

    from app.chatwoot import ChatwootClient

    account_id = 5
    conversation_id = 77
    client = ChatwootClient(
        base_url="http://chatwoot.test",
        api_token="token-abc",
        account_id=account_id,
    )

    expected_url = (
        f"http://chatwoot.test/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_id}/messages"
    )

    with respx.mock:
        mock_route = respx.post(expected_url).mock(
            return_value=httpx.Response(200, json={"id": 1, "content": "Hello!"})
        )
        result = client.send_message(conversation_id=conversation_id, message="Hello!")

    assert mock_route.called
    assert result["id"] == 1


def test_chatwoot_client_raises_on_error():
    """ChatwootClient.send_message should raise on non-2xx responses."""
    import httpx
    import respx

    from app.chatwoot import ChatwootClient

    client = ChatwootClient(
        base_url="http://chatwoot.test",
        api_token="bad-token",
        account_id=1,
    )

    with respx.mock:
        respx.post("http://chatwoot.test/api/v1/accounts/1/conversations/1/messages").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            client.send_message(conversation_id=1, message="Hello!")
