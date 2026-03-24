"""Chatwoot API client for sending reply messages."""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ChatwootClient:
    """Thin wrapper around the Chatwoot REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
        account_id: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.chatwoot_base_url).rstrip("/")
        self.api_token = api_token or settings.chatwoot_api_token
        self.account_id = account_id if account_id is not None else settings.chatwoot_account_id

    def _headers(self) -> dict[str, str]:
        return {
            "api_access_token": self.api_token,
            "Content-Type": "application/json",
        }

    def send_message(
        self,
        conversation_id: int,
        message: str,
        *,
        message_type: str = "outgoing",
        private: bool = False,
    ) -> dict:
        """Send a message to a Chatwoot conversation.

        Args:
            conversation_id: The Chatwoot conversation ID.
            message: The text content to send.
            message_type: ``"outgoing"`` for agent replies visible to contacts.
            private: When ``True`` the message is a private note.

        Returns:
            The Chatwoot API response payload as a dict.

        Raises:
            httpx.HTTPStatusError: On non-2xx HTTP responses.
        """
        url = (
            f"{self.base_url}/api/v1/accounts/{self.account_id}"
            f"/conversations/{conversation_id}/messages"
        )
        payload = {
            "content": message,
            "message_type": message_type,
            "private": private,
        }
        logger.debug("Sending message to conversation %d: %s", conversation_id, message[:80])
        with httpx.Client(timeout=30) as client:
            response = client.post(url, json=payload, headers=self._headers())
            response.raise_for_status()
            result = response.json()
            logger.info(
                "Message sent to Chatwoot conversation %d (HTTP %d, message_id=%s)",
                conversation_id,
                response.status_code,
                result.get("id"),
            )
            return result

    def toggle_status(self, conversation_id: int, status: str) -> dict:
        """Change the status of a Chatwoot conversation.

        Args:
            conversation_id: The Chatwoot conversation ID.
            status: Target status — ``"open"``, ``"pending"``, or
                ``"resolved"``.

        Returns:
            The Chatwoot API response payload as a dict.

        Raises:
            httpx.HTTPStatusError: On non-2xx HTTP responses.
        """
        url = (
            f"{self.base_url}/api/v1/accounts/{self.account_id}"
            f"/conversations/{conversation_id}/toggle_status"
        )
        logger.debug(
            "Toggling conversation %d status to %r.", conversation_id, status
        )
        with httpx.Client(timeout=30) as client:
            response = client.post(url, json={"status": status}, headers=self._headers())
            response.raise_for_status()
            result = response.json()
            logger.info(
                "Chatwoot conversation %d status changed to %r (HTTP %d).",
                conversation_id,
                result.get("status"),
                response.status_code,
            )
            return result

    def handover_to_human(self, conversation_id: int) -> dict:
        """Hand over a conversation from the bot to a human agent.

        Changes the conversation status from ``"pending"`` (bot-handled) to
        ``"open"`` so that human agents can take over.  Once open, the bot
        stops receiving events for that conversation unless the status is
        switched back to ``"pending"``.

        Args:
            conversation_id: The Chatwoot conversation ID.

        Returns:
            The Chatwoot API response payload as a dict.

        Raises:
            httpx.HTTPStatusError: On non-2xx HTTP responses.
        """
        logger.info("Handing over conversation %d to a human agent.", conversation_id)
        result = self.toggle_status(conversation_id, "open")
        logger.info(
            "Chatwoot conversation %d handed over to human (status=%r).",
            conversation_id,
            result.get("status"),
        )
        return result
