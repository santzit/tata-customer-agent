"""FastAPI application -- Tata customer support webhook server."""

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, status

from app.agent import run_agent
from app.chatwoot import ChatwootClient
from app.config import settings
from app.conversation_memory import ConversationMemory
from app.message_buffer import MessageBuffer
from app.pg_vector_store import PgVectorStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singletons (created once at startup)
# ---------------------------------------------------------------------------

_vector_store: PgVectorStore | None = None
_conversation_memory: ConversationMemory | None = None
_chatwoot_client: ChatwootClient | None = None
_message_buffer: MessageBuffer | None = None


# ---------------------------------------------------------------------------
# Background processing (called from the timer thread by MessageBuffer)
# ---------------------------------------------------------------------------


def _process_buffered_messages(conversation_id: int, combined_text: str) -> None:
    """Process all accumulated messages for *conversation_id* and reply via Chatwoot.

    This function runs in the :class:`~app.message_buffer.MessageBuffer` timer
    thread after the debounce window expires.  It calls the LangGraph agent with
    the combined text and delivers each reply part to Chatwoot.
    """
    logger.info(
        "Processing buffered messages for conversation %d (%d chars)",
        conversation_id,
        len(combined_text),
    )
    try:
        reply_parts = run_agent(
            user_message=combined_text,
            vector_store=_vector_store,
            conversation_memory=_conversation_memory,
            conversation_id=conversation_id,
        )
    except Exception as exc:
        logger.exception(
            "Agent error for conversation %d: %s", conversation_id, exc
        )
        return

    try:
        for part in reply_parts:
            _chatwoot_client.send_message(
                conversation_id=conversation_id, message=part
            )
    except Exception as exc:
        logger.exception(
            "Failed to send reply to Chatwoot for conversation %d: %s",
            conversation_id,
            exc,
        )


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _vector_store, _conversation_memory, _chatwoot_client, _message_buffer
    _vector_store = PgVectorStore()
    _conversation_memory = ConversationMemory()
    _chatwoot_client = ChatwootClient()
    _message_buffer = MessageBuffer(
        delay_seconds=settings.response_delay_seconds,
        on_flush=_process_buffered_messages,
    )
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
    """Receive Chatwoot webhook events and queue an AI-generated reply.

    The endpoint:

    1. Validates an optional webhook token.
    2. Ignores events that are not new incoming customer messages.
    3. Adds the message to the per-conversation :class:`~app.message_buffer.MessageBuffer`.
       Messages arriving within the debounce window (``RESPONSE_DELAY_SECONDS``,
       default 120 s) are batched together and processed as a single agent call once
       the window expires.
    4. Returns ``{"status": "queued"}`` immediately; the Chatwoot reply is sent
       from the buffer's background timer thread after the silence window closes.
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

    logger.info(
        "Queuing message for conversation %d (delay=%.0fs): %s",
        conversation_id,
        settings.response_delay_seconds,
        user_text[:80],
    )

    _message_buffer.add_message(conversation_id, user_text)

    return {"status": "queued", "conversation_id": conversation_id}
