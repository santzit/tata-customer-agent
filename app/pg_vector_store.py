"""PostgreSQL + pgvector knowledge store for retrieval-augmented generation (RAG).

Uses the same Postgres instance that Chatwoot already runs, so no extra
service is needed.  Documents are stored in a table with a ``vector(1536)``
column and retrieved via cosine-distance nearest-neighbour search using the
``<=>`` operator provided by the pgvector extension.
"""

import logging
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector

from app.config import settings

logger = logging.getLogger(__name__)


class PgVectorStore:
    """Manages the pgvector table and cosine-similarity search."""

    def __init__(
        self,
        dsn: str | None = None,
        table: str | None = None,
        openai_client: Any | None = None,
        embedding_model: str | None = None,
        vector_size: int | None = None,
    ) -> None:
        # Table name comes from trusted config, not user input.
        self._dsn = dsn or settings.postgres_dsn
        self._table = table or settings.pg_vector_table
        self._openai = openai_client or settings.make_openai_client()
        self._embedding_model = embedding_model or settings.embedding_model_small
        self._vector_size = vector_size or settings.embedding_dimension

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    @contextmanager
    def _connection(self):
        conn = psycopg2.connect(self._dsn)
        try:
            register_vector(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def ensure_table(self) -> None:
        """Create the pgvector table and index if they do not already exist."""
        # Phase 1: bootstrap the extension using a plain psycopg2 connection.
        # register_vector() (called inside _connection()) requires the vector
        # type to already exist in the database, so we must CREATE EXTENSION
        # before opening a register_vector()-aware connection.
        conn = psycopg2.connect(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()
        finally:
            conn.close()

        # Phase 2: now that the extension is present, register_vector works.
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table} (
                        id TEXT PRIMARY KEY,
                        text TEXT NOT NULL,
                        embedding vector({self._vector_size}),
                        metadata JSONB DEFAULT '{{}}'
                    )
                    """
                )
                # Use HNSW instead of IVFFlat:
                # - HNSW is an incremental online index that works correctly
                #   even when the index is created before any rows are inserted.
                # - IVFFlat requires the centroids to be computed from existing
                #   data; an index created on an empty table has no centroids and
                #   can miss results for small datasets.
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {self._table}_embedding_idx
                    ON {self._table} USING hnsw (embedding vector_cosine_ops)
                    """
                )
        logger.info("Ensured pgvector table '%s'", self._table)

    # keep the same method name used in main.py lifespan
    def ensure_collection(self) -> None:
        self.ensure_table()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list[float]:
        response = self._openai.embeddings.create(
            model=self._embedding_model,
            input=text,
        )
        return response.data[0].embedding

    def upsert(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        """Embed *text* and upsert it into the table.

        Args:
            doc_id: Unique string identifier for the document.
            text: The raw text to embed.
            metadata: Optional JSON payload stored alongside the vector.
        """
        vector = self._embed(text)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self._table} (id, text, embedding, metadata)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET text      = EXCLUDED.text,
                            embedding = EXCLUDED.embedding,
                            metadata  = EXCLUDED.metadata
                    """,
                    (doc_id, text, vector, psycopg2.extras.Json(metadata or {})),
                )
        logger.debug("Upserted document '%s' into '%s'", doc_id, self._table)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the number of documents currently indexed in the knowledge store.

        Returns ``-1`` when the table does not yet exist or the database is
        unreachable (so callers can distinguish "unknown" from "zero").
        """
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM {self._table}")
                    result = cur.fetchone()
                    return int(result[0]) if result else 0
        except Exception as exc:
            logger.debug("count() failed for table %r: %s", self._table, exc)
            return -1

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return the *top_k* most relevant knowledge snippets for *query*.

        Uses cosine distance (``<=>`` operator) for nearest-neighbour search.

        Returns:
            A list of payload dicts, each containing at least a ``"text"`` key.
        """
        vector = self._embed(query)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT text, metadata
                    FROM {self._table}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vector, top_k),
                )
                rows = cur.fetchall()
        return [{**(row[1] or {}), "text": row[0]} for row in rows]
