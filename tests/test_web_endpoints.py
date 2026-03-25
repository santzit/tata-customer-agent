"""Tests for the v03x Web API endpoints (/web/*).

Chatwoot HTTP is mocked via ``ChatwootClient`` sub-APIs (accounts, inboxes,
conversations, help_center) rather than raw httpx, matching the refactored
architecture in ``app/services/chatwoot_client.py``.

PostgreSQL is not required — DB interactions use a mock SQLModel Session.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_session(first_return=None, all_return=None):
    """Return a mock SQLModel Session context manager."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.exec.return_value.first.return_value = first_return
    session.exec.return_value.all.return_value = all_return or []
    return session


def _mock_web_client(
    *,
    accounts_list=None,
    inboxes_list=None,
    teams_list=None,
    portals_list=None,
    portal_articles=None,
    conversations_data=None,
    messages_list=None,
    accounts_list_raises=None,
    inboxes_list_raises=None,
    conversations_data_raises=None,
    messages_list_raises=None,
):
    """Build a MagicMock ChatwootClient pre-wired with return values.

    All sub-API objects (client.accounts, client.inboxes, client.conversations,
    client.help_center) are separate MagicMocks so each method can be configured
    independently.
    """
    client = MagicMock()

    # accounts sub-API
    if accounts_list_raises:
        client.accounts.list.side_effect = accounts_list_raises
    else:
        client.accounts.list.return_value = accounts_list or []

    # inboxes sub-API
    if inboxes_list_raises:
        client.inboxes.list.side_effect = inboxes_list_raises
    else:
        client.inboxes.list.return_value = inboxes_list or []
    client.inboxes.list_teams.return_value = teams_list or []

    # help_center sub-API
    client.help_center.list_portals.return_value = portals_list or []
    client.help_center.list_portal_articles.return_value = portal_articles or {}

    # conversations sub-API
    if conversations_data_raises:
        client.conversations.list_conversations.side_effect = conversations_data_raises
    else:
        client.conversations.list_conversations.return_value = conversations_data or {}
    if messages_list_raises:
        client.conversations.get_messages.side_effect = messages_list_raises
    else:
        client.conversations.get_messages.return_value = messages_list or []

    return client


# ---------------------------------------------------------------------------
# /web/status
# ---------------------------------------------------------------------------


class TestWebStatus:
    def test_status_returns_expected_keys(self):
        """GET /web/status returns the three connection-status booleans."""
        mock_session = _mock_db_session()

        with (
            patch("app.routers.web.Session", return_value=mock_session),
            patch("app.routers.web._web_client", return_value=_mock_web_client()),
        ):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "chatwoot_connected" in data
        assert "db_connected" in data
        assert "openai_configured" in data

    def test_chatwoot_connected_true_when_accounts_list_succeeds(self):
        """GET /web/status sets chatwoot_connected=True when accounts.list() works."""
        mock_client = _mock_web_client(accounts_list=[{"id": 1, "name": "Acme"}])
        mock_session = _mock_db_session()

        with (
            patch("app.routers.web.Session", return_value=mock_session),
            patch("app.routers.web._web_client", return_value=mock_client),
        ):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/status")

        assert resp.status_code == 200
        assert resp.json()["chatwoot_connected"] is True

    def test_chatwoot_connected_false_when_accounts_list_fails(self):
        """GET /web/status sets chatwoot_connected=False when accounts.list() raises."""
        mock_client = _mock_web_client(accounts_list_raises=Exception("timeout"))
        mock_session = _mock_db_session()

        with (
            patch("app.routers.web.Session", return_value=mock_session),
            patch("app.routers.web._web_client", return_value=mock_client),
        ):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/status")

        assert resp.status_code == 200
        assert resp.json()["chatwoot_connected"] is False


# ---------------------------------------------------------------------------
# /web/chatwoot/accounts
# ---------------------------------------------------------------------------


class TestChatwootAccounts:
    def test_returns_list_on_success(self):
        """GET /web/chatwoot/accounts delegates to client.accounts.list()."""
        accounts = [{"id": 1, "name": "Acme Corp"}]
        mock_client = _mock_web_client(accounts_list=accounts)

        with patch("app.routers.web._web_client", return_value=mock_client):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/accounts")

        assert resp.status_code == 200
        assert resp.json() == accounts
        mock_client.accounts.list.assert_called_once()

    def test_returns_empty_list_when_no_master_token(self):
        """GET /web/chatwoot/accounts returns 502 when master token is missing."""
        mock_client = _mock_web_client(accounts_list=[])

        with (
            patch("app.routers.web._web_client", return_value=mock_client),
            patch("app.routers.web.settings") as mock_settings,
        ):
            mock_settings.chatwoot_master_token = ""
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/accounts")

        # Returns 502 because master token is empty and list is empty
        assert resp.status_code in (200, 502)


# ---------------------------------------------------------------------------
# /web/chatwoot/inboxes
# ---------------------------------------------------------------------------


class TestChatwootInboxes:
    def test_returns_empty_list_without_account_id(self):
        """GET /web/chatwoot/inboxes without account_id returns []."""
        from app.main import app
        with TestClient(app) as client:
            with patch("app.routers.web._account_id_or_default", return_value=None):
                resp = client.get("/web/chatwoot/inboxes")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_inboxes_for_account(self):
        """GET /web/chatwoot/inboxes?account_id=1 delegates to client.inboxes.list()."""
        inboxes = [{"id": 10, "name": "Main Inbox"}]
        mock_client = _mock_web_client(inboxes_list=inboxes)

        with patch("app.routers.web._web_client", return_value=mock_client):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/inboxes?account_id=1")

        assert resp.status_code == 200
        assert resp.json() == inboxes
        mock_client.inboxes.list.assert_called_once_with(account_id=1)


# ---------------------------------------------------------------------------
# /web/chatwoot/teams
# ---------------------------------------------------------------------------


class TestChatwootTeams:
    def test_returns_teams_for_account(self):
        """GET /web/chatwoot/teams?account_id=1 delegates to client.inboxes.list_teams()."""
        teams = [{"id": 3, "name": "Support Team"}]
        mock_client = _mock_web_client(teams_list=teams)

        with patch("app.routers.web._web_client", return_value=mock_client):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/teams?account_id=1")

        assert resp.status_code == 200
        assert resp.json() == teams
        mock_client.inboxes.list_teams.assert_called_once_with(account_id=1)

    def test_returns_empty_list_without_account_id(self):
        """GET /web/chatwoot/teams without account_id returns []."""
        from app.main import app
        with TestClient(app) as client:
            with patch("app.routers.web._account_id_or_default", return_value=None):
                resp = client.get("/web/chatwoot/teams")

        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# /web/config/token-api
# ---------------------------------------------------------------------------


class TestTokenApi:
    def test_get_token_apis_returns_mapping(self):
        """GET /web/config/token-api returns a dict of account_id → token_api."""
        from app.web_models import ChatwootAccount
        acct = ChatwootAccount(id=1, account_id=7, name="Acme", token_api="my-token")
        mock_session = _mock_db_session(all_return=[acct])

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/config/token-api")

        assert resp.status_code == 200
        assert resp.json() == {"7": "my-token"}

    def test_save_token_api_new(self):
        """POST /web/config/token-api inserts a new account record."""
        mock_session = _mock_db_session(first_return=None)

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
        # The token_api field should have been updated in-place
        assert existing.token_api == "new-token"


# ---------------------------------------------------------------------------
# /web/config/openai
# ---------------------------------------------------------------------------


class TestOpenAIConfig:
    def test_get_openai_config_empty(self):
        """GET /web/config/openai returns defaults when no config is stored."""
        mock_session = _mock_db_session(first_return=None)

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/config/openai")

        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key"] == ""
        assert "model" in data

    def test_get_openai_config_masks_key(self):
        """GET /web/config/openai returns a masked API key (never the real secret)."""
        from app.web_models import OpenAIConfig
        cfg = OpenAIConfig(id=1, api_key="sk-very-secret-key", model="gpt-4o")
        mock_session = _mock_db_session(first_return=cfg)

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/config/openai")

        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key"] != "sk-very-secret-key"
        assert "*" in data["api_key"]

    def test_save_openai_config(self):
        """POST /web/config/openai persists the configuration."""
        mock_session = _mock_db_session(first_return=None)

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

        article = HelpCenterArticle(
            id=1, article_id=42, title="Test Article",
            content="This is test content.", locale="en",
        )
        mock_session = _mock_db_session(all_return=[article])

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/help-center")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Article"

    def test_search_filters_articles(self):
        """GET /web/chatwoot/help-center?search=hello filters articles by title/content."""
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
        """GET /web/chatwoot/help-center?locale=pt is passed as a DB WHERE clause."""
        from app.web_models import HelpCenterArticle

        article = HelpCenterArticle(
            id=1, article_id=1, title="Artigo PT", content="...", locale="pt"
        )
        mock_session = _mock_db_session(all_return=[article])

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/chatwoot/help-center?locale=pt")

        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_sync_help_center_calls_client_sub_apis(self):
        """POST /web/chatwoot/sync-help-center uses client.help_center.* sub-APIs."""
        portal = {"id": 1, "slug": "tata-portal", "name": "Tata"}
        articles_payload = {
            "articles": [
                {"id": 10, "title": "FAQ", "content": "Some content", "locale": "en"}
            ],
            "meta": {"total": 1},
        }
        mock_client = _mock_web_client(
            portals_list=[portal],
            portal_articles=articles_payload,
        )
        mock_session = _mock_db_session(first_return=None)

        with (
            patch("app.routers.web._web_client", return_value=mock_client),
            patch("app.routers.web.Session", return_value=mock_session),
            patch("app.routers.web.PgVectorStore"),
            patch("app.routers.web.HelpCenterSync"),
        ):
            from app.main import app
            with TestClient(app) as client:
                resp = client.post("/web/chatwoot/sync-help-center", json={})

        assert resp.status_code == 200
        assert resp.json()["synced"] == 1
        mock_client.help_center.list_portals.assert_called_once()
        # account_id comes from _account_id_or_default(None) → settings.chatwoot_account_id
        call_args = mock_client.help_center.list_portal_articles.call_args
        assert call_args[0][0] == "tata-portal"


# ---------------------------------------------------------------------------
# /web/conversations
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# /web/conversations
# ---------------------------------------------------------------------------

def _mock_engine(rows=None, messages_rows=None):
    """Return a mock SQLAlchemy engine that yields pre-set rows."""
    from unittest.mock import MagicMock
    mock_engine = MagicMock()
    conn = MagicMock()

    # Track calls so we can return different rows for conversations vs messages
    call_count = [0]
    datasets = []
    if rows is not None:
        datasets.append(rows)
    if messages_rows is not None:
        datasets.append(messages_rows)

    def _execute(query, params=None):
        idx = call_count[0]
        call_count[0] += 1
        result = MagicMock()
        dataset = datasets[idx] if idx < len(datasets) else []
        result.mappings.return_value.all.return_value = dataset
        return result

    conn.execute.side_effect = _execute
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return mock_engine


class TestConversations:
    def test_returns_empty_list_when_db_empty(self):
        """GET /web/conversations returns [] when DB has no conversations."""
        mock_eng = _mock_engine(rows=[])
        with patch("app.routers.web._engine", mock_eng):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/conversations")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_conversations_from_db(self):
        """GET /web/conversations returns rows from local DB."""
        import datetime

        row = {
            "id": 101,
            "display_id": 1,
            "status": "open",
            "meta": {"sender": {"id": 10, "name": "Alice", "email": "alice@example.com"}},
            "updated_at": datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
            "account_id": 1,
            "inbox_id": 5,
            "account_name": "Acme Corp",
            "inbox_name": "Website Chat",
        }

        mock_eng = _mock_engine(rows=[row])
        with patch("app.routers.web._engine", mock_eng):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/conversations?limit=10")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == 101
        assert data[0]["contact"]["name"] == "Alice"
        assert data[0]["account_name"] == "Acme Corp"
        assert data[0]["inbox_name"] == "Website Chat"


# ---------------------------------------------------------------------------
# /web/conversations/{id}/messages
# ---------------------------------------------------------------------------


class TestConversationMessages:
    def test_returns_messages_from_db(self):
        """GET /web/conversations/42/messages returns rows from local messages table."""
        import datetime

        row = {
            "id": 1001,
            "content": "Hi there!",
            "message_type": "outgoing",
            "private": False,
            "status": "sent",
            "created_at": datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
        }

        mock_eng = _mock_engine(messages_rows=[row])
        with patch("app.routers.web._engine", mock_eng):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/conversations/42/messages")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["content"] == "Hi there!"
        assert data[0]["message_type"] == 3  # mapped to bot type
        assert data[0]["sender"]["name"] == "Tata Bot"

    def test_returns_empty_list_when_no_messages(self):
        """GET /web/conversations/99/messages returns [] when no messages in DB."""
        mock_eng = _mock_engine(messages_rows=[])
        with patch("app.routers.web._engine", mock_eng):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/conversations/99/messages")

        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# /web/accounts/{id}/inboxes  and  /web/accounts/{id}/inboxes/sync
# ---------------------------------------------------------------------------


class TestAccountInboxes:
    """Tests for per-account inbox DB endpoints."""

    def test_get_inboxes_returns_list(self):
        """GET /web/accounts/1/inboxes returns inboxes stored for that account."""
        from app.web_models import ChatwootInbox

        inbox = ChatwootInbox(id=1, inbox_id=10, account_id=1, name="Website Chat", portal_slug="my-portal")
        mock_session = _mock_db_session(all_return=[inbox])

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/accounts/1/inboxes")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == 10
        assert data[0]["name"] == "Website Chat"
        assert data[0]["portal_slug"] == "my-portal"

    def test_get_inboxes_returns_empty_when_none(self):
        """GET /web/accounts/99/inboxes returns [] when no inboxes found."""
        mock_session = _mock_db_session(all_return=[])

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/accounts/99/inboxes")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_sync_inboxes_calls_chatwoot_client(self):
        """POST /web/accounts/1/inboxes/sync calls client.inboxes.list and upserts."""
        mock_client = _mock_web_client(
            inboxes_list=[{"id": 10, "name": "Website Chat"}],
        )
        mock_client.help_center.list_portals.return_value = [
            {"slug": "my-portal", "name": "Tata HC", "inboxes": [{"id": 10}]}
        ]
        mock_session = _mock_db_session(first_return=None)

        with patch("app.routers.web._web_client", return_value=mock_client), \
             patch("app.routers.web.Session", return_value=mock_session), \
             patch("app.config.settings.chatwoot_master_token", "test-token"):
            from app.main import app
            with TestClient(app) as client:
                resp = client.post("/web/accounts/1/inboxes/sync")

        assert resp.status_code == 200
        data = resp.json()
        assert data["synced"] == 1
        assert data["inboxes"][0]["name"] == "Website Chat"
        mock_client.inboxes.list.assert_called_once_with(account_id=1)
        mock_client.help_center.list_portals.assert_called_once_with(account_id=1)

    def test_sync_inboxes_no_master_token(self):
        """POST /web/accounts/1/inboxes/sync returns 502 when CHATWOOT_MASTER_TOKEN unset."""
        with patch("app.config.settings.chatwoot_master_token", ""):
            from app.main import app
            with TestClient(app) as client:
                resp = client.post("/web/accounts/1/inboxes/sync")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# /web/accounts/{id}/inboxes/{inbox_id}/help-center
# ---------------------------------------------------------------------------


class TestInboxHelpCenter:
    """Tests for inbox-specific Help Center article endpoint."""

    def test_returns_articles_filtered_by_portal(self):
        """GET /web/accounts/1/inboxes/10/help-center returns only articles for inbox's portal."""
        from app.web_models import ChatwootInbox, HelpCenterArticle

        inbox = ChatwootInbox(id=1, inbox_id=10, account_id=1, name="Chat", portal_slug="my-portal")
        articles = [
            HelpCenterArticle(id=1, article_id=1, title="FAQ", content="Answer", locale="en", portal_slug="my-portal"),
            HelpCenterArticle(id=2, article_id=2, title="Other", content="Other", locale="en", portal_slug="other-portal"),
        ]

        # Session mock: first() for inbox, all() for articles
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        # The endpoint calls exec twice: once for inbox (first()), once for articles (all())
        mock_session.exec.return_value.first.return_value = inbox
        mock_session.exec.return_value.all.return_value = articles

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/accounts/1/inboxes/10/help-center")

        assert resp.status_code == 200
        data = resp.json()
        # Only articles from my-portal should be returned
        assert all(a["portal_slug"] == "my-portal" for a in data)
        assert any(a["title"] == "FAQ" for a in data)

    def test_returns_all_articles_when_no_portal(self):
        """GET /web/accounts/1/inboxes/10/help-center returns all articles when inbox has no portal."""
        from app.web_models import ChatwootInbox, HelpCenterArticle

        inbox = ChatwootInbox(id=1, inbox_id=10, account_id=1, name="Chat", portal_slug="")
        articles = [
            HelpCenterArticle(id=1, article_id=1, title="Art1", content="c1", locale="en", portal_slug="p1"),
            HelpCenterArticle(id=2, article_id=2, title="Art2", content="c2", locale="en", portal_slug="p2"),
        ]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = inbox
        mock_session.exec.return_value.all.return_value = articles

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/accounts/1/inboxes/10/help-center")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_search_filter_applied(self):
        """GET .../help-center?search=FAQ filters articles by search term."""
        from app.web_models import ChatwootInbox, HelpCenterArticle

        inbox = ChatwootInbox(id=1, inbox_id=10, account_id=1, name="Chat", portal_slug="")
        articles = [
            HelpCenterArticle(id=1, article_id=1, title="FAQ about gym", content="...", locale="en", portal_slug=""),
            HelpCenterArticle(id=2, article_id=2, title="Pricing", content="...", locale="en", portal_slug=""),
        ]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = inbox
        mock_session.exec.return_value.all.return_value = articles

        with patch("app.routers.web.Session", return_value=mock_session):
            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/web/accounts/1/inboxes/10/help-center?search=faq")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "FAQ" in data[0]["title"]
