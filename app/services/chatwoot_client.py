"""Chatwoot API client — organized by API domain.

Follows the same pattern as the Ruby Chatwoot demo client
(chatwoot/dialogflow-agent-bot-demo), with a common HTTP helper
(``_get`` / ``_post``) shared by all sub-API sections.

Sub-API sections are accessed as attributes of :class:`ChatwootClient`:

    client.conversations.send_message(conv_id, text)
    client.conversations.list_conversations(account_id=1)
    client.conversations.get_messages(conv_id, account_id=1)
    client.conversations.handover_to_human(conv_id)

    client.accounts.list()

    client.inboxes.list(account_id=1)
    client.inboxes.list_teams(account_id=1)

    client.help_center.list_portals(account_id=1)
    client.help_center.list_portal_articles(slug, account_id=1)

Backward-compatible proxy methods are kept on the top-level
:class:`ChatwootClient` so existing callers (``app/main.py``,
``app/hc_sync.py``) work without changes.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ChatwootClient:
    """Chatwoot REST API client.

    Args:
        base_url: Base URL of the Chatwoot instance.
        api_token: ``api_access_token`` used in all request headers.
        account_id: Default account ID used when sub-API calls omit ``account_id``.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
        account_id: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.chatwoot_base_url).rstrip("/")
        self.api_token = api_token or settings.chatwoot_api_token
        self.account_id = account_id if account_id is not None else settings.chatwoot_account_id

        # Sub-API sections
        self.conversations = _ConversationsAPI(self)
        self.accounts = _AccountsAPI(self)
        self.inboxes = _InboxesAPI(self)
        self.help_center = _HelpCenterAPI(self)

    # ------------------------------------------------------------------
    # Common HTTP helpers — mirrors Ruby demo's ``self.post`` pattern
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "api_access_token": self.api_token,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, *, params: dict | None = None) -> Any:
        """Send a GET request and return the parsed JSON body.

        Mirrors the common HTTP helper in the Ruby demo (``self.post``).

        Args:
            path: API path relative to ``base_url`` (e.g. ``/api/v1/accounts/1/inboxes``).
            params: Optional query-string parameters.

        Raises:
            httpx.HTTPStatusError: On non-2xx HTTP responses.
        """
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, payload: dict | None = None) -> Any:
        """Send a POST request with a JSON body and return the parsed response.

        Directly mirrors Ruby demo's ``self.post(url, payload)``.

        Args:
            path: API path relative to ``base_url``.
            payload: JSON-serialisable dict to send as the request body.

        Raises:
            httpx.HTTPStatusError: On non-2xx HTTP responses.
        """
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=30) as client:
            response = client.post(url, json=payload or {}, headers=self._headers())
            response.raise_for_status()
            return response.json()

    # ------------------------------------------------------------------
    # Backward-compatible proxy methods
    # (keep existing app/main.py and app/hc_sync.py callers working)
    # ------------------------------------------------------------------

    def send_message(
        self,
        conversation_id: int,
        message: str,
        *,
        message_type: str = "outgoing",
        private: bool = False,
    ) -> dict:
        """Send a message to a Chatwoot conversation.

        Delegates to :meth:`_ConversationsAPI.send_message`.
        """
        return self.conversations.send_message(
            conversation_id,
            message,
            message_type=message_type,
            private=private,
        )

    def list_portals(self) -> list[dict]:
        """Return all Help Center portals for the configured account.

        Delegates to :meth:`_HelpCenterAPI.list_portals`.
        """
        return self.help_center.list_portals()

    def list_portal_articles(
        self,
        portal_slug: str,
        *,
        status: str = "published",
        page: int = 1,
    ) -> dict:
        """Return one page of articles for *portal_slug*.

        Delegates to :meth:`_HelpCenterAPI.list_portal_articles`.
        """
        return self.help_center.list_portal_articles(portal_slug, status=status, page=page)

    def handover_to_human(self, conversation_id: int) -> dict:
        """Hand over a conversation from the bot to a human agent.

        Delegates to :meth:`_ConversationsAPI.handover_to_human`.
        """
        return self.conversations.handover_to_human(conversation_id)


# ---------------------------------------------------------------------------
# Sub-API: Conversations
# ---------------------------------------------------------------------------


class _ConversationsAPI:
    """Conversation-related Chatwoot API calls."""

    def __init__(self, client: ChatwootClient) -> None:
        self._c = client

    def _aid(self, account_id: int | None) -> int:
        return account_id or self._c.account_id

    def send_message(
        self,
        conversation_id: int,
        message: str,
        *,
        message_type: str = "outgoing",
        private: bool = False,
        account_id: int | None = None,
    ) -> dict:
        """Send a reply message to a conversation.

        Args:
            conversation_id: Chatwoot conversation ID.
            message: Text content to send.
            message_type: ``"outgoing"`` for agent replies visible to contacts.
            private: When ``True`` the message is a private note.
            account_id: Override the client's default account ID.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
        """
        aid = self._aid(account_id)
        logger.debug("Sending message to conversation %d: %s", conversation_id, message[:80])
        result = self._c._post(
            f"/api/v1/accounts/{aid}/conversations/{conversation_id}/messages",
            {"content": message, "message_type": message_type, "private": private},
        )
        logger.info(
            "Message sent to Chatwoot conversation %d (message_id=%s)",
            conversation_id,
            result.get("id"),
        )
        return result

    def handover_to_human(
        self,
        conversation_id: int,
        *,
        status: str = "open",
        account_id: int | None = None,
    ) -> dict:
        """Change conversation status to *status* (default ``"open"``).

        This hands the conversation off from the bot to a human agent.

        Args:
            conversation_id: Chatwoot conversation ID.
            status: Target status (``"open"`` to un-assign from the bot).
            account_id: Override the client's default account ID.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
        """
        aid = self._aid(account_id)
        logger.info("Handing over conversation %d to a human agent.", conversation_id)
        result = self._c._post(
            f"/api/v1/accounts/{aid}/conversations/{conversation_id}/toggle_status",
            {"status": status},
        )
        logger.info(
            "Conversation %d handed over (status=%r).",
            conversation_id,
            result.get("status"),
        )
        return result

    def list_conversations(
        self,
        *,
        account_id: int | None = None,
        page: int = 1,
        inbox_id: int | None = None,
    ) -> dict:
        """Return one page of conversations for an account.

        Args:
            account_id: Override the client's default account ID.
            page: 1-based page number.
            inbox_id: Filter by inbox ID (optional).

        Returns:
            The ``data`` dict from the Chatwoot response (contains ``payload``
            list and ``meta`` dict).  Returns an empty dict on any error.
        """
        aid = self._aid(account_id)
        params: dict = {"page": page}
        if inbox_id:
            params["inbox_id"] = inbox_id
        try:
            data = self._c._get(f"/api/v1/accounts/{aid}/conversations", params=params)
        except Exception as exc:
            logger.warning(
                "ConversationsAPI: failed to list conversations for account %d: %s", aid, exc
            )
            return {}
        return data.get("data", {}) if isinstance(data, dict) else {}

    def get_messages(
        self,
        conversation_id: int,
        *,
        account_id: int | None = None,
    ) -> list[dict]:
        """Return all messages for *conversation_id*.

        Args:
            conversation_id: Chatwoot conversation ID.
            account_id: Override the client's default account ID.

        Returns:
            List of message dicts.  Returns an empty list on any error.
        """
        aid = self._aid(account_id)
        try:
            data = self._c._get(
                f"/api/v1/accounts/{aid}/conversations/{conversation_id}/messages"
            )
        except Exception as exc:
            logger.warning(
                "ConversationsAPI: failed to get messages for conversation %d: %s",
                conversation_id,
                exc,
            )
            return []
        messages = data.get("payload", []) if isinstance(data, dict) else data
        return messages if isinstance(messages, list) else []


# ---------------------------------------------------------------------------
# Sub-API: Accounts
# ---------------------------------------------------------------------------


class _AccountsAPI:
    """Account-related Chatwoot API calls (super-admin / master token required)."""

    def __init__(self, client: ChatwootClient) -> None:
        self._c = client

    def list(self) -> list[dict]:
        """Return all Chatwoot accounts visible to the authenticated user.

        Uses ``GET /api/v1/profile`` (works with any user token, including
        the master token) which returns the user's profile with an ``accounts``
        array listing every account they are a member of.

        Returns:
            List of account dicts.  Returns an empty list on any error.
        """
        try:
            data = self._c._get("/api/v1/profile")
        except Exception as exc:
            logger.warning("AccountsAPI: failed to list accounts: %s", exc)
            return []
        if not isinstance(data, dict):
            return []
        accounts = data.get("accounts", [])
        # Normalise: ensure each entry has 'id' and 'name' at the top level.
        result = []
        for entry in accounts:
            if isinstance(entry, dict) and "id" in entry:
                result.append(entry)
        return result


# ---------------------------------------------------------------------------
# Sub-API: Inboxes / Teams
# ---------------------------------------------------------------------------


class _InboxesAPI:
    """Inbox and team Chatwoot API calls."""

    def __init__(self, client: ChatwootClient) -> None:
        self._c = client

    def _aid(self, account_id: int | None) -> int:
        return account_id or self._c.account_id

    def list(self, *, account_id: int | None = None) -> list[dict]:
        """Return all inboxes for an account.

        Args:
            account_id: Override the client's default account ID.

        Returns:
            List of inbox dicts.  Returns an empty list on any error.
        """
        aid = self._aid(account_id)
        try:
            data = self._c._get(f"/api/v1/accounts/{aid}/inboxes")
        except Exception as exc:
            logger.warning("InboxesAPI: failed to list inboxes for account %d: %s", aid, exc)
            return []
        payload = data.get("payload", data) if isinstance(data, dict) else data
        return payload if isinstance(payload, list) else []

    def list_teams(self, *, account_id: int | None = None) -> list[dict]:
        """Return all teams for an account.

        Args:
            account_id: Override the client's default account ID.

        Returns:
            List of team dicts.  Returns an empty list on any error.
        """
        aid = self._aid(account_id)
        try:
            data = self._c._get(f"/api/v1/accounts/{aid}/teams")
        except Exception as exc:
            logger.warning("InboxesAPI: failed to list teams for account %d: %s", aid, exc)
            return []
        if isinstance(data, list):
            return data
        return data.get("payload", data) if isinstance(data, dict) else []


# ---------------------------------------------------------------------------
# Sub-API: Help Center
# ---------------------------------------------------------------------------


class _HelpCenterAPI:
    """Help Center (portals + articles) Chatwoot API calls."""

    def __init__(self, client: ChatwootClient) -> None:
        self._c = client

    def _aid(self, account_id: int | None) -> int:
        return account_id or self._c.account_id

    def list_portals(self, *, account_id: int | None = None) -> list[dict]:
        """Return all Help Center portals for an account.

        Args:
            account_id: Override the client's default account ID.

        Returns:
            List of portal dicts.  Returns an empty list on any error.
        """
        aid = self._aid(account_id)
        try:
            data = self._c._get(f"/api/v1/accounts/{aid}/portals")
        except Exception as exc:
            logger.warning("HelpCenterAPI: failed to fetch portals: %s", exc)
            return []
        portals = data.get("payload", data) if isinstance(data, dict) else data
        if not isinstance(portals, list):
            logger.warning(
                "HelpCenterAPI: unexpected portals response shape: %r", type(data)
            )
            return []
        return portals

    def list_portal_articles(
        self,
        portal_slug: str,
        *,
        account_id: int | None = None,
        status: str = "published",
        page: int = 1,
    ) -> dict:
        """Return one page of articles for *portal_slug*.

        Args:
            portal_slug: Help Center portal slug.
            account_id: Override the client's default account ID.
            status: Article status filter (``"published"``, ``"draft"``, …).
            page: 1-based page number.

        Returns:
            The ``payload`` dict from the Chatwoot response, containing
            ``articles`` (list) and ``meta`` (dict).
            Returns an empty dict on any error.
        """
        aid = self._aid(account_id)
        try:
            data = self._c._get(
                f"/api/v1/accounts/{aid}/portals/{portal_slug}/articles",
                params={"status": status, "page": page},
            )
        except Exception as exc:
            logger.warning(
                "HelpCenterAPI: failed to fetch articles for portal '%s' page %d: %s",
                portal_slug,
                page,
                exc,
            )
            return {}
        payload = data.get("payload", {}) if isinstance(data, dict) else {}
        # Chatwoot returns payload as a list of articles; normalise to a dict
        # with an "articles" key so callers (hc_sync.py) can use payload.get("articles").
        if isinstance(payload, list):
            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            return {"articles": payload, "meta": meta}
        if not isinstance(payload, dict):
            logger.warning(
                "HelpCenterAPI: unexpected articles payload shape for portal '%s': %r",
                portal_slug,
                type(payload),
            )
            return {}
        return payload
