"""CI tests that simulate Chatwoot webhook messages sent to the Tata agent.

All external services are real (OpenAI, PostgreSQL/pgvector, ConversationMemory).
Only the outbound Chatwoot HTTP client is replaced by a MagicMock so tests run
without a live Chatwoot instance.

The :class:`~app.message_buffer.MessageBuffer` is initialised with
``delay_seconds=0`` for every test fixture, which makes it flush synchronously
in the calling thread.  This means a ``client.post("/webhook", ...)`` call
blocks until the full agent pipeline has run and Chatwoot has been notified —
no ``time.sleep`` required.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chatwoot_payload(
    content: str = "Hello, I need help!",
    conversation_id: int = 42,
    message_type: str = "incoming",
    event: str = "message_created",
) -> dict:
    """Return a minimal Chatwoot agent bot webhook payload for a new incoming message.

    The real Chatwoot agent bot webhook sends a **flat** payload where
    ``message_type`` is a string (``"incoming"`` / ``"outgoing"`` /
    ``"template"``) and ``content`` lives at the top level — not nested inside
    a ``"message"`` object as in the regular Chatwoot webhook.
    """
    return {
        "event": event,
        "id": 1,
        "content": content,
        "created_at": 1234567890,
        "message_type": message_type,
        "conversation": {
            "id": conversation_id,
            "inbox_id": 1,
            "status": "pending",
            "contact": {
                "id": 10,
                "name": "John Doe",
                "email": "john@example.com",
            },
        },
        "account": {"id": 1, "name": "Test Account"},
        "sender": {"id": 10, "name": "John Doe"},
    }


@pytest.fixture()
def mock_chatwoot_client():
    """Return a mock ChatwootClient (outbound Chatwoot HTTP)."""
    client = MagicMock()
    client.send_message.return_value = {"id": 99, "content": "mocked reply"}
    return client


@pytest.fixture()
def test_client(
    require_pg,
    pg_dsn,
    pg_test_vector_table,
    pg_test_memory_table,
    mock_chatwoot_client,
):
    """Build a FastAPI TestClient with real services.

    Uses:
    - Real PostgreSQL/pgvector for the knowledge store (no OpenAI call at fixture setup).
    - Real PostgreSQL for conversation memory.
    - Synchronous :class:`~app.message_buffer.MessageBuffer` (``delay_seconds=0``)
      so each POST blocks until the agent has replied to Chatwoot.
    - MagicMock for the outbound Chatwoot HTTP client.

    No OpenAI API call is made during fixture setup — the OpenAI client is created
    (object only) but never called until an agent-routed message arrives.

    Fails if PostgreSQL is not reachable.
    """
    from app.config import settings
    from app.conversation_memory import ConversationMemory
    from app.main import _process_buffered_messages, app
    from app.message_buffer import MessageBuffer
    from app.pg_vector_store import PgVectorStore

    openai_client = settings.make_openai_client()

    store = PgVectorStore(
        dsn=pg_dsn, table=pg_test_vector_table, openai_client=openai_client
    )
    memory = ConversationMemory(dsn=pg_dsn, table=pg_test_memory_table)
    buffer = MessageBuffer(delay_seconds=0, on_flush=_process_buffered_messages)

    with (
        patch("app.main._vector_store", store),
        patch("app.main._conversation_memory", memory),
        patch("app.main._chatwoot_client", mock_chatwoot_client),
        patch("app.main._message_buffer", buffer),
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
# Webhook -- ignored events
# ---------------------------------------------------------------------------


def test_webhook_ignores_non_message_created_event(test_client):
    """Events other than message_created should be silently ignored."""
    payload = _make_chatwoot_payload(event="conversation_updated")
    response = test_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webhook_ignores_outgoing_messages(test_client):
    """Outgoing messages (sent by the agent) must not trigger a reply loop."""
    payload = _make_chatwoot_payload(message_type="outgoing")
    response = test_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webhook_ignores_activity_messages(test_client):
    """Non-incoming message types (e.g. template) should be ignored."""
    payload = _make_chatwoot_payload(message_type="template")
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
# Webhook -- happy path (real OpenAI + real pgvector)
# ---------------------------------------------------------------------------


@pytest.mark.openai
def test_webhook_processes_incoming_message(test_client, mock_chatwoot_client):
    """A valid incoming customer message triggers a real agent reply via Chatwoot."""
    payload = _make_chatwoot_payload(
        content="Hi, what can I do here?",
        conversation_id=4200,
    )
    response = test_client.post("/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["conversation_id"] == 4200
    # With delay_seconds=0 the buffer flushes synchronously; Chatwoot is already called.
    mock_chatwoot_client.send_message.assert_called()
    call_kwargs = mock_chatwoot_client.send_message.call_args
    assert call_kwargs.kwargs["conversation_id"] == 4200
    assert isinstance(call_kwargs.kwargs["message"], str)
    assert len(call_kwargs.kwargs["message"]) > 0


@pytest.mark.openai
def test_webhook_processes_different_conversations(test_client, mock_chatwoot_client):
    """Each conversation ID is passed correctly to the Chatwoot client."""
    for conv_id in (4300, 4301, 4302):
        mock_chatwoot_client.reset_mock()
        payload = _make_chatwoot_payload(content="Hi!", conversation_id=conv_id)
        response = test_client.post("/webhook", json=payload)
        assert response.status_code == 200
        assert response.json()["conversation_id"] == conv_id
        mock_chatwoot_client.send_message.assert_called()
        actual_conv_id = mock_chatwoot_client.send_message.call_args.kwargs["conversation_id"]
        assert actual_conv_id == conv_id


# ---------------------------------------------------------------------------
# Webhook -- token validation
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
        payload = _make_chatwoot_payload(event="conversation_updated")  # ignored event
        response = test_client.post(
            "/webhook",
            json=payload,
            headers={"X-Chatwoot-Signature": "secret-token"},
        )
    # Event is ignored (not message_created), but token was valid → not 401.
    assert response.status_code != 401
    assert response.json()["status"] == "ignored"


# ---------------------------------------------------------------------------
# Conversation memory integration tests (real PostgreSQL)
# ---------------------------------------------------------------------------


def test_conversation_memory_add_and_get_history(
    require_pg, pg_dsn, pg_test_memory_table
):
    """ConversationMemory persists a turn and retrieves it in chronological order."""
    from app.conversation_memory import ConversationMemory

    memory = ConversationMemory(dsn=pg_dsn, table=pg_test_memory_table)
    conv_id = 99901
    memory.add_turn(
        conversation_id=conv_id,
        user_message="What is the price?",
        assistant_reply="The price is X.",
    )

    history = memory.get_history(conversation_id=conv_id)
    assert len(history) == 2
    assert history[0] == {"role": "user",      "content": "What is the price?"}
    assert history[1] == {"role": "assistant", "content": "The price is X."}


def test_conversation_memory_add_turn_inserts_two_rows(
    require_pg, pg_dsn, pg_test_memory_table
):
    """add_turn must insert exactly two rows per turn — one user, one assistant."""
    import psycopg2 as _psycopg2

    from app.conversation_memory import ConversationMemory

    conv_id = 99902
    memory = ConversationMemory(dsn=pg_dsn, table=pg_test_memory_table)
    memory.add_turn(
        conversation_id=conv_id,
        user_message="Question",
        assistant_reply="Answer",
    )

    conn = _psycopg2.connect(pg_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT role FROM {pg_test_memory_table}"
                " WHERE conversation_id = %s ORDER BY role_order",
                (conv_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    assert len(rows) == 2
    assert {row[0] for row in rows} == {"user", "assistant"}


def test_conversation_memory_history_filters_by_conversation(
    require_pg, pg_dsn, pg_test_memory_table
):
    """get_history must only return messages for the requested conversation_id."""
    from app.conversation_memory import ConversationMemory

    conv_a, conv_b = 99903, 99904
    memory = ConversationMemory(dsn=pg_dsn, table=pg_test_memory_table)
    memory.add_turn(conversation_id=conv_a, user_message="Hello A", assistant_reply="Hi A!")
    memory.add_turn(conversation_id=conv_b, user_message="Hello B", assistant_reply="Hi B!")

    history_a = memory.get_history(conversation_id=conv_a)
    assert len(history_a) == 2
    assert all("A" in m["content"] for m in history_a)
    assert all("B" not in m["content"] for m in history_a)


# ---------------------------------------------------------------------------
# PgVectorStore integration tests (real PostgreSQL/pgvector + real embeddings)
# ---------------------------------------------------------------------------


@pytest.mark.openai
def test_pg_vector_store_upsert_and_search(
    require_pg, pg_dsn, pg_test_vector_table
):
    """PgVectorStore upserts documents and retrieves them via real cosine similarity.

    Uses the real OpenAI embedding API so this test exercises both the pgvector
    SQL round-trip and the embedding pipeline end-to-end.
    """
    from app.config import settings
    from app.pg_vector_store import PgVectorStore

    openai_client = settings.make_openai_client()
    store = PgVectorStore(dsn=pg_dsn, table=pg_test_vector_table, openai_client=openai_client)
    store.upsert("unit-test-doc-a", "Knowledge snippet A about gym activities", {"source": "unit-test"})
    store.upsert("unit-test-doc-b", "Knowledge snippet B about membership prices", {"source": "unit-test"})

    results = store.search("gym activities", top_k=10)
    texts = [r["text"] for r in results]
    assert "Knowledge snippet A about gym activities" in texts
    assert "Knowledge snippet B about membership prices" in texts


# ---------------------------------------------------------------------------
# MessageBuffer unit tests (pure timer logic, no OpenAI required)
# ---------------------------------------------------------------------------


def test_message_buffer_accumulates_messages_within_window():
    """Messages arriving within the debounce window are joined into a single flush."""
    from app.message_buffer import MessageBuffer

    received: list[tuple[int, str]] = []

    def on_flush(conv_id: int, text: str) -> None:
        received.append((conv_id, text))

    buf = MessageBuffer(delay_seconds=0.1, on_flush=on_flush)
    buf.add_message(1, "Hello")
    buf.add_message(1, "What are the prices?")  # resets the timer

    time.sleep(0.5)  # wait for the single flush

    assert len(received) == 1, f"Expected 1 flush but got {len(received)}: {received}"
    conv_id, combined = received[0]
    assert conv_id == 1
    assert "Hello" in combined
    assert "What are the prices?" in combined


def test_message_buffer_separates_messages_after_window():
    """Messages arriving after the debounce window fire as separate flushes."""
    from app.message_buffer import MessageBuffer

    received: list[tuple[int, str]] = []

    def on_flush(conv_id: int, text: str) -> None:
        received.append((conv_id, text))

    buf = MessageBuffer(delay_seconds=0.1, on_flush=on_flush)
    buf.add_message(2, "First message")
    time.sleep(0.4)  # let the first flush fire

    buf.add_message(2, "Second message")  # starts a new timer
    time.sleep(0.4)  # let the second flush fire

    assert len(received) == 2, f"Expected 2 flushes but got {len(received)}: {received}"
    assert "First message" in received[0][1]
    assert "Second message" in received[1][1]


def test_message_buffer_zero_delay_flushes_synchronously():
    """When delay_seconds=0 the flush happens synchronously in the calling thread."""
    from app.message_buffer import MessageBuffer

    received: list[str] = []

    def on_flush(conv_id: int, text: str) -> None:
        received.append(text)

    buf = MessageBuffer(delay_seconds=0, on_flush=on_flush)
    buf.add_message(3, "Immediate message")

    # No sleep needed — flush is synchronous
    assert len(received) == 1
    assert "Immediate message" in received[0]


# ---------------------------------------------------------------------------
# Chatwoot client unit tests
# ---------------------------------------------------------------------------


def test_chatwoot_client_sends_post_request():
    """ChatwootClient.send_message should POST to the correct Chatwoot endpoint."""
    import httpx
    import respx

    from app.services.chatwoot_client import ChatwootClient

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
    sent_request = mock_route.calls.last.request
    assert sent_request.headers["api_access_token"] == "token-abc"


def test_chatwoot_client_raises_on_error():
    """ChatwootClient.send_message should raise on non-2xx responses."""
    import httpx
    import respx

    from app.services.chatwoot_client import ChatwootClient

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


def test_chatwoot_client_handover_posts_to_toggle_status():
    """ChatwootClient.handover_to_human should POST to the /toggle_status endpoint."""
    import httpx
    import respx

    from app.services.chatwoot_client import ChatwootClient

    account_id = 5
    conversation_id = 77
    client = ChatwootClient(
        base_url="http://chatwoot.test",
        api_token="token-abc",
        account_id=account_id,
    )

    expected_url = (
        f"http://chatwoot.test/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_id}/toggle_status"
    )

    with respx.mock:
        mock_route = respx.post(expected_url).mock(
            return_value=httpx.Response(200, json={"id": conversation_id, "status": "open"})
        )
        result = client.handover_to_human(conversation_id=conversation_id)

    assert mock_route.called
    assert result["status"] == "open"
    sent_request = mock_route.calls.last.request
    assert sent_request.headers["api_access_token"] == "token-abc"
    body = json.loads(sent_request.content)
    assert body == {"status": "open"}


# ---------------------------------------------------------------------------
# ChatwootClient -- Help Center read methods
# ---------------------------------------------------------------------------


def test_chatwoot_client_list_portals_returns_portal_list():
    """ChatwootClient.list_portals() should GET /portals and unwrap the payload list."""
    import httpx
    import respx

    from app.services.chatwoot_client import ChatwootClient

    account_id = 5
    client = ChatwootClient(
        base_url="http://chatwoot.test",
        api_token="token-abc",
        account_id=account_id,
    )
    expected_url = f"http://chatwoot.test/api/v1/accounts/{account_id}/portals"
    portals_data = [{"id": 1, "slug": "main-portal", "name": "Main Portal"}]

    with respx.mock:
        mock_route = respx.get(expected_url).mock(
            return_value=httpx.Response(200, json={"payload": portals_data})
        )
        result = client.list_portals()

    assert mock_route.called
    assert result == portals_data
    sent_request = mock_route.calls.last.request
    assert sent_request.headers["api_access_token"] == "token-abc"


def test_chatwoot_client_list_portals_returns_empty_on_error():
    """ChatwootClient.list_portals() should return [] on HTTP errors."""
    import httpx
    import respx

    from app.services.chatwoot_client import ChatwootClient

    client = ChatwootClient(
        base_url="http://chatwoot.test",
        api_token="bad-token",
        account_id=1,
    )

    with respx.mock:
        respx.get("http://chatwoot.test/api/v1/accounts/1/portals").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        result = client.list_portals()

    assert result == []


def test_chatwoot_client_list_portal_articles_returns_payload():
    """ChatwootClient.list_portal_articles() should GET articles and return the payload dict."""
    import httpx
    import respx

    from app.services.chatwoot_client import ChatwootClient

    account_id = 5
    portal_slug = "main-portal"
    client = ChatwootClient(
        base_url="http://chatwoot.test",
        api_token="token-abc",
        account_id=account_id,
    )
    expected_url = (
        f"http://chatwoot.test/api/v1/accounts/{account_id}/portals/{portal_slug}/articles"
    )
    articles_payload = {
        "articles": [
            {"id": 101, "title": "Getting Started", "content": "Welcome!"},
            {"id": 102, "title": "Pricing", "content": "Plans start at R$150."},
        ],
        "meta": {"total": 2},
    }

    with respx.mock:
        mock_route = respx.get(expected_url).mock(
            return_value=httpx.Response(200, json={"payload": articles_payload})
        )
        result = client.list_portal_articles(portal_slug, status="published", page=1)

    assert mock_route.called
    assert result == articles_payload
    sent_request = mock_route.calls.last.request
    assert sent_request.headers["api_access_token"] == "token-abc"


def test_chatwoot_client_list_portal_articles_returns_empty_on_error():
    """ChatwootClient.list_portal_articles() should return {} on HTTP errors."""
    import httpx
    import respx

    from app.services.chatwoot_client import ChatwootClient

    client = ChatwootClient(
        base_url="http://chatwoot.test",
        api_token="bad-token",
        account_id=1,
    )

    with respx.mock:
        respx.get("http://chatwoot.test/api/v1/accounts/1/portals/no-portal/articles").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        result = client.list_portal_articles("no-portal")

    assert result == {}


# ---------------------------------------------------------------------------
# HelpCenterSync unit tests (mock ChatwootClient + mock vector store)
# ---------------------------------------------------------------------------


def test_hc_sync_upserts_articles_from_mocked_chatwoot_api():
    """HelpCenterSync.run() should fetch portals/articles via ChatwootClient and index them."""
    from unittest.mock import MagicMock, call

    from app.hc_sync import HelpCenterSync

    mock_store = MagicMock()
    mock_client = MagicMock()
    mock_client.api_token = "test-token"
    mock_client.list_portals.return_value = [
        {"id": 1, "slug": "test-portal", "name": "Test Portal"}
    ]
    mock_client.list_portal_articles.return_value = {
        "articles": [
            {"id": 101, "title": "Getting Started", "content": "Welcome to our gym."},
            {"id": 102, "title": "Pricing Plans", "content": "Plans start at R$150/month."},
        ],
        "meta": {"total": 2},
    }

    sync = HelpCenterSync(mock_store, chatwoot_client=mock_client)
    count = sync.run()

    assert count == 2
    mock_client.list_portals.assert_called_once()
    mock_client.list_portal_articles.assert_called_once_with(
        "test-portal", status="published", page=1
    )
    assert mock_store.upsert.call_count == 2
    upserted_ids = [c.kwargs["doc_id"] for c in mock_store.upsert.call_args_list]
    assert "hc-article-101" in upserted_ids
    assert "hc-article-102" in upserted_ids


def test_hc_sync_skips_when_no_api_token():
    """HelpCenterSync.run() should return 0 and skip sync when api_token is empty."""
    from unittest.mock import MagicMock

    from app.hc_sync import HelpCenterSync

    mock_store = MagicMock()
    mock_client = MagicMock()
    mock_client.api_token = ""  # empty — no token configured

    sync = HelpCenterSync(mock_store, chatwoot_client=mock_client)
    count = sync.run()

    assert count == 0
    mock_client.list_portals.assert_not_called()
    mock_store.upsert.assert_not_called()


def test_hc_sync_skips_articles_without_id_or_title():
    """HelpCenterSync.run() should skip malformed articles missing id or title."""
    from unittest.mock import MagicMock

    from app.hc_sync import HelpCenterSync

    mock_store = MagicMock()
    mock_client = MagicMock()
    mock_client.api_token = "test-token"
    mock_client.list_portals.return_value = [{"id": 1, "slug": "p", "name": "P"}]
    mock_client.list_portal_articles.return_value = {
        "articles": [
            {"id": None, "title": "No ID article", "content": "x"},   # missing id → skip
            {"id": 200, "title": "", "content": "no title"},           # empty title → skip
            {"id": 201, "title": "Valid Article", "content": "content"},  # valid → indexed
        ],
        "meta": {"total": 3},
    }

    sync = HelpCenterSync(mock_store, chatwoot_client=mock_client)
    count = sync.run()

    assert count == 1
    assert mock_store.upsert.call_count == 1
    assert mock_store.upsert.call_args.kwargs["doc_id"] == "hc-article-201"
