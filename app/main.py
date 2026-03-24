"""FastAPI application -- Tata customer support webhook server."""

import hmac
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, status

from app.agent import run_agent
from app.chatwoot import ChatwootClient
from app.config import settings
from app.conversation_memory import ConversationMemory
from app.message_buffer import MessageBuffer
from app.pg_vector_store import PgVectorStore

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
        else:
            # Move the conversation from "pending" to "open" so that the bot's
            # replies are visible in the Chatwoot Inbox/Conversations view.
            # While the bot handled this turn autonomously, keeping the
            # conversation in "pending" status hides it from the normal inbox,
            # so agents cannot see the exchange.
            logger.info(
                "Setting conversation %d to 'open' so replies are visible in Chatwoot inbox.",
                conversation_id,
            )
            _chatwoot_client.toggle_status(conversation_id=conversation_id, status="open")
    except Exception as exc:
        logger.exception(
            "Failed to send reply to Chatwoot for conversation %d: %s",
            conversation_id,
            exc,
        )


def _start_hc_sync_background() -> None:
    """Run a Chatwoot Help Center sync in a background daemon thread.

    Fires once at startup when ``CHATWOOT_DSN`` is set and
    ``HC_SYNC_ON_STARTUP`` is ``true``.  Runs as a daemon so it does not
    block the process from shutting down.  Any errors are logged as warnings
    and do not affect the webhook server.
    """
    from app.hc_sync import HelpCenterSync

    def _run() -> None:
        try:
            sync = HelpCenterSync(vector_store=_vector_store)
            count = sync.sync()
            logger.info("Startup HC sync complete: %d article(s) indexed.", count)
        except Exception as exc:
            logger.warning("Startup HC sync failed (RAG will use existing data): %s", exc)

    thread = threading.Thread(target=_run, name="hc-sync", daemon=True)
    thread.start()
    logger.info(
        "Help Center sync started in background thread "
        "(CHATWOOT_DSN configured, account_id=%d).",
        settings.chatwoot_account_id,
    )


def _start_docs_ingest_background() -> None:
    """Ingest markdown files from ``DOCS_DIR`` in a background daemon thread.

    Fires once at startup when ``DOCS_DIR`` is set.  Errors are logged as
    warnings and do not affect the webhook server.
    """
    from app.ingest_docs import DocsIngestion

    def _run() -> None:
        try:
            ingestor = DocsIngestion(docs_dir=settings.docs_dir, vector_store=_vector_store)
            count = ingestor.ingest()
            logger.info(
                "Startup docs ingestion complete: %d chunk(s) indexed from %r.",
                count,
                settings.docs_dir,
            )
        except Exception as exc:
            logger.warning("Startup docs ingestion failed (RAG will use existing data): %s", exc)

    thread = threading.Thread(target=_run, name="docs-ingest", daemon=True)
    thread.start()
    logger.info(
        "Docs ingestion started in background thread (DOCS_DIR=%r).",
        settings.docs_dir,
    )


def _log_knowledge_store_status() -> None:
    """Log the number of documents in the knowledge store.

    Emits a prominent WARNING when the store is empty so operators can
    immediately see that RAG will not return any context.  This is the most
    common reason the bot answers "I'm not sure" for every question on a
    fresh deployment.
    """
    if _vector_store is None:
        return
    doc_count = _vector_store.count()
    if doc_count < 0:
        logger.warning(
            "RAG knowledge store: could not determine document count "
            "(table may not exist yet — it will be created on first sync)."
        )
    elif doc_count == 0:
        logger.warning(
            "RAG knowledge store is EMPTY — the bot will answer 'I'm not sure' "
            "for every question until documents are indexed. "
            "To populate it, choose one of:\n"
            "  1. Set CHATWOOT_DSN and run: python -m app.hc_sync\n"
            "  2. Set DOCS_DIR to a directory of .md files and restart, or run: "
            "python -m app.ingest_docs [/path/to/docs]"
        )
    else:
        logger.info(
            "RAG knowledge store: %d document(s) indexed and ready.", doc_count
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

    if settings.chatwoot_dsn and settings.hc_sync_on_startup:
        _start_hc_sync_background()

    if settings.docs_dir:
        _start_docs_ingest_background()

    # Log knowledge-store size so operators can confirm RAG is populated.
    _log_knowledge_store_status()

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
    """Liveness probe and RAG status endpoint.

    Returns the number of documents indexed in the knowledge store so
    operators can verify RAG is populated without inspecting logs.
    A ``knowledge_docs`` value of ``0`` means the store is empty and the
    bot will reply "I'm not sure" to every question.
    """
    doc_count = _vector_store.count() if _vector_store else -1
    return {"status": "ok", "knowledge_docs": doc_count}


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
