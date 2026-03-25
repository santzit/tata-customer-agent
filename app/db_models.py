"""Tata agent database schema — SQLModel edition.

Two sets of tables are managed here:

**Chatwoot-mirrored entity tables**:
  users, accounts, inboxes, portals, portal_articles, portal_inboxes,
  conversations, messages (with send-status tracking + retry).

**Tata admin tables**:
  tata_accounts — Chatwoot account connections configured via the web UI.
  tata_settings — general application settings (key-value store).

Call :func:`ensure_schema` once at application startup (after the database
itself has been created by :mod:`app.db_bootstrap`).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

import sqlalchemy as sa
from sqlmodel import Field, Session, SQLModel, create_engine, select, text

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
# SQLModel table definitions
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


class TataAccount(SQLModel, table=True):
    """Chatwoot account connection configured via the web UI."""

    __tablename__ = "tata_accounts"
    __table_args__ = (
        sa.UniqueConstraint(
            "chatwoot_base_url",
            "chatwoot_account_id",
            name="tata_accounts_url_acct_idx",
        ),
        {"extend_existing": True},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(default="")
    chatwoot_base_url: str
    chatwoot_account_id: int
    api_token: str = Field(default="")
    is_active: bool = Field(default=True)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


class TataSetting(SQLModel, table=True):
    """General application settings stored as a key-value store."""

    __tablename__ = "tata_settings"
    __table_args__ = {"extend_existing": True}

    key: str = Field(primary_key=True)
    value: str
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


def ensure_schema(dsn: str | None = None) -> None:
    """Create all entity tables if they do not already exist.

    Uses SQLModel's ``metadata.create_all`` so each table is created only when
    missing — existing tables (and their data) are never touched.

    Args:
        dsn: Optional override for the PostgreSQL DSN.  Defaults to
             ``settings.postgres_dsn``.
    """
    engine = _get_engine(dsn)
    SQLModel.metadata.create_all(engine)
    logger.info(
        "Tata entity schema ensured via SQLModel: users, accounts, inboxes, "
        "portals, portal_articles, portal_inboxes, conversations, messages, "
        "tata_accounts, tata_settings."
    )


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
    """Return the most recent outgoing messages ordered newest-first.

    Args:
        limit: Maximum number of rows to return.
        dsn: Optional override for the PostgreSQL DSN.
    """
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
        "chatwoot_base_url": acct.chatwoot_base_url,
        "chatwoot_account_id": acct.chatwoot_account_id,
        "api_token": acct.api_token,
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
    chatwoot_base_url: str,
    chatwoot_account_id: int,
    api_token: str,
    *,
    name: str = "",
    is_active: bool = True,
    dsn: str | None = None,
) -> dict:
    """Insert a new tata_accounts row and return the created row."""
    acct = TataAccount(
        name=name,
        chatwoot_base_url=chatwoot_base_url.rstrip("/"),
        chatwoot_account_id=chatwoot_account_id,
        api_token=api_token,
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
    chatwoot_base_url: str | None = None,
    chatwoot_account_id: int | None = None,
    api_token: str | None = None,
    is_active: bool | None = None,
    dsn: str | None = None,
) -> dict | None:
    """Update editable fields on a tata_accounts row.

    Only fields that are not ``None`` are written.  Returns ``None`` when no
    account with *account_id* exists.
    """
    with _session(dsn) as session:
        acct = session.get(TataAccount, account_id)
        if acct is None:
            return None
        if name is not None:
            acct.name = name
        if chatwoot_base_url is not None:
            acct.chatwoot_base_url = chatwoot_base_url.rstrip("/")
        if chatwoot_account_id is not None:
            acct.chatwoot_account_id = chatwoot_account_id
        if api_token is not None:
            acct.api_token = api_token
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
# tata_settings helpers
# ---------------------------------------------------------------------------


def get_setting(key: str, default: Any = None, dsn: str | None = None) -> Any:
    """Return the value for *key*, or *default* when not set."""
    with _session(dsn) as session:
        row = session.get(TataSetting, key)
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return row.value


def set_setting(key: str, value: Any, dsn: str | None = None) -> None:
    """Upsert *key* → *value* in tata_settings."""
    serialised = json.dumps(value) if not isinstance(value, str) else value
    with _session(dsn) as session:
        row = session.get(TataSetting, key)
        if row is None:
            row = TataSetting(key=key, value=serialised)
        else:
            row.value = serialised
            row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()


def get_all_settings(dsn: str | None = None) -> dict[str, Any]:
    """Return all settings as a ``{key: value}`` dict."""
    with _session(dsn) as session:
        rows = session.exec(select(TataSetting)).all()
    result: dict[str, Any] = {}
    for row in rows:
        try:
            result[row.key] = json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            result[row.key] = row.value
    return result


def set_many_settings(data: dict[str, Any], dsn: str | None = None) -> None:
    """Upsert multiple settings in a single transaction."""
    with _session(dsn) as session:
        for key, value in data.items():
            serialised = json.dumps(value) if not isinstance(value, str) else value
            row = session.get(TataSetting, key)
            if row is None:
                row = TataSetting(key=key, value=serialised)
            else:
                row.value = serialised
                row.updated_at = datetime.utcnow()
            session.add(row)
        session.commit()
