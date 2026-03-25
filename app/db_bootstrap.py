"""Boot-time database bootstrap.

On startup, :func:`ensure_database` uses *POSTGRES_USER* and
*POSTGRES_PASSWORD* (the same credentials used by the Postgres Docker
container) to connect to the maintenance ``postgres`` database and:

1. Create the ``tata_agent`` database if it does not yet exist.
2. Enable the ``vector`` extension inside ``tata_agent``.

The host, port, and SSL parameters are derived from *POSTGRES_DSN* so there
is a single source of truth for the server address.  If *POSTGRES_USER* or
*POSTGRES_PASSWORD* is empty the function is a no-op — the database is
assumed to already exist (e.g. when it is provisioned externally or by CI).
"""

import logging
import urllib.parse

import psycopg2
import psycopg2.extensions
import psycopg2.sql

from app.config import settings

logger = logging.getLogger(__name__)


def _build_master_dsn(postgres_dsn: str, user: str, password: str) -> str | None:
    """Build a superuser DSN targeting the maintenance ``postgres`` database.

    Takes the host / port / SSL options from *postgres_dsn* and substitutes
    the *user*, *password*, and database name (fixed to ``postgres``).

    Returns ``None`` if the DSN cannot be parsed (missing hostname).
    """
    parsed = urllib.parse.urlparse(postgres_dsn)
    if not parsed.hostname:
        return None
    # Keep query string (e.g. sslmode) but swap everything else.
    master = parsed._replace(
        scheme="postgresql",
        netloc=f"{urllib.parse.quote(user, safe='')}:{urllib.parse.quote(password, safe='')}@{parsed.hostname}:{parsed.port or 5432}",
        path="/postgres",
    )
    return urllib.parse.urlunparse(master)


def _db_name_from_dsn(dsn: str) -> str:
    """Return the database name component of a postgres DSN/URL."""
    parsed = urllib.parse.urlparse(dsn)
    # path is like "/tata_agent"
    return parsed.path.lstrip("/")


def ensure_database() -> None:
    """Create *tata_agent* (and the vector extension) if they do not exist.

    This function is idempotent: running it against an already-provisioned
    server is safe and has no effect.

    If :attr:`~app.config.Settings.postgres_user` or
    :attr:`~app.config.Settings.postgres_password` is empty the call is
    a no-op so that deployments that pre-provision the database do not need
    the superuser credentials.
    """
    user = settings.postgres_user
    password = settings.postgres_password

    if not user or not password:
        logger.info(
            "POSTGRES_USER / POSTGRES_PASSWORD not set — skipping automatic database creation."
        )
        return

    db_name = _db_name_from_dsn(settings.postgres_dsn)
    if not db_name:
        logger.warning(
            "Could not extract database name from POSTGRES_DSN=%r — skipping bootstrap.",
            settings.postgres_dsn,
        )
        return

    master_dsn = _build_master_dsn(settings.postgres_dsn, user, password)
    if not master_dsn:
        logger.warning(
            "Could not parse host from POSTGRES_DSN=%r — skipping bootstrap.",
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
            "Could not connect as superuser to create database: %s", exc
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

