"""API routes for displaying recent conversation messages."""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app import db_models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class MessageOut(BaseModel):
    id: int
    chatwoot_conv_id: int
    content: str
    message_type: str
    status: str
    send_attempts: int
    error: str | None
    created_at: str
    updated_at: str


@router.get("/messages", response_model=list[MessageOut])
def list_recent_messages(limit: int = Query(default=10, ge=1, le=100)):
    """Return the most recent outgoing messages, ordered newest-first.

    Args:
        limit: Maximum number of messages to return (1–100, default 10).
    """
    rows = db_models.list_recent_messages(limit=limit)
    return [
        MessageOut(
            id=r["id"],
            chatwoot_conv_id=r["chatwoot_conv_id"],
            content=r["content"],
            message_type=r["message_type"],
            status=r["status"],
            send_attempts=r["send_attempts"],
            error=r.get("error"),
            created_at=str(r["created_at"]),
            updated_at=str(r["updated_at"]),
        )
        for r in rows
    ]
