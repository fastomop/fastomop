"""This is a placeholder and not fully implemented."""

from a2a.client import A2AClient
from a2a.types import SendMessageRequest, AgentCard
from a2a.types import (
    MessageSendParams,
)
from typing import Any
import json
import httpx
import uuid


class A2AToolClient:
    """A2A client."""

    def __init__(self, default_timeout: float = 120.0):
        # Cache for agent metadata - also serves as the list of registered agents
        # None value indicates agent is registered but metadata not yet fetched
        self._agent_info_cache: dict[str, dict[str, Any] | None] = {}
        # Default timeout for requests (in seconds)
        self.default_timeout = default_timeout

    def add_remote_agent(self, agent_url: str):
        """Add agent to the list of available remote agents."""
        normalized_url = agent_url.rstrip("/")
        if normalized_url not in self._agent_info_cache:
            # Initialize with None to indicate metadata not yet fetched
            self._agent_info_cache[normalized_url] = None

    def list_remote_agents(self) -> list[dict[str, Any]]:
        """List available remote agents with caching."""
        if not self._agent_info_cache:
            return []

        remote_agents_info = []
        for remote_connection in self._agent_info_cache:
            # Use cached data if available
            if self._agent_info_cache[remote_connection] is not None:
                remote_agents_info.append(self._agent_info_cache[remote_connection])
            else:
                try:
                    # Fetch and cache agent info
                    agent_info = httpx.get(
                        f"{remote_connection}/.well-known/agent.json"
                    )
                    agent_data = agent_info.json()
                    self._agent_info_cache[remote_connection] = agent_data
                    remote_agents_info.append(agent_data)
                except Exception as e:
                    print(f"Failed to fetch agent info from {remote_connection}: {e}")

        return self._agent_info_cache  # type: ignore

    async def create_task(self, agent_url: str, message: str) -> str:
        """Send a message following the official A2A SDK pattern."""
        # Configure httpx client with timeout
        timeout_config = httpx.Timeout(
            timeout=self.default_timeout,
            connect=10.0,
            read=self.default_timeout,
            write=10.0,
            pool=5.0,
        )

        async with httpx.AsyncClient(timeout=timeout_config) as httpx_client:
            # Check if we have cached agent card data
            if (
                agent_url in self._agent_info_cache
                and self._agent_info_cache[agent_url] is not None
            ):
                agent_card_data = self._agent_info_cache[agent_url]
            else:
                # Fetch the agent card
                agent_card_response = await httpx_client.get(
                    f"{agent_url}/.well-known/agent.json"
                )
                agent_card_data = agent_card_response.json()

            # Create AgentCard from data
            agent_card = AgentCard(**agent_card_data)  # type: ignore

            # Create A2A client with the agent card
            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)

            # Build the message parameters following official structure
            send_message_payload = {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": message}],
                    "messageId": uuid.uuid4().hex,
                }
            }

            # Create the request
            request = SendMessageRequest(
                id=str(uuid.uuid4()), params=MessageSendParams(**send_message_payload)
            )

            # Send the message with timeout configuration
            response = await client.send_message(request)

            # Extract text from response
            try:
                response_dict = response.model_dump(mode="json", exclude_none=True)
                if "result" in response_dict and "artifacts" in response_dict["result"]:
                    artifacts = response_dict["result"]["artifacts"]
                    for artifact in artifacts:
                        if "parts" in artifact:
                            for part in artifact["parts"]:
                                if "text" in part:
                                    return part["text"]

                # If we couldn't extract text, return the full response as formatted JSON
                return json.dumps(response_dict, indent=2)

            except Exception as e:
                # Log the error and return string representation
                print(f"Error parsing response: {e}")
                return str(response)

    def remove_remote_agent(self, agent_url: str):
        """Remove an agent from the list of available remote agents."""
        normalized_url = agent_url.rstrip("/")
        if normalized_url in self._agent_info_cache:
            del self._agent_info_cache[normalized_url]
