"""Shared pytest fixtures for the Tata agent test suite."""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import psycopg2
import pytest

# PostgreSQL DSN for the test database.  In CI this points at the
# pgvector service container; override locally via POSTGRES_DSN.
_PG_DSN = os.environ.get(
    "POSTGRES_DSN",
    "postgresql://postgres:postgres@localhost:5432/tata_agent",
)

# Dedicated test table names — distinct from production tables so tests
# never interfere with a live deployment sharing the same database.
_TEST_VECTOR_TABLE = "tata_knowledge_test"
_TEST_MEMORY_TABLE = "tata_conversations_test"


# ---------------------------------------------------------------------------
# Core DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    """Return the PostgreSQL DSN for the test database."""
    return _PG_DSN


@pytest.fixture(scope="session")
def pg_test_vector_table() -> str:
    """Return the pgvector table name used exclusively in tests."""
    return _TEST_VECTOR_TABLE


@pytest.fixture(scope="session")
def pg_test_memory_table() -> str:
    """Return the conversation memory table name used exclusively in tests."""
    return _TEST_MEMORY_TABLE


@pytest.fixture(scope="session")
def require_pg(pg_dsn: str) -> None:
    """Skip any test that declares this fixture when PostgreSQL is not reachable.

    In CI the pgvector service container is always present.  During offline
    local development without Docker, DB-dependent tests skip gracefully
    instead of failing with a connection error.
    """
    try:
        conn = psycopg2.connect(pg_dsn, connect_timeout=3)
        conn.close()
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")


# ---------------------------------------------------------------------------
# Schema bootstrap (runs once per session, before any test)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def ensure_pg_schema(
    pg_dsn: str,
    pg_test_vector_table: str,
    pg_test_memory_table: str,
) -> None:
    """Create the pgvector extension and test tables once for the whole session.

    Uses the real PostgreSQL/pgvector service so that integration tests interact
    with an actual database.  Completes silently when the DB is not reachable;
    individual tests that need the DB declare the ``require_pg`` fixture.
    """
    try:
        from app.conversation_memory import ConversationMemory
        from app.pg_vector_store import PgVectorStore

        # ensure_table() only runs DDL — no OpenAI embedding call is made.
        mock_openai = MagicMock()
        PgVectorStore(
            dsn=pg_dsn, table=pg_test_vector_table, openai_client=mock_openai
        ).ensure_table()
        ConversationMemory(dsn=pg_dsn, table=pg_test_memory_table).ensure_table()
    except Exception:
        pass  # DB not available; unit tests that mock psycopg2 are unaffected.
