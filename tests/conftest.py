"""Shared pytest fixtures for the Tata agent test suite.

A ``.env`` file in the project root is loaded automatically at session start
so that local credentials (OPENAI_API_KEY, POSTGRES_DSN, etc.) are available
without exporting them by hand.  CI injects the same variables via GitHub
Actions secrets/variables, so no ``.env`` file is needed there.
"""
from __future__ import annotations

import os
import pathlib

import psycopg2
import pytest
from dotenv import load_dotenv

# Load .env from the repo root (ignored by git, created by each developer).
# Variables already set in the environment take precedence (CI secrets win).
load_dotenv(pathlib.Path(__file__).parent.parent / ".env", override=False)

# PostgreSQL DSN for the test database.  In CI this points at the
# pgvector service container; override locally via POSTGRES_DSN or .env.
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
    """Fail any test that declares this fixture when PostgreSQL is not reachable.

    CI and local runs are expected to provide pgvector. DB-dependent tests must
    run against a real Postgres instance instead of skipping silently.
    """
    try:
        conn = psycopg2.connect(pg_dsn, connect_timeout=3)
        conn.close()
    except Exception as exc:
        pytest.fail(
            "PostgreSQL not reachable. Start pgvector/pg16 and set POSTGRES_DSN. "
            f"Error: {exc}"
        )


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

    Also truncates both tables so every session starts with a clean slate,
    preventing stale rows from a previous run from causing assertion failures.
    """
    try:
        conn = psycopg2.connect(pg_dsn, connect_timeout=3)
        conn.close()
    except Exception:
        return  # DB not available; pure unit tests are unaffected.

    from app.conversation_memory import ConversationMemory
    from app.db_models import ensure_schema
    from app.pg_vector_store import PgVectorStore

    ensure_schema(pg_dsn)
    PgVectorStore(dsn=pg_dsn, table=pg_test_vector_table).ensure_table()
    ConversationMemory(dsn=pg_dsn, table=pg_test_memory_table).ensure_table()

    conn = psycopg2.connect(pg_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {pg_test_vector_table} RESTART IDENTITY")
            cur.execute(f"TRUNCATE TABLE {pg_test_memory_table} RESTART IDENTITY")
        conn.commit()
    finally:
        conn.close()
