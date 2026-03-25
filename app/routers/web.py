"""Web API router for the v03x Web/App Frontend feature."""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, create_engine, select

from app.config import settings
from app.web_models import (
    ChatwootAccount,
    HelpCenterArticle,
    OpenAIConfig,
    create_web_tables,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web", tags=["web"])

_engine = create_engine(settings.postgres_dsn)

# Ensure tables exist when the router module is loaded.
try:
    create_web_tables(_engine)
except Exception as _exc:
    logger.warning("Could not create web tables at import time: %s", _exc)


def _master_headers() -> dict:
    return {"api_access_token": settings.chatwoot_master_token}


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
    params: Optional[dict] = None


class SyncHelpCenterBody(BaseModel):
    account_id: Optional[int] = None
    portal_slug: Optional[str] = None


# ---------------------------------------------------------------------------
# Chatwoot endpoints
# ---------------------------------------------------------------------------


@router.get("/chatwoot/accounts")
async def get_chatwoot_accounts():
    """Fetch accounts from Chatwoot API using the master token."""
    url = f"{settings.chatwoot_base_url}/api/v1/accounts"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_master_headers())
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", data)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chatwoot unreachable: {exc}") from exc


@router.get("/chatwoot/inboxes")
async def get_chatwoot_inboxes(account_id: Optional[int] = Query(default=None)):
    """Fetch inboxes from Chatwoot for a given account."""
    aid = _account_id_or_default(account_id)
    if not aid:
        return []
    url = f"{settings.chatwoot_base_url}/api/v1/accounts/{aid}/inboxes"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_master_headers())
        resp.raise_for_status()
        data = resp.json()
        return data.get("payload", data) if isinstance(data, dict) else data
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chatwoot unreachable: {exc}") from exc


@router.get("/chatwoot/teams")
async def get_chatwoot_teams(account_id: Optional[int] = Query(default=None)):
    """Fetch teams from Chatwoot for a given account."""
    aid = _account_id_or_default(account_id)
    if not aid:
        return []
    url = f"{settings.chatwoot_base_url}/api/v1/accounts/{aid}/teams"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_master_headers())
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("payload", data)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chatwoot unreachable: {exc}") from exc


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
async def sync_help_center(body: SyncHelpCenterBody):
    """Sync help center articles from Chatwoot into the local DB."""
    from app.pg_vector_store import PgVectorStore
    from app.hc_sync import HelpCenterSync

    aid = _account_id_or_default(body.account_id)
    synced = 0

    try:
        vector_store = PgVectorStore()
        hc_sync = HelpCenterSync(vector_store)

        portals = hc_sync._fetch_portals()
        if body.portal_slug:
            portals = [p for p in portals if p.get("slug") == body.portal_slug]

        with Session(_engine) as session:
            for portal in portals:
                portal_slug = portal.get("slug") or str(portal.get("id", ""))
                if not portal_slug:
                    continue
                articles = hc_sync._fetch_articles_for_portal(portal_slug)
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
                        session.add(existing)
                    else:
                        session.add(
                            HelpCenterArticle(
                                article_id=article_id,
                                title=title,
                                content=content,
                                locale=locale,
                            )
                        )
                    synced += 1

            session.commit()

        # Also sync into vector store
        try:
            hc_sync.run()
        except Exception as exc:
            logger.warning("Vector store sync failed (continuing): %s", exc)

        return {"synced": synced}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


@router.post("/config/token-api")
def save_token_api(body: TokenApiBody):
    """Save or update the Chatwoot API token for an account."""
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
    """Return a masked version of an API key, showing only the last 4 characters."""
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
            return {"api_key": "", "model": "gpt-4.1", "params": None}
        return {"api_key": _mask_api_key(cfg.api_key), "model": cfg.model, "params": cfg.params}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/config/openai")
def save_openai_config(body: OpenAIConfigBody):
    """Save OpenAI config to DB."""
    try:
        with Session(_engine) as session:
            cfg = session.exec(select(OpenAIConfig)).first()
            if cfg:
                if body.api_key:
                    cfg.api_key = body.api_key
                cfg.model = body.model
                cfg.params = body.params
                session.add(cfg)
            else:
                session.add(
                    OpenAIConfig(
                        api_key=body.api_key,
                        model=body.model,
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
async def get_conversations(
    limit: int = Query(default=50),
    account_id: Optional[int] = Query(default=None),
    inbox_id: Optional[int] = Query(default=None),
):
    """Fetch conversations from Chatwoot."""
    aid = _account_id_or_default(account_id)
    if not aid:
        return []
    url = f"{settings.chatwoot_base_url}/api/v1/accounts/{aid}/conversations"
    params: dict = {"page": 1}
    if inbox_id:
        params["inbox_id"] = inbox_id

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_master_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()

        payload = data.get("data", {}) if isinstance(data, dict) else {}
        conversations = payload.get("payload", []) if isinstance(payload, dict) else payload
        if not isinstance(conversations, list):
            conversations = []

        result = []
        for conv in conversations[:limit]:
            meta = conv.get("meta", {}) or {}
            contact = meta.get("sender", {}) or {}
            result.append(
                {
                    "id": conv.get("id"),
                    "display_id": conv.get("display_id"),
                    "status": conv.get("status"),
                    "contact": {
                        "id": contact.get("id"),
                        "name": contact.get("name"),
                        "email": contact.get("email"),
                    },
                    "inbox_id": conv.get("inbox_id"),
                    "account_id": conv.get("account_id"),
                    "last_activity_at": conv.get("last_activity_at"),
                    "last_message": conv.get("last_non_activity_message", {}).get("content")
                    if conv.get("last_non_activity_message")
                    else None,
                }
            )
        return result
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chatwoot unreachable: {exc}") from exc


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: int,
    account_id: Optional[int] = Query(default=None),
):
    """Fetch messages for a conversation from Chatwoot."""
    aid = _account_id_or_default(account_id)
    if not aid:
        raise HTTPException(status_code=400, detail="account_id is required")
    url = f"{settings.chatwoot_base_url}/api/v1/accounts/{aid}/conversations/{conversation_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_master_headers())
        resp.raise_for_status()
        data = resp.json()

        messages = data.get("payload", []) if isinstance(data, dict) else data
        if not isinstance(messages, list):
            messages = []

        return [
            {
                "id": msg.get("id"),
                "content": msg.get("content"),
                "message_type": msg.get("message_type"),
                "sender": {
                    "id": msg.get("sender", {}).get("id") if msg.get("sender") else None,
                    "name": msg.get("sender", {}).get("name") if msg.get("sender") else None,
                    "type": msg.get("sender", {}).get("type") if msg.get("sender") else None,
                },
                "created_at": msg.get("created_at"),
                "private": msg.get("private", False),
            }
            for msg in messages
        ]
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chatwoot unreachable: {exc}") from exc


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_status():
    """Check connection status for Chatwoot, DB, and OpenAI."""
    chatwoot_connected = False
    db_connected = False
    openai_configured = False

    # Check Chatwoot
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.chatwoot_base_url}/auth/sign_in",
                headers=_master_headers(),
            )
        chatwoot_connected = resp.status_code < 500
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
