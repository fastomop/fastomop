from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastomop.agents.agent_factory import create_agent
from fastomop.agents.semantic_agent import agent as semantic_agent
from fastomop.agents.sql_agent import agent as sql_agent
from fastomop.config import config as cfg
from fastomop.otel import tracer


@dataclass
class AgentExecution:
    agent_name: str
    input: str
    output: Optional[str] = None
    error: Optional[str] = None
    start_time: Optional[datetime] = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    duration: Optional[float] = None
    retry_count: int = 0

    def complete(self, output: Optional[str] = None, error: Optional[str] = None):
        """Mark execution as complete."""
        self.output = output
        self.error = error
        self.end_time = datetime.now()
        self.duration = (self.end_time - self.start_time).total_seconds()  # type: ignore


@dataclass
class QueryResult:
    query: str
    semantic_execution: Optional[AgentExecution] = None
    sql_execution: Optional[AgentExecution] = None
    synthesis_execution: Optional[AgentExecution] = None
    final_answer: Optional[str] = None
    total_duration_ms: Optional[float] = None
    success: bool = False
    workflow_pattern: str = "semantic_sql_synthesis"

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the query result."""
        return {
            "query": self.query[:100] + "..." if len(self.query) > 100 else self.query,
            "workflow_pattern": self.workflow_pattern,
            "success": self.success,
            "total_duration_ms": self.total_duration_ms,
            "semantic_duration_ms": self.semantic_execution.duration
            if self.semantic_execution
            else None,
            "sql_duration_ms": self.sql_execution.duration
            if self.sql_execution
            else None,
            "synthesis_duration_ms": self.synthesis_execution.duration
            if self.synthesis_execution
            else None,
            "final_answer": self.final_answer,
        }


class FastOmopSupervisor:
    def __init__(self):
        self.semantic_agent = semantic_agent
        self.sql_agent = sql_agent
        self.supervisor_agent = create_agent(cfg.supervisor_agent)

        self.history: List[QueryResult] = []

    def build_sql_prompt(self, user_query: str, semantic_output: str) -> str:
        """Build a prompt for the SQL agent."""
        return f"""
        Given this user query: {user_query}
        and the semantic meaning of the query: {semantic_output}
        Please generate a SQL query to answer the user query and execute it against the OMOP database in the MCP server.
        """

    def build_synthesis_prompt(
        self, user_query: str, semantic_output: str, sql_output: str
    ) -> str:
        """Build a prompt for the synthesis agent."""
        return f"""
        User query: {user_query}
        Semantic meaning: {semantic_output}
       Database results: {sql_output}

       Tasks:
       1. Synthesize a comprehensive answer to the user query based on the semantic meaning and the database results.
       2. Validate medical accuracy and clinical relevance of the answer.
       3. Flag potential limitations, data quality issues, or uncertainties in the answer.
       4. Provide a clear and concise answer to the user query.
        """

    async def process_query(self, user_query: str) -> QueryResult:
        """Process a query and return a QueryResult."""

        result = QueryResult(query=user_query)
        start_time = datetime.now()

        try:
            # Semantic Agent
            # semantic_prompt = self.build_semantic_prompt(user_query)
            semantic_prompt_client = tracer.get_prompt(
                "semantic_agent.user_prompt", label="latest"
            )
            semantic_prompt = semantic_prompt_client.compile(user_query=user_query)

            result.semantic_execution = AgentExecution(
                agent_name="semantic",
                input=semantic_prompt,
            )

            semantic_output = await self.semantic_agent.run(semantic_prompt)
            result.semantic_execution.complete(output=semantic_output.output)

            if not result.semantic_execution.output:
                raise Exception("Semantic agent failed to produce output")

            # SQL Agent
            sql_prompt = self.build_sql_prompt(user_query, semantic_output.output)
            result.sql_execution = AgentExecution(
                agent_name="sql",
                input=sql_prompt,
            )

            sql_output = await self.sql_agent.run(sql_prompt)
            result.sql_execution.complete(output=sql_output.output)

            # Synthesis Agent
            synthesis_prompt = self.build_synthesis_prompt(
                user_query, semantic_output.output, sql_output.output
            )

            result.synthesis_execution = AgentExecution(
                agent_name="supervisor",
                input=synthesis_prompt,
            )

            final_output = await self.supervisor_agent.run(synthesis_prompt)
            result.synthesis_execution.complete(output=final_output.output)

            result.final_answer = final_output.output
            result.success = True

        except Exception as e:
            if result.semantic_execution and not result.semantic_execution.output:
                result.semantic_execution.complete(error=str(e))

            if result.sql_execution and not result.sql_execution.output:
                result.sql_execution.complete(error=str(e))

            if result.synthesis_execution and not result.synthesis_execution.output:
                result.synthesis_execution.complete(error=str(e))

            result.success = False
            result.final_answer = f"Error processing query: {str(e)}"

        finally:
            result.total_duration_ms = (
                datetime.now() - start_time
            ).total_seconds() * 1000
            self.history.append(result)
            return result

    def get_history(self) -> List[QueryResult]:
        """Get the history of queries."""
        return self.history
