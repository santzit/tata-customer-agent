"""Help Center synchronisation — index portal articles into the RAG vector store.

Published articles from the ``portal_articles`` table are embedded and upserted
into the pgvector knowledge store so that the agent can retrieve relevant
knowledge-base content when answering customer questions.

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

import psycopg2

from app.config import settings
from app.pg_vector_store import PgVectorStore

logger = logging.getLogger(__name__)

_ARTICLE_DOC_PREFIX = "hc-article-"


class HelpCenterSync:
    """Synchronises published Help Center articles into the pgvector RAG store.

    Args:
        vector_store: A :class:`~app.pg_vector_store.PgVectorStore` instance
            to upsert articles into.
        dsn: Optional override for the PostgreSQL DSN used to read articles.
             Defaults to ``settings.postgres_dsn``.
    """

    def __init__(
        self,
        vector_store: PgVectorStore,
        dsn: str | None = None,
    ) -> None:
        self._store = vector_store
        self._dsn = dsn or settings.postgres_dsn

    def _fetch_published_articles(self) -> list[dict]:
        """Return all published portal articles with their portal metadata."""
        try:
            conn = psycopg2.connect(self._dsn, connect_timeout=10)
        except Exception as exc:
            logger.warning("HelpCenterSync: cannot connect to database: %s", exc)
            return []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        pa.id,
                        pa.title,
                        pa.content,
                        p.name  AS portal_name,
                        p.slug  AS portal_slug,
                        p.id    AS portal_id
                    FROM portal_articles pa
                    JOIN portals p ON p.id = pa.portal_id
                    WHERE pa.status = 'published'
                      AND p.archived = FALSE
                    ORDER BY pa.id
                    """
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        articles = []
        for row in rows:
            articles.append(
                {
                    "id": row[0],
                    "title": row[1],
                    "content": row[2],
                    "portal_name": row[3],
                    "portal_slug": row[4],
                    "portal_id": row[5],
                }
            )
        return articles

    def run(self) -> int:
        """Sync all published articles into the vector store.

        Returns:
            The number of articles that were upserted.
        """
        articles = self._fetch_published_articles()
        if not articles:
            logger.info("HelpCenterSync: no published articles found — nothing to sync.")
            return 0

        synced = 0
        for article in articles:
            doc_id = f"{_ARTICLE_DOC_PREFIX}{article['id']}"
            # Combine title + content so the embedding captures both.
            text = f"{article['title']}\n\n{article['content']}"
            metadata = {
                "source": "help_center",
                "article_id": article["id"],
                "portal_id": article["portal_id"],
                "portal_name": article["portal_name"],
                "portal_slug": article["portal_slug"],
                "title": article["title"],
            }
            try:
                self._store.upsert(doc_id=doc_id, text=text, metadata=metadata)
                synced += 1
            except Exception as exc:
                logger.warning(
                    "HelpCenterSync: failed to upsert article %d ('%s'): %s",
                    article["id"],
                    article["title"],
                    exc,
                )

        logger.info(
            "HelpCenterSync: upserted %d/%d published articles into the RAG store.",
            synced,
            len(articles),
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
