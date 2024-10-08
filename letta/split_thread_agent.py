import datetime
import threading
from typing import List, Optional, Tuple, Union

from letta.agent import Agent, BaseAgent, save_agent
from letta.constants import FIRST_MESSAGE_ATTEMPTS
from letta.functions.functions import parse_source_code
from letta.functions.schema_generator import generate_schema
from letta.interface import AgentInterface
from letta.metadata import MetadataStore
from letta.prompts import gpt_system
from letta.schemas.agent import AgentState, AgentStepResponse, AgentType, CreateAgent
from letta.schemas.embedding_config import EmbeddingConfig
from letta.schemas.enums import OptionState
from letta.schemas.llm_config import LLMConfig
from letta.schemas.message import Message
from letta.schemas.openai.chat_completion_response import UsageStatistics
from letta.schemas.tool import Tool

MEMORY_TOOLS = [
    "core_memory_append",
    "core_memory_replace",
    "archival_memory_insert",
]


class SplitThreadAgent(BaseAgent):
    def __init__(
        self,
        interface: AgentInterface,
        agent_state: AgentState,
        conversation_agent_state: AgentState,
        conversation_tools: List[Tool],
        memory_agent_state: AgentState,
        memory_tools: List[Tool],
        # extras
        messages_total: Optional[int] = None,  # TODO remove?
        first_message_verify_mono: bool = True,  # TODO move to config?
    ):
        self.agent_state = agent_state
        self.memory = agent_state.memory
        self.system = agent_state.system
        self.interface = interface

        self.agent = Agent(
            interface=interface,
            agent_state=agent_state,
            tools=[],
            messages_total=messages_total,
            first_message_verify_mono=first_message_verify_mono,
        )

        self.conversation_agent = Agent(
            interface=interface,
            agent_state=conversation_agent_state,
            tools=conversation_tools,
            messages_total=messages_total,
            first_message_verify_mono=first_message_verify_mono,
        )
        self.conversation_waited = False
        self.conversation_agent_lock = threading.Lock()

        self.memory_wait_tool = Tool(
            name="wait_for_memory_update",
            source_type="python",
            source_code=parse_source_code(self._wait_for_memory_tool),
            json_schema=generate_schema(self._wait_for_memory_tool),
            description="",
            module="",
            user_id=conversation_agent_state.user_id,
            tags=[],
        )
        conversation_agent_state.tools.append(self.memory_wait_tool.name)
        self.conversation_agent.link_tools(conversation_tools + [self.memory_wait_tool])
        self.conversation_agent.update_state()

        self.memory_agent = Agent(
            interface=interface,
            agent_state=memory_agent_state,
            tools=memory_tools,
            messages_total=messages_total,
            first_message_verify_mono=first_message_verify_mono,
        )
        self.memory_result = None
        self.memory_result_lock = threading.Lock()
        self.memory_finished = False
        self.memory_condition = threading.Condition()

        self.update_state()

    def step(
        self,
        messages: Union[Message, List[Message], str],  # TODO deprecate str inputs
        first_message: bool = False,
        first_message_retry_limit: int = FIRST_MESSAGE_ATTEMPTS,
        skip_verify: bool = False,
        return_dicts: bool = True,  # if True, return dicts, if False, return Message objects
        recreate_message_timestamp: bool = True,  # if True, when input is a Message type, recreated the 'created_at' field
        stream: bool = False,  # TODO move to config?
        timestamp: Optional[datetime.datetime] = None,
        inner_thoughts_in_kwargs_option: OptionState = OptionState.DEFAULT,
        ms: Optional[MetadataStore] = None,
    ) -> AgentStepResponse:
        self.memory_finished = False
        memory_thread = threading.Thread(
            target=self._memory_step,
            args=(
                messages,
                first_message,
                first_message_retry_limit,
                skip_verify,
                return_dicts,
                recreate_message_timestamp,
                stream,
                timestamp,
                inner_thoughts_in_kwargs_option,
                ms,
            ),
        )
        memory_thread.start()

        with self.conversation_agent_lock:
            conversation_step = self.conversation_agent.step(
                first_message=first_message,
                user_message=messages,
                first_message_retry_limit=first_message_retry_limit,
                skip_verify=skip_verify,
                return_dicts=return_dicts,
                recreate_message_timestamp=recreate_message_timestamp,
                stream=stream,
                timestamp=timestamp,
                inner_thoughts_in_kwargs_option=inner_thoughts_in_kwargs_option,
                ms=ms,
            )

            if self.conversation_waited:
                next_conversation_step = self.conversation_agent.step(
                    first_message=first_message,
                    user_message=messages,
                    first_message_retry_limit=first_message_retry_limit,
                    skip_verify=skip_verify,
                    return_dicts=return_dicts,
                    recreate_message_timestamp=recreate_message_timestamp,
                    stream=stream,
                    timestamp=timestamp,
                    inner_thoughts_in_kwargs_option=inner_thoughts_in_kwargs_option,
                    ms=ms,
                )
                conversation_step = self._combine_steps(conversation_step, next_conversation_step)
                self.conversation_waited = False

        step = conversation_step
        with self.memory_result_lock:
            if self.memory_result:
                step = self._combine_steps(self.memory_result, conversation_step)
                self.memory_result = None

        return step

    def _memory_step(
        self,
        messages: Union[Message, List[Message], str],  # TODO deprecate str inputs
        first_message: bool = False,
        first_message_retry_limit: int = FIRST_MESSAGE_ATTEMPTS,
        skip_verify: bool = False,
        return_dicts: bool = True,  # if True, return dicts, if False, return Message objects
        recreate_message_timestamp: bool = True,  # if True, when input is a Message type, recreated the 'created_at' field
        stream: bool = False,  # TODO move to config?
        timestamp: Optional[datetime.datetime] = None,
        inner_thoughts_in_kwargs_option: OptionState = OptionState.DEFAULT,
        ms: Optional[MetadataStore] = None,
    ) -> AgentStepResponse:
        memory_step = self.memory_agent.step(
            user_message=messages,
            first_message=first_message,
            first_message_retry_limit=first_message_retry_limit,
            skip_verify=skip_verify,
            return_dicts=return_dicts,
            recreate_message_timestamp=recreate_message_timestamp,
            stream=stream,
            timestamp=timestamp,
            inner_thoughts_in_kwargs_option=inner_thoughts_in_kwargs_option,
            ms=ms,
        )
        with self.memory_result_lock:
            if self.memory_result:
                self.memory_result = self._combine_steps(self.memory_result, memory_step)
            else:
                self.memory_result = memory_step
        self.memory_finished = True

        with self.conversation_agent_lock:
            self.conversation_agent.memory = self.memory_agent.memory
            self.conversation_agent.update_state()
            save_agent(agent=self.conversation_agent, ms=ms)

        with self.memory_condition:
            self.memory_condition.notify()

    def _wait_for_memory_tool(self):
        with self.memory_condition:
            while not self.memory_finished:
                self.memory_condition.wait()

        self.conversation_waited = True

    def _combine_steps(self, *steps: AgentStepResponse) -> AgentStepResponse:
        combined_step = AgentStepResponse(
            messages=[],
            heartbeat_request=False,
            function_failed=False,
            in_context_memory_warning=False,
            usage=UsageStatistics(),
        )

        for step in steps:
            combined_step.messages += step.messages
            combined_step.heartbeat_request = combined_step.heartbeat_request or step.heartbeat_request
            combined_step.function_failed = combined_step.function_failed or step.function_failed
            combined_step.in_context_memory_warning = combined_step.in_context_memory_warning or step.in_context_memory_warning
            combined_step.usage += step.usage

        return combined_step

    def update_state(self) -> AgentState:
        self.conversation_agent.update_state()
        self.memory_agent.update_state()
        self.agent.update_state()

        self.agent_state = self.agent.agent_state
        self.agent_state.memory = self.memory
        self.agent_state.system = self.system

        return self.agent_state


def create_split_thread_agent(
    request: CreateAgent,
    user_id: str,
    tool_objs: List[Tool],
    llm_config: LLMConfig,
    embedding_config: EmbeddingConfig,
    interface: AgentInterface,
) -> Tuple[SplitThreadAgent, AgentState]:
    conversation_prompt = gpt_system.get_system_text("split_conversation")
    memory_prompt = gpt_system.get_system_text("split_memory")

    memory_tool_objs = [i for i in tool_objs if i.name in MEMORY_TOOLS]
    conversation_tool_objs = [i for i in tool_objs if i.name not in MEMORY_TOOLS]

    conversation_agent_state = AgentState(
        name=f"{request.name}_conversation",
        user_id=user_id,
        tools=[i.name for i in conversation_tool_objs],
        agent_type=AgentType.memgpt_agent,
        llm_config=llm_config,
        embedding_config=embedding_config,
        system=conversation_prompt,
        memory=request.memory,
        description=request.description,
        metadata_=request.metadata_,
    )

    memory_agent_state = AgentState(
        name=f"{request.name}_memory",
        user_id=user_id,
        tools=[i.name for i in memory_tool_objs],
        agent_type=AgentType.memgpt_agent,
        llm_config=llm_config,
        embedding_config=embedding_config,
        system=memory_prompt,
        memory=request.memory,
        description=request.description,
        metadata_=request.metadata_,
    )

    agent_state = AgentState(
        name=request.name,
        user_id=user_id,
        tools=[],
        agent_type=AgentType.split_thread_agent,
        llm_config=llm_config,
        embedding_config=embedding_config,
        system=request.system,
        memory=request.memory,
        description=request.description,
        metadata_=request.metadata_,
    )

    agent = SplitThreadAgent(
        interface=interface,
        agent_state=agent_state,
        conversation_agent_state=conversation_agent_state,
        conversation_tools=conversation_tool_objs,
        memory_agent_state=memory_agent_state,
        memory_tools=memory_tool_objs,
        # gpt-3.5-turbo tends to omit inner monologue, relax this requirement for now
        first_message_verify_mono=True if (llm_config.model is not None and "gpt-4" in llm_config.model) else False,
    )

    return agent, agent_state


def save_split_thread_agent(agent: SplitThreadAgent, ms: MetadataStore):
    """Save agent to metadata store"""

    assert agent.agent_state.agent_type == AgentType.split_thread_agent, "Agent state must be a split thread agent."

    # save conversational agent
    save_agent(agent=agent.agent, ms=ms)
    save_agent(agent=agent.conversation_agent, ms=ms)
    save_agent(agent=agent.memory_agent, ms=ms)
    if ms.get_tool(tool_name=agent.memory_wait_tool.name, user_id=agent.memory_agent.agent_state.user_id) is None:
        ms.create_tool(agent.memory_wait_tool)
    agent.update_state()