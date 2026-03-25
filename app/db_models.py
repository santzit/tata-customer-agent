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

    logger.info(
        "Tata entity schema ensured: users, accounts, inboxes, portals, "
        "portal_articles, portal_inboxes."
    )
