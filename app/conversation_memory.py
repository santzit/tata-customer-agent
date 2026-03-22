"""PostgreSQL-backed conversation memory for multi-turn chat history.

Each conversation turn (user message + assistant reply) is stored as two rows
in a dedicated PostgreSQL table.  History is retrieved per-conversation with a
simple ``WHERE conversation_id = %s`` query ordered by timestamp — no vector
search is required.

Why PostgreSQL instead of a separate Qdrant service?
- Chatwoot already runs a Postgres/pgvector instance; no extra service needed.
- Relational storage is a natural fit for ordered, per-conversation history.
- Enables future SQL analytics (e.g. volume per conversation, resolution time).
"""

import logging
import time
from contextlib import contextmanager

import psycopg2

from app.config import settings

logger = logging.getLogger(__name__)


class ConversationMemory:
    """Stores and retrieves per-conversation message history in PostgreSQL."""

    def __init__(
        self,
        dsn: str | None = None,
        table: str | None = None,
    ) -> None:
        # Table name comes from trusted config, not user input.
        self._dsn = dsn or settings.postgres_dsn
        self._table = table or settings.pg_memory_table

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    @contextmanager
    def _connection(self):
        conn = psycopg2.connect(self._dsn)
        try:
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
        """Create the conversations table and index if they do not already exist."""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table} (
                        id             SERIAL PRIMARY KEY,
                        conversation_id INTEGER NOT NULL,
                        role           TEXT    NOT NULL,
                        content        TEXT    NOT NULL,
                        timestamp_ms   BIGINT  NOT NULL,
                        role_order     INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {self._table}_conv_ts_idx
                    ON {self._table} (conversation_id, timestamp_ms ASC, role_order ASC)
                    """
                )
        logger.info("Ensured conversation memory table '%s'", self._table)

    # keep the same method name used in main.py lifespan
    def ensure_collection(self) -> None:
        self.ensure_table()

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def add_turn(
        self,
        conversation_id: int,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        """Persist one conversation turn (user + assistant) to PostgreSQL.

        Args:
            conversation_id: Chatwoot conversation ID.
            user_message: The customer's message text.
            assistant_reply: Tata's generated reply text.
        """
        now_ms = int(time.time() * 1000)
        rows = [
            (conversation_id, "user",      user_message,    now_ms, 0),
            (conversation_id, "assistant", assistant_reply, now_ms, 1),
        ]
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    f"""
                    INSERT INTO {self._table}
                        (conversation_id, role, content, timestamp_ms, role_order)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    rows,
                )
        logger.debug(
            "Saved turn for conversation %d (%d chars user, %d chars reply)",
            conversation_id,
            len(user_message),
            len(assistant_reply),
        )

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get_history(
        self, conversation_id: int, max_turns: int | None = None
    ) -> list[dict[str, str]]:
        """Return recent messages for *conversation_id* as OpenAI chat messages.

        Args:
            conversation_id: Chatwoot conversation ID.
            max_turns: Maximum number of turns (user+assistant pairs) to return.
                       Defaults to ``settings.memory_max_turns``.

        Returns:
            A list of ``{"role": ..., "content": ...}`` dicts, oldest first,
            ready to be inserted into an OpenAI ``messages`` array.
        """
        limit = (max_turns or settings.memory_max_turns) * 2  # 2 messages per turn
        with self._connection() as conn:
            with conn.cursor() as cur:
                # Fetch the most recent *limit* rows, then flip to chronological order.
                cur.execute(
                    f"""
                    SELECT role, content FROM (
                        SELECT role, content, timestamp_ms, role_order
                        FROM {self._table}
                        WHERE conversation_id = %s
                        ORDER BY timestamp_ms DESC, role_order DESC
                        LIMIT %s
                    ) sub
                    ORDER BY timestamp_ms ASC, role_order ASC
                    """,
                    (conversation_id, limit),
                )
                rows = cur.fetchall()
        messages = [{"role": row[0], "content": row[1]} for row in rows]
        logger.debug(
            "Loaded %d history messages for conversation %d",
            len(messages),
            conversation_id,
        )
        return messages
