"""LangGraph-based agent workflow for Tata."""

import logging
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Tata, a helpful and friendly customer support agent. "
    "Use only the provided knowledge context to answer questions. "
    "If the context does not contain enough information, politely say you are "
    "not sure and suggest the user contact a human agent. "
    "Reply in the same language the user used."
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """State passed between LangGraph nodes."""

    conversation_id: int
    user_message: str
    history: Annotated[list[dict[str, str]], "Previous conversation turns (OpenAI message format)"]
    context_docs: Annotated[list[dict], "Retrieved knowledge snippets"]
    response: str


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def load_history_node(state: AgentState, *, conversation_memory: Any) -> AgentState:
    """Load previous conversation turns from Qdrant memory."""
    history = conversation_memory.get_history(state["conversation_id"])
    return {**state, "history": history}


def retrieve_node(state: AgentState, *, qdrant_store: Any) -> AgentState:
    """Retrieve relevant knowledge from Qdrant."""
    docs = qdrant_store.search(state["user_message"])
    logger.debug("Retrieved %d docs for query: %s", len(docs), state["user_message"][:80])
    return {**state, "context_docs": docs}


def generate_node(state: AgentState, *, openai_client: OpenAI) -> AgentState:
    """Generate a response using OpenAI with the retrieved context and history."""
    context_text = "\n\n".join(
        doc.get("text", "") for doc in state.get("context_docs", [])
    )
    # Build the messages array: system → history → current user message
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(state.get("history", []))
    messages.append(
        {
            "role": "user",
            "content": (
                f"Knowledge context:\n{context_text}\n\n"
                f"User question: {state['user_message']}"
            ),
        }
    )
    completion = openai_client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
    )
    response = completion.choices[0].message.content or ""
    logger.debug("Generated response (%d chars)", len(response))
    return {**state, "response": response}


def save_turn_node(state: AgentState, *, conversation_memory: Any) -> AgentState:
    """Persist the current user message and agent reply to memory."""
    conversation_memory.add_turn(
        conversation_id=state["conversation_id"],
        user_message=state["user_message"],
        assistant_reply=state["response"],
    )
    return state


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_agent(
    qdrant_store: Any,
    conversation_memory: Any,
    openai_client: OpenAI | None = None,
) -> Any:
    """Build and compile the LangGraph workflow.

    The graph runs four nodes in sequence:
    ``load_history`` → ``retrieve`` → ``generate`` → ``save_turn``

    Args:
        qdrant_store: An instance of :class:`~app.qdrant_store.QdrantStore`.
        conversation_memory: An instance of
            :class:`~app.conversation_memory.ConversationMemory`.
        openai_client: Optional OpenAI client; a default one is created if omitted.

    Returns:
        A compiled LangGraph ``CompiledGraph`` ready to be invoked.
    """
    client = openai_client or OpenAI(api_key=settings.openai_api_key)

    graph = StateGraph(AgentState)

    graph.add_node(
        "load_history",
        lambda state: load_history_node(state, conversation_memory=conversation_memory),
    )
    graph.add_node(
        "retrieve",
        lambda state: retrieve_node(state, qdrant_store=qdrant_store),
    )
    graph.add_node(
        "generate",
        lambda state: generate_node(state, openai_client=client),
    )
    graph.add_node(
        "save_turn",
        lambda state: save_turn_node(state, conversation_memory=conversation_memory),
    )

    graph.set_entry_point("load_history")
    graph.add_edge("load_history", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "save_turn")
    graph.add_edge("save_turn", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------


def run_agent(
    user_message: str,
    qdrant_store: Any,
    conversation_memory: Any,
    conversation_id: int = 0,
    openai_client: OpenAI | None = None,
) -> str:
    """Run the agent and return the generated reply text.

    Args:
        user_message: The message received from the user/Chatwoot.
        qdrant_store: Configured :class:`~app.qdrant_store.QdrantStore`.
        conversation_memory: Configured
            :class:`~app.conversation_memory.ConversationMemory`.
        conversation_id: Chatwoot conversation ID (used to load/save history).
        openai_client: Optional pre-configured OpenAI client.

    Returns:
        The agent's reply as a plain string.
    """
    agent = build_agent(qdrant_store, conversation_memory, openai_client)
    initial_state: AgentState = {
        "conversation_id": conversation_id,
        "user_message": user_message,
        "history": [],
        "context_docs": [],
        "response": "",
    }
    final_state = agent.invoke(initial_state)
    return final_state["response"]
