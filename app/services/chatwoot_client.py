"""Chatwoot API client for sending reply messages and reading Help Center content."""

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

    # ------------------------------------------------------------------
    # Help Center (read-only) methods
    # ------------------------------------------------------------------

    def list_portals(self) -> list[dict]:
        """Return all Help Center portals for the configured account.

        Returns:
            A list of portal dicts as returned by the Chatwoot API.
            Returns an empty list on any error.
        """
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/portals"
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(url, headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.warning("ChatwootClient: failed to fetch portals: %s", exc)
            return []

        # Chatwoot returns {"payload": [...]} for the portals list.
        portals = data.get("payload", data) if isinstance(data, dict) else data
        if not isinstance(portals, list):
            logger.warning(
                "ChatwootClient: unexpected portals response shape: %r", type(data)
            )
            return []
        return portals

    def list_portal_articles(
        self, portal_slug: str, *, status: str = "published", page: int = 1
    ) -> dict:
        """Return one page of articles for *portal_slug*.

        Args:
            portal_slug: The slug of the Help Center portal.
            status: Article status filter (``"published"``, ``"draft"``, …).
            page: 1-based page number.

        Returns:
            The ``payload`` dict from the Chatwoot API response, containing
            ``articles`` (list) and ``meta`` (dict with ``total``).
            Returns an empty dict on any error.
        """
        url = (
            f"{self.base_url}/api/v1/accounts/{self.account_id}"
            f"/portals/{portal_slug}/articles"
        )
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    url,
                    params={"status": status, "page": page},
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.warning(
                "ChatwootClient: failed to fetch articles for portal '%s' page %d: %s",
                portal_slug,
                page,
                exc,
            )
            return {}

        # Chatwoot returns {"payload": {"articles": [...], "meta": {...}}}
        payload = data.get("payload", {}) if isinstance(data, dict) else {}
        if not isinstance(payload, dict):
            logger.warning(
                "ChatwootClient: unexpected articles payload shape for portal '%s': %r",
                portal_slug,
                type(payload),
            )
            return {}
        return payload

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
        url = (
            f"{self.base_url}/api/v1/accounts/{self.account_id}"
            f"/conversations/{conversation_id}/toggle_status"
        )
        logger.info("Handing over conversation %d to a human agent.", conversation_id)
        with httpx.Client(timeout=30) as client:
            response = client.post(url, json={"status": "open"}, headers=self._headers())
            response.raise_for_status()
            result = response.json()
            logger.info(
                "Chatwoot conversation %d handed over to human (HTTP %d, status=%r)",
                conversation_id,
                response.status_code,
                result.get("status"),
            )
            return result
