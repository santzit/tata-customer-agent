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

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
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

    When the supervisor escalates the conversation to a human agent, the
    escalation message is sent to the customer and the conversation status is
    changed to ``"open"`` so a human agent can take over in Chatwoot.
    """
    logger.info(
        "Processing buffered messages for conversation %d (%d chars)",
        conversation_id,
        len(combined_text),
    )
    logger.debug(
        "Buffered message content for conversation %d: %s",
        conversation_id,
        combined_text,
    )
    try:
        reply_parts, needs_human = run_agent(
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

    logger.info(
        "Agent produced %d reply part(s) for conversation %d (needs_human=%s)",
        len(reply_parts),
        conversation_id,
        needs_human,
    )
    try:
        for idx, part in enumerate(reply_parts, start=1):
            logger.debug(
                "Sending part %d/%d to Chatwoot for conversation %d: %s",
                idx,
                len(reply_parts),
                conversation_id,
                part[:120],
            )
            _chatwoot_client.send_message(
                conversation_id=conversation_id, message=part
            )
            logger.info(
                "Sent part %d/%d to Chatwoot for conversation %d",
                idx,
                len(reply_parts),
                conversation_id,
            )
        if needs_human:
            logger.info(
                "Handing off conversation %d to a human agent via Chatwoot.",
                conversation_id,
            )
            _chatwoot_client.handover_to_human(conversation_id=conversation_id)
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
    if settings.webhook_token:
        logger.info(
            "Webhook token authentication is ENABLED. "
            "Chatwoot must send the matching token in the X-Chatwoot-Signature header."
        )
    else:
        logger.info(
            "Webhook token authentication is DISABLED (WEBHOOK_TOKEN is not set). "
            "All incoming requests will be accepted without token verification."
        )
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
        logger.warning(
            "Webhook request rejected: WEBHOOK_TOKEN is set but the request "
            "did not include an X-Chatwoot-Signature header."
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    if not hmac.compare_digest(token, expected):
        logger.warning(
            "Webhook request rejected: X-Chatwoot-Signature token does not match "
            "the configured WEBHOOK_TOKEN."
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _is_incoming_customer_message(payload: dict) -> bool:
    """Return True only for new messages sent *by* a contact (not the agent).

    The Chatwoot agent bot webhook sends a flat payload where ``message_type``
    is a string (``"incoming"`` for customer messages, ``"outgoing"`` for agent
    or bot replies, ``"template"`` for channel-template messages) at the top
    level of the payload — not nested inside a ``"message"`` key.
    """
    if payload.get("event") != "message_created":
        return False
    return payload.get("message_type") == "incoming"


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
    logger.debug("Received Chatwoot webhook payload: %s", payload)

    if not _is_incoming_customer_message(payload):
        logger.debug(
            "Ignoring non-incoming event (event=%r, message_type=%r)",
            payload.get("event"),
            payload.get("message_type"),
        )
        return {"status": "ignored"}

    # Real Chatwoot agent bot payload: content and conversation_id are top-level fields.
    # The conversation object contains the internal id (int) and the display_id (str).
    user_text: str = payload.get("content", "")
    conversation: dict = payload.get("conversation", {})
    raw_conv_id = (
        payload.get("conversation_id")
        or conversation.get("id")
        or conversation.get("display_id")
    )
    try:
        conversation_id: int = int(raw_conv_id) if raw_conv_id is not None else 0
    except (TypeError, ValueError):
        conversation_id = 0

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
