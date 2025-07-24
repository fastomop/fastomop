from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from fastomop.agents.sqlagent import agent as sql_agent


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
    response = await sql_agent.run(state["messages"])

    out = {"messages": response.new_messages_json()}

    return out


graph_builder.add_node("sql_agent", node_sqlagent)

graph_builder.add_edge(START, "sql_agent")
graph_builder.add_edge("sql_agent", END)

graph = graph_builder.compile()
