"""Qdrant-backed conversation memory for multi-turn chat history.

Each conversation turn (user message + assistant reply) is stored as two
payload-only points in a dedicated Qdrant collection.  History is retrieved
via Qdrant's ``scroll`` API filtered by ``conversation_id`` — no vector
similarity search is required.

Why Qdrant instead of pgvector?
- Qdrant is already in the stack; no extra service is needed.
- ``scroll`` + payload filtering gives fast chronological retrieval.
- Storing embeddings alongside messages enables optional semantic search
  over history in the future (e.g. "what did the user ask about yesterday?").
- pgvector / PostgreSQL would be a better fit if you need ACID transactions,
  complex relational queries, or analytics over conversation data.
"""

import hashlib
import logging
import time
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    OrderBy,
    PointStruct,
    VectorParams,
)

from app.config import settings

logger = logging.getLogger(__name__)

# We store a tiny 1-dimensional dummy vector because Qdrant collections
# require vectors.  Actual retrieval uses payload filtering, not ANN search.
_DUMMY_VECTOR_SIZE = 1
_DUMMY_VECTOR = [0.0]


def _point_id(conversation_id: int, role: str, timestamp_ms: int) -> int:
    """Return a deterministic unsigned 64-bit integer point ID."""
    key = f"{conversation_id}:{role}:{timestamp_ms}"
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**64)


class ConversationMemory:
    """Stores and retrieves per-conversation message history in Qdrant."""

    def __init__(
        self,
        qdrant_url: str | None = None,
        qdrant_api_key: str | None = None,
        collection: str | None = None,
        qdrant_client: Any | None = None,
    ) -> None:
        self.collection = collection or settings.qdrant_memory_collection
        self._qdrant = qdrant_client or QdrantClient(
            url=qdrant_url or settings.qdrant_url,
            api_key=qdrant_api_key or settings.qdrant_api_key or None,
        )

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def ensure_collection(self) -> None:
        """Create the memory collection if it does not already exist."""
        existing = {c.name for c in self._qdrant.get_collections().collections}
        if self.collection not in existing:
            self._qdrant.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=_DUMMY_VECTOR_SIZE, distance=Distance.DOT
                ),
            )
            logger.info("Created memory collection '%s'", self.collection)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def add_turn(
        self,
        conversation_id: int,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        """Persist one conversation turn (user + assistant) to Qdrant.

        Args:
            conversation_id: Chatwoot conversation ID.
            user_message: The customer's message text.
            assistant_reply: Tata's generated reply text.
        """
        now_ms = int(time.time() * 1000)
        points = [
            PointStruct(
                id=_point_id(conversation_id, "user", now_ms),
                vector=_DUMMY_VECTOR,
                payload={
                    "conversation_id": conversation_id,
                    "role": "user",
                    "content": user_message,
                    "timestamp_ms": now_ms,
                    "role_order": 0,
                },
            ),
            PointStruct(
                id=_point_id(conversation_id, "assistant", now_ms),
                vector=_DUMMY_VECTOR,
                payload={
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": assistant_reply,
                    "timestamp_ms": now_ms,
                    "role_order": 1,
                },
            ),
        ]
        self._qdrant.upsert(collection_name=self.collection, points=points)
        logger.debug(
            "Saved turn for conversation %d (%d chars user, %d chars reply)",
            conversation_id,
            len(user_message),
            len(assistant_reply),
        )

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get_history(
        self, conversation_id: int, max_turns: int | None = None
    ) -> list[dict[str, str]]:
        """Return recent messages for *conversation_id* as OpenAI chat messages.

        Args:
            conversation_id: Chatwoot conversation ID.
            max_turns: Maximum number of turns (user+assistant pairs) to return.
                       Defaults to ``settings.memory_max_turns``.

        Returns:
            A list of ``{"role": ..., "content": ...}`` dicts, oldest first,
            ready to be inserted into an OpenAI ``messages`` array.
        """
        limit = (max_turns or settings.memory_max_turns) * 2  # 2 messages per turn
        conv_filter = Filter(
            must=[
                FieldCondition(
                    key="conversation_id",
                    match=MatchValue(value=conversation_id),
                )
            ]
        )
        points, _ = self._qdrant.scroll(
            collection_name=self.collection,
            scroll_filter=conv_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
            order_by=OrderBy(key="timestamp_ms", direction="desc"),
        )
        # Reverse to chronological order (oldest → newest)
        messages = [
            {"role": p.payload["role"], "content": p.payload["content"]}
            for p in reversed(points)
        ]
        logger.debug(
            "Loaded %d history messages for conversation %d",
            len(messages),
            conversation_id,
        )
        return messages
