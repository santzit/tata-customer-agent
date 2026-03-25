"""Tests for the v03x Web API endpoints (/web/*).

These tests use FastAPI's TestClient and mock external dependencies
(Chatwoot API, PostgreSQL) so they run without any live services.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_httpx_response(json_data, status_code: int = 200):
    """Create a mock httpx response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data
    mock_response.raise_for_status = MagicMock()
    return mock_response


def _mock_httpx_client(response=None, *, side_effect=None):
    """Create a mock httpx.AsyncClient async context manager."""
    mock_client = AsyncMock()
    if side_effect is not None:
        mock_client.get = AsyncMock(side_effect=side_effect)
        mock_client.post = AsyncMock(side_effect=side_effect)
    else:
        mock_client.get = AsyncMock(return_value=response)
        mock_client.post = AsyncMock(return_value=response)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


def _mock_db_session(first_return=None, all_return=None):
    """Create a mock SQLModel Session context manager."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.exec.return_value.first.return_value = first_return
    mock_session.exec.return_value.all.return_value = all_return or []
    return mock_session


# ---------------------------------------------------------------------------
# /web/status
# ---------------------------------------------------------------------------


class TestWebStatus:
    def test_status_returns_expected_keys(self):
        """GET /web/status returns the three connection-status booleans."""
        mock_ctx = _mock_httpx_client(side_effect=Exception("refused"))
        mock_session = _mock_db_session()

        with (
            patch("app.routers.web.Session", return_value=mock_session),
            patch("app.routers.web.httpx.AsyncClient", return_value=mock_ctx),
        ):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "chatwoot_connected" in data
        assert "db_connected" in data
        assert "openai_configured" in data


# ---------------------------------------------------------------------------
# /web/chatwoot/accounts
# ---------------------------------------------------------------------------


class TestChatwootAccounts:
    def test_returns_list_on_success(self):
        """GET /web/chatwoot/accounts returns the list from Chatwoot API."""
        mock_resp = _mock_httpx_response([{"id": 1, "name": "Acme Corp"}])
        mock_ctx = _mock_httpx_client(mock_resp)

        with patch("app.routers.web.httpx.AsyncClient", return_value=mock_ctx):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/accounts")

        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_returns_502_when_chatwoot_unreachable(self):
        """GET /web/chatwoot/accounts returns 502 when Chatwoot is unreachable."""
        mock_ctx = _mock_httpx_client(side_effect=Exception("connection refused"))

        with patch("app.routers.web.httpx.AsyncClient", return_value=mock_ctx):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/accounts")

        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# /web/chatwoot/inboxes
# ---------------------------------------------------------------------------


class TestChatwootInboxes:
    def test_returns_empty_list_without_account_id(self):
        """GET /web/chatwoot/inboxes without account_id returns [] when no default set."""
        from app.main import app
        with TestClient(app) as client:
            with patch("app.routers.web._account_id_or_default", return_value=None):
                resp = client.get("/web/chatwoot/inboxes")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_inboxes_for_account(self):
        """GET /web/chatwoot/inboxes?account_id=1 calls Chatwoot and returns list."""
        mock_resp = _mock_httpx_response({"payload": [{"id": 10, "name": "Main Inbox"}]})
        mock_ctx = _mock_httpx_client(mock_resp)

        with patch("app.routers.web.httpx.AsyncClient", return_value=mock_ctx):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/inboxes?account_id=1")

        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# /web/chatwoot/teams
# ---------------------------------------------------------------------------


class TestChatwootTeams:
    def test_returns_teams_for_account(self):
        """GET /web/chatwoot/teams?account_id=1 returns teams list."""
        mock_resp = _mock_httpx_response([{"id": 3, "name": "Support Team"}])
        mock_ctx = _mock_httpx_client(mock_resp)

        with patch("app.routers.web.httpx.AsyncClient", return_value=mock_ctx):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/teams?account_id=1")

        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# /web/config/token-api
# ---------------------------------------------------------------------------


class TestTokenApi:
    def test_save_token_api(self):
        """POST /web/config/token-api saves the token and returns ok."""
        mock_session = _mock_db_session()

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.post(
                    "/web/config/token-api",
                    json={"account_id": 1, "token_api": "test-token-123"},
                )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_save_token_api_updates_existing(self):
        """POST /web/config/token-api updates an existing account record."""
        from app.web_models import ChatwootAccount
        existing = ChatwootAccount(id=1, account_id=1, name="1", token_api="old-token")
        mock_session = _mock_db_session(first_return=existing)

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.post(
                    "/web/config/token-api",
                    json={"account_id": 1, "token_api": "new-token"},
                )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


# ---------------------------------------------------------------------------
# /web/config/openai
# ---------------------------------------------------------------------------


class TestOpenAIConfig:
    def test_get_openai_config_empty(self):
        """GET /web/config/openai returns defaults when no config is stored."""
        mock_session = _mock_db_session()

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/config/openai")

        assert resp.status_code == 200
        data = resp.json()
        assert "api_key" in data
        assert "model" in data

    def test_get_openai_config_masks_key(self):
        """GET /web/config/openai returns a masked API key."""
        from app.web_models import OpenAIConfig
        cfg = OpenAIConfig(id=1, api_key="sk-real-secret-key", model="gpt-4o")
        mock_session = _mock_db_session(first_return=cfg)

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/config/openai")

        assert resp.status_code == 200
        data = resp.json()
        # Key should be masked — must not expose the real key
        assert data["api_key"] != "sk-real-secret-key"
        assert "*" in data["api_key"]

    def test_save_openai_config(self):
        """POST /web/config/openai persists the configuration."""
        mock_session = _mock_db_session()

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.post(
                    "/web/config/openai",
                    json={"api_key": "sk-test", "model": "gpt-4o", "params": None},
                )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


# ---------------------------------------------------------------------------
# /web/chatwoot/help-center
# ---------------------------------------------------------------------------


class TestHelpCenter:
    def test_get_help_center_articles(self):
        """GET /web/chatwoot/help-center returns a list of stored articles."""
        from app.web_models import HelpCenterArticle

        mock_article = HelpCenterArticle(
            id=1,
            article_id=42,
            title="Test Article",
            content="This is test content.",
            locale="en",
        )
        mock_session = _mock_db_session(all_return=[mock_article])

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/help-center")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["title"] == "Test Article"

    def test_search_filters_articles(self):
        """GET /web/chatwoot/help-center?search=hello filters by title/content."""
        from app.web_models import HelpCenterArticle

        articles = [
            HelpCenterArticle(id=1, article_id=1, title="Hello world", content="foo"),
            HelpCenterArticle(id=2, article_id=2, title="Another article", content="bar"),
        ]
        mock_session = _mock_db_session(all_return=articles)

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/help-center?search=hello")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "Hello" in data[0]["title"]

    def test_locale_filter(self):
        """GET /web/chatwoot/help-center?locale=pt filters by locale in the query."""
        from app.web_models import HelpCenterArticle

        articles = [
            HelpCenterArticle(id=1, article_id=1, title="Article PT", content="...", locale="pt"),
        ]
        mock_session = _mock_db_session(all_return=articles)

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/help-center?locale=pt")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# /web/conversations
# ---------------------------------------------------------------------------


class TestConversations:
    def test_returns_empty_without_account(self):
        """GET /web/conversations returns [] when no account_id is resolvable."""
        from app.main import app
        with TestClient(app) as client:
            with patch("app.routers.web._account_id_or_default", return_value=None):
                resp = client.get("/web/conversations")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_conversations_list(self):
        """GET /web/conversations?account_id=1 returns a list of conversations."""
        chatwoot_payload = {
            "data": {
                "payload": [
                    {
                        "id": 101,
                        "display_id": 1,
                        "status": "open",
                        "inbox_id": 5,
                        "account_id": 1,
                        "last_activity_at": 1700000000,
                        "meta": {
                            "sender": {"id": 10, "name": "Alice", "email": "alice@example.com"}
                        },
                        "last_non_activity_message": {"content": "Hello!"},
                    }
                ]
            }
        }
        mock_resp = _mock_httpx_response(chatwoot_payload)
        mock_ctx = _mock_httpx_client(mock_resp)

        with patch("app.routers.web.httpx.AsyncClient", return_value=mock_ctx):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/conversations?account_id=1&limit=10")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == 101
        assert data[0]["contact"]["name"] == "Alice"

    def test_limit_respected(self):
        """GET /web/conversations?limit=1 returns at most 1 conversation."""
        conversations = [
            {
                "id": i,
                "display_id": i,
                "status": "open",
                "inbox_id": 1,
                "account_id": 1,
                "last_activity_at": 1700000000,
                "meta": {"sender": {"id": i, "name": f"User {i}"}},
            }
            for i in range(1, 6)
        ]
        chatwoot_payload = {"data": {"payload": conversations}}
        mock_resp = _mock_httpx_response(chatwoot_payload)
        mock_ctx = _mock_httpx_client(mock_resp)

        with patch("app.routers.web.httpx.AsyncClient", return_value=mock_ctx):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/conversations?account_id=1&limit=1")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 1


# ---------------------------------------------------------------------------
# /web/conversations/{id}/messages
# ---------------------------------------------------------------------------


class TestConversationMessages:
    def test_requires_account_id(self):
        """GET /web/conversations/1/messages without account_id returns 400."""
        from app.main import app
        with TestClient(app) as client:
            with patch("app.routers.web._account_id_or_default", return_value=None):
                resp = client.get("/web/conversations/1/messages")

        assert resp.status_code == 400

    def test_returns_messages_list(self):
        """GET /web/conversations/1/messages?account_id=1 returns messages."""
        chatwoot_payload = {
            "payload": [
                {
                    "id": 1001,
                    "content": "Hi there!",
                    "message_type": 0,
                    "created_at": 1700000000,
                    "sender": {"id": 10, "name": "Alice", "type": "contact"},
                    "private": False,
                }
            ]
        }
        mock_resp = _mock_httpx_response(chatwoot_payload)
        mock_ctx = _mock_httpx_client(mock_resp)

        with patch("app.routers.web.httpx.AsyncClient", return_value=mock_ctx):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/conversations/1/messages?account_id=1")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["content"] == "Hi there!"
        assert data[0]["sender"]["name"] == "Alice"

    def test_returns_502_when_chatwoot_unreachable(self):
        """GET /web/conversations/{id}/messages returns 502 when Chatwoot unreachable."""
        mock_ctx = _mock_httpx_client(side_effect=Exception("timeout"))

        with patch("app.routers.web.httpx.AsyncClient", return_value=mock_ctx):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/conversations/1/messages?account_id=1")

        assert resp.status_code == 502
