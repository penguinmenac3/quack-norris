from quack_norris.api.chat_handler import ChatHandlerProvider, ChatHandler
from quack_norris.core.agents.agent import get_agent, list_agents


class AgentProvider(ChatHandlerProvider):
    def get_handler(self, name: str) -> ChatHandler:
        if name not in self.list_handlers():
            raise RuntimeError(f"Model/Agent '{name}' not found in multi-agent runner provider.")
        name = name.replace("agent.", "")

        agent = get_agent(name)
        if agent is None:
            raise RuntimeError(f"Agent '{name}' could not be found.")
        return agent

    def list_handlers(self) -> list[str]:
        return [f"agent.{k}" for k in list_agents().keys()]
