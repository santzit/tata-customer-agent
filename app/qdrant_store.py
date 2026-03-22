"""Qdrant-backed knowledge store for retrieval-augmented generation (RAG)."""

import hashlib
import logging
from typing import Any

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from app.config import settings

logger = logging.getLogger(__name__)

_VECTOR_SIZE = 1536  # text-embedding-3-small output dimension


class QdrantStore:
    """Manages the Qdrant vector collection and similarity search."""

    def __init__(
        self,
        qdrant_url: str | None = None,
        qdrant_api_key: str | None = None,
        collection: str | None = None,
        openai_client: Any | None = None,
    ) -> None:
        self.collection = collection or settings.qdrant_collection
        self._openai = openai_client or OpenAI(api_key=settings.openai_api_key)
        self._qdrant = QdrantClient(
            url=qdrant_url or settings.qdrant_url,
            api_key=qdrant_api_key or settings.qdrant_api_key or None,
        )

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def ensure_collection(self) -> None:
        """Create the Qdrant collection if it does not already exist."""
        existing = {c.name for c in self._qdrant.get_collections().collections}
        if self.collection not in existing:
            self._qdrant.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=_VECTOR_SIZE, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection '%s'", self.collection)

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list[float]:
        response = self._openai.embeddings.create(
            model=settings.openai_embedding_model,
            input=text,
        )
        return response.data[0].embedding

    def upsert(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        """Embed *text* and upsert it into the collection.

        Args:
            doc_id: Unique string identifier for the document.
            text: The raw text to embed.
            metadata: Optional payload stored alongside the vector.
        """
        from qdrant_client.http.models import PointStruct

        vector = self._embed(text)
        payload = {"text": text, **(metadata or {})}
        point = PointStruct(
            id=int(hashlib.sha256(doc_id.encode()).hexdigest(), 16) % (2**63),
            vector=vector,
            payload=payload,
        )
        self._qdrant.upsert(collection_name=self.collection, points=[point])
        logger.debug("Upserted document '%s' into '%s'", doc_id, self.collection)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return the *top_k* most relevant knowledge snippets for *query*.

        Returns:
            A list of payload dicts, each containing at least a ``"text"`` key.
        """
        vector = self._embed(query)
        results = self._qdrant.search(
            collection_name=self.collection,
            query_vector=vector,
            limit=top_k,
        )
        return [hit.payload for hit in results]
