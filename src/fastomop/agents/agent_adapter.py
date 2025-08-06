from fastomop.agents.agent_protocol import RunnableAgent
from pydantic_ai.agent import Agent as PydanticAgent
from langchain.agents import AgentExecutor

class PydanticAgentAdapter(RunnableAgent):
    """Adapter for pydantic_ai.agent.Agent to conform to the RunnableAgent protocol.
    """
    def __init__(self, agent: PydanticAgent):
        self._agent = agent

    async def run(self, input_str: str) -> str:
        response = await self._agent.run(input_str)
        return response.output

_pydantic_agent_adapter: type[RunnableAgent] = PydanticAgentAdapter

class LangchainAgentAdapter(RunnableAgent):
    """Adapter for langchain.agents.AgentExecutor to conform to the RunnableAgent protocol.
    """
    def __init__(self, agent: AgentExecutor):
        self._agent = agent

    async def run(self, input_str: str) -> str:
        response = await self._agent.ainvoke({"input": input_str})
        return response.get("output", "")

_langchain_agent_adapter: type[RunnableAgent] = LangchainAgentAdapter




