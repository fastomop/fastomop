"""Module for creating agents in FastOMOP."""

from typing import Any

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.openai import OpenAIProvider

from fastomop.config import AgentSettings, ProviderConfig
from fastomop.config import config as cfg
from fastomop.otel import tracer

Agent.instrument_all()


def _create_provider(provider_config: ProviderConfig) -> Any:
    """Create an appropriate provider based on config.

    Args:
        config: Provider configuration

    Returns:
        Appropriate provider instance

    Raises:
        ValueError: If provider type is not supported
    """

    match provider_config.provider_type:
        case "openai":
            return OpenAIProvider(
                api_key=provider_config.api_key, base_url=provider_config.base_url
            )
        case "azure":
            return AzureProvider(
                api_key=provider_config.api_key,
                azure_endpoint=provider_config.azure_endpoint,
                api_version=provider_config.api_version,
            )
        case "anthropic":
            return AnthropicProvider(api_key=provider_config.api_key)
        case _:
            raise ValueError(f"Unknown provider type: {provider_config.provider_type}")


def _create_model(
    model_name: str, provider: Any, provider_config: ProviderConfig
) -> Any:
    """Create an appropriate model based on provider type

    Args:
        model_name: Name of the model to create
        provider: Provider instance
        provider_config: Provider configuration

    Returns:
        Appropriate model instance

    Raises:
        ValueError: If model type is not supported
    """

    match provider_config.provider_type:
        case "openai" | "azure":
            return OpenAIModel(
                model_name=model_name,  # Azure OpenAI needs to be specified with deployment name
                provider=provider,
            )
        case "anthropic":
            return AnthropicModel(model_name=model_name, provider=provider)
        case _:
            raise ValueError(f"Unknown provider type: {provider_config.provider_type}")


def _create_pydantic_agent(
    settings: AgentSettings, toolsets: list[MCPServerStdio]
) -> Agent:
    """Create an appropriate agent based on Agent settings

    Args:
        settings: Agent settings
        mcp_server: MCP server instance

    Returns:
        Appropriate agent instance

    Raises:
        ValueError: If agent type is not supported
    """

    provider = _create_provider(settings.provider)
    model = _create_model(settings.model_name, provider, settings.provider)

    system_prompt_client = tracer.get_prompt(
        name=settings.agent_name + "/system_prompt", label="latest"
    )

    if settings.needs_omop_schema:
        system_prompt = system_prompt_client.compile(
            clinical_tables_schema=cfg.omop.clinical_tables_schema,
            vocabulary_tables_schema=cfg.omop.vocabulary_tables_schema,
            clinical_tables=cfg.omop.clinical_tables,
            vocabulary_tables=cfg.omop.vocabulary_tables,
        )
    else:
        system_prompt = system_prompt_client.compile()

    agent = Agent(
        name=settings.agent_name,
        model=model,
        system_prompt=system_prompt,
        toolsets=toolsets or [],
        output_retries=3,
        retries=5,
    )
    return agent


def create_agent(settings: AgentSettings) -> Agent:
    """Create an appropriate agent based on Agent settings

    Args:
        settings: Agent settings
        mcp_server: MCP server instance
    """
    toolsets = []
    if settings.mcp_servers:
        for server_name in settings.mcp_servers:
            server_config = next(
                (s for s in cfg.mcp_servers if s.name == server_name), None
            )
            if server_config:
                mcp_server = MCPServerStdio(
                    command=server_config.command, args=server_config.args
                )
                toolsets.append(mcp_server)
                print(f"Added MCP server: {server_name}")
            else:
                print(f"MCP server not found: {server_name}")

    return _create_pydantic_agent(settings, toolsets)
