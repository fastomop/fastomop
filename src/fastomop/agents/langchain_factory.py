from fastomop.agents.llm_builder import create_langchain_llm
from fastomop.config import AgentSettings, MCPServerSettings, config as cfg
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.prompts import ChatPromptTemplate
from typing import Any
from langchain.agents import create_react_agent, AgentExecutor
from fastomop.agents.agent_protocol import RunnableAgent
from fastomop.agents.agent_adapter import LangchainAgentAdapter


async def create_langchain_agent(settings: AgentSettings, mcp_server: MCPServerSettings) -> RunnableAgent:
    
    llm = create_langchain_llm(settings.model_name, settings.provider)
    mcp_config_dict = { mcp_server.name: {
        "command": mcp_server.command,
        "args": mcp_server.args,
        "transport": "stdio"
        }
        for mcp_server in cfg.mcp_servers
    }
    client = MultiServerMCPClient(mcp_config_dict) 
    tools = await client.get_tools()

    prompt = ChatPromptTemplate.from_messages([
        ("system", settings.system_prompt),
        ("user", "{input}"),
        ("agent_scratchpad", "{agent_scratchpad}")
    ])
    agent = create_react_agent(llm, tools, prompt)

    return LangchainAgentAdapter(agent)
    
