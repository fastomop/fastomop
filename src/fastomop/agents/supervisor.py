from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from fastomop.agents.sql_agent import agent as sql_agent
from fastomop.agents.semantic_agent import agent as semantic_agent


class State(TypedDict):
    # Messages have the type "list". The `add_messages` function
    # in the annotation defines how this state key should be updated
    # (in this case, it appends messages to the list, rather than overwriting them)
    messages: Annotated[list, add_messages]


graph_builder = StateGraph(State)


async def node_sqlagent(state: State):
    """
    Node that calls the SQL agent.
    """
    # Call the SQL agent with the current messages

    response = await sql_agent.run(f"{state['messages']}")

    out = {"messages": response.output}

    return out


async def node_semantic_agent(state: State):
    """
    Node that calls the Semantic agent.
    """
    # Call the Semantic agent with the current messages

    response = await semantic_agent.run(f"{state['messages']}")

    out = {"messages": response.output}

    return out


graph_builder.add_node("sql_agent", node_sqlagent)
graph_builder.add_node("semantic_agent", node_semantic_agent)

graph_builder.add_edge(START, "semantic_agent")
graph_builder.add_edge(START, "sql_agent")
graph_builder.add_edge("semantic_agent", "sql_agent")
graph_builder.add_edge("sql_agent", END)

graph = graph_builder.compile()

print(graph.get_graph().draw_mermaid())

# model = ChatOpenAI(
#     model=cfg.supervisor_agent.model_name,
#     base_url=cfg.supervisor_agent.openai_url,
#     api_key="OLLAMA_API_KEY",  # Replace with your actual API key
# )

# supervisor = create_supervisor(
#     agents=[sql_agent, semantic_agent],
#     model=model,
#     prompt=cfg.supervisor_agent.system_prompt,
# )

# graph = supervisor.compile()
