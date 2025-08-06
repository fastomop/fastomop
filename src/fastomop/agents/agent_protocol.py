"""Protocol for agents adapter."""
from typing import Protocol

class RunnableAgent(Protocol):
    """Protocol that defines the standard interface for any agent (pydantic or langchain)
    """

    async def run(self, input: str) -> str:
        """Run the agent with the given input and return the output.
        """
        ...