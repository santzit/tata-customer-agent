"""Tests for ChatwootClient.toggle_status and the inbox-visibility fix.

Verifies that:
1. ``toggle_status`` POSTs to the correct Chatwoot endpoint with the given status.
2. ``handover_to_human`` delegates to ``toggle_status`` (so the endpoint URL is
   not duplicated).
3. After a normal (non-escalation) bot reply, ``toggle_status("open")`` is
   called so the conversation appears in the Chatwoot Inbox/Conversations view.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import httpx
import pytest
import respx


# ---------------------------------------------------------------------------
# ChatwootClient.toggle_status unit tests
# ---------------------------------------------------------------------------


def test_chatwoot_toggle_status_posts_to_correct_endpoint():
    """toggle_status should POST ``{"status": <status>}`` to /toggle_status."""
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
        f"/conversations/{conversation_id}/toggle_status"
    )

    with respx.mock:
        mock_route = respx.post(expected_url).mock(
            return_value=httpx.Response(200, json={"id": conversation_id, "status": "open"})
        )
        result = client.toggle_status(conversation_id=conversation_id, status="open")

    assert mock_route.called
    assert result["status"] == "open"
    sent_request = mock_route.calls.last.request
    assert sent_request.headers["api_access_token"] == "token-abc"
    body = json.loads(sent_request.content)
    assert body == {"status": "open"}


def test_chatwoot_toggle_status_sends_given_status():
    """toggle_status should send whatever status string is passed."""
    from app.chatwoot import ChatwootClient

    client = ChatwootClient(
        base_url="http://chatwoot.test",
        api_token="tok",
        account_id=1,
    )

    with respx.mock:
        mock_route = respx.post(
            "http://chatwoot.test/api/v1/accounts/1/conversations/10/toggle_status"
        ).mock(return_value=httpx.Response(200, json={"status": "pending"}))
        client.toggle_status(conversation_id=10, status="pending")

    body = json.loads(mock_route.calls.last.request.content)
    assert body == {"status": "pending"}


def test_chatwoot_toggle_status_raises_on_error():
    """toggle_status should raise on non-2xx responses."""
    from app.chatwoot import ChatwootClient

    client = ChatwootClient(
        base_url="http://chatwoot.test",
        api_token="bad",
        account_id=1,
    )

    with respx.mock:
        respx.post(
            "http://chatwoot.test/api/v1/accounts/1/conversations/1/toggle_status"
        ).mock(return_value=httpx.Response(422, json={"error": "unprocessable"}))
        with pytest.raises(httpx.HTTPStatusError):
            client.toggle_status(conversation_id=1, status="open")


def test_handover_to_human_delegates_to_toggle_status():
    """handover_to_human must call toggle_status with status='open'."""
    from app.chatwoot import ChatwootClient

    client = ChatwootClient(
        base_url="http://chatwoot.test",
        api_token="token-abc",
        account_id=5,
    )

    expected_url = (
        "http://chatwoot.test/api/v1/accounts/5"
        "/conversations/77/toggle_status"
    )

    with respx.mock:
        mock_route = respx.post(expected_url).mock(
            return_value=httpx.Response(200, json={"id": 77, "status": "open"})
        )
        result = client.handover_to_human(conversation_id=77)

    assert mock_route.called
    body = json.loads(mock_route.calls.last.request.content)
    assert body == {"status": "open"}
    assert result["status"] == "open"


# ---------------------------------------------------------------------------
# _process_buffered_messages – inbox visibility fix
# ---------------------------------------------------------------------------


def test_process_buffered_messages_toggles_open_after_normal_reply():
    """After a normal bot reply (no escalation) toggle_status('open') is called."""
    from app.main import _process_buffered_messages

    mock_chatwoot = MagicMock()
    mock_chatwoot.send_message.return_value = {"id": 1}
    mock_chatwoot.toggle_status.return_value = {"status": "open"}

    mock_vector_store = MagicMock()
    mock_memory = MagicMock()

    reply_parts = ["Here is your answer."]
    needs_human = False

    with (
        patch("app.main._chatwoot_client", mock_chatwoot),
        patch("app.main._vector_store", mock_vector_store),
        patch("app.main._conversation_memory", mock_memory),
        patch(
            "app.main.run_agent",
            return_value=(reply_parts, needs_human),
        ),
    ):
        _process_buffered_messages(conversation_id=42, combined_text="Hello")

    mock_chatwoot.send_message.assert_called_once_with(
        conversation_id=42, message="Here is your answer."
    )
    mock_chatwoot.toggle_status.assert_called_once_with(
        conversation_id=42, status="open"
    )
    mock_chatwoot.handover_to_human.assert_not_called()


def test_process_buffered_messages_toggle_status_error_is_logged_not_raised():
    """If toggle_status raises, the exception is caught and logged — not propagated."""
    import logging

    from app.main import _process_buffered_messages

    mock_chatwoot = MagicMock()
    mock_chatwoot.send_message.return_value = {"id": 3}
    mock_chatwoot.toggle_status.side_effect = httpx.HTTPStatusError(
        "Server error", request=MagicMock(), response=MagicMock(status_code=500)
    )

    with (
        patch("app.main._chatwoot_client", mock_chatwoot),
        patch("app.main._vector_store", MagicMock()),
        patch("app.main._conversation_memory", MagicMock()),
        patch("app.main.run_agent", return_value=(["A reply."], False)),
    ):
        # Must not raise even though toggle_status fails.
        _process_buffered_messages(conversation_id=55, combined_text="Hey")

    mock_chatwoot.send_message.assert_called_once()
    mock_chatwoot.toggle_status.assert_called_once_with(conversation_id=55, status="open")


def test_process_buffered_messages_calls_handover_not_toggle_on_escalation():
    """On escalation handover_to_human is called; toggle_status is NOT called separately."""
    from app.main import _process_buffered_messages

    mock_chatwoot = MagicMock()
    mock_chatwoot.send_message.return_value = {"id": 2}
    mock_chatwoot.handover_to_human.return_value = {"status": "open"}

    reply_parts = ["Connecting you with a human agent."]
    needs_human = True

    with (
        patch("app.main._chatwoot_client", mock_chatwoot),
        patch("app.main._vector_store", MagicMock()),
        patch("app.main._conversation_memory", MagicMock()),
        patch(
            "app.main.run_agent",
            return_value=(reply_parts, needs_human),
        ),
    ):
        _process_buffered_messages(conversation_id=99, combined_text="I need help now")

    mock_chatwoot.send_message.assert_called_once_with(
        conversation_id=99, message="Connecting you with a human agent."
    )
    mock_chatwoot.handover_to_human.assert_called_once_with(conversation_id=99)
    mock_chatwoot.toggle_status.assert_not_called()
