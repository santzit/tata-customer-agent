"""Tata agent database schema.

Two tables are managed here:

* **tata_accounts** — Chatwoot account connections.  Each row stores the
  base URL, numeric account ID, and the per-account API access token so that
  multiple Chatwoot accounts can be configured from the web UI without
  touching environment variables.

* **tata_settings** — General application settings (OpenAI key, model,
  database DSN override, etc.) stored as a typed key-value store.

Call :func:`ensure_schema` once at application startup.
"""

import json
import logging
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


def ensure_schema(dsn: str | None = None) -> None:
    """Create the tata_accounts and tata_settings tables if they do not exist.

    Args:
        dsn: Optional PostgreSQL DSN override.  Defaults to
             ``settings.postgres_dsn``.
    """
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            # ----------------------------------------------------------
            # tata_accounts — one row per Chatwoot account connection.
            #
            # api_token stores the Chatwoot API access token for this
            # account so that each connection has its own credentials.
            # ----------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tata_accounts (
                    id                   SERIAL PRIMARY KEY,
                    name                 TEXT        NOT NULL DEFAULT '',
                    chatwoot_base_url    TEXT        NOT NULL,
                    chatwoot_account_id  INTEGER     NOT NULL,
                    api_token            TEXT        NOT NULL DEFAULT '',
                    is_active            BOOLEAN     NOT NULL DEFAULT TRUE,
                    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS tata_accounts_url_acct_idx
                ON tata_accounts (chatwoot_base_url, chatwoot_account_id)
                """
            )

            # ----------------------------------------------------------
            # tata_settings — application-level key-value configuration.
            # ----------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tata_settings (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    logger.info("Tata schema ensured: tata_accounts, tata_settings.")


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------


def list_accounts(dsn: str | None = None) -> list[dict]:
    """Return all Chatwoot account connections ordered by id.

    The ``api_token`` field is included so the frontend can display whether a
    token is configured (the UI should never render the raw token value).
    """
    with _connection(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, name, chatwoot_base_url, chatwoot_account_id,
                       api_token, is_active, created_at, updated_at
                FROM tata_accounts
                ORDER BY id
                """
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_account(account_id: int, dsn: str | None = None) -> dict | None:
    """Return a single account row by primary key, or ``None``."""
    with _connection(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, name, chatwoot_base_url, chatwoot_account_id,
                       api_token, is_active, created_at, updated_at
                FROM tata_accounts WHERE id = %s
                """,
                (account_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def create_account(
    chatwoot_base_url: str,
    chatwoot_account_id: int,
    api_token: str,
    *,
    name: str = "",
    is_active: bool = True,
    dsn: str | None = None,
) -> dict:
    """Insert a new account connection and return the created row.

    Args:
        chatwoot_base_url: Base URL of the Chatwoot instance.
        chatwoot_account_id: Numeric account ID inside Chatwoot.
        api_token: API access token for this account.
        name: Optional human-readable label.
        is_active: Whether the account is currently active.
        dsn: Optional PostgreSQL DSN override.

    Returns:
        The newly created account dict.
    """
    with _connection(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO tata_accounts
                    (name, chatwoot_base_url, chatwoot_account_id, api_token, is_active)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, chatwoot_base_url, chatwoot_account_id,
                          api_token, is_active, created_at, updated_at
                """,
                (name, chatwoot_base_url.rstrip("/"), chatwoot_account_id, api_token, is_active),
            )
            row = cur.fetchone()
    return dict(row)


def update_account(
    account_id: int,
    *,
    name: str | None = None,
    chatwoot_base_url: str | None = None,
    chatwoot_account_id: int | None = None,
    api_token: str | None = None,
    is_active: bool | None = None,
    dsn: str | None = None,
) -> dict | None:
    """Update editable fields on an account and return the updated row.

    Only fields that are not ``None`` are written.  Returns ``None`` when no
    account with *account_id* exists.
    """
    fields: list[str] = ["updated_at = NOW()"]
    params: list[Any] = []

    if name is not None:
        fields.append("name = %s")
        params.append(name)
    if chatwoot_base_url is not None:
        fields.append("chatwoot_base_url = %s")
        params.append(chatwoot_base_url.rstrip("/"))
    if chatwoot_account_id is not None:
        fields.append("chatwoot_account_id = %s")
        params.append(chatwoot_account_id)
    if api_token is not None:
        fields.append("api_token = %s")
        params.append(api_token)
    if is_active is not None:
        fields.append("is_active = %s")
        params.append(is_active)

    params.append(account_id)
    with _connection(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE tata_accounts
                SET {', '.join(fields)}
                WHERE id = %s
                RETURNING id, name, chatwoot_base_url, chatwoot_account_id,
                          api_token, is_active, created_at, updated_at
                """,
                params,
            )
            row = cur.fetchone()
    return dict(row) if row else None


def delete_account(account_id: int, dsn: str | None = None) -> bool:
    """Delete an account by primary key.  Returns ``True`` if a row was deleted."""
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tata_accounts WHERE id = %s", (account_id,)
            )
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def get_setting(key: str, default: Any = None, dsn: str | None = None) -> Any:
    """Return the value for *key*, or *default* when not set."""
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM tata_settings WHERE key = %s", (key,)
            )
            row = cur.fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return row[0]


def set_setting(key: str, value: Any, dsn: str | None = None) -> None:
    """Upsert *key* → *value* in the settings table."""
    serialised = json.dumps(value) if not isinstance(value, str) else value
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tata_settings (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = NOW()
                """,
                (key, serialised),
            )


def get_all_settings(dsn: str | None = None) -> dict[str, Any]:
    """Return all settings as a ``{key: value}`` dict."""
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM tata_settings")
            rows = cur.fetchall()
    result: dict[str, Any] = {}
    for key, raw in rows:
        try:
            result[key] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            result[key] = raw
    return result


def set_many_settings(data: dict[str, Any], dsn: str | None = None) -> None:
    """Upsert multiple settings in a single transaction."""
    with _connection(dsn) as conn:
        with conn.cursor() as cur:
            for key, value in data.items():
                serialised = json.dumps(value) if not isinstance(value, str) else value
                cur.execute(
                    """
                    INSERT INTO tata_settings (key, value, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE
                        SET value = EXCLUDED.value,
                            updated_at = NOW()
                    """,
                    (key, serialised),
                )
