from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from acp import (
    PROTOCOL_VERSION,
    Client,
    RequestError,
    start_tool_call,
    text_block,
    tool_content,
    tool_diff_content,
    update_agent_message_text,
    update_agent_thought_text,
    update_tool_call,
    update_user_message_text,
)
from acp.helpers import update_available_commands, update_current_mode
from acp.schema import (
    AgentCapabilities,
    AvailableCommand,
    ClientCapabilities,
    CloseSessionResponse,
    ConfigOptionUpdate,
    ForkSessionResponse,
    Implementation,
    InitializeResponse,
    ListSessionsResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptCapabilities,
    PromptResponse,
    ResumeSessionResponse,
    SessionCapabilities,
    SessionConfigOptionBoolean,
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    SessionInfoUpdate,
    SessionListCapabilities,
    SessionMode,
    SessionModeState,
    SetSessionConfigOptionResponse,
    SetSessionModeResponse,
    TextContentBlock,
    ToolCallUpdate,
    ToolKind,
)

from quack_norris.acp.approval import ApprovalPolicy
from quack_norris.acp.session import ACPSession, SessionStore
from quack_norris.acp.title import generate_session_title
from quack_norris.acp.tools import ACPOperationRegistry, make_acp_tools
from quack_norris.core import (
    LLM,
    AgentOutput,
    CheckpointOutput,
    ContextPolicy,
    ErrorOutput,
    MessageEnd,
    NudgeOutput,
    TextOutput,
    ThinkingOutput,
    ToolCallOutput,
    ToolResultOutput,
    agent,
)
from quack_norris.core.llm import ToolResult, UserMessage
from quack_norris.skills_and_agents import (
    discover_agents,
    discover_skill_info,
    discover_skills,
    load_agent_system_prompt,
    load_skill_content,
    make_skill_invoke_tool,
)

_DEFAULT_MODEL = "ollama/qwen3:14b"
_DEFAULT_PROMPT = (
    "You are Quack Norris, a concise coding agent. Use the available tools to inspect and "
    "modify the workspace. Validate your work before reporting completion."
)
_COMMANDS = [
    AvailableCommand(name="skills", description="List available skills"),
    AvailableCommand(name="skill", description="Invoke a skill for this turn"),
    AvailableCommand(name="refresh", description="Refresh agent and skill discovery"),
]


class QuackNorrisACPAgent:
    def __init__(self, *, store: SessionStore | None = None, agent_fn=agent) -> None:
        self._connection: Client | None = None
        self._client_capabilities = ClientCapabilities()
        self._sessions: dict[str, ACPSession] = {}
        self._store = store or SessionStore()
        self._agent_fn = agent_fn

    def on_connect(self, conn: Client) -> None:
        self._connection = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        self._client_capabilities = client_capabilities or ClientCapabilities()
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(
                    image=False,
                    audio=False,
                    embedded_context=False,
                ),
                session_capabilities=SessionCapabilities(list=SessionListCapabilities()),
            ),
            auth_methods=[],
            agent_info=Implementation(name="quack-norris", title="Quack Norris", version="3.0.0"),
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        if mcp_servers:
            raise RequestError.invalid_params({"mcpServers": "MCP servers are not supported"})
        project_root = self._validate_cwd(cwd)
        try:
            session = self._store.create(
                cwd=project_root,
                model=LLM.default_model() or _DEFAULT_MODEL,
                system_prompt=_DEFAULT_PROMPT,
                additional_directories=additional_directories,
            )
        except ValueError as exc:
            raise RequestError.invalid_params({"additionalDirectories": str(exc)}) from exc
        self._configure_session(session)
        self._sessions[session.session_id] = session
        await LLM.refresh_available_models()
        await self._emit_commands(session)
        return NewSessionResponse(
            session_id=session.session_id,
            modes=self._session_modes(session),
            config_options=self._session_config_options(session),
        )

    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[Any] | None = None,
        additional_directories: list[str] | None = None,
        **kwargs: Any,
    ) -> LoadSessionResponse:
        if mcp_servers:
            raise RequestError.invalid_params({"mcpServers": "MCP servers are not supported"})
        session = self._store.load(session_id)
        if session is None:
            raise RequestError.resource_not_found(session_id)
        if session.cwd.resolve() != self._validate_cwd(cwd):
            raise RequestError.invalid_params({"cwd": "CWD does not match the stored session"})
        self._configure_session(session)
        self._sessions[session_id] = session
        await LLM.refresh_available_models()
        for update in self._store.read_updates(session_id):
            await self._require_connection().session_update(session_id, update)
        if session.title:
            await self._require_connection().session_update(
                session_id,
                SessionInfoUpdate(
                    session_update="session_info_update",
                    title=session.title,
                    updated_at=session.updated_at,
                ),
            )
        await self._emit_commands(session, persist=False)
        return LoadSessionResponse(
            modes=self._session_modes(session),
            config_options=self._session_config_options(session),
        )

    async def list_sessions(
        self,
        cwd: str | None = None,
        cursor: str | None = None,
        **kwargs: Any,
    ) -> ListSessionsResponse:
        try:
            offset = int(cursor) if cursor else 0
        except ValueError as exc:
            raise RequestError.invalid_params({"cursor": "Invalid cursor"}) from exc
        if offset < 0:
            raise RequestError.invalid_params({"cursor": "Invalid cursor"})
        sessions = self._store.list_sessions(cwd)
        page = sessions[offset : offset + 50]
        next_cursor = str(offset + 50) if offset + 50 < len(sessions) else None
        return ListSessionsResponse(sessions=page, next_cursor=next_cursor)

    async def prompt(
        self,
        session_id: str,
        prompt: list[Any],
        **kwargs: Any,
    ) -> PromptResponse:
        session = self._require_session(session_id)
        text = self._prompt_text(prompt)
        async with session.prompt_lock:
            session.cancelled = False
            session.active_prompt = asyncio.current_task()
            try:
                if await self._handle_command(session, text):
                    self._store.save(session)
                    return PromptResponse(stop_reason="end_turn")
                await self._emit(session, update_user_message_text(text))
                core_text = self._expand_skill_command(session, text)
                session.chat_history.append(UserMessage(content=core_text))
                needs_title = session.title is None
                self._store.save(session)
                assistant_text = await self._run_core(session)
                if needs_title and not session.cancelled:
                    title_model = (
                        session.context_policy.config.summarizer_model
                        if session.context_policy
                        else None
                    ) or session.model
                    session.title = await generate_session_title(
                        text,
                        assistant_text,
                        title_model,
                    )
                    await self._emit(
                        session,
                        SessionInfoUpdate(
                            session_update="session_info_update",
                            title=session.title,
                        ),
                    )
                self._store.save(session)
                return PromptResponse(stop_reason="cancelled" if session.cancelled else "end_turn")
            except asyncio.CancelledError:
                session.cancelled = True
                await self._cancel_operations(session)
                self._store.save(session)
                return PromptResponse(stop_reason="cancelled")
            except Exception:
                self._store.save(session)
                raise
            finally:
                session.active_prompt = None

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        session = self._require_session(session_id)
        session.cancelled = True
        if (
            session.active_prompt is not None
            and session.active_prompt is not asyncio.current_task()
        ):
            session.active_prompt.cancel()
        await self._cancel_operations(session)

    async def set_session_mode(
        self, session_id: str, mode_id: str, **kwargs: Any
    ) -> SetSessionModeResponse:
        session = self._require_session(session_id)
        available = {mode.id for mode in self._session_modes(session).available_modes}
        if mode_id not in available:
            raise RequestError.invalid_params({"modeId": "Unknown agent persona"})
        if mode_id == "Quack Norris":
            session.system_prompt = _DEFAULT_PROMPT
        else:
            try:
                session.system_prompt = load_agent_system_prompt(mode_id, session.cwd)
            except KeyError as exc:
                raise RequestError.invalid_params({"modeId": "Unknown agent persona"}) from exc
        session.selected_agent = mode_id
        self._store.save(session)
        await self._emit(session, update_current_mode(mode_id))
        return SetSessionModeResponse()

    async def set_config_option(
        self,
        config_id: str,
        session_id: str,
        value: str | bool,
        **kwargs: Any,
    ) -> SetSessionConfigOptionResponse:
        if not isinstance(value, str):
            raise RequestError.invalid_params({"value": "Select options require a string value"})
        session = self._require_session(session_id)
        if config_id == "agent":
            await self.set_session_mode(session_id, value)
        elif config_id == "model":
            await LLM.refresh_available_models()
            if value not in LLM.available_models():
                raise RequestError.invalid_params({"value": "Unknown model"})
            session.model = value
            self._configure_session(session)
            self._store.save(session)
        else:
            raise RequestError.invalid_params({"configId": "Unsupported configuration option"})
        config_options = self._session_config_options(session)
        await self._emit(
            session,
            ConfigOptionUpdate(
                session_update="config_option_update",
                config_options=config_options,
            ),
        )
        return SetSessionConfigOptionResponse(config_options=config_options)

    async def authenticate(self, method_id: str, **kwargs: Any) -> None:
        raise RequestError.method_not_found("authenticate")

    async def fork_session(
        self,
        session_id: str,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> ForkSessionResponse:
        raise RequestError.method_not_found("session/fork")

    async def resume_session(
        self,
        session_id: str,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> ResumeSessionResponse:
        raise RequestError.method_not_found("session/resume")

    async def close_session(
        self, session_id: str, **kwargs: Any
    ) -> CloseSessionResponse | None:
        raise RequestError.method_not_found("session/close")

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RequestError.method_not_found(f"_{method}")

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        return None

    def _configure_session(self, session: ACPSession) -> None:
        project_root = session.cwd
        session.skills = discover_skill_info(project_root)
        registry = session.operation_registry or ACPOperationRegistry()
        session.operation_registry = registry
        fs = self._client_capabilities.fs
        session.tools = make_acp_tools(
            connection=self._require_connection(),
            session_id=session.session_id,
            cwd=session.cwd,
            additional_directories=session.additional_directories,
            can_read=bool(fs and fs.read_text_file),
            can_write=bool(fs and fs.write_text_file),
            can_use_terminal=bool(self._client_capabilities.terminal),
            registry=registry,
        )
        session.tools.append(make_skill_invoke_tool(project_root))
        config = LLM.context_config()
        session.context_policy = ContextPolicy(
            config=config,
            context_window=LLM.get_context_window(session.model),
        )

    async def _run_core(self, session: ACPSession) -> str:
        tool_calls: dict[str, ToolCallOutput] = {}

        async def on_output(output: AgentOutput) -> None:
            if isinstance(output, TextOutput):
                await self._emit(session, update_agent_message_text(output.text))
            elif isinstance(output, ThinkingOutput):
                await self._emit(session, update_agent_thought_text(output.text))
            elif isinstance(output, ToolCallOutput):
                tool_calls[output.tool_call_id] = output
                await self._emit(
                    session,
                    start_tool_call(
                        output.tool_call_id,
                        _tool_title(output.tool_name, output.arguments),
                        kind=_tool_kind(output.tool_name),
                        status="pending",
                        content=_tool_diff(output.tool_name, output.arguments),
                        raw_input=output.arguments,
                    ),
                )
            elif isinstance(output, ToolResultOutput):
                status = "failed" if output.result.is_error else "completed"
                call = tool_calls.get(output.tool_call_id)
                content = _tool_diff(call.tool_name, call.arguments) if call else []
                content = [*content, tool_content(text_block(output.result.content))]
                await self._emit(
                    session,
                    update_tool_call(
                        output.tool_call_id,
                        status=status,
                        content=content,
                        raw_output={"is_error": output.result.is_error},
                    ),
                )
            elif isinstance(output, NudgeOutput):
                await self._emit(session, update_user_message_text(output.text))
            elif isinstance(output, ErrorOutput):
                await self._emit(session, update_agent_message_text(output.message))
            elif isinstance(output, (MessageEnd, CheckpointOutput)):
                return

        async def on_permission(call: ToolCallOutput) -> bool | ToolResult:
            policy = ApprovalPolicy(session.cwd)
            if call.needs_approval != "human" and policy.is_allowed(
                call.tool_name, call.arguments
            ):
                return True
            choices = policy.choices(call.tool_name, call.arguments)
            response = await self._require_connection().request_permission(
                session.session_id,
                ToolCallUpdate(
                    tool_call_id=call.tool_call_id,
                    title=_tool_title(call.tool_name, call.arguments),
                    kind=_tool_kind(call.tool_name),
                    status="pending",
                    raw_input=call.arguments,
                ),
                [choice.option for choice in choices],
            )
            outcome = response.outcome
            if getattr(outcome, "outcome", None) != "selected":
                return False
            selected = next(
                (
                    choice
                    for choice in choices
                    if choice.option.option_id == getattr(outcome, "option_id", None)
                ),
                None,
            )
            if selected is None or selected.option.kind.startswith("reject"):
                return False
            policy.persist(selected)
            return True

        return await self._agent_fn(
            model=session.model,
            system_prompt=session.system_prompt,
            tools=session.tools,
            chat_history=session.chat_history,
            on_permission_request=on_permission,
            on_output=on_output,
            context=session.context_policy,
            skills=session.skills,
        )

    async def _handle_command(self, session: ACPSession, text: str) -> bool:
        command, _, argument = text.strip().partition(" ")
        if command == "/skills":
            names = discover_skills(session.cwd)
            content = "Available skills:\n" + "\n".join(names) if names else "No skills found."
            await self._emit(session, update_agent_message_text(content))
            return True
        if command == "/refresh":
            LLM.reload()
            await LLM.refresh_available_models(force=True)
            self._configure_session(session)
            await self._emit_commands(session)
            await self._emit(
                session,
                ConfigOptionUpdate(
                    session_update="config_option_update",
                    config_options=self._session_config_options(session),
                ),
            )
            await self._emit(
                session,
                update_agent_message_text("Agent and skill discovery refreshed."),
            )
            return True
        return False

    def _expand_skill_command(self, session: ACPSession, text: str) -> str:
        command, _, argument = text.strip().partition(" ")
        if command != "/skill":
            return text
        name, _, task = argument.partition(" ")
        content = load_skill_content(name, session.cwd)
        if content is None:
            return f"The requested skill '{name}' was not found. {task}".strip()
        return f"{task}\n\n[User-invoked skill: {name}]\n{content}".strip()

    async def _emit_commands(self, session: ACPSession, *, persist: bool = False) -> None:
        update = update_available_commands(_COMMANDS)
        await self._require_connection().session_update(session.session_id, update)
        if persist:
            self._store.append_update(session.session_id, update)

    async def _emit(self, session: ACPSession, update: Any) -> None:
        await self._require_connection().session_update(session.session_id, update)
        self._store.append_update(session.session_id, update)

    @staticmethod
    def _validate_cwd(cwd: str) -> Path:
        path = Path(cwd)
        if not path.is_absolute() or not path.exists() or not path.is_dir():
            raise RequestError.invalid_params({"cwd": "CWD must be an existing absolute directory"})
        return path.resolve()

    @staticmethod
    def _prompt_text(prompt: list[Any]) -> str:
        if not prompt:
            raise RequestError.invalid_params({"prompt": "Prompt must not be empty"})
        chunks: list[str] = []
        for block in prompt:
            if not isinstance(block, TextContentBlock):
                raise RequestError.invalid_params({"prompt": "Only text prompts are supported"})
            chunks.append(block.text)
        return "\n".join(chunks)

    @staticmethod
    def _session_modes(session: ACPSession) -> SessionModeState:
        names = {"Quack Norris", *discover_agents(session.cwd), session.selected_agent}
        modes = [
            SessionMode(id=name, name=name)
            for name in sorted(names, key=lambda item: (item != "Quack Norris", item.casefold()))
        ]
        return SessionModeState(
            current_mode_id=session.selected_agent,
            available_modes=modes,
        )

    @staticmethod
    def _session_config_options(
        session: ACPSession,
    ) -> list[SessionConfigOptionSelect | SessionConfigOptionBoolean]:
        agents = {"Quack Norris", *discover_agents(session.cwd), session.selected_agent}
        agent_options = [
            SessionConfigSelectOption(value=name, name=name)
            for name in sorted(agents, key=lambda item: (item != "Quack Norris", item.casefold()))
        ]
        models = set(LLM.available_models())
        models.add(session.model)
        model_options = [
            SessionConfigSelectOption(value=model, name=model)
            for model in sorted(models, key=str.casefold)
        ]
        return [
            SessionConfigOptionSelect(
                id="agent",
                name="Agent",
                description="Agent persona used for this session",
                category="mode",
                type="select",
                current_value=session.selected_agent,
                options=agent_options,
            ),
            SessionConfigOptionSelect(
                id="model",
                name="Model",
                description="LLM used for this session",
                category="model",
                type="select",
                current_value=session.model,
                options=model_options,
            ),
        ]

    async def _cancel_operations(self, session: ACPSession) -> None:
        registry = session.operation_registry
        if registry is None:
            return
        connection = self._require_connection()
        for operation in registry.take_all():
            with contextlib.suppress(Exception):
                await connection.kill_terminal(session.session_id, operation.terminal_id)
            if not operation.wait_task.done():
                operation.wait_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await operation.wait_task
            with contextlib.suppress(Exception):
                await connection.release_terminal(session.session_id, operation.terminal_id)

    def _require_session(self, session_id: str) -> ACPSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise RequestError.resource_not_found(session_id)
        return session

    def _require_connection(self) -> Client:
        if self._connection is None:
            raise RequestError.internal_error({"connection": "ACP client is not connected"})
        return self._connection


def _tool_title(tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name in {"pwsh", "bash"}:
        return f"{tool_name}: {arguments.get('command', '')}"
    if tool_name == "file_view":
        return f"Read {arguments.get('path', '')}"
    if tool_name == "file_write":
        return f"Write {arguments.get('path', '')}"
    if tool_name == "file_str_replace":
        return f"Edit {arguments.get('path', '')}"
    if tool_name == "file_move":
        return f"Move {arguments.get('source', '')} → {arguments.get('destination', '')}"
    if tool_name == "file_delete":
        return f"Delete {arguments.get('path', '')}"
    return tool_name


def _tool_diff(tool_name: str, arguments: dict[str, Any]) -> list[Any]:
    path = arguments.get("path")
    if not isinstance(path, str):
        return []
    if tool_name == "file_write":
        content = arguments.get("content")
        return [tool_diff_content(path, content)] if isinstance(content, str) else []
    if tool_name == "file_str_replace":
        old_text = arguments.get("old_string")
        new_text = arguments.get("new_string")
        if isinstance(old_text, str) and isinstance(new_text, str):
            return [tool_diff_content(path, new_text, old_text)]
    return []


def _tool_kind(tool_name: str) -> ToolKind:
    if tool_name == "file_view":
        return "read"
    if tool_name in {"file_write", "file_str_replace"}:
        return "edit"
    if tool_name == "file_move":
        return "move"
    if tool_name == "file_delete":
        return "delete"
    if tool_name in {"pwsh", "bash", "check_tool", "await_tool", "kill_tool"}:
        return "execute"
    return "other"
