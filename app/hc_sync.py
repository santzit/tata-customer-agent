"""Help Center synchronisation — index Chatwoot Help Center articles into the RAG vector store.

Fetches published articles from the Chatwoot Help Center REST API via
:class:`~app.chatwoot.ChatwootClient` and upserts them into the pgvector
knowledge store so that the agent can retrieve relevant knowledge-base content
when answering customer questions.

API endpoints used (via ChatwootClient):
  GET /api/v1/accounts/{account_id}/portals
      → List all portals (knowledge bases).
  GET /api/v1/accounts/{account_id}/portals/{portal_slug}/articles?status=published&page=N
      → Paginated list of published articles for a portal.

Usage
-----
**Programmatic (at startup)**::

    from app.hc_sync import HelpCenterSync
    sync = HelpCenterSync(vector_store)
    sync.run()

**CLI**::

    python -m app.hc_sync

Article document IDs use the pattern ``hc-article-<id>`` so they do not clash
with documents ingested via other pipelines (e.g. :mod:`app.ingest_docs`).
"""

import logging

from app.chatwoot import ChatwootClient
from app.config import settings
from app.pg_vector_store import PgVectorStore

logger = logging.getLogger(__name__)

_ARTICLE_DOC_PREFIX = "hc-article-"


class HelpCenterSync:
    """Fetches published Help Center articles from the Chatwoot API and indexes
    them into the pgvector RAG store.

    Uses :class:`~app.chatwoot.ChatwootClient` for all HTTP communication with
    the Chatwoot Help Center REST API.

    Args:
        vector_store: A :class:`~app.pg_vector_store.PgVectorStore` instance
            to upsert articles into.
        chatwoot_client: An optional pre-configured
            :class:`~app.chatwoot.ChatwootClient`.  When omitted a new client
            is created from the application :mod:`~app.config`.
    """

    def __init__(
        self,
        vector_store: PgVectorStore,
        chatwoot_client: ChatwootClient | None = None,
    ) -> None:
        self._store = vector_store
        self._client = chatwoot_client or ChatwootClient()

    def _fetch_portals(self) -> list[dict]:
        """Return all portals for the configured Chatwoot account."""
        portals = self._client.list_portals()
        logger.info("HelpCenterSync: found %d portal(s).", len(portals))
        return portals

    def _fetch_articles_for_portal(self, portal_slug: str) -> list[dict]:
        """Return all published articles for *portal_slug*, handling pagination."""
        articles: list[dict] = []
        page = 1
        while True:
            payload = self._client.list_portal_articles(
                portal_slug, status="published", page=page
            )
            if not payload:
                break

            page_articles = payload.get("articles", [])
            if not isinstance(page_articles, list) or not page_articles:
                break

            articles.extend(page_articles)

            # Check meta for total count to decide if there are more pages.
            meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
            total = meta.get("total", len(articles)) if isinstance(meta, dict) else len(articles)
            if len(articles) >= total:
                break

            page += 1

        return articles

    def run(self) -> int:
        """Sync all published Help Center articles from Chatwoot into the vector store.

        Returns:
            The number of articles that were upserted.
        """
        if not self._client.api_token:
            logger.info(
                "HelpCenterSync: CHATWOOT_API_TOKEN is not set — skipping HC sync."
            )
            return 0

        portals = self._fetch_portals()
        if not portals:
            logger.info(
                "HelpCenterSync: no portals found — nothing to sync."
            )
            return 0

        synced = 0
        for portal in portals:
            portal_slug = portal.get("slug") or portal.get("id")
            portal_name = portal.get("name", portal_slug)
            portal_id = portal.get("id")

            if not portal_slug:
                logger.warning("HelpCenterSync: portal without slug, skipping: %r", portal)
                continue

            logger.info(
                "HelpCenterSync: fetching articles for portal '%s' (slug=%r).",
                portal_name,
                portal_slug,
            )
            articles = self._fetch_articles_for_portal(str(portal_slug))
            logger.info(
                "HelpCenterSync: found %d published article(s) in portal '%s'.",
                len(articles),
                portal_name,
            )

            for article in articles:
                article_id = article.get("id")
                title = article.get("title", "")
                content = article.get("content", "")

                if not article_id or not title:
                    logger.debug(
                        "HelpCenterSync: skipping article with missing id or title: %r",
                        article,
                    )
                    continue

                doc_id = f"{_ARTICLE_DOC_PREFIX}{article_id}"
                # Combine title + content so the embedding captures both.
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
                    self._store.upsert(doc_id=doc_id, text=text, metadata=metadata)
                    synced += 1
                except Exception as exc:
                    logger.warning(
                        "HelpCenterSync: failed to upsert article %s ('%s'): %s",
                        article_id,
                        title,
                        exc,
                    )

        logger.info(
            "HelpCenterSync: upserted %d published article(s) into the RAG store.",
            synced,
        )
        return synced


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _run_cli() -> None:
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    vector_store = PgVectorStore()
    vector_store.ensure_table()

    sync = HelpCenterSync(vector_store)
    count = sync.run()
    print(f"HelpCenterSync complete: {count} article(s) indexed.")


if __name__ == "__main__":
    _run_cli()


