"""Module for initial loading of prompts to Langfuse"""
# This currently needs to be called manually once to bootstrap the prompt database with the initial prompts.

from fastomop.config import config as cfg
from fastomop.otel import tracer

# Bootstrap/update Langfuse prompt database
# ToDo: Add logging and error handling

tracer.create_prompt(
    name="Semantic Agent/user_prompt",
    type="text",
    prompt=cfg.semantic_agent.user_prompt,
)

tracer.create_prompt(
    name="Semantic Agent/system_prompt",
    type="text",
    prompt=cfg.semantic_agent.system_prompt,
)

tracer.create_prompt(
    name="SQL Agent/user_prompt",
    type="text",
    prompt=cfg.sql_agent.user_prompt,
)
tracer.create_prompt(
    name="SQL Agent/system_prompt",
    type="text",
    prompt=cfg.sql_agent.system_prompt,
)
tracer.create_prompt(
    name="Supervisor Agent/user_prompt",
    type="text",
    prompt=cfg.supervisor_agent.user_prompt,
)
tracer.create_prompt(
    name="Supervisor Agent/system_prompt",
    type="text",
    prompt=cfg.supervisor_agent.system_prompt,
)
