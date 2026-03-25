"""API routes for Help Center article management.

Articles are read from the pgvector RAG store (``tata_knowledge`` table) and
can be refreshed by triggering a sync against the Chatwoot Help Center API.
The sync uses the stored per-account ``api_token`` from ``tata_accounts``.
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app import db_models
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/help-center", tags=["help-center"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ArticleOut(BaseModel):
    id: str
    title: str
    text: str
    portal_name: str | None = None
    portal_slug: str | None = None
    source: str | None = None


class SyncResult(BaseModel):
    synced: int
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_rag_articles(
    table: str,
    dsn: str,
    search: str | None = None,
    portal_slug: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Query the pgvector store for stored HC articles.

    Filters on the ``metadata`` JSONB column.  Articles ingested via HC sync
    have ``metadata.source = 'help_center'``.
    """
    import psycopg2
    import psycopg2.extras

    # Validate table name against the known configured value to prevent
    # SQL injection via the table parameter (table names cannot be
    # parameterised with %s in psycopg2).
    allowed_tables = {settings.pg_vector_table}
    if table not in allowed_tables:
        raise ValueError(f"Unexpected table name: {table!r}")

    conditions = ["metadata->>'source' = 'help_center'"]
    params: list = []

    if portal_slug:
        conditions.append("metadata->>'portal_slug' = %s")
        params.append(portal_slug)

    if search:
        conditions.append("(text ILIKE %s OR metadata->>'title' ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    params.append(limit)

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, text, metadata
                FROM {table}
                WHERE {where}
                ORDER BY id
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        meta = row["metadata"] or {}
        result.append(
            {
                "id": row["id"],
                "title": meta.get("title", ""),
                "text": row["text"],
                "portal_name": meta.get("portal_name"),
                "portal_slug": meta.get("portal_slug"),
                "source": meta.get("source"),
            }
        )
    return result


def _sync_account(account_row: dict, vector_store) -> int:
    """Sync HC articles for one account into the RAG store.

    Uses the per-account ``api_token`` stored in ``tata_accounts``.

    Returns the number of articles upserted.
    """
    from app.chatwoot import ChatwootClient

    client = ChatwootClient(
        base_url=account_row["chatwoot_base_url"],
        api_token=account_row["api_token"],
        account_id=account_row["chatwoot_account_id"],
    )

    portals = client.list_portals()
    synced = 0

    for portal in portals:
        portal_slug = portal.get("slug") or str(portal.get("id", ""))
        portal_name = portal.get("name", portal_slug)
        portal_id = portal.get("id")
        if not portal_slug:
            continue

        articles: list[dict] = []
        page = 1
        while True:
            payload = client.list_portal_articles(portal_slug, status="published", page=page)
            if not payload:
                break
            page_articles = payload.get("articles", [])
            if not page_articles:
                break
            articles.extend(page_articles)
            meta = payload.get("meta", {})
            total = meta.get("total", len(articles)) if isinstance(meta, dict) else len(articles)
            if len(articles) >= total:
                break
            page += 1

        for article in articles:
            article_id = article.get("id")
            title = article.get("title", "")
            content = article.get("content", "")
            if not article_id or not title:
                continue
            doc_id = f"hc-article-{article_id}"
            text = f"{title}\n\n{content}" if content else title
            metadata = {
                "source": "help_center",
                "article_id": article_id,
                "portal_id": portal_id,
                "portal_name": portal_name,
                "portal_slug": portal_slug,
                "title": title,
            }
            try:
                vector_store.upsert(doc_id=doc_id, text=text, metadata=metadata)
                synced += 1
            except Exception as exc:
                logger.warning("HC sync: failed to upsert article %s: %s", article_id, exc)

    return synced


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/articles", response_model=list[ArticleOut])
def list_articles(
    search: str | None = Query(default=None, description="Filter by title or content"),
    portal_slug: str | None = Query(default=None, description="Filter by portal slug"),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """Return Help Center articles currently stored in the RAG vector store.

    Supports free-text search and portal-slug filtering.
    """
    try:
        rows = _list_rag_articles(
            table=settings.pg_vector_table,
            dsn=settings.postgres_dsn,
            search=search,
            portal_slug=portal_slug,
            limit=limit,
        )
        return [ArticleOut(**r) for r in rows]
    except Exception as exc:
        logger.exception("Failed to list articles: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to query articles")


@router.post("/sync", response_model=SyncResult)
def trigger_sync(account_id: int | None = Query(default=None)):
    """Trigger a Help Center sync for one or all active accounts.

    Args:
        account_id: When provided, only the specified account is synced.
                    When omitted, all active accounts with an API token are synced.

    The sync fetches published articles from the Chatwoot Help Center REST API
    using the per-account ``api_token`` and upserts them into the pgvector RAG store.
    """
    from app.pg_vector_store import PgVectorStore

    vector_store = PgVectorStore()
    try:
        vector_store.ensure_table()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector store unavailable: {exc}")

    if account_id is not None:
        row = db_models.get_account(account_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Account not found")
        accounts = [row]
    else:
        accounts = [a for a in db_models.list_accounts() if a["is_active"] and a["api_token"]]

    if not accounts:
        return SyncResult(synced=0, message="No active accounts with API tokens configured")

    total = 0
    for acct in accounts:
        try:
            total += _sync_account(acct, vector_store)
        except Exception as exc:
            logger.warning("HC sync failed for account %d: %s", acct["id"], exc)

    return SyncResult(
        synced=total,
        message=f"Synced {total} article(s) from {len(accounts)} account(s)",
    )
