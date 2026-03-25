"""Tata-owned database entity schema — mirrors the key Chatwoot entities.

All tables are created here (in our own ``tata_agent`` database) so that the
agent is completely independent of the Chatwoot database.

Entities
--------
* **users** — agents / support staff (mirrors Chatwoot ``users``).
* **accounts** — organisations / tenants (mirrors Chatwoot ``accounts``).
* **inboxes** — communication channels within an account
  (mirrors Chatwoot ``inboxes``).
* **portals** — Help Center portals belonging to an account
  (mirrors Chatwoot ``portals``).
* **portal_articles** — knowledge-base articles inside a portal
  (mirrors Chatwoot ``portal_articles``).
* **portal_inboxes** — many-to-many join between portals and inboxes so that
  the RAG pipeline can narrow knowledge retrieval to the inbox that received
  the customer message.
* **conversations** — customer conversations (mirrors Chatwoot ``conversations``).
* **messages** — individual messages with send-status tracking and automatic
  retry on failure (mirrors Chatwoot ``messages``).

Call :func:`ensure_schema` once at application startup (after the database
itself has been created by :mod:`app.db_bootstrap`).
"""

import logging
from contextlib import contextmanager

import psycopg2

from app.config import settings

logger = logging.getLogger(__name__)


@contextmanager
def _connection(dsn: str | None = None):
    conn = psycopg2.connect(dsn or settings.postgres_dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(dsn: str | None = None) -> None:
    """Create all entity tables and indexes if they do not already exist.

    Args:
        dsn: Optional override for the PostgreSQL DSN.  Defaults to
             ``settings.postgres_dsn``.
    """
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            # ----------------------------------------------------------
            # users (agents / support staff)
            # ----------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id                  SERIAL PRIMARY KEY,
                    name                TEXT        NOT NULL,
                    email               TEXT        NOT NULL UNIQUE,
                    display_name        TEXT        NOT NULL DEFAULT '',
                    role                TEXT        NOT NULL DEFAULT 'agent',
                    availability_status TEXT        NOT NULL DEFAULT 'online',
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            # ----------------------------------------------------------
            # accounts (organisations / tenants)
            # ----------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id           SERIAL PRIMARY KEY,
                    name         TEXT        NOT NULL,
                    locale       VARCHAR(10) NOT NULL DEFAULT 'en',
                    timezone     TEXT        NOT NULL DEFAULT 'UTC',
                    status       TEXT        NOT NULL DEFAULT 'active',
                    plan_name    TEXT        NOT NULL DEFAULT '',
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            # ----------------------------------------------------------
            # inboxes (communication channels)
            # ----------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS inboxes (
                    id                      SERIAL PRIMARY KEY,
                    account_id              INTEGER     NOT NULL REFERENCES accounts(id),
                    name                    TEXT        NOT NULL,
                    channel_type            TEXT        NOT NULL DEFAULT 'Channel::Api',
                    enable_auto_assignment  BOOLEAN     NOT NULL DEFAULT FALSE,
                    working_hours_enabled   BOOLEAN     NOT NULL DEFAULT FALSE,
                    out_of_office_message   TEXT        NOT NULL DEFAULT '',
                    greeting_message        TEXT        NOT NULL DEFAULT '',
                    greeting_enabled        BOOLEAN     NOT NULL DEFAULT FALSE,
                    reply_time              TEXT        NOT NULL DEFAULT 'within_a_day',
                    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            # ----------------------------------------------------------
            # portals (Help Center portals)
            # ----------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS portals (
                    id            SERIAL PRIMARY KEY,
                    account_id    INTEGER     NOT NULL REFERENCES accounts(id),
                    name          TEXT        NOT NULL,
                    slug          TEXT        NOT NULL UNIQUE,
                    color         TEXT        NOT NULL DEFAULT '',
                    custom_domain TEXT        NOT NULL DEFAULT '',
                    archived      BOOLEAN     NOT NULL DEFAULT FALSE,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            # ----------------------------------------------------------
            # portal_articles (knowledge-base articles)
            # ----------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS portal_articles (
                    id          SERIAL PRIMARY KEY,
                    portal_id   INTEGER     NOT NULL REFERENCES portals(id),
                    title       TEXT        NOT NULL,
                    content     TEXT        NOT NULL DEFAULT '',
                    author_id   INTEGER     REFERENCES users(id),
                    status      TEXT        NOT NULL DEFAULT 'draft',
                    views       INTEGER     NOT NULL DEFAULT 0,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            # Index for efficient lookup of published articles per portal.
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS portal_articles_portal_status_idx
                ON portal_articles (portal_id, status)
                """
            )

            # ----------------------------------------------------------
            # portal_inboxes (many-to-many join)
            # ----------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS portal_inboxes (
                    portal_id   INTEGER NOT NULL REFERENCES portals(id),
                    inbox_id    INTEGER NOT NULL REFERENCES inboxes(id),
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (portal_id, inbox_id)
                )
                """
            )

            # ----------------------------------------------------------
            # conversations (mirrors Chatwoot conversations)
            # ----------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id              SERIAL PRIMARY KEY,
                    chatwoot_id     INTEGER     NOT NULL UNIQUE,
                    display_id      INTEGER,
                    account_id      INTEGER     REFERENCES accounts(id),
                    inbox_id        INTEGER     REFERENCES inboxes(id),
                    status          TEXT        NOT NULL DEFAULT 'pending',
                    assignee_id     INTEGER     REFERENCES users(id),
                    meta            JSONB       NOT NULL DEFAULT '{}',
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS conversations_chatwoot_id_idx
                ON conversations (chatwoot_id)
                """
            )

            # ----------------------------------------------------------
            # messages (mirrors Chatwoot messages, with send-status tracking)
            #
            # status values:
            #   pending  — queued, not yet sent to Chatwoot
            #   sent     — successfully delivered to Chatwoot API
            #   failed   — send failed; will be retried up to MAX_SEND_ATTEMPTS
            # ----------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id                  SERIAL PRIMARY KEY,
                    chatwoot_conv_id    INTEGER     NOT NULL,
                    account_id          INTEGER     REFERENCES accounts(id),
                    chatwoot_message_id INTEGER,
                    content             TEXT        NOT NULL,
                    message_type        TEXT        NOT NULL DEFAULT 'outgoing',
                    private             BOOLEAN     NOT NULL DEFAULT FALSE,
                    status              TEXT        NOT NULL DEFAULT 'pending',
                    send_attempts       INTEGER     NOT NULL DEFAULT 0,
                    next_retry_at       TIMESTAMPTZ,
                    error               TEXT,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS messages_status_retry_idx
                ON messages (status, next_retry_at)
                WHERE status = 'failed'
                """
            )

    logger.info(
        "Tata entity schema ensured: users, accounts, inboxes, portals, "
        "portal_articles, portal_inboxes, conversations, messages."
    )

# ---------------------------------------------------------------------------
# Message persistence helpers
# ---------------------------------------------------------------------------

#: Maximum number of send attempts before a message is permanently failed.
MAX_SEND_ATTEMPTS = 5

#: Retry back-off in seconds per attempt.  The last value is reused for any
#: attempt beyond ``len(_RETRY_DELAYS_SEC)``.
_RETRY_DELAYS_SEC = [60, 120, 300, 600, 600]


def _get_retry_delay(attempts: int) -> int:
    """Return the back-off delay in seconds for the given attempt count."""
    idx = min(attempts - 1, len(_RETRY_DELAYS_SEC) - 1)
    return _RETRY_DELAYS_SEC[idx]


def create_pending_message(
    chatwoot_conv_id: int,
    content: str,
    *,
    message_type: str = "outgoing",
    private: bool = False,
    dsn: str | None = None,
) -> int:
    """Insert a new message record with ``status='pending'`` and return its id.

    Args:
        chatwoot_conv_id: The Chatwoot conversation id from the webhook payload.
        content: Message text content.
        message_type: ``"outgoing"`` for agent replies visible to contacts.
        private: When ``True`` the message is a private note.
        dsn: Optional override for the PostgreSQL DSN.

    Returns:
        The internal ``messages.id`` primary key.
    """
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages
                    (chatwoot_conv_id, content, message_type, private, status)
                VALUES (%s, %s, %s, %s, 'pending')
                RETURNING id
                """,
                (chatwoot_conv_id, content, message_type, private),
            )
            row = cur.fetchone()
    return row[0]


def mark_message_sent(
    message_id: int,
    chatwoot_message_id: int,
    *,
    dsn: str | None = None,
) -> None:
    """Mark a message as successfully sent.

    Args:
        message_id: The ``messages.id`` primary key.
        chatwoot_message_id: The id returned by the Chatwoot API.
        dsn: Optional override for the PostgreSQL DSN.
    """
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE messages
                SET status = 'sent',
                    chatwoot_message_id = %s,
                    error = NULL,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (chatwoot_message_id, message_id),
            )


def mark_message_failed(
    message_id: int,
    error: str,
    *,
    dsn: str | None = None,
) -> None:
    """Increment send_attempts and schedule a retry (or permanently fail).

    If ``send_attempts`` reaches ``MAX_SEND_ATTEMPTS`` the status is set to
    ``'failed'`` with no ``next_retry_at`` so the record is excluded from
    future retry queries.

    Args:
        message_id: The ``messages.id`` primary key.
        error: Human-readable error description.
        dsn: Optional override for the PostgreSQL DSN.
    """
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            # Fetch current attempt count.
            cur.execute(
                "SELECT send_attempts FROM messages WHERE id = %s", (message_id,)
            )
            row = cur.fetchone()
            if row is None:
                logger.warning("mark_message_failed: message id=%d not found", message_id)
                return
            attempts = row[0] + 1
            if attempts >= MAX_SEND_ATTEMPTS:
                # Permanently failed — no more retries.
                cur.execute(
                    """
                    UPDATE messages
                    SET status = 'failed',
                        send_attempts = %s,
                        next_retry_at = NULL,
                        error = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (attempts, error[:500], message_id),
                )
                logger.warning(
                    "Message id=%d permanently failed after %d attempts: %s",
                    message_id,
                    attempts,
                    error,
                )
            else:
                delay = _get_retry_delay(attempts)
                cur.execute(
                    """
                    UPDATE messages
                    SET status = 'failed',
                        send_attempts = %s,
                        next_retry_at = NOW() + (%s || ' seconds')::INTERVAL,
                        error = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (attempts, delay, error[:500], message_id),
                )
                logger.info(
                    "Message id=%d failed (attempt %d/%d); retry in %ds: %s",
                    message_id,
                    attempts,
                    MAX_SEND_ATTEMPTS,
                    delay,
                    error,
                )


def fetch_messages_due_for_retry(
    limit: int = 50,
    *,
    dsn: str | None = None,
) -> list[dict]:
    """Return up to *limit* failed messages whose ``next_retry_at`` is overdue.

    Args:
        limit: Maximum number of rows to return.
        dsn: Optional override for the PostgreSQL DSN.

    Returns:
        A list of dicts with keys: ``id``, ``chatwoot_conv_id``, ``content``,
        ``message_type``, ``private``, ``send_attempts``.
    """
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, chatwoot_conv_id, content, message_type, private, send_attempts
                FROM messages
                WHERE status = 'failed'
                  AND next_retry_at IS NOT NULL
                  AND next_retry_at <= NOW()
                ORDER BY next_retry_at
                LIMIT %s
                """,
                (limit,),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def reset_message_to_pending(message_id: int, *, dsn: str | None = None) -> None:
    """Reset a message back to ``pending`` immediately before a retry attempt.

    Args:
        message_id: The ``messages.id`` primary key.
        dsn: Optional override for the PostgreSQL DSN.
    """
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE messages
                SET status = 'pending',
                    next_retry_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (message_id,),
            )
