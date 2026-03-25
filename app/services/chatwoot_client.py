"""Rich Chatwoot API client with support for interactive message types.

This module is a Python port of the Ruby ``ChatwootClient`` from the
`Chatwoot Dialogflow Agent Bot Demo
<https://github.com/chatwoot/dialogflow-agent-bot-demo/blob/main/app/services/chatwoot_client.rb>`_,
extended with all Chatwoot interactive content types and conversation
management helpers.

Usage example::

    from app.services import ChatwootClient

    client = ChatwootClient()          # reads settings from .env

    # Plain text reply
    client.send_message(conversation_id, "Hello! How can I help you?")

    # Interactive select (customer picks one option)
    client.send_options_message(
        conversation_id,
        "Which plan are you interested in?",
        [
            {"title": "Basic — R$150/mo",   "value": "basic"},
            {"title": "Standard — R$250/mo", "value": "standard"},
            {"title": "Premium — R$400/mo",  "value": "premium"},
        ],
    )

    # Form (collects structured data from the customer)
    client.send_form_message(
        conversation_id,
        "Please fill in your details:",
        [
            {"label": "Full name",  "name": "name",  "type": "text",  "required": True},
            {"label": "Email",      "name": "email", "type": "email", "required": True},
            {"label": "Phone",      "name": "phone", "type": "text",  "required": False},
        ],
    )

    # Cards / carousel
    client.send_cards_message(
        conversation_id,
        "Our membership plans:",
        [
            {
                "title":       "Basic",
                "description": "Unlimited group classes + gym floor access.",
                "cta":         [{"type": "link", "label": "Sign up", "url": "https://nova-gym.com/join"}],
            },
        ],
    )

    # Hand off to a human agent
    client.handoff_conversation(conversation_id)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ChatwootClient:
    """Full-featured Chatwoot API client.

    Supports plain text, interactive (options, form, cards, article), and
    conversation management operations.

    All message-sending methods accept an optional *private* flag — when
    ``True`` the message is posted as a private agent note instead of a
    customer-visible reply.

    Args:
        base_url:   Base URL of the Chatwoot instance (default: ``CHATWOOT_BASE_URL``).
        api_token:  Agent bot API token (default: ``CHATWOOT_API_TOKEN``).
        account_id: Chatwoot account ID (default: ``CHATWOOT_ACCOUNT_ID``).
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
        account_id: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.chatwoot_base_url).rstrip("/")
        self.api_token = api_token or settings.chatwoot_api_token
        self.account_id = (
            account_id if account_id is not None else settings.chatwoot_account_id
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "api_access_token": self.api_token,
            "Content-Type": "application/json",
        }

    def _messages_url(self, conversation_id: int) -> str:
        return (
            f"{self.base_url}/api/v1/accounts/{self.account_id}"
            f"/conversations/{conversation_id}/messages"
        )

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST *payload* to *url* and return the parsed JSON response.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
        """
        with httpx.Client(timeout=30) as client:
            response = client.post(url, json=payload, headers=self._headers())
            response.raise_for_status()
            return response.json()

    def _send(
        self,
        conversation_id: int,
        payload: dict[str, Any],
        *,
        private: bool = False,
    ) -> dict[str, Any]:
        """Send a message payload to *conversation_id*.

        Merges shared fields (*message_type*, *private*) into *payload* and
        POSTs to the Chatwoot messages endpoint.
        """
        payload.setdefault("message_type", "outgoing")
        payload["private"] = private
        url = self._messages_url(conversation_id)
        logger.debug(
            "Posting message to conversation %d (content_type=%r, private=%s).",
            conversation_id,
            payload.get("content_type", "text"),
            private,
        )
        result = self._post(url, payload)
        logger.info(
            "Message sent to Chatwoot conversation %d (id=%s, content_type=%r).",
            conversation_id,
            result.get("id"),
            payload.get("content_type", "text"),
        )
        return result

    # ------------------------------------------------------------------
    # Plain text
    # ------------------------------------------------------------------

    def send_message(
        self,
        conversation_id: int,
        message: str,
        *,
        private: bool = False,
    ) -> dict[str, Any]:
        """Send a plain-text message to *conversation_id*.

        Args:
            conversation_id: Chatwoot conversation ID.
            message:         Text content to send.
            private:         Post as a private note when ``True``.

        Returns:
            Chatwoot API response payload.
        """
        return self._send(
            conversation_id,
            {"content": message},
            private=private,
        )

    # ------------------------------------------------------------------
    # Interactive — input_select (option picker)
    # ------------------------------------------------------------------

    def send_options_message(
        self,
        conversation_id: int,
        message: str,
        items: list[dict[str, str]],
        *,
        private: bool = False,
    ) -> dict[str, Any]:
        """Send an interactive option-picker message.

        The customer sees a list of buttons and can select one. Their choice
        is sent back to the webhook as ``content_attributes.submitted_values``.

        Args:
            conversation_id: Chatwoot conversation ID.
            message:         Prompt shown above the options.
            items:           List of ``{"title": str, "value": str}`` dicts.
            private:         Post as a private note when ``True``.

        Example::

            client.send_options_message(
                conversation_id,
                "Escolha um plano:",
                [
                    {"title": "Basic",    "value": "basic"},
                    {"title": "Standard", "value": "standard"},
                    {"title": "Premium",  "value": "premium"},
                ],
            )

        Returns:
            Chatwoot API response payload.
        """
        return self._send(
            conversation_id,
            {
                "content": message,
                "content_type": "input_select",
                "content_attributes": {"items": items},
            },
            private=private,
        )

    # ------------------------------------------------------------------
    # Interactive — form (structured data collection)
    # ------------------------------------------------------------------

    def send_form_message(
        self,
        conversation_id: int,
        message: str,
        items: list[dict[str, Any]],
        *,
        private: bool = False,
    ) -> dict[str, Any]:
        """Send an interactive form to collect structured data.

        Submitted values are returned to the webhook as
        ``content_attributes.submitted_values``.

        Args:
            conversation_id: Chatwoot conversation ID.
            message:         Title / instruction shown above the form.
            items:           List of field descriptors.  Each field supports:

                             - ``"label"`` (str) — visible field label.
                             - ``"name"`` (str) — field identifier in submitted values.
                             - ``"type"`` (str) — ``"text"``, ``"email"``, ``"number"``, etc.
                             - ``"required"`` (bool) — whether the field is mandatory.
                             - ``"placeholder"`` (str, optional) — placeholder hint.

            private:         Post as a private note when ``True``.

        Example::

            client.send_form_message(
                conversation_id,
                "Preencha seus dados:",
                [
                    {"label": "Nome completo", "name": "name",  "type": "text",  "required": True},
                    {"label": "E-mail",        "name": "email", "type": "email", "required": True},
                    {"label": "Telefone",      "name": "phone", "type": "text",  "required": False},
                ],
            )

        Returns:
            Chatwoot API response payload.
        """
        return self._send(
            conversation_id,
            {
                "content": message,
                "content_type": "form",
                "content_attributes": {"items": items},
            },
            private=private,
        )

    # ------------------------------------------------------------------
    # Interactive — cards / carousel
    # ------------------------------------------------------------------

    def send_cards_message(
        self,
        conversation_id: int,
        message: str,
        items: list[dict[str, Any]],
        *,
        private: bool = False,
    ) -> dict[str, Any]:
        """Send a card carousel message.

        Each card can have a title, description, thumbnail image, and
        call-to-action buttons.

        Args:
            conversation_id: Chatwoot conversation ID.
            message:         Optional intro text displayed above the carousel.
            items:           List of card dicts.  Each card supports:

                             - ``"title"`` (str) — card heading.
                             - ``"description"`` (str, optional) — card body text.
                             - ``"media_url"`` (str, optional) — thumbnail image URL.
                             - ``"cta"`` (list, optional) — call-to-action buttons,
                               each with ``"type"`` (``"link"`` or ``"postback"``),
                               ``"label"``, and ``"url"`` / ``"payload"``.

            private:         Post as a private note when ``True``.

        Example::

            client.send_cards_message(
                conversation_id,
                "Nossos planos de academia:",
                [
                    {
                        "title":       "Basic — R$150/mês",
                        "description": "Aulas em grupo + acesso ao gym.",
                        "cta": [{"type": "link", "label": "Assinar", "url": "https://nova-gym.com/join"}],
                    },
                    {
                        "title":       "Premium — R$400/mês",
                        "description": "Tudo do Basic + personal trainer ilimitado.",
                        "cta": [{"type": "link", "label": "Assinar", "url": "https://nova-gym.com/join"}],
                    },
                ],
            )

        Returns:
            Chatwoot API response payload.
        """
        return self._send(
            conversation_id,
            {
                "content": message,
                "content_type": "cards",
                "content_attributes": {"items": items},
            },
            private=private,
        )

    # ------------------------------------------------------------------
    # Interactive — articles
    # ------------------------------------------------------------------

    def send_article_message(
        self,
        conversation_id: int,
        message: str,
        items: list[dict[str, Any]],
        *,
        private: bool = False,
    ) -> dict[str, Any]:
        """Send a list of Help Center article links.

        Args:
            conversation_id: Chatwoot conversation ID.
            message:         Intro text (e.g. "Here are some helpful articles:").
            items:           List of article dicts.  Each item supports:

                             - ``"title"`` (str) — article title.
                             - ``"description"`` (str, optional) — short summary.
                             - ``"link"`` (str) — URL to the article.

            private:         Post as a private note when ``True``.

        Returns:
            Chatwoot API response payload.
        """
        return self._send(
            conversation_id,
            {
                "content": message,
                "content_type": "article",
                "content_attributes": {"items": items},
            },
            private=private,
        )

    # ------------------------------------------------------------------
    # Conversation management
    # ------------------------------------------------------------------

    def toggle_status(self, conversation_id: int, status: str) -> dict[str, Any]:
        """Change the status of a conversation.

        Args:
            conversation_id: Chatwoot conversation ID.
            status:          Target status: ``"open"``, ``"pending"``, or
                             ``"resolved"``.

        Returns:
            Chatwoot API response payload.
        """
        url = (
            f"{self.base_url}/api/v1/accounts/{self.account_id}"
            f"/conversations/{conversation_id}/toggle_status"
        )
        logger.debug(
            "Toggling conversation %d status to %r.", conversation_id, status
        )
        result = self._post(url, {"status": status})
        logger.info(
            "Chatwoot conversation %d status set to %r.",
            conversation_id,
            result.get("status"),
        )
        return result

    def handoff_conversation(
        self, conversation_id: int, status: str = "open"
    ) -> dict[str, Any]:
        """Hand off a conversation (matches the Ruby ``handoff_conversation`` API).

        Changes the conversation status so a human agent can take over.
        Defaults to ``"open"`` which removes the conversation from the bot
        queue and places it in the inbox for human agents.

        Args:
            conversation_id: Chatwoot conversation ID.
            status:          Target status (default ``"open"``).

        Returns:
            Chatwoot API response payload.
        """
        logger.info(
            "Handing off conversation %d to status=%r.", conversation_id, status
        )
        return self.toggle_status(conversation_id, status)

    def handover_to_human(self, conversation_id: int) -> dict[str, Any]:
        """Convenience alias: open conversation for human agent takeover.

        Equivalent to ``handoff_conversation(conversation_id, status="open")``.
        """
        return self.handoff_conversation(conversation_id, status="open")
