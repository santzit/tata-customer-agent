"""LangGraph-based agent workflow for Tata."""

import logging
import re
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# Delimiter used to separate individual messages within one LLM response.
# The LLM is instructed to place a line containing only "---" between parts.
MSG_DELIMITER = "\n---\n"

SYSTEM_PROMPT = (
    "You are Tata, a helpful and friendly customer support agent for Nova Gym Academy. "
    "Use only the provided knowledge context to answer questions. "
    "If the context does not contain enough information, politely say you are "
    "not sure and suggest the user contact a human agent. "
    "Always reply in English, regardless of the language the user writes in. "
    "When a customer sends a simple greeting during an ongoing conversation, provide a "
    "contextual follow-up response that references the previous topic and offers helpful "
    "next steps — for example: 'Is there anything else you'd like to know about our gym "
    "plans?' or 'Would you like to book a free experimental class?' "
    "You may split your reply into multiple messages when it improves clarity — for "
    "example, a short intro message, then a detailed content block, then a friendly "
    "closing. Separate each message with a line containing only '---'. "
    "Example of a multi-message reply:\n"
    "Hi! Here are our membership plans:\n---\n"
    "• Basic — R$150/month\n• Standard — R$250/month\n• Premium — R$400/month\n---\n"
    "Feel free to ask if you'd like more details or want to book a free trial class!"
)

SUPERVISOR_PROMPT = (
    "You are Tata's supervisor at Nova Gym Academy. Your job is to review the full "
    "customer support response — which may consist of one or several messages sent in "
    "sequence — before any part is delivered to the customer. Evaluate all parts "
    "together as a single cohesive response.\n\n"
    "Guidelines:\n"
    "1. The response must be relevant to the customer's question and to our gym/fitness services.\n"
    "2. The response must NOT contain sensitive information (e.g. passwords, internal "
    "system details, personal data of other customers).\n"
    "3. The response must be professional, respectful, and follow our messaging policy "
    "(no offensive, misleading, or inappropriate content).\n"
    "4. The response must contain ONLY information related to Nova Gym Academy services.\n\n"
    "Reply with ONLY:\n"
    "- 'APPROVED' — if all parts meet the guidelines and are safe to deliver.\n"
    "- 'NEEDS_HUMAN: <brief reason>' — if any part violates a guideline and the "
    "conversation should be handed off to a human agent instead."
)

HUMAN_ESCALATION_MESSAGE = (
    "I'm going to connect you with one of our human agents who will be able to assist "
    "you better. Please hold on for a moment — someone will be with you shortly! 🙏"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_messages(raw: str) -> list[str]:
    """Split a raw LLM response into individual message parts.

    The LLM is instructed to separate messages with a line containing only
    ``---``.  Empty parts (e.g. leading/trailing whitespace) are discarded.
    If the response contains no delimiter, it is returned as a single-element list.
    """
    parts = re.split(r"\n---\n", raw)
    return [p.strip() for p in parts if p.strip()]


def _format_for_supervisor(messages: list[str]) -> str:
    """Format the message list for the supervisor review prompt.

    When there is only one message it is presented as-is.  When there are
    multiple messages they are shown as a numbered sequence so the supervisor
    can evaluate them together as a cohesive whole.
    """
    if len(messages) == 1:
        return messages[0]
    parts = "\n\n".join(
        f"[Message {i + 1} of {len(messages)}]:\n{msg}"
        for i, msg in enumerate(messages)
    )
    return f"{len(messages)} messages to be sent in sequence:\n\n{parts}"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """State passed between LangGraph nodes."""

    conversation_id: int
    user_message: str
    history: Annotated[list[dict[str, str]], "Previous conversation turns (OpenAI message format)"]
    context_docs: Annotated[list[dict], "Retrieved knowledge snippets"]
    messages: Annotated[list[str], "Individual message parts to deliver to the customer"]
    needs_human_review: bool


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def load_history_node(state: AgentState, *, conversation_memory: Any) -> AgentState:
    """Load previous conversation turns from PostgreSQL memory."""
    history = conversation_memory.get_history(state["conversation_id"])
    return {**state, "history": history}


def retrieve_node(state: AgentState, *, vector_store: Any) -> AgentState:
    """Retrieve relevant knowledge from the pgvector store."""
    docs = vector_store.search(state["user_message"])
    logger.debug("Retrieved %d docs for query: %s", len(docs), state["user_message"][:80])
    return {**state, "context_docs": docs}


def generate_node(state: AgentState, *, openai_client: OpenAI) -> AgentState:
    """Generate a response using OpenAI with the retrieved context and history.

    The LLM may return a single message or multiple messages separated by
    ``\\n---\\n``.  The raw output is split into individual parts and stored
    in ``state["messages"]``.
    """
    context_text = "\n\n".join(
        doc.get("text", "") for doc in state.get("context_docs", [])
    )
    # Build the messages array: system → history → current user message
    prompt_messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    prompt_messages.extend(state.get("history", []))
    prompt_messages.append(
        {
            "role": "user",
            "content": (
                f"Knowledge context:\n{context_text}\n\n"
                f"User question: {state['user_message']}"
            ),
        }
    )
    completion = openai_client.chat.completions.create(
        model=settings.llm_model,
        messages=prompt_messages,
    )
    raw_response = completion.choices[0].message.content or ""
    messages = _split_messages(raw_response)
    logger.debug(
        "Generated %d message part(s) (%d chars total)",
        len(messages),
        len(raw_response),
    )
    return {**state, "messages": messages}


def review_node(state: AgentState, *, openai_client: OpenAI) -> AgentState:
    """Supervisor review: evaluate all message parts together as a cohesive response.

    The supervisor LLM acts as Tata's manager and checks the complete set of
    messages (shown as a numbered sequence) against quality and policy guidelines:
    - Relevance to the customer's question and to Nova Gym Academy services.
    - Absence of sensitive information.
    - Professional tone and policy compliance.
    - No off-topic content.

    All parts are reviewed together in one call so the supervisor can assess
    the full conversation turn as a whole.

    Sets ``needs_human_review = True`` when any part should be escalated to a
    human agent; ``False`` when the full response is safe to deliver.
    """
    formatted = _format_for_supervisor(state["messages"])
    review_messages: list[dict] = [
        {"role": "system", "content": SUPERVISOR_PROMPT},
        {
            "role": "user",
            "content": (
                f"Customer question: {state['user_message']}\n\n"
                f"Tata's response:\n{formatted}"
            ),
        },
    ]
    completion = openai_client.chat.completions.create(
        model=settings.llm_model,
        messages=review_messages,
    )
    verdict = (completion.choices[0].message.content or "").strip()
    needs_human = not verdict.upper().startswith("APPROVED")
    if needs_human:
        logger.info(
            "Supervisor flagged response for human review (conversation %d): %s",
            state["conversation_id"],
            verdict,
        )
    else:
        logger.debug(
            "Supervisor approved %d message part(s) for conversation %d",
            len(state["messages"]),
            state["conversation_id"],
        )
    return {**state, "needs_human_review": needs_human}


def escalate_to_human_node(state: AgentState) -> AgentState:
    """Replace all message parts with a single human escalation message.

    Called when the supervisor flags the response as unsuitable for delivery.
    The escalation message is saved to memory so the conversation history
    reflects exactly what the customer received.
    """
    logger.info(
        "Escalating conversation %d to a human agent.", state["conversation_id"]
    )
    return {**state, "messages": [HUMAN_ESCALATION_MESSAGE]}


def save_turn_node(state: AgentState, *, conversation_memory: Any) -> AgentState:
    """Persist the current user message and agent reply to memory.

    Multiple message parts are joined with double newlines so the stored
    history is readable and can be injected cleanly into future prompts.
    """
    assistant_reply = "\n\n".join(state["messages"])
    conversation_memory.add_turn(
        conversation_id=state["conversation_id"],
        user_message=state["user_message"],
        assistant_reply=assistant_reply,
    )
    return state


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _route_after_review(state: AgentState) -> str:
    """Conditional edge: route to human escalation or direct customer delivery."""
    return "escalate_to_human" if state["needs_human_review"] else "save_turn"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_agent(
    vector_store: Any,
    conversation_memory: Any,
    openai_client: OpenAI | None = None,
) -> Any:
    """Build and compile the LangGraph workflow.

    The graph runs the following nodes in sequence:

    ``load_history`` → ``retrieve`` → ``generate`` → ``review``
        → (approved) ``save_turn`` → END
        → (flagged)  ``escalate_to_human`` → ``save_turn`` → END

    The ``review`` node acts as Tata's supervisor/manager: it presents all
    message parts **together** in a single review call so the supervisor can
    evaluate the full response as a cohesive whole before deciding whether to
    deliver it to the customer or hand the conversation off to a human agent.

    Args:
        vector_store: An instance of :class:`~app.pg_vector_store.PgVectorStore`.
        conversation_memory: An instance of
            :class:`~app.conversation_memory.ConversationMemory`.
        openai_client: Optional OpenAI client; a default one is created if omitted.

    Returns:
        A compiled LangGraph ``CompiledGraph`` ready to be invoked.
    """
    client = openai_client or settings.make_openai_client()

    graph = StateGraph(AgentState)

    graph.add_node(
        "load_history",
        lambda state: load_history_node(state, conversation_memory=conversation_memory),
    )
    graph.add_node(
        "retrieve",
        lambda state: retrieve_node(state, vector_store=vector_store),
    )
    graph.add_node(
        "generate",
        lambda state: generate_node(state, openai_client=client),
    )
    graph.add_node(
        "review",
        lambda state: review_node(state, openai_client=client),
    )
    graph.add_node("escalate_to_human", escalate_to_human_node)
    graph.add_node(
        "save_turn",
        lambda state: save_turn_node(state, conversation_memory=conversation_memory),
    )

    graph.set_entry_point("load_history")
    graph.add_edge("load_history", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "review")
    graph.add_conditional_edges("review", _route_after_review)
    graph.add_edge("escalate_to_human", "save_turn")
    graph.add_edge("save_turn", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------


def run_agent(
    user_message: str,
    vector_store: Any,
    conversation_memory: Any,
    conversation_id: int = 0,
    openai_client: OpenAI | None = None,
) -> list[str]:
    """Run the agent and return the approved message parts.

    Each element of the returned list is an individual message to be delivered
    to the customer in order.  Normally this is a single string, but the agent
    may return multiple parts when a sequential multi-message reply improves
    clarity.

    When the supervisor flags the response, a single-element list containing
    the human escalation message is returned instead.

    Args:
        user_message: The message received from the user/Chatwoot.
        vector_store: Configured :class:`~app.pg_vector_store.PgVectorStore`.
        conversation_memory: Configured
            :class:`~app.conversation_memory.ConversationMemory`.
        conversation_id: Chatwoot conversation ID (used to load/save history).
        openai_client: Optional pre-configured OpenAI client.

    Returns:
        An ordered list of message strings to send to the customer.
    """
    agent = build_agent(vector_store, conversation_memory, openai_client)
    initial_state: AgentState = {
        "conversation_id": conversation_id,
        "user_message": user_message,
        "history": [],
        "context_docs": [],
        "messages": [],
        "needs_human_review": False,
    }
    final_state = agent.invoke(initial_state)
    return final_state["messages"]
