"""Tata agent database schema — SQLModel edition.

Two sets of tables are managed here:

**Chatwoot-mirrored entity tables**:
  users, accounts, inboxes, portals, portal_articles, portal_inboxes,
  conversations, messages (with send-status tracking + retry).

**Tata admin tables**:
  tata_accounts  — Chatwoot account connections (name, base_url, account_id).
                   Credentials are stored in tata_variables, not here.
  tata_variables — Unified env-var-style config store (Chatwoot, database,
                   OpenAI, agent settings). Each row has a key, value,
                   human-readable description, category tag, and a flag that
                   marks sensitive values so the API never returns their value
                   in plain text.

Call :func:`ensure_schema` once at application startup (after the database
itself has been created by :mod:`app.db_bootstrap`).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import sqlalchemy as sa
from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine (module-level singleton; created once, re-used across requests)
# ---------------------------------------------------------------------------

_engine: sa.engine.Engine | None = None


def _get_engine(dsn: str | None = None) -> sa.engine.Engine:
    """Return (and lazily create) the SQLAlchemy engine."""
    global _engine
    if _engine is None or dsn:
        url = dsn or settings.postgres_dsn
        _engine = create_engine(url, echo=False)
    return _engine


def _session(dsn: str | None = None) -> Session:
    """Return a new SQLModel ``Session`` bound to the configured engine."""
    return Session(_get_engine(dsn))


# ---------------------------------------------------------------------------
# SQLModel table definitions — Chatwoot-mirrored entities
# ---------------------------------------------------------------------------


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(sa_column=sa.Column(sa.Text, unique=True, nullable=False))
    display_name: str = Field(default="")
    role: str = Field(default="agent")
    availability_status: str = Field(default="online")
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


class AccountEntity(SQLModel, table=True):
    """Mirrors the Chatwoot *accounts* (tenants) table."""

    __tablename__ = "accounts"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    locale: str = Field(default="en")
    timezone: str = Field(default="UTC")
    status: str = Field(default="active")
    plan_name: str = Field(default="")
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


class Inbox(SQLModel, table=True):
    __tablename__ = "inboxes"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="accounts.id")
    name: str
    channel_type: str = Field(default="Channel::Api")
    enable_auto_assignment: bool = Field(default=False)
    working_hours_enabled: bool = Field(default=False)
    out_of_office_message: str = Field(default="")
    greeting_message: str = Field(default="")
    greeting_enabled: bool = Field(default=False)
    reply_time: str = Field(default="within_a_day")
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


class Portal(SQLModel, table=True):
    __tablename__ = "portals"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="accounts.id")
    name: str
    slug: str = Field(sa_column=sa.Column(sa.Text, unique=True, nullable=False))
    color: str = Field(default="")
    custom_domain: str = Field(default="")
    archived: bool = Field(default=False)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


class PortalArticle(SQLModel, table=True):
    __tablename__ = "portal_articles"
    __table_args__ = (
        sa.Index("portal_articles_portal_status_idx", "portal_id", "status"),
        {"extend_existing": True},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portal_id: int = Field(foreign_key="portals.id")
    title: str
    content: str = Field(default="")
    author_id: Optional[int] = Field(default=None, foreign_key="users.id")
    status: str = Field(default="draft")
    views: int = Field(default=0)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


class PortalInbox(SQLModel, table=True):
    __tablename__ = "portal_inboxes"
    __table_args__ = {"extend_existing": True}

    portal_id: int = Field(foreign_key="portals.id", primary_key=True)
    inbox_id: int = Field(foreign_key="inboxes.id", primary_key=True)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"
    __table_args__ = (
        sa.Index("conversations_chatwoot_id_idx", "chatwoot_id"),
        {"extend_existing": True},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    chatwoot_id: int = Field(sa_column=sa.Column(sa.Integer, unique=True, nullable=False))
    display_id: Optional[int] = Field(default=None)
    account_id: Optional[int] = Field(default=None, foreign_key="accounts.id")
    inbox_id: Optional[int] = Field(default=None, foreign_key="inboxes.id")
    status: str = Field(default="pending")
    assignee_id: Optional[int] = Field(default=None, foreign_key="users.id")
    meta: str = Field(
        default="{}",
        sa_column=sa.Column(sa.Text, server_default="'{}'"),
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


class Message(SQLModel, table=True):
    """Outgoing message with send-status tracking and retry scheduling."""

    __tablename__ = "messages"
    __table_args__ = (
        sa.Index(
            "messages_status_retry_idx",
            "status",
            "next_retry_at",
            postgresql_where=sa.text("status = 'failed'"),
        ),
        {"extend_existing": True},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    chatwoot_conv_id: int
    account_id: Optional[int] = Field(default=None, foreign_key="accounts.id")
    chatwoot_message_id: Optional[int] = Field(default=None)
    content: str
    message_type: str = Field(default="outgoing")
    private: bool = Field(default=False)
    status: str = Field(default="pending")
    send_attempts: int = Field(default=0)
    next_retry_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    error: Optional[str] = Field(default=None)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


# ---------------------------------------------------------------------------
# SQLModel table definitions — Tata admin tables
# ---------------------------------------------------------------------------


class TataAccount(SQLModel, table=True):
    """Chatwoot account connection configured via the web UI.

    Credentials (API token, base URL) are stored in ``tata_variables``,
    not on this model — this record only tracks the human-readable name,
    the numeric Chatwoot account ID, and the active/inactive flag.
    """

    __tablename__ = "tata_accounts"
    __table_args__ = (
        sa.UniqueConstraint(
            "chatwoot_account_id",
            name="tata_accounts_acct_idx",
        ),
        {"extend_existing": True},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(default="")
    chatwoot_account_id: int
    is_active: bool = Field(default=True)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


class TataVariable(SQLModel, table=True):
    """Unified configuration store that replaces environment variables.

    Each row represents one named configuration value (e.g. ``OPENAI_API_KEY``).
    Secret variables (``is_secret=True``) must never be returned in plain text
    by the API — return ``"***"`` or a boolean *is_set* flag instead.

    Categories: ``chatwoot`` | ``database`` | ``openai`` | ``agent``
    """

    __tablename__ = "tata_variables"
    __table_args__ = {"extend_existing": True}

    key: str = Field(primary_key=True)
    value: str = Field(default="")
    description: str = Field(default="")
    category: str = Field(default="")
    is_secret: bool = Field(default=False)
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


# ---------------------------------------------------------------------------
# Default variable definitions seeded at startup
# ---------------------------------------------------------------------------

#: Variables seeded the first time the schema is created (empty values).
_DEFAULT_VARIABLES: list[dict] = [
    # Chatwoot
    {
        "key": "CHATWOOT_BASE_URL",
        "description": "Chatwoot instance URL (e.g. https://app.chatwoot.com)",
        "category": "chatwoot",
        "is_secret": False,
    },
    {
        "key": "CHATWOOT_ACCOUNT_ID",
        "description": "Numeric Chatwoot account ID",
        "category": "chatwoot",
        "is_secret": False,
    },
    {
        "key": "CHATWOOT_API_TOKEN",
        "description": "Chatwoot API access token",
        "category": "chatwoot",
        "is_secret": True,
    },
    # Database
    {
        "key": "POSTGRES_HOST",
        "description": "PostgreSQL server hostname or IP",
        "category": "database",
        "is_secret": False,
        "default": "localhost",
    },
    {
        "key": "POSTGRES_PORT",
        "description": "PostgreSQL port (default: 5432)",
        "category": "database",
        "is_secret": False,
        "default": "5432",
    },
    {
        "key": "POSTGRES_USER",
        "description": "Database user",
        "category": "database",
        "is_secret": False,
        "default": "postgres",
    },
    {
        "key": "POSTGRES_PASSWORD",
        "description": "Database password",
        "category": "database",
        "is_secret": True,
    },
    {
        "key": "POSTGRES_DB",
        "description": "Database name",
        "category": "database",
        "is_secret": False,
        "default": "tata_agent",
    },
    # OpenAI
    {
        "key": "OPENAI_API_KEY",
        "description": "OpenAI API key (sk-...)",
        "category": "openai",
        "is_secret": True,
    },
    {
        "key": "OPENAI_MODEL",
        "description": "LLM model name (e.g. gpt-4.1, gpt-4o)",
        "category": "openai",
        "is_secret": False,
        "default": "gpt-4.1",
    },
    {
        "key": "OPENAI_PROVIDER",
        "description": "LLM provider: openai or azure",
        "category": "openai",
        "is_secret": False,
        "default": "openai",
    },
    {
        "key": "OPENAI_API_ENDPOINT",
        "description": "Azure OpenAI endpoint URL (leave blank for standard OpenAI)",
        "category": "openai",
        "is_secret": False,
    },
    {
        "key": "EMBEDDING_MODEL",
        "description": "Embedding model name",
        "category": "openai",
        "is_secret": False,
        "default": "text-embedding-3-small",
    },
    # Agent
    {
        "key": "RESPONSE_DELAY_SECONDS",
        "description": "Silence window in seconds before the agent replies (default: 120)",
        "category": "agent",
        "is_secret": False,
        "default": "120",
    },
    {
        "key": "WEBHOOK_TOKEN",
        "description": "Webhook security token (leave blank to disable verification)",
        "category": "agent",
        "is_secret": True,
    },
    {
        "key": "LOG_LEVEL",
        "description": "Logging verbosity: debug, info, warning, error",
        "category": "agent",
        "is_secret": False,
        "default": "info",
    },
]


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


def ensure_schema(dsn: str | None = None) -> None:
    """Create all entity tables if they do not already exist.

    Also seeds the ``tata_variables`` table with default variable definitions
    (empty values) the first time the application starts so the web UI
    immediately shows a complete settings form.

    Args:
        dsn: Optional override for the PostgreSQL DSN.  Defaults to
             ``settings.postgres_dsn``.
    """
    engine = _get_engine(dsn)
    SQLModel.metadata.create_all(engine)
    _seed_default_variables(dsn)
    logger.info(
        "Tata entity schema ensured via SQLModel: users, accounts, inboxes, "
        "portals, portal_articles, portal_inboxes, conversations, messages, "
        "tata_accounts, tata_variables."
    )


def _seed_default_variables(dsn: str | None = None) -> None:
    """Insert default variable definitions that do not yet exist."""
    with _session(dsn) as session:
        for defn in _DEFAULT_VARIABLES:
            key = defn["key"]
            existing = session.get(TataVariable, key)
            if existing is None:
                # Fall back to the env-var default value if provided
                default_value = defn.get("default", "")
                session.add(
                    TataVariable(
                        key=key,
                        value=default_value,
                        description=defn.get("description", ""),
                        category=defn.get("category", ""),
                        is_secret=defn.get("is_secret", False),
                    )
                )
        session.commit()


# ---------------------------------------------------------------------------
# Message persistence helpers
# ---------------------------------------------------------------------------

#: Maximum number of send attempts before a message is permanently failed.
MAX_SEND_ATTEMPTS = 5

#: Retry back-off in seconds per attempt.
_RETRY_DELAYS_SEC = [60, 120, 300, 600, 600]


def _get_retry_delay(attempts: int) -> int:
    """Return the back-off delay in seconds for the given attempt count."""
    idx = min(attempts - 1, len(_RETRY_DELAYS_SEC) - 1)
    return _RETRY_DELAYS_SEC[idx]


def _msg_to_dict(msg: Message) -> dict:
    return {
        "id": msg.id,
        "chatwoot_conv_id": msg.chatwoot_conv_id,
        "content": msg.content,
        "message_type": msg.message_type,
        "private": msg.private,
        "status": msg.status,
        "send_attempts": msg.send_attempts,
        "next_retry_at": msg.next_retry_at,
        "error": msg.error,
        "created_at": msg.created_at,
        "updated_at": msg.updated_at,
    }


def create_pending_message(
    chatwoot_conv_id: int,
    content: str,
    *,
    message_type: str = "outgoing",
    private: bool = False,
    dsn: str | None = None,
) -> int:
    """Insert a new message record with ``status='pending'`` and return its id."""
    msg = Message(
        chatwoot_conv_id=chatwoot_conv_id,
        content=content,
        message_type=message_type,
        private=private,
        status="pending",
    )
    with _session(dsn) as session:
        session.add(msg)
        session.commit()
        session.refresh(msg)
    return msg.id  # type: ignore[return-value]


def mark_message_sent(
    message_id: int,
    chatwoot_message_id: int,
    *,
    dsn: str | None = None,
) -> None:
    """Mark a message as successfully sent."""
    with _session(dsn) as session:
        msg = session.get(Message, message_id)
        if msg is None:
            logger.warning("mark_message_sent: message id=%d not found", message_id)
            return
        msg.chatwoot_message_id = chatwoot_message_id
        msg.status = "sent"
        msg.error = None
        msg.updated_at = datetime.utcnow()
        session.add(msg)
        session.commit()


def mark_message_failed(
    message_id: int,
    error: str,
    *,
    dsn: str | None = None,
) -> None:
    """Increment send_attempts and schedule a retry (or permanently fail)."""
    from datetime import timedelta

    with _session(dsn) as session:
        msg = session.get(Message, message_id)
        if msg is None:
            logger.warning("mark_message_failed: message id=%d not found", message_id)
            return
        attempts = (msg.send_attempts or 0) + 1
        msg.send_attempts = attempts
        msg.error = error[:500]
        msg.updated_at = datetime.utcnow()
        if attempts >= MAX_SEND_ATTEMPTS:
            msg.status = "failed"
            msg.next_retry_at = None
            logger.warning(
                "Message id=%d permanently failed after %d attempts: %s",
                message_id, attempts, error,
            )
        else:
            delay = _get_retry_delay(attempts)
            msg.status = "failed"
            msg.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
            logger.info(
                "Message id=%d failed (attempt %d/%d); retry in %ds: %s",
                message_id, attempts, MAX_SEND_ATTEMPTS, delay, error,
            )
        session.add(msg)
        session.commit()


def fetch_messages_due_for_retry(
    limit: int = 50,
    *,
    dsn: str | None = None,
) -> list[dict]:
    """Return up to *limit* failed messages whose ``next_retry_at`` is overdue."""
    now = datetime.utcnow()
    with _session(dsn) as session:
        stmt = (
            select(Message)
            .where(
                Message.status == "failed",
                Message.next_retry_at.is_not(None),  # type: ignore[union-attr]
                Message.next_retry_at <= now,
            )
            .order_by(Message.next_retry_at)
            .limit(limit)
        )
        rows = session.exec(stmt).all()
    return [_msg_to_dict(r) for r in rows]


def reset_message_to_pending(message_id: int, *, dsn: str | None = None) -> None:
    """Reset a message back to ``pending`` immediately before a retry attempt."""
    with _session(dsn) as session:
        msg = session.get(Message, message_id)
        if msg is None:
            return
        msg.status = "pending"
        msg.next_retry_at = None
        msg.updated_at = datetime.utcnow()
        session.add(msg)
        session.commit()


def list_recent_messages(limit: int = 10, *, dsn: str | None = None) -> list[dict]:
    """Return the most recent outgoing messages ordered newest-first."""
    with _session(dsn) as session:
        stmt = (
            select(Message)
            .order_by(Message.created_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        )
        rows = session.exec(stmt).all()
    return [_msg_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# tata_accounts helpers
# ---------------------------------------------------------------------------


def _acct_to_dict(acct: TataAccount) -> dict:
    return {
        "id": acct.id,
        "name": acct.name,
        "chatwoot_account_id": acct.chatwoot_account_id,
        "is_active": acct.is_active,
        "created_at": acct.created_at,
        "updated_at": acct.updated_at,
    }


def list_accounts(dsn: str | None = None) -> list[dict]:
    """Return all Chatwoot account connections ordered by id."""
    with _session(dsn) as session:
        stmt = select(TataAccount).order_by(TataAccount.id)
        rows = session.exec(stmt).all()
    return [_acct_to_dict(r) for r in rows]


def get_account(account_id: int, dsn: str | None = None) -> dict | None:
    """Return a single tata_accounts row by primary key, or ``None``."""
    with _session(dsn) as session:
        acct = session.get(TataAccount, account_id)
    return _acct_to_dict(acct) if acct else None


def create_account(
    chatwoot_account_id: int,
    *,
    name: str = "",
    is_active: bool = True,
    dsn: str | None = None,
) -> dict:
    """Insert a new tata_accounts row and return the created row."""
    acct = TataAccount(
        name=name,
        chatwoot_account_id=chatwoot_account_id,
        is_active=is_active,
    )
    with _session(dsn) as session:
        session.add(acct)
        session.commit()
        session.refresh(acct)
    return _acct_to_dict(acct)


def update_account(
    account_id: int,
    *,
    name: str | None = None,
    chatwoot_account_id: int | None = None,
    is_active: bool | None = None,
    dsn: str | None = None,
) -> dict | None:
    """Update editable fields on a tata_accounts row."""
    with _session(dsn) as session:
        acct = session.get(TataAccount, account_id)
        if acct is None:
            return None
        if name is not None:
            acct.name = name
        if chatwoot_account_id is not None:
            acct.chatwoot_account_id = chatwoot_account_id
        if is_active is not None:
            acct.is_active = is_active
        acct.updated_at = datetime.utcnow()
        session.add(acct)
        session.commit()
        session.refresh(acct)
    return _acct_to_dict(acct)


def delete_account(account_id: int, dsn: str | None = None) -> bool:
    """Delete a tata_accounts row by primary key.  Returns ``True`` if deleted."""
    with _session(dsn) as session:
        acct = session.get(TataAccount, account_id)
        if acct is None:
            return False
        session.delete(acct)
        session.commit()
    return True


# ---------------------------------------------------------------------------
# tata_variables helpers
# ---------------------------------------------------------------------------


def _var_to_dict(var: TataVariable, *, mask_secrets: bool = True) -> dict:
    """Convert a TataVariable row to a plain dict.

    When *mask_secrets* is ``True`` (the default), secret values are replaced
    by ``"***"`` if set, or an empty string if unset.
    """
    value = var.value
    if mask_secrets and var.is_secret and value:
        value = "***"
    return {
        "key": var.key,
        "value": value,
        "description": var.description,
        "category": var.category,
        "is_secret": var.is_secret,
        "is_set": bool(var.value),
        "updated_at": var.updated_at,
    }


def list_variables(
    category: str | None = None,
    *,
    mask_secrets: bool = True,
    dsn: str | None = None,
) -> list[dict]:
    """Return all configuration variables, optionally filtered by *category*.

    Secret values are masked unless *mask_secrets* is ``False``.
    """
    with _session(dsn) as session:
        stmt = select(TataVariable).order_by(TataVariable.category, TataVariable.key)
        if category:
            stmt = stmt.where(TataVariable.category == category)
        rows = session.exec(stmt).all()
    return [_var_to_dict(r, mask_secrets=mask_secrets) for r in rows]


def get_variable(key: str, *, dsn: str | None = None) -> TataVariable | None:
    """Return the raw TataVariable row for *key*, or ``None``."""
    with _session(dsn) as session:
        return session.get(TataVariable, key)


def get_variable_value(key: str, default: str = "", *, dsn: str | None = None) -> str:
    """Return the plain-text value for *key*, or *default* if not set."""
    with _session(dsn) as session:
        row = session.get(TataVariable, key)
    return row.value if (row and row.value) else default


def set_variable(key: str, value: str, *, dsn: str | None = None) -> None:
    """Upsert a single variable value.

    If the key is not already defined in the schema, it is created as a
    generic, non-secret variable with no category.
    """
    with _session(dsn) as session:
        row = session.get(TataVariable, key)
        if row is None:
            row = TataVariable(key=key, value=value)
        else:
            row.value = value
            row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()


def set_many_variables(data: dict[str, str], *, dsn: str | None = None) -> None:
    """Upsert multiple variable values in a single transaction."""
    with _session(dsn) as session:
        for key, value in data.items():
            row = session.get(TataVariable, key)
            if row is None:
                row = TataVariable(key=key, value=value)
            else:
                row.value = value
                row.updated_at = datetime.utcnow()
            session.add(row)
        session.commit()


# ---------------------------------------------------------------------------
# Backward-compat setting helpers (used by settings.py router)
# ---------------------------------------------------------------------------
#
# These thin wrappers map the old lowercase setting keys used by the app
# internals to the UPPERCASE variable keys in tata_variables.  New code
# should call get_variable_value / set_variable / set_many_variables directly.
#
# Mapping (old internal key → tata_variables key):
#   openai_api_key           → OPENAI_API_KEY
#   llm_model                → OPENAI_MODEL
#   llm_provider             → OPENAI_PROVIDER
#   openai_api_endpoint      → OPENAI_API_ENDPOINT
#   embedding_model          → EMBEDDING_MODEL
#   embedding_dimension      → (stored as str in EMBEDDING_DIMENSION var)
#   response_delay_seconds   → RESPONSE_DELAY_SECONDS
#   webhook_token            → WEBHOOK_TOKEN
#   log_level                → LOG_LEVEL

_SETTING_KEY_MAP: dict[str, str] = {
    "openai_api_key": "OPENAI_API_KEY",
    "llm_model": "OPENAI_MODEL",
    "llm_provider": "OPENAI_PROVIDER",
    "openai_api_endpoint": "OPENAI_API_ENDPOINT",
    "embedding_model": "EMBEDDING_MODEL",
    "embedding_dimension": "EMBEDDING_DIMENSION",
    "response_delay_seconds": "RESPONSE_DELAY_SECONDS",
    "webhook_token": "WEBHOOK_TOKEN",
    "log_level": "LOG_LEVEL",
}


def get_setting(key: str, default: Any = None, dsn: str | None = None) -> Any:
    """Return the value for *key* from tata_variables.

    Translates lowercase internal keys via ``_SETTING_KEY_MAP``.  Falls back
    to *default* when the variable is not set.
    """
    var_key = _SETTING_KEY_MAP.get(key, key.upper())
    raw = get_variable_value(var_key, default="", dsn=dsn)
    if not raw:
        return default
    # Try to coerce to original type if default provides a hint.
    if default is not None and not isinstance(default, str):
        try:
            if isinstance(default, bool):
                return raw.lower() in ("1", "true", "yes")
            return type(default)(raw)
        except (ValueError, TypeError):
            pass
    return raw


def set_setting(key: str, value: Any, dsn: str | None = None) -> None:
    """Upsert *key* → *value* using the internal key mapping."""
    var_key = _SETTING_KEY_MAP.get(key, key.upper())
    set_variable(var_key, str(value) if value is not None else "", dsn=dsn)


def get_all_settings(dsn: str | None = None) -> dict[str, Any]:
    """Return all settings as ``{internal_key: value}`` using the key mapping."""
    reverse_map = {v: k for k, v in _SETTING_KEY_MAP.items()}
    rows = list_variables(mask_secrets=False, dsn=dsn)
    result: dict[str, Any] = {}
    for row in rows:
        internal_key = reverse_map.get(row["key"], row["key"].lower())
        result[internal_key] = row["value"]
    return result


def set_many_settings(data: dict[str, Any], dsn: str | None = None) -> None:
    """Upsert multiple settings using the internal key mapping."""
    mapped = {
        _SETTING_KEY_MAP.get(k, k.upper()): (str(v) if v is not None else "")
        for k, v in data.items()
    }
    set_many_variables(mapped, dsn=dsn)
