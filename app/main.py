"""FastAPI application -- Tata customer support webhook server."""

import hmac
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.agent import run_agent
from app.services.chatwoot_client import ChatwootClient
from app.config import settings
from app.conversation_memory import ConversationMemory
from app.db_bootstrap import ensure_database
from app.db_models import (
    create_pending_message,
    ensure_schema,
    fetch_messages_due_for_retry,
    mark_message_failed,
    mark_message_sent,
    reset_message_to_pending,
)
from app.hc_sync import HelpCenterSync
from app.message_buffer import MessageBuffer
from app.pg_vector_store import PgVectorStore
from app.routers import accounts, helpcenter, settings as settings_router, conversations as conversations_router, variables as variables_router

_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# basicConfig is a no-op when uvicorn has already installed handlers.
# Explicitly set the level on the root logger and the app namespace so
# the configured LOG_LEVEL takes effect regardless of launch method.
logging.getLogger().setLevel(_log_level)
logging.getLogger("app").setLevel(_log_level)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singletons (created once at startup)
# ---------------------------------------------------------------------------

_vector_store: PgVectorStore | None = None
_conversation_memory: ConversationMemory | None = None
_chatwoot_client: ChatwootClient | None = None
_message_buffer: MessageBuffer | None = None

# ---------------------------------------------------------------------------
# Message retry worker
# ---------------------------------------------------------------------------

#: How often the retry worker checks for overdue messages (seconds).
_RETRY_POLL_INTERVAL_SEC = 60


def _send_message_with_tracking(
    conversation_id: int,
    content: str,
    *,
    message_type: str = "outgoing",
    private: bool = False,
) -> None:
    """Persist and send a single outgoing message, updating send status.

    Creates a ``pending`` record before attempting the send, then marks it
    ``sent`` on success or ``failed`` (with retry scheduling) on error.

    Args:
        conversation_id: Chatwoot conversation id.
        content: Message text.
        message_type: ``"outgoing"`` for customer-visible replies.
        private: When ``True`` the message is a private note.
    """
    message_id: int | None = None
    try:
        message_id = create_pending_message(
            conversation_id,
            content,
            message_type=message_type,
            private=private,
        )
    except Exception as db_exc:
        logger.warning(
            "Could not persist outgoing message to DB (conv %d): %s",
            conversation_id,
            db_exc,
        )

    try:
        result = _chatwoot_client.send_message(
            conversation_id=conversation_id,
            message=content,
            message_type=message_type,
            private=private,
        )
        if message_id is not None:
            try:
                cw_msg_id = result.get("id")
                if cw_msg_id is None:
                    logger.warning(
                        "Chatwoot API response missing 'id' for conv %d; "
                        "marking sent without chatwoot_message_id",
                        conversation_id,
                    )
                mark_message_sent(message_id, cw_msg_id or 0)
            except Exception as db_exc:
                logger.warning("Could not mark message %d as sent: %s", message_id, db_exc)
    except Exception as send_exc:
        logger.exception(
            "Failed to send message to Chatwoot (conv %d): %s", conversation_id, send_exc
        )
        if message_id is not None:
            try:
                mark_message_failed(message_id, str(send_exc))
            except Exception as db_exc:
                logger.warning(
                    "Could not mark message %d as failed: %s", message_id, db_exc
                )
        raise


def _retry_failed_messages() -> None:
    """Fetch overdue failed messages and attempt to re-send them."""
    try:
        rows = fetch_messages_due_for_retry()
    except Exception as exc:
        logger.warning("Retry worker: failed to fetch messages due for retry: %s", exc)
        return

    for row in rows:
        msg_id = row["id"]
        conv_id = row["chatwoot_conv_id"]
        content = row["content"]
        logger.info(
            "Retry worker: retrying message id=%d (conv=%d, attempt=%d)",
            msg_id,
            conv_id,
            row["send_attempts"] + 1,
        )
        try:
            reset_message_to_pending(msg_id)
            result = _chatwoot_client.send_message(
                conversation_id=conv_id,
                message=content,
                message_type=row.get("message_type", "outgoing"),
                private=bool(row.get("private", False)),
            )
            cw_msg_id = result.get("id")
            if cw_msg_id is None:
                logger.warning(
                    "Retry worker: Chatwoot response missing 'id' for conv %d message %d",
                    conv_id,
                    msg_id,
                )
            mark_message_sent(msg_id, cw_msg_id or 0)
            logger.info("Retry worker: message id=%d sent successfully.", msg_id)
        except Exception as exc:
            logger.warning(
                "Retry worker: message id=%d re-send failed: %s", msg_id, exc
            )
            try:
                mark_message_failed(msg_id, str(exc))
            except Exception as db_exc:
                logger.warning(
                    "Retry worker: could not update failure status for message %d: %s",
                    msg_id,
                    db_exc,
                )


def _start_retry_worker(stop_event: threading.Event) -> threading.Thread:
    """Start a daemon thread that periodically retries failed messages.

    Args:
        stop_event: Set this event to stop the retry loop cleanly.

    Returns:
        The started :class:`threading.Thread`.
    """

    def _worker() -> None:
        logger.info(
            "Message retry worker started (poll every %ds).",
            _RETRY_POLL_INTERVAL_SEC,
        )
        while not stop_event.wait(_RETRY_POLL_INTERVAL_SEC):
            _retry_failed_messages()
        logger.info("Message retry worker stopped.")

    thread = threading.Thread(target=_worker, name="message-retry-worker", daemon=True)
    thread.start()
    return thread


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
            try:
                _send_message_with_tracking(conversation_id=conversation_id, content=part)
            except Exception:
                # Error already logged and persisted inside _send_message_with_tracking.
                pass
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

    # ------------------------------------------------------------------
    # 1. Ensure the tata_agent database exists (creates it if missing).
    # ------------------------------------------------------------------
    try:
        ensure_database()
    except Exception as exc:
        logger.warning("Database bootstrap failed (continuing anyway): %s", exc)

    # ------------------------------------------------------------------
    # 2. Ensure all entity tables exist in tata_agent.
    # ------------------------------------------------------------------
    try:
        ensure_schema()
    except Exception as exc:
        logger.warning("Entity schema setup failed (continuing anyway): %s", exc)

    # ------------------------------------------------------------------
    # 3. Initialise RAG vector store and conversation memory.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 4. Sync Help Center articles into the RAG vector store.
    # ------------------------------------------------------------------
    try:
        logger.info("Triggering Help Center article sync into the RAG vector store.")
        hc_sync = HelpCenterSync(_vector_store)
        hc_sync.run()
    except Exception as exc:
        logger.warning("Help Center sync failed at startup (continuing anyway): %s", exc)

    # ------------------------------------------------------------------
    # 5. Start background retry worker for failed outgoing messages.
    # ------------------------------------------------------------------
    _retry_stop = threading.Event()
    _start_retry_worker(_retry_stop)

    logger.info(
        "Chatwoot client configured: base_url=%r, account_id=%d, api_token_set=%s",
        settings.chatwoot_base_url,
        settings.chatwoot_account_id,
        bool(settings.chatwoot_api_token),
    )
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

    # ------------------------------------------------------------------
    # Shutdown: stop the retry worker cleanly.
    # ------------------------------------------------------------------
    _retry_stop.set()


app = FastAPI(title="Tata Customer Agent", version="1.0.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS — allow the Next.js frontend (dev: port 3000, prod: same origin)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(accounts.router)
app.include_router(settings_router.router)
app.include_router(helpcenter.router)
app.include_router(conversations_router.router)
app.include_router(variables_router.router)


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


@app.get("/")
async def root_redirect():
    """Redirect browser requests to the Next.js frontend.

    The web UI is served by the ``tata-frontend`` container on port 3000.
    Redirecting from the API root prevents a confusing 404 when users open
    ``http://localhost:8000`` in a browser.
    """
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="http://localhost:3000", status_code=302)


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
