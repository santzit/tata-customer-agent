"""Ingest markdown files from a directory into the pgvector RAG knowledge store.

Each ``.md`` file is split into sections by H2 headings (``## ...``) so that
large files become smaller, independently-searchable chunks.  When a file has
no H2 headings it is treated as a single document.

Re-running the ingestion is safe (idempotent) — every chunk is stored with a
stable document ID (``docs-<filename>-<chunk_index>``) and upserted, so
duplicate runs only update existing rows rather than creating new ones.

Usage::

    # Read from the directory set by DOCS_DIR (default: "docs/")
    python -m app.ingest_docs

    # Read from an explicit path
    python -m app.ingest_docs /path/to/my-docs

The application also runs docs ingestion automatically at startup when
``DOCS_DIR`` is set in the environment.  Set it to an empty string to disable
auto-ingestion.

Typical VPS setup to populate the knowledge store from a local markdown folder::

    DOCS_DIR=/home/myapp/knowledge
    python -m app.ingest_docs   # first-time load (or run on a schedule)
"""

import logging
import pathlib
import re
import sys
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Splits a markdown file into sections at each H2 heading ("## …").
# Uses a zero-width look-ahead so the heading line is included in each chunk.
_H2_SPLIT_RE = re.compile(r"(?=^## )", re.MULTILINE)


class DocsIngestion:
    """Read ``.md`` files from a directory and upsert them into the vector store.

    Each file is split on H2 headings so large documents are broken into
    focused, independently-retrievable chunks.  Every chunk gets a stable
    document ID so the operation is idempotent.
    """

    def __init__(
        self,
        docs_dir: str | pathlib.Path | None = None,
        vector_store: Any | None = None,
    ) -> None:
        """Initialise the docs ingestion helper.

        Args:
            docs_dir: Directory containing ``.md`` files.  Falls back to
                ``settings.docs_dir`` and then to ``"docs"`` if omitted.
            vector_store: Pre-configured
                :class:`~app.pg_vector_store.PgVectorStore` instance.  A
                default one is created from settings when omitted.
        """
        raw_dir = docs_dir or settings.docs_dir or "docs"
        self._docs_dir = pathlib.Path(raw_dir)
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

    def _chunks_from_file(self, path: pathlib.Path) -> list[tuple[str, str]]:
        """Split a markdown file into (chunk_id, text) tuples.

        Splits on H2 headings so each section becomes its own document.
        If the file has no H2 headings the entire content is a single chunk.

        Empty files and files that produce only whitespace-only chunks are
        silently skipped (returns an empty list).
        """
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []

        sections = [s.strip() for s in _H2_SPLIT_RE.split(text) if s.strip()]
        if not sections:
            return []

        # Build stable chunk IDs from the file stem.
        stem = re.sub(r"[^a-z0-9]+", "_", path.stem.lower()).strip("_")
        stem = re.sub(r"_+", "_", stem)  # collapse consecutive underscores
        return [(f"docs-{stem}-{i}", section) for i, section in enumerate(sections)]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self) -> int:
        """Read all ``.md`` files and upsert their chunks into the vector store.

        Returns:
            Total number of chunks successfully indexed.

        The method is safe to call multiple times — existing chunks are updated
        in-place rather than duplicated.
        """
        if not self._docs_dir.exists():
            logger.warning(
                "Docs directory %r does not exist — skipping docs ingestion. "
                "Set DOCS_DIR to the path of your markdown knowledge files.",
                str(self._docs_dir),
            )
            return 0

        md_files = sorted(self._docs_dir.glob("*.md"))
        if not md_files:
            logger.info(
                "No .md files found in %r — nothing to ingest.",
                str(self._docs_dir),
            )
            return 0

        store = self._get_store()
        store.ensure_table()

        total = 0
        for path in md_files:
            chunks = self._chunks_from_file(path)
            if not chunks:
                logger.debug("Skipping empty file: %s", path.name)
                continue
            for chunk_id, text in chunks:
                store.upsert(
                    chunk_id,
                    text,
                    {"source": "docs", "file": path.name},
                )
                logger.debug("Indexed chunk %r (%d chars)", chunk_id, len(text))
            logger.info(
                "Indexed %d chunk(s) from %s", len(chunks), path.name
            )
            total += len(chunks)

        logger.info(
            "Docs ingestion complete: %d chunk(s) from %d file(s) in %r.",
            total,
            len(md_files),
            str(self._docs_dir),
        )
        return total


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    docs_dir = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        count = DocsIngestion(docs_dir=docs_dir).ingest()
        print(f"\nDone — {count} chunk(s) indexed into the RAG knowledge store.")
    except Exception as exc:
        logger.exception("Docs ingestion failed: %s", exc)
        sys.exit(1)
