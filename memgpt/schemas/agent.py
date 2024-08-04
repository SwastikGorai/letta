import uuid
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import Field

from memgpt.schemas.embedding_config import EmbeddingConfig
from memgpt.schemas.llm_config import LLMConfig
from memgpt.schemas.memgpt_base import MemGPTBase
from memgpt.schemas.memory import Memory


class BaseAgent(MemGPTBase):
    __id_prefix__ = "agent"
    description: Optional[str] = Field(None, description="The description of the agent.")

    # metadata
    metadata_: Optional[Dict] = Field(None, description="The metadata of the agent.", alias="metadata_")
    user_id: Optional[str] = Field(None, description="The user id of the agent.")


class AgentState(BaseAgent):
    """Representation of an agent's state."""

    id: str = BaseAgent.generate_id_field()
    name: str = Field(..., description="The name of the agent.")
    created_at: datetime = Field(..., description="The datetime the agent was created.", default_factory=datetime.now)

    # in-context memory
    message_ids: Optional[List[str]] = Field(default=None, description="The ids of the messages in the agent's in-context memory.")
    memory: Memory = Field(default_factory=Memory, description="The in-context memory of the agent.")

    # tools
    tools: List[str] = Field(..., description="The tools used by the agent.")

    # system prompt
    system: str = Field(..., description="The system prompt used by the agent.")

    # llm information
    llm_config: LLMConfig = Field(..., description="The LLM configuration used by the agent.")
    embedding_config: EmbeddingConfig = Field(..., description="The embedding configuration used by the agent.")


class CreateAgent(BaseAgent):
    # all optional as server can generate defaults
    name: Optional[str] = Field(None, description="The name of the agent.")
    message_ids: Optional[List[uuid.UUID]] = Field(None, description="The ids of the messages in the agent's in-context memory.")
    memory: Optional[Memory] = Field(None, description="The in-context memory of the agent.")
    tools: Optional[List[str]] = Field(None, description="The tools used by the agent.")
    system: Optional[str] = Field(None, description="The system prompt used by the agent.")
    llm_config: Optional[LLMConfig] = Field(None, description="The LLM configuration used by the agent.")
    embedding_config: Optional[EmbeddingConfig] = Field(None, description="The embedding configuration used by the agent.")


class UpdateAgentState(BaseAgent):
    id: str = Field(..., description="The id of the agent.")
    name: Optional[str] = Field(None, description="The name of the agent.")
    tools: Optional[List[str]] = Field(None, description="The tools used by the agent.")
    system: Optional[str] = Field(None, description="The system prompt used by the agent.")
    llm_config: Optional[LLMConfig] = Field(None, description="The LLM configuration used by the agent.")
    embedding_config: Optional[EmbeddingConfig] = Field(None, description="The embedding configuration used by the agent.")

    # TODO: determine if these should be editable via this schema?
    message_ids: Optional[List[str]] = Field(None, description="The ids of the messages in the agent's in-context memory.")
    memory: Optional[Memory] = Field(None, description="The in-context memory of the agent.")
