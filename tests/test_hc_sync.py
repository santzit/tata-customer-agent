"""Unit tests for app.hc_sync.HelpCenterSync.

All external dependencies (psycopg2, PgVectorStore) are mocked so these
tests run without a real database or OpenAI key.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# HTML stripping helper
# ---------------------------------------------------------------------------


def test_strip_html_removes_tags():
    from app.hc_sync import _strip_html

    assert _strip_html("<p>Hello <b>world</b>!</p>") == "Hello world !"


def test_strip_html_collapses_whitespace():
    from app.hc_sync import _strip_html

    result = _strip_html("<p>  Multiple   spaces  </p>")
    assert "  " not in result


def test_strip_html_handles_empty():
    from app.hc_sync import _strip_html

    assert _strip_html("") == ""
    assert _strip_html(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HelpCenterSync._article_to_text
# ---------------------------------------------------------------------------


def test_article_to_text_combines_title_description_content():
    from app.hc_sync import HelpCenterSync

    sync = HelpCenterSync(chatwoot_dsn="postgresql://x", account_id=1, vector_store=MagicMock())
    article = {
        "id": 1,
        "title": "Membership Plans",
        "description": "Overview of plans",
        "content": "<p>Basic, Standard, Premium</p>",
    }
    text = sync._article_to_text(article)
    assert "Membership Plans" in text
    assert "Overview of plans" in text
    assert "Basic, Standard, Premium" in text
    assert "<p>" not in text


def test_article_to_text_skips_empty_fields():
    from app.hc_sync import HelpCenterSync

    sync = HelpCenterSync(chatwoot_dsn="postgresql://x", account_id=1, vector_store=MagicMock())
    article = {"id": 2, "title": "Title only", "description": None, "content": ""}
    text = sync._article_to_text(article)
    assert text == "Title only"


# ---------------------------------------------------------------------------
# HelpCenterSync.sync — no DSN raises RuntimeError
# ---------------------------------------------------------------------------


def test_sync_raises_when_no_dsn_configured():
    from app.hc_sync import HelpCenterSync

    sync = HelpCenterSync(chatwoot_dsn="", account_id=1, vector_store=MagicMock())
    with pytest.raises(RuntimeError, match="CHATWOOT_DSN"):
        sync.sync()


# ---------------------------------------------------------------------------
# HelpCenterSync.sync — happy path (mocked DB + vector store)
# ---------------------------------------------------------------------------


def _make_sync(articles: list[dict]) -> tuple:
    """Return (sync_instance, mock_store) with the DB pre-populated."""
    from app.hc_sync import HelpCenterSync

    mock_store = MagicMock()
    mock_store._table = "tata_knowledge"

    sync = HelpCenterSync(
        chatwoot_dsn="postgresql://chatwoot:pw@localhost/chatwoot",
        account_id=1,
        vector_store=mock_store,
    )

    # Patch _fetch_published_articles so no real DB call is made.
    sync._fetch_published_articles = MagicMock(return_value=articles)
    return sync, mock_store


def test_sync_upserts_each_article():
    sync, store = _make_sync([
        {"id": 10, "title": "Plans", "description": "Our plans", "content": "<p>Details</p>"},
        {"id": 11, "title": "FAQ", "description": "", "content": "<ul><li>Q1</li></ul>"},
    ])
    count = sync.sync()

    assert count == 2
    assert store.upsert.call_count == 2

    first_call = store.upsert.call_args_list[0]
    assert first_call.args[0] == "hc-article-10"
    assert "Plans" in first_call.args[1]
    assert first_call.args[2]["source"] == "chatwoot_hc"
    assert first_call.args[2]["article_id"] == 10

    second_call = store.upsert.call_args_list[1]
    assert second_call.args[0] == "hc-article-11"


def test_sync_skips_articles_with_no_text():
    sync, store = _make_sync([
        {"id": 20, "title": "", "description": None, "content": ""},
    ])
    count = sync.sync()

    assert count == 0
    store.upsert.assert_not_called()


def test_sync_returns_zero_for_empty_list():
    sync, store = _make_sync([])
    assert sync.sync() == 0
    store.upsert.assert_not_called()


def test_sync_calls_ensure_table():
    sync, store = _make_sync([])
    sync.sync()
    store.ensure_table.assert_called_once()


# ---------------------------------------------------------------------------
# Startup background thread (_start_hc_sync_background)
# ---------------------------------------------------------------------------


def test_start_hc_sync_background_spawns_daemon_thread():
    from app.main import _start_hc_sync_background

    mock_vector_store = MagicMock()
    mock_sync_instance = MagicMock()
    mock_sync_instance.sync.return_value = 3

    threads_started: list = []

    original_thread = __import__("threading").Thread

    def capture_thread(*args, **kwargs):
        t = original_thread(*args, **kwargs)
        threads_started.append(t)
        return t

    with (
        patch("app.main._vector_store", mock_vector_store),
        patch("app.main.settings") as mock_settings,
        patch("app.hc_sync.HelpCenterSync", return_value=mock_sync_instance),
        patch("threading.Thread", side_effect=capture_thread),
    ):
        mock_settings.chatwoot_dsn = "postgresql://x"
        mock_settings.chatwoot_account_id = 1
        _start_hc_sync_background()

    assert len(threads_started) == 1
    assert threads_started[0].daemon is True
    assert threads_started[0].name == "hc-sync"


def test_start_hc_sync_background_exception_does_not_propagate():
    """A failing sync must not crash the startup thread."""
    from app.main import _start_hc_sync_background
    import time

    mock_sync_instance = MagicMock()
    mock_sync_instance.sync.side_effect = Exception("DB unreachable")

    with (
        patch("app.main._vector_store", MagicMock()),
        patch("app.main.settings") as mock_settings,
        patch("app.hc_sync.HelpCenterSync", return_value=mock_sync_instance),
    ):
        mock_settings.chatwoot_dsn = "postgresql://x"
        mock_settings.chatwoot_account_id = 1
        # Must not raise.
        _start_hc_sync_background()

    # Give the background thread a moment to finish.
    time.sleep(0.2)
    # Reaching here without an exception is the assertion.
