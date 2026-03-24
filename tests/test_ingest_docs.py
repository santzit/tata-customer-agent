"""Unit tests for app.ingest_docs.DocsIngestion and PgVectorStore.count().

All external dependencies (psycopg2, PgVectorStore) are mocked so these
tests run without a real database or OpenAI key.
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# PgVectorStore.count()
# ---------------------------------------------------------------------------


def test_pg_vector_store_count_returns_row_count():
    """count() should return the integer value from SELECT COUNT(*)."""
    from app.pg_vector_store import PgVectorStore

    store = PgVectorStore.__new__(PgVectorStore)
    store._table = "tata_knowledge"

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchone.return_value = (42,)
    mock_conn.cursor.return_value = mock_cursor

    with patch.object(store, "_connection") as mock_ctx:
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        result = store.count()

    assert result == 42


def test_pg_vector_store_count_returns_minus_one_on_error():
    """count() should return -1 when the DB is unreachable."""
    from app.pg_vector_store import PgVectorStore

    store = PgVectorStore.__new__(PgVectorStore)
    store._table = "tata_knowledge"

    with patch.object(store, "_connection", side_effect=Exception("connection refused")):
        result = store.count()

    assert result == -1


# ---------------------------------------------------------------------------
# DocsIngestion._chunks_from_file
# ---------------------------------------------------------------------------


def test_chunks_from_file_splits_on_h2(tmp_path: pathlib.Path):
    """H2 headings should produce separate chunks."""
    from app.ingest_docs import DocsIngestion

    md = tmp_path / "test.md"
    md.write_text(
        "# Title\n\nIntro text.\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B.",
        encoding="utf-8",
    )

    ingestor = DocsIngestion(docs_dir=str(tmp_path), vector_store=MagicMock())
    chunks = ingestor._chunks_from_file(md)

    assert len(chunks) == 3  # intro + section A + section B
    chunk_ids = [c[0] for c in chunks]
    assert all(cid.startswith("docs-test-") for cid in chunk_ids)
    # The first chunk is the title/intro (before first H2)
    assert "Intro text." in chunks[0][1]
    assert "Content A." in chunks[1][1]
    assert "Content B." in chunks[2][1]


def test_chunks_from_file_no_h2_is_single_chunk(tmp_path: pathlib.Path):
    """A file with no H2 headings should be a single chunk."""
    from app.ingest_docs import DocsIngestion

    md = tmp_path / "plain.md"
    md.write_text("Just some plain text with no headings.", encoding="utf-8")

    ingestor = DocsIngestion(docs_dir=str(tmp_path), vector_store=MagicMock())
    chunks = ingestor._chunks_from_file(md)

    assert len(chunks) == 1
    assert "plain text" in chunks[0][1]


def test_chunks_from_file_empty_file_returns_nothing(tmp_path: pathlib.Path):
    """An empty file should produce no chunks."""
    from app.ingest_docs import DocsIngestion

    md = tmp_path / "empty.md"
    md.write_text("", encoding="utf-8")

    ingestor = DocsIngestion(docs_dir=str(tmp_path), vector_store=MagicMock())
    assert ingestor._chunks_from_file(md) == []


# ---------------------------------------------------------------------------
# DocsIngestion.ingest()
# ---------------------------------------------------------------------------


def test_ingest_processes_all_md_files(tmp_path: pathlib.Path):
    """ingest() should upsert chunks from every .md file in the directory."""
    from app.ingest_docs import DocsIngestion

    (tmp_path / "a.md").write_text("## A\n\nAlpha content.", encoding="utf-8")
    (tmp_path / "b.md").write_text("## B\n\nBeta content.", encoding="utf-8")

    mock_store = MagicMock()
    mock_store._table = "tata_knowledge"

    ingestor = DocsIngestion(docs_dir=str(tmp_path), vector_store=mock_store)
    count = ingestor.ingest()

    assert count == 2
    assert mock_store.upsert.call_count == 2
    # Source metadata should always be "docs"
    for call_args in mock_store.upsert.call_args_list:
        assert call_args.args[2]["source"] == "docs"


def test_ingest_returns_zero_when_dir_missing():
    """ingest() should return 0 and not raise when the directory doesn't exist."""
    from app.ingest_docs import DocsIngestion

    ingestor = DocsIngestion(docs_dir="/nonexistent/path", vector_store=MagicMock())
    assert ingestor.ingest() == 0


def test_ingest_returns_zero_when_no_md_files(tmp_path: pathlib.Path):
    """ingest() should return 0 when the directory has no .md files."""
    from app.ingest_docs import DocsIngestion

    (tmp_path / "notes.txt").write_text("not markdown", encoding="utf-8")
    ingestor = DocsIngestion(docs_dir=str(tmp_path), vector_store=MagicMock())
    assert ingestor.ingest() == 0


def test_ingest_calls_ensure_table(tmp_path: pathlib.Path):
    """ingest() should call ensure_table() on the store before upserting."""
    from app.ingest_docs import DocsIngestion

    (tmp_path / "c.md").write_text("Content.", encoding="utf-8")
    mock_store = MagicMock()
    ingestor = DocsIngestion(docs_dir=str(tmp_path), vector_store=mock_store)
    ingestor.ingest()
    mock_store.ensure_table.assert_called_once()


def test_ingest_skips_non_md_files(tmp_path: pathlib.Path):
    """ingest() should only process .md files, not .txt or other formats."""
    from app.ingest_docs import DocsIngestion

    (tmp_path / "knowledge.md").write_text("## FAQ\n\nAnswer here.", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("Should be ignored.", encoding="utf-8")
    (tmp_path / "ignore.json").write_text('{"key": "value"}', encoding="utf-8")

    mock_store = MagicMock()
    ingestor = DocsIngestion(docs_dir=str(tmp_path), vector_store=mock_store)
    count = ingestor.ingest()

    assert count == 1  # only the .md file


def test_ingest_chunk_ids_are_stable(tmp_path: pathlib.Path):
    """The same file should always produce the same chunk IDs (idempotent)."""
    from app.ingest_docs import DocsIngestion

    md = tmp_path / "guide.md"
    md.write_text("## Plans\n\nDetails.", encoding="utf-8")

    mock_store = MagicMock()
    ingestor = DocsIngestion(docs_dir=str(tmp_path), vector_store=mock_store)
    ingestor.ingest()
    first_call_id = mock_store.upsert.call_args_list[0].args[0]

    mock_store.reset_mock()
    ingestor.ingest()
    second_call_id = mock_store.upsert.call_args_list[0].args[0]

    assert first_call_id == second_call_id


# ---------------------------------------------------------------------------
# Startup background thread (_start_docs_ingest_background)
# ---------------------------------------------------------------------------


def test_start_docs_ingest_background_spawns_daemon_thread():
    """_start_docs_ingest_background should launch a daemon thread named 'docs-ingest'."""
    from app.main import _start_docs_ingest_background

    mock_ingestor = MagicMock()
    mock_ingestor.ingest.return_value = 5

    threads_started: list = []
    original_thread = __import__("threading").Thread

    def capture_thread(*args, **kwargs):
        t = original_thread(*args, **kwargs)
        threads_started.append(t)
        return t

    with (
        patch("app.main._vector_store", MagicMock()),
        patch("app.main.settings") as mock_settings,
        patch("app.ingest_docs.DocsIngestion", return_value=mock_ingestor),
        patch("threading.Thread", side_effect=capture_thread),
    ):
        mock_settings.docs_dir = "/tmp/docs"
        _start_docs_ingest_background()

    assert len(threads_started) == 1
    assert threads_started[0].daemon is True
    assert threads_started[0].name == "docs-ingest"


def test_start_docs_ingest_background_exception_does_not_propagate():
    """A failing docs ingest must not crash the startup thread."""
    import time

    from app.main import _start_docs_ingest_background

    mock_ingestor = MagicMock()
    mock_ingestor.ingest.side_effect = Exception("disk error")

    with (
        patch("app.main._vector_store", MagicMock()),
        patch("app.main.settings") as mock_settings,
        patch("app.ingest_docs.DocsIngestion", return_value=mock_ingestor),
    ):
        mock_settings.docs_dir = "/tmp/docs"
        # Must not raise.
        _start_docs_ingest_background()

    time.sleep(0.2)


# ---------------------------------------------------------------------------
# _log_knowledge_store_status
# ---------------------------------------------------------------------------


def test_log_knowledge_store_status_logs_count(caplog):
    """When the store has documents, INFO is logged with the count."""
    import logging

    from app.main import _log_knowledge_store_status

    mock_store = MagicMock()
    mock_store.count.return_value = 12

    with patch("app.main._vector_store", mock_store), caplog.at_level(logging.INFO, logger="app.main"):
        _log_knowledge_store_status()

    assert any("12" in r.message for r in caplog.records)


def test_log_knowledge_store_status_warns_when_empty(caplog):
    """When the store is empty, a WARNING is emitted."""
    import logging

    from app.main import _log_knowledge_store_status

    mock_store = MagicMock()
    mock_store.count.return_value = 0

    with patch("app.main._vector_store", mock_store), caplog.at_level(logging.WARNING, logger="app.main"):
        _log_knowledge_store_status()

    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert any("EMPTY" in r.message for r in caplog.records)
