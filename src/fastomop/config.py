"""Configuration settings for FastOMOP."""

import os
from pathlib import Path
from typing import Literal, Optional, Union

from dotenv import find_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

config_file_path = Path(
    os.getenv(
        "CONFIG_FILE_PATH", Path(__file__).parent.parent.parent.joinpath("config.toml")
    )
)

env_file_path = find_dotenv()

assert config_file_path.exists(), f"Config file not found: {config_file_path}"


class OpenAIConfig(BaseModel):
    """Settings for OpenAI."""

    provider_type: Literal["openai"] = "openai"
    api_key: Optional[str] = None
    base_url: str = "https://api.openai.com/v1"
    organization: Optional[str] = None


class AnthropicConfig(BaseModel):
    """Settings for Anthropic."""

    provider_type: Literal["anthropic"] = "anthropic"
    api_key: Optional[str] = None
    base_url: str = "https://api.anthropic.com/v1"


class AzureConfig(BaseModel):
    """Settings for Azure."""

    provider_type: Literal["azure"] = "azure"
    api_key: str
    azure_endpoint: str
    api_version: str = "2024-02-15-preview"


def create_ollama_config() -> OpenAIConfig:
    """Create an Ollama config."""
    return OpenAIConfig(
        provider_type="openai",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
    )


ProviderConfig = Union[OpenAIConfig, AzureConfig, AnthropicConfig]


class AgentSettings(BaseModel):
    """Settings for the agent configuration."""

    agent_name: str = "Default Agent"
    model_name: str = "qwen3:14b"
    temperature: float = 0.1
    provider: ProviderConfig = Field(default_factory=lambda: create_ollama_config())
    description: str = "A helpful assistant for FastOMOP."
    needs_omop_schema: bool = False
    system_prompt: str = "You are a helpful assistant."
    user_prompt: str = "How can I assist you today?"
    mcp_servers: list[str] = []


class MCPServerSettings(BaseModel):
    """Settings for the MCP server."""

    name: str = "sql_mcp_server"
    command: str = "uv"
    args: list[str] = ["run", "fastomop_mcp_sql"]


class TracerSettings(BaseModel):
    """Settings for the Langfuse OpenTelemetry tracer."""

    public_key: str = os.environ["LANGFUSE_PUBLIC_KEY"]
    secret_key: str = os.environ["LANGFUSE_SECRET_KEY"]
    host: str = os.environ["LANGFUSE_HOST"]


class OMOPSettings(BaseModel):
    """Settings for OMOP database connection."""

    db_connection_string: str = "sqlite:///fastomop.db"
    allowed_tables: list[str] = [
        "care_site",
        "cdm_source",
        "concept",
        "concept_ancestor",
        "concept_class",
        "concept_relationship",
        "concept_synonym",
        "condition_era",
        "condition_occurrence",
        "cost",
        "death",
        "device_exposure",
        "domain",
        "dose_era",
        "drug_era",
        "drug_exposure",
        "drug_strength",
        "episode",
        "episode_event",
        "fact_relationship",
        "location",
        "measurement",
        "metadata",
        "note",
        "note_nlp",
        "observation",
        "observation_period",
        "payer_plan_period",
        "person",
        "procedure_occurrence",
        "provider",
        "relationship",
        "specimen",
        "visit_detail",
        "visit_occurrence",
        "vocabulary",
    ]
    clinical_tables_schema: str = "cdm"
    vocabulary_tables_schema: str = "vocab"

    clinical_tables: list[str] = [
        "care_site",
        "condition_era",
        "condition_occurrence",
        "cost",
        "death",
        "device_exposure",
        "dose_era",
        "drug_era",
        "drug_exposure",
        "drug_strength",
        "episode",
        "episode_event",
        "fact_relationship",
        "location",
        "measurement",
        "note",
        "note_nlp",
        "observation",
        "observation_period",
        "payer_plan_period",
        "person",
        "procedure_occurrence",
        "provider",
        "specimen",
        "visit_detail",
        "visit_occurrence",
    ]
    vocabulary_tables: list[str] = [
        "concept",
        "concept_ancestor",
        "concept_class",
        "concept_relationship",
        "concept_synonym",
        "domain",
        "relationship",
        "vocabulary",
    ]
    metadata_tables: list[str] = [
        "cdm_source",
        "metadata",
    ]


class FastOMOPSettings(BaseSettings):
    """Settings for FastOMOP."""

    # Agent settings
    supervisor_agent: AgentSettings = AgentSettings()
    sql_agent: AgentSettings = AgentSettings()
    semantic_agent: AgentSettings = AgentSettings()

    # OMOP settings
    omop: OMOPSettings = OMOPSettings()
    db_connection_string: str = "sqlite:///fastomop.db"  # placeholder

    # MCP server settings
    mcp_servers: list[MCPServerSettings] = [MCPServerSettings()]

    # OpenTelemetry tracer settings
    tracer: TracerSettings = TracerSettings()

    model_config = SettingsConfigDict(
        env_file=env_file_path,
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        validate_assignment=True,
        toml_file=config_file_path,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: BaseSettings,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Return sources in order of precedence (lowest to highest):
        # In Pydantic, the LAST source in the tuple has the highest precedence
        # 1. Init settings (defaults) - lowest precedence
        # 2. TOML config file
        # 3. .env file (dotenv_settings)
        # 4. Environment variables (env_settings) - highest precedence
        return (
            init_settings,
            TomlConfigSettingsSource(settings_cls),
            dotenv_settings,
            env_settings,
        )


config = FastOMOPSettings()
