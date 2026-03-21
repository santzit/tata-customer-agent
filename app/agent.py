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

    user_message: str
    context_docs: Annotated[list[dict], "Retrieved knowledge snippets"]
    response: str


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def retrieve_node(state: AgentState, *, qdrant_store: Any) -> AgentState:
    """Retrieve relevant knowledge from Qdrant."""
    docs = qdrant_store.search(state["user_message"])
    logger.debug("Retrieved %d docs for query: %s", len(docs), state["user_message"][:80])
    return {**state, "context_docs": docs}


def generate_node(state: AgentState, *, openai_client: OpenAI) -> AgentState:
    """Generate a response using OpenAI with the retrieved context."""
    context_text = "\n\n".join(
        doc.get("text", "") for doc in state.get("context_docs", [])
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Knowledge context:\n{context_text}\n\n"
                f"User question: {state['user_message']}"
            ),
        },
    ]
    completion = openai_client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
    )
    response = completion.choices[0].message.content or ""
    logger.debug("Generated response (%d chars)", len(response))
    return {**state, "response": response}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_agent(qdrant_store: Any, openai_client: OpenAI | None = None) -> Any:
    """Build and compile the LangGraph workflow.

    Args:
        qdrant_store: An instance of :class:`~app.qdrant_store.QdrantStore`.
        openai_client: Optional OpenAI client; a default one is created if omitted.

    Returns:
        A compiled LangGraph ``CompiledGraph`` ready to be invoked.
    """
    client = openai_client or OpenAI(api_key=settings.openai_api_key)

    graph = StateGraph(AgentState)

    # Bind dependencies via closures so nodes are plain callables
    graph.add_node(
        "retrieve",
        lambda state: retrieve_node(state, qdrant_store=qdrant_store),
    )
    graph.add_node(
        "generate",
        lambda state: generate_node(state, openai_client=client),
    )

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------


def run_agent(user_message: str, qdrant_store: Any, openai_client: OpenAI | None = None) -> str:
    """Run the agent and return the generated reply text.

    Args:
        user_message: The message received from the user/Chatwoot.
        qdrant_store: Configured :class:`~app.qdrant_store.QdrantStore`.
        openai_client: Optional pre-configured OpenAI client.

    Returns:
        The agent's reply as a plain string.
    """
    agent = build_agent(qdrant_store, openai_client)
    initial_state: AgentState = {
        "user_message": user_message,
        "context_docs": [],
        "response": "",
    }
    final_state = agent.invoke(initial_state)
    return final_state["response"]
