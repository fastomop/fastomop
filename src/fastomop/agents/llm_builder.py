from fastomop.config import ProviderConfig
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.models.anthropic import AnthropicModel
from typing import Any

def create_provider(provider_config: ProviderConfig) -> Any:
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
                api_key=provider_config.api_key,
                base_url=provider_config.base_url
            )
        case "azure":
            return AzureProvider(
                api_key=provider_config.api_key,
                azure_endpoint=provider_config.azure_endpoint,
                api_version=provider_config.api_version
            )
        case "anthropic":
            return AnthropicProvider(
                api_key=provider_config.api_key
            )
        case _:
            raise ValueError(f"Unknown provider type: {provider_config.provider_type}")

def create_model(model_name: str, provider: Any, provider_config: ProviderConfig) -> Any:
    """Create an appropriate model based on proider type

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
                model_name=model_name, #Azure OpenAI needs to be specified with deployment name
                provider=provider
            )
        case "anthropic":
            return AnthropicModel(
                model_name=model_name,
                provider=provider
            )
        case _:
            raise ValueError(f"Unknown provider type: {provider_config.provider_type}")