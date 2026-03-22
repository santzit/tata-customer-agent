"""FastAPI application -- Tata customer support webhook server."""

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, status

from app.agent import run_agent
from app.chatwoot import ChatwootClient
from app.config import settings
from app.conversation_memory import ConversationMemory
from app.pg_vector_store import PgVectorStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singletons (created once at startup)
# ---------------------------------------------------------------------------

_vector_store: PgVectorStore | None = None
_conversation_memory: ConversationMemory | None = None
_chatwoot_client: ChatwootClient | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _vector_store, _conversation_memory, _chatwoot_client
    _vector_store = PgVectorStore()
    _conversation_memory = ConversationMemory()
    _chatwoot_client = ChatwootClient()
    for store in (_vector_store, _conversation_memory):
        try:
            store.ensure_collection()
        except Exception as exc:
            logger.warning("Could not connect to PostgreSQL at startup: %s", exc)
    yield


app = FastAPI(title="Tata Customer Agent", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verify_webhook_token(token: str | None) -> None:
    """Reject requests with an invalid webhook token (if one is configured)."""
    expected = settings.webhook_token
    if not expected:
        return
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _is_incoming_customer_message(payload: dict) -> bool:
    """Return True only for new messages sent *by* a contact (not the agent)."""
    if payload.get("event") != "message_created":
        return False
    msg = payload.get("message", {})
    # message_type: 0 = incoming, 1 = outgoing, 2 = activity
    return msg.get("message_type") == 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health_check() -> dict:
    """Liveness probe endpoint."""
    return {"status": "ok"}


@app.post("/webhook")
async def chatwoot_webhook(
    request: Request,
    x_chatwoot_signature: str | None = Header(default=None, alias="X-Chatwoot-Signature"),
) -> dict:
    """Receive Chatwoot webhook events and reply with AI-generated responses.

    The endpoint:

    1. Validates an optional webhook token.
    2. Ignores events that are not new incoming customer messages.
    3. Runs the LangGraph RAG agent to generate a reply.
    4. Posts the reply back to Chatwoot.
    """
    _verify_webhook_token(x_chatwoot_signature)

    payload: dict = await request.json()

    if not _is_incoming_customer_message(payload):
        return {"status": "ignored"}

    msg = payload["message"]
    conversation_id: int = msg.get("conversation_id") or payload.get("conversation", {}).get("id")
    user_text: str = msg.get("content", "")

    if not user_text or not conversation_id:
        return {"status": "ignored", "reason": "empty message or missing conversation_id"}

    logger.info("Processing message for conversation %d: %s", conversation_id, user_text[:80])

    try:
        reply_parts = run_agent(
            user_message=user_text,
            vector_store=_vector_store,
            conversation_memory=_conversation_memory,
            conversation_id=conversation_id,
        )
    except Exception as exc:
        logger.exception("Agent error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent failed to generate a response",
        ) from exc

    try:
        for part in reply_parts:
            _chatwoot_client.send_message(conversation_id=conversation_id, message=part)
    except Exception as exc:
        logger.exception("Failed to send reply to Chatwoot: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send reply to Chatwoot",
        ) from exc

    return {"status": "replied", "conversation_id": conversation_id}
