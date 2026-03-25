"""Web API router for the v03x Web/App Frontend feature.

All Chatwoot API calls go through :class:`~app.services.chatwoot_client.ChatwootClient`
(using the master token) so there is a single, consistent HTTP layer across the
application — no raw ``httpx`` calls in this module.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from app.config import settings
from app.hc_sync import HelpCenterSync
from app.pg_vector_store import PgVectorStore
from app.services.chatwoot_client import ChatwootClient
from app.web_models import (
    ChatwootAccount,
    ChatwootInbox,
    HelpCenterArticle,
    OpenAIConfig,
    create_web_tables,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web", tags=["web"])

_engine = create_engine(settings.postgres_dsn)


def _web_client() -> ChatwootClient:
    """Return a ChatwootClient configured with the master token.

    Used for all web-facing Chatwoot API calls that require super-admin access
    (listing accounts, inboxes, teams, conversations, messages).
    """
    return ChatwootClient(api_token=settings.chatwoot_master_token)


def _account_id_or_default(account_id: Optional[int]) -> Optional[int]:
    if account_id:
        return account_id
    return settings.chatwoot_account_id or None


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------


class TokenApiBody(BaseModel):
    account_id: int
    token_api: str


class OpenAIConfigBody(BaseModel):
    api_key: str = ""
    model: str = "gpt-4.1"
    api_endpoint: str = ""
    embedding_model_small: str = ""
    embedding_model_large: str = ""
    llm_provider: str = "openai"
    params: Optional[dict] = None


class SyncHelpCenterBody(BaseModel):
    account_id: Optional[int] = None
    portal_slug: Optional[str] = None


# ---------------------------------------------------------------------------
# Accounts endpoints (DB-backed with Chatwoot sync)
# ---------------------------------------------------------------------------


@router.get("/accounts")
def get_accounts_from_db():
    """Return accounts stored in the local DB."""
    try:
        with Session(_engine) as session:
            accounts = session.exec(select(ChatwootAccount)).all()
        return [
            {
                "id": a.account_id,
                "name": a.name,
                "token_api": a.token_api,
            }
            for a in accounts
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/accounts/sync")
def sync_accounts():
    """Fetch accounts from Chatwoot and upsert them into the local DB."""
    if not settings.chatwoot_master_token:
        raise HTTPException(
            status_code=502,
            detail="CHATWOOT_MASTER_TOKEN is not set — cannot sync accounts.",
        )
    client = _web_client()
    accounts = client.accounts.list()
    synced = 0
    try:
        with Session(_engine) as session:
            for acc in accounts:
                account_id = acc.get("id")
                name = acc.get("name", str(account_id))
                if not account_id:
                    continue
                existing = session.exec(
                    select(ChatwootAccount).where(ChatwootAccount.account_id == account_id)
                ).first()
                if existing:
                    existing.name = name
                else:
                    session.add(ChatwootAccount(account_id=account_id, name=name))
                synced += 1
            session.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"synced": synced, "accounts": [{"id": a.get("id"), "name": a.get("name")} for a in accounts]}


def ensure_account_in_db(account_id: int, account_name: str = "") -> None:
    """Upsert a Chatwoot account into the local DB if it doesn't exist yet.

    Called from the webhook handler on each incoming message so that accounts
    are automatically registered without requiring a manual sync.
    """
    if not account_id:
        return
    try:
        with Session(_engine) as session:
            existing = session.exec(
                select(ChatwootAccount).where(ChatwootAccount.account_id == account_id)
            ).first()
            if existing:
                if account_name and not existing.name:
                    existing.name = account_name
                    session.commit()
                return
            # Try to get a better name from Chatwoot if we have a master token.
            # Chatwoot's super-admin API exposes accounts via GET /api/v1/profile
            # (which returns all accounts), so we iterate to find the matching one.
            name = account_name or str(account_id)
            if settings.chatwoot_master_token:
                try:
                    client = _web_client()
                    chatwoot_accounts = client.accounts.list()
                    for acc in chatwoot_accounts:
                        if acc.get("id") == account_id:
                            name = acc.get("name", name)
                            break
                except Exception:
                    pass
            session.add(ChatwootAccount(account_id=account_id, name=name))
            session.commit()
            logger.info("Auto-created account %d (%s) in local DB", account_id, name)
    except Exception as exc:
        logger.warning("Could not ensure account %d in DB: %s", account_id, exc)


# ---------------------------------------------------------------------------
# Chatwoot endpoints (live API pass-through)
# ---------------------------------------------------------------------------


@router.get("/chatwoot/accounts")
def get_chatwoot_accounts():
    """Fetch accounts directly from Chatwoot using the master token (live pass-through)."""
    client = _web_client()
    accounts = client.accounts.list()
    if accounts == [] and not settings.chatwoot_master_token:
        raise HTTPException(
            status_code=502,
            detail="CHATWOOT_MASTER_TOKEN is not set — cannot list accounts.",
        )
    return accounts


@router.get("/chatwoot/inboxes")
def get_chatwoot_inboxes(account_id: Optional[int] = Query(default=None)):
    """Fetch inboxes from Chatwoot for a given account."""
    aid = _account_id_or_default(account_id)
    if not aid:
        return []
    client = _web_client()
    return client.inboxes.list(account_id=aid)


@router.get("/chatwoot/teams")
def get_chatwoot_teams(account_id: Optional[int] = Query(default=None)):
    """Fetch teams from Chatwoot for a given account."""
    aid = _account_id_or_default(account_id)
    if not aid:
        return []
    client = _web_client()
    return client.inboxes.list_teams(account_id=aid)


@router.get("/chatwoot/help-center")
def get_help_center_articles(
    search: Optional[str] = Query(default=None),
    locale: Optional[str] = Query(default=None),
):
    """Return locally stored help center articles, with optional filtering."""
    try:
        with Session(_engine) as session:
            query = select(HelpCenterArticle)
            if locale:
                query = query.where(HelpCenterArticle.locale == locale)
            articles = session.exec(query).all()

        if search:
            s = search.lower()
            articles = [
                a for a in articles
                if s in a.title.lower() or s in a.content.lower()
            ]

        return [
            {
                "id": a.id,
                "article_id": a.article_id,
                "title": a.title,
                "content": a.content,
                "locale": a.locale,
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in articles
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chatwoot/sync-help-center")
def sync_help_center(body: SyncHelpCenterBody):
    """Sync Help Center articles from Chatwoot into the local DB and RAG store."""
    client = _web_client()
    synced = 0

    try:
        # Fetch portals via the help_center sub-API
        aid = _account_id_or_default(body.account_id)
        portals = client.help_center.list_portals(account_id=aid)
        if body.portal_slug:
            portals = [p for p in portals if p.get("slug") == body.portal_slug]

        with Session(_engine) as session:
            for portal in portals:
                portal_slug = portal.get("slug") or str(portal.get("id", ""))
                if not portal_slug:
                    continue

                # Fetch articles via the help_center sub-API
                payload = client.help_center.list_portal_articles(
                    portal_slug, account_id=aid
                )
                articles = payload.get("articles", []) if isinstance(payload, dict) else []

                for article in articles:
                    article_id = article.get("id")
                    title = article.get("title", "")
                    content = article.get("content", "")
                    locale = article.get("locale", "en")
                    if not article_id or not title:
                        continue

                    existing = session.exec(
                        select(HelpCenterArticle).where(
                            HelpCenterArticle.article_id == article_id
                        )
                    ).first()

                    if existing:
                        existing.title = title
                        existing.content = content
                        existing.locale = locale
                        existing.portal_slug = portal_slug
                        session.add(existing)
                    else:
                        session.add(
                            HelpCenterArticle(
                                article_id=article_id,
                                title=title,
                                content=content,
                                locale=locale,
                                portal_slug=portal_slug,
                            )
                        )
                    synced += 1

            session.commit()

        # Also push articles into the RAG vector store
        try:
            vector_store = PgVectorStore()
            HelpCenterSync(vector_store, chatwoot_client=client).run()
        except Exception as exc:
            logger.warning("Vector store sync failed (continuing): %s", exc)

        return {"synced": synced}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Per-account inbox endpoints (DB-backed with Chatwoot sync)
# ---------------------------------------------------------------------------


@router.get("/accounts/{account_id}/inboxes")
def get_account_inboxes(account_id: int):
    """Return inboxes for a specific Chatwoot account from the local DB."""
    try:
        with Session(_engine) as session:
            inboxes = session.exec(
                select(ChatwootInbox).where(ChatwootInbox.account_id == account_id)
            ).all()
        return [
            {
                "id": i.inbox_id,
                "name": i.name,
                "account_id": i.account_id,
                "portal_slug": i.portal_slug,
            }
            for i in inboxes
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/accounts/{account_id}/inboxes/sync")
def sync_account_inboxes(account_id: int):
    """Fetch inboxes from Chatwoot for an account and upsert into local DB.

    Also discovers portal associations so that ``portal_slug`` is populated
    for each inbox (enabling per-inbox Help Center filtering).
    """
    if not settings.chatwoot_master_token:
        raise HTTPException(
            status_code=502,
            detail="CHATWOOT_MASTER_TOKEN is not set — cannot sync inboxes.",
        )
    client = _web_client()

    # Build a mapping of inbox_id → portal_slug from portals
    portal_by_inbox: dict[int, str] = {}
    try:
        portals = client.help_center.list_portals(account_id=account_id)
        for portal in portals:
            slug = portal.get("slug", "")
            for pb_inbox in portal.get("inboxes", []):
                iid = pb_inbox.get("id") if isinstance(pb_inbox, dict) else pb_inbox
                if iid and slug:
                    portal_by_inbox[int(iid)] = slug
    except Exception as exc:
        logger.warning("Could not fetch portals for account %d: %s", account_id, exc)

    inboxes = client.inboxes.list(account_id=account_id)
    synced = 0
    try:
        with Session(_engine) as session:
            for inbox in inboxes:
                inbox_id = inbox.get("id")
                name = inbox.get("name", str(inbox_id))
                if not inbox_id:
                    continue
                portal_slug = portal_by_inbox.get(int(inbox_id), "")
                existing = session.exec(
                    select(ChatwootInbox).where(
                        ChatwootInbox.inbox_id == inbox_id,
                        ChatwootInbox.account_id == account_id,
                    )
                ).first()
                if existing:
                    existing.name = name
                    existing.portal_slug = portal_slug
                else:
                    session.add(
                        ChatwootInbox(
                            inbox_id=inbox_id,
                            account_id=account_id,
                            name=name,
                            portal_slug=portal_slug,
                        )
                    )
                synced += 1
            session.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"synced": synced, "inboxes": [{"id": i.get("id"), "name": i.get("name")} for i in inboxes]}


@router.get("/accounts/{account_id}/inboxes/{inbox_id}/help-center")
def get_inbox_help_center(
    account_id: int,
    inbox_id: int,
    search: Optional[str] = Query(default=None),
    locale: Optional[str] = Query(default=None),
):
    """Return Help Center articles for the portal linked to a specific inbox.

    Looks up the inbox's ``portal_slug`` in the local DB, then filters
    ``web_help_center_articles`` to only return articles from that portal.
    Returns an empty list (not 404) when no portal is linked yet.
    """
    try:
        with Session(_engine) as session:
            inbox = session.exec(
                select(ChatwootInbox).where(
                    ChatwootInbox.inbox_id == inbox_id,
                    ChatwootInbox.account_id == account_id,
                )
            ).first()
            portal_slug = inbox.portal_slug if inbox else ""

            articles = session.exec(select(HelpCenterArticle)).all()

        # Filter by portal_slug if the inbox has one
        if portal_slug:
            articles = [a for a in articles if a.portal_slug == portal_slug]

        if search:
            q = search.lower()
            articles = [
                a for a in articles if q in a.title.lower() or q in a.content.lower()
            ]
        if locale:
            articles = [a for a in articles if a.locale == locale]

        return [
            {
                "id": a.article_id,
                "title": a.title,
                "content": a.content,
                "locale": a.locale,
                "portal_slug": a.portal_slug,
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in articles
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------



@router.get("/config/token-api")
def get_token_apis():
    """Return all locally stored token_api values keyed by account_id."""
    try:
        with Session(_engine) as session:
            accounts = session.exec(select(ChatwootAccount)).all()
        return {str(a.account_id): a.token_api for a in accounts}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/config/token-api")
def save_token_api(body: TokenApiBody):
    """Save or update the TOKEN_API for a Chatwoot account."""
    try:
        with Session(_engine) as session:
            existing = session.exec(
                select(ChatwootAccount).where(
                    ChatwootAccount.account_id == body.account_id
                )
            ).first()
            if existing:
                existing.token_api = body.token_api
                session.add(existing)
            else:
                session.add(
                    ChatwootAccount(
                        account_id=body.account_id,
                        name=str(body.account_id),
                        token_api=body.token_api,
                    )
                )
            session.commit()
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _mask_api_key(key: str) -> str:
    """Return a masked API key showing only the last 4 characters."""
    if not key:
        return ""
    if len(key) <= 4:
        return "*" * len(key)
    return "*" * 8 + key[-4:]


@router.get("/config/openai")
def get_openai_config():
    """Return OpenAI config from DB (api_key is masked)."""
    try:
        with Session(_engine) as session:
            cfg = session.exec(select(OpenAIConfig)).first()
        if not cfg:
            return {
                "api_key": "",
                "model": "gpt-4.1",
                "api_endpoint": "",
                "embedding_model_small": "",
                "embedding_model_large": "",
                "llm_provider": "openai",
                "params": None,
            }
        return {
            "api_key": _mask_api_key(cfg.api_key),
            "model": cfg.model,
            "api_endpoint": cfg.api_endpoint,
            "embedding_model_small": cfg.embedding_model_small,
            "embedding_model_large": cfg.embedding_model_large,
            "llm_provider": cfg.llm_provider,
            "params": cfg.params,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/config/openai")
def save_openai_config(body: OpenAIConfigBody):
    """Persist OpenAI config to DB."""
    try:
        with Session(_engine) as session:
            cfg = session.exec(select(OpenAIConfig)).first()
            if cfg:
                if body.api_key:
                    cfg.api_key = body.api_key
                cfg.model = body.model
                cfg.api_endpoint = body.api_endpoint
                cfg.embedding_model_small = body.embedding_model_small
                cfg.embedding_model_large = body.embedding_model_large
                cfg.llm_provider = body.llm_provider
                cfg.params = body.params
                session.add(cfg)
            else:
                session.add(
                    OpenAIConfig(
                        api_key=body.api_key,
                        model=body.model,
                        api_endpoint=body.api_endpoint,
                        embedding_model_small=body.embedding_model_small,
                        embedding_model_large=body.embedding_model_large,
                        llm_provider=body.llm_provider,
                        params=body.params,
                    )
                )
            session.commit()
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Conversations endpoints
# ---------------------------------------------------------------------------


@router.get("/conversations")
def get_conversations(
    limit: int = Query(default=50),
    account_id: Optional[int] = Query(default=None),
    inbox_id: Optional[int] = Query(default=None),
):
    """Fetch conversations from the local database (ordered by most recent activity)."""
    try:
        params: dict = {
            "limit": limit,
            "account_id": account_id,
            "inbox_id": inbox_id,
        }

        with _engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT
                        c.chatwoot_id   AS id,
                        c.display_id,
                        c.status,
                        c.meta,
                        c.updated_at,
                        c.account_id,
                        c.inbox_id,
                        a.name          AS account_name,
                        i.name          AS inbox_name
                    FROM conversations c
                    LEFT JOIN accounts a ON c.account_id = a.id
                    LEFT JOIN inboxes  i ON c.inbox_id  = i.id
                    WHERE (:account_id IS NULL OR c.account_id = :account_id)
                      AND (:inbox_id   IS NULL OR c.inbox_id   = :inbox_id)
                    ORDER BY c.updated_at DESC
                    LIMIT :limit
                """),
                params,
            ).mappings().all()

        result = []
        for row in rows:
            meta = row["meta"] or {}
            contact = meta.get("sender", {}) or {}
            result.append(
                {
                    "id": row["id"],
                    "display_id": row["display_id"],
                    "status": row["status"],
                    "contact": {
                        "id": contact.get("id"),
                        "name": contact.get("name"),
                        "email": contact.get("email"),
                    },
                    "account_name": row["account_name"],
                    "inbox_name": row["inbox_name"],
                    "last_activity_at": (
                        int(row["updated_at"].timestamp()) if row["updated_at"] else None
                    ),
                }
            )
        return result
    except Exception as exc:
        logger.warning("conversations: local DB query failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int,
    account_id: Optional[int] = Query(default=None),
):
    """Fetch bot messages for a conversation from the local database."""
    try:
        with _engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT
                        id,
                        content,
                        message_type,
                        private,
                        status,
                        created_at
                    FROM messages
                    WHERE chatwoot_conv_id = :conv_id
                    ORDER BY created_at ASC
                    LIMIT 500
                """),
                {"conv_id": conversation_id},
            ).mappings().all()

        # Our messages table stores bot-sent outgoing messages.
        # message_type in DB is text ('outgoing'); map to integer 3 (bot)
        # so the frontend MessageBubble can colour them correctly.
        return [
            {
                "id": row["id"],
                "content": row["content"],
                "message_type": 3,  # bot outgoing
                "sender": {"name": "Tata Bot", "type": "bot"},
                "created_at": (
                    int(row["created_at"].timestamp()) if row["created_at"] else None
                ),
                "private": row["private"],
                "status": row["status"],
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("conversation messages: local DB query failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


@router.get("/status")
def get_status():
    """Check connection status for Chatwoot, DB, and OpenAI."""
    chatwoot_connected = False
    db_connected = False
    openai_configured = False

    # Check Chatwoot reachability via accounts.list()
    try:
        client = _web_client()
        client.accounts.list()
        chatwoot_connected = True
    except Exception:
        chatwoot_connected = False

    # Check DB
    try:
        with Session(_engine) as session:
            session.exec(select(OpenAIConfig)).first()
        db_connected = True
    except Exception:
        db_connected = False

    # Check OpenAI config
    try:
        with Session(_engine) as session:
            cfg = session.exec(select(OpenAIConfig)).first()
        openai_configured = bool(cfg and cfg.api_key) or bool(settings.openai_api_key)
    except Exception:
        openai_configured = bool(settings.openai_api_key)

    return {
        "chatwoot_connected": chatwoot_connected,
        "db_connected": db_connected,
        "openai_configured": openai_configured,
    }
