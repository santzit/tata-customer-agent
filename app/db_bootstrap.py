"""Boot-time database bootstrap.

On startup, :func:`ensure_database` uses *POSTGRES_MASTER_DSN* (a superuser
connection to the Postgres server) to:

1. Create the ``tata_agent`` database if it does not yet exist.
2. Enable the ``vector`` extension inside ``tata_agent``.

The target database name is extracted from *POSTGRES_DSN*.  If
*POSTGRES_MASTER_DSN* is empty the function is a no-op — the database is
assumed to already exist (e.g. when it is provisioned externally or by CI).
"""

import logging
import urllib.parse

import psycopg2
import psycopg2.extensions
import psycopg2.sql

from app.config import settings

logger = logging.getLogger(__name__)


def _db_name_from_dsn(dsn: str) -> str:
    """Return the database name component of a postgres DSN/URL."""
    parsed = urllib.parse.urlparse(dsn)
    # path is like "/tata_agent"
    return parsed.path.lstrip("/")


def ensure_database() -> None:
    """Create *tata_agent* (and the vector extension) if they do not exist.

    This function is idempotent: running it against an already-provisioned
    server is safe and has no effect.

    If :attr:`~app.config.Settings.postgres_master_dsn` is empty the call is
    a no-op so that deployments that pre-provision the database do not need
    the master credential.
    """
    master_dsn = settings.postgres_master_dsn
    if not master_dsn:
        logger.info(
            "POSTGRES_MASTER_DSN is not set — skipping automatic database creation."
        )
        return

    db_name = _db_name_from_dsn(settings.postgres_dsn)
    if not db_name:
        logger.warning(
            "Could not extract database name from POSTGRES_DSN=%r — skipping bootstrap.",
            settings.postgres_dsn,
        )
        return

    # -----------------------------------------------------------------------
    # Step 1: create the database using the master connection.
    # CREATE DATABASE cannot run inside a transaction, so we need
    # AUTOCOMMIT isolation level.
    # -----------------------------------------------------------------------
    try:
        conn = psycopg2.connect(master_dsn, connect_timeout=10)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
                )
                exists = cur.fetchone() is not None

            if not exists:
                logger.info(
                    "Database '%s' not found — creating it now.", db_name
                )
                with conn.cursor() as cur:
                    cur.execute(
                        psycopg2.sql.SQL("CREATE DATABASE {}").format(
                            psycopg2.sql.Identifier(db_name)
                        )
                    )
                logger.info("Database '%s' created successfully.", db_name)
            else:
                logger.debug("Database '%s' already exists.", db_name)
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(
            "Could not connect to master DSN for database bootstrap: %s", exc
        )
        return

    # -----------------------------------------------------------------------
    # Step 2: enable pgvector inside the target database.
    # (PgVectorStore.ensure_table also does this, but we do it here so that
    # the extension is available even before the vector store is initialised.)
    # -----------------------------------------------------------------------
    try:
        conn = psycopg2.connect(settings.postgres_dsn, connect_timeout=10)
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()
        finally:
            conn.close()
        logger.info("pgvector extension ensured in database '%s'.", db_name)
    except Exception as exc:
        logger.warning(
            "Could not enable pgvector extension in '%s': %s", db_name, exc
        )
