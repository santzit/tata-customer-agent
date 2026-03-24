"""Sync Chatwoot Help Center articles into the pgvector RAG knowledge store.

Published articles are read directly from the Chatwoot PostgreSQL database,
HTML content is stripped, and each article is upserted into the vector store
via :class:`~app.pg_vector_store.PgVectorStore`.

Usage as a CLI command (recommended for initial load or cron jobs)::

    python -m app.hc_sync

The application also runs this sync automatically at startup when
``CHATWOOT_DSN`` is configured and ``HC_SYNC_ON_STARTUP`` is ``true``
(the default).

Required environment variables
-------------------------------
``CHATWOOT_DSN``
    DSN for the Chatwoot PostgreSQL database, e.g.
    ``postgresql://chatwoot:password@localhost:5432/chatwoot_production``.
    This is often the same host as ``POSTGRES_DSN`` but points at Chatwoot's
    own database.

``CHATWOOT_ACCOUNT_ID``
    Chatwoot account ID (default ``1``).  Only articles belonging to this
    account are synced.
"""

import logging
import re
import sys
from typing import Any

import psycopg2
import psycopg2.extras

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_WS_RE = re.compile(r"\s{2,}")


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = _HTML_TAG_RE.sub(" ", html or "")
    return _MULTI_WS_RE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Sync class
# ---------------------------------------------------------------------------


class HelpCenterSync:
    """Read published Help Center articles from Chatwoot and upsert into pgvector.

    Chatwoot stores Help Center articles in the ``articles`` table of its own
    PostgreSQL database.  The ``status`` column is a string; published articles
    have ``status = 'published'``.

    Each article is turned into a single text blob (title + description +
    stripped HTML body) and stored in the vector store with the document ID
    ``hc-article-<article_id>``, so re-running the sync is idempotent.
    """

    def __init__(
        self,
        chatwoot_dsn: str | None = None,
        account_id: int | None = None,
        vector_store: Any | None = None,
    ) -> None:
        """Initialise the sync helper.

        Args:
            chatwoot_dsn: DSN for the Chatwoot database.  Defaults to
                ``settings.chatwoot_dsn``.
            account_id: Chatwoot account ID used to filter articles.  Defaults
                to ``settings.chatwoot_account_id``.
            vector_store: A pre-configured
                :class:`~app.pg_vector_store.PgVectorStore` instance.  When
                omitted a new one is created from settings.
        """
        self._dsn = chatwoot_dsn or settings.chatwoot_dsn
        self._account_id = (
            account_id if account_id is not None else settings.chatwoot_account_id
        )
        self._vector_store = vector_store

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_store(self):
        """Return the vector store, creating one from settings if needed."""
        if self._vector_store is not None:
            return self._vector_store
        from app.pg_vector_store import PgVectorStore

        return PgVectorStore()

    def _fetch_published_articles(self) -> list[dict]:
        """Query Chatwoot DB for published HC articles for the configured account.

        Returns:
            A list of dicts with keys ``id``, ``title``, ``content``,
            ``description``.

        Raises:
            psycopg2.Error: On any database error.
        """
        conn = psycopg2.connect(self._dsn)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, title, content, description
                    FROM   articles
                    WHERE  account_id = %s
                      AND  status     = 'published'
                    ORDER  BY updated_at DESC
                    """,
                    (self._account_id,),
                )
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def _article_to_text(self, article: dict) -> str:
        """Combine title, description and body into a single embeddable string."""
        parts: list[str] = []
        if article.get("title"):
            parts.append(article["title"].strip())
        if article.get("description"):
            parts.append(_strip_html(article["description"]))
        if article.get("content"):
            parts.append(_strip_html(article["content"]))
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync(self) -> int:
        """Fetch published articles and upsert them into the vector store.

        Returns:
            The number of articles successfully synced.

        Raises:
            RuntimeError: When ``CHATWOOT_DSN`` is not configured.
            psycopg2.Error: On Chatwoot database errors.
        """
        if not self._dsn:
            raise RuntimeError(
                "CHATWOOT_DSN is not set.  "
                "Set it to the Chatwoot PostgreSQL DSN to enable Help Center sync."
            )

        store = self._get_store()
        store.ensure_table()

        articles = self._fetch_published_articles()
        logger.info(
            "HC sync: found %d published article(s) for account %d.",
            len(articles),
            self._account_id,
        )

        synced = 0
        for article in articles:
            text = self._article_to_text(article)
            if not text:
                logger.debug("Skipping article %d — no text content.", article["id"])
                continue
            doc_id = f"hc-article-{article['id']}"
            metadata = {
                "source": "chatwoot_hc",
                "article_id": article["id"],
                "title": article.get("title") or "",
            }
            store.upsert(doc_id, text, metadata)
            logger.info(
                "  Synced article %d: %s",
                article["id"],
                article.get("title", "(no title)"),
            )
            synced += 1

        logger.info(
            "HC sync complete: %d/%d article(s) synced into '%s'.",
            synced,
            len(articles),
            store._table,
        )
        return synced


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        count = HelpCenterSync().sync()
        print(f"\nDone — {count} Help Center article(s) synced into the RAG knowledge store.")
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        logger.exception("HC sync failed: %s", exc)
        sys.exit(1)
