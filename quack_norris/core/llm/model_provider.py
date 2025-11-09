import concurrent.futures
import importlib
import glob
import os
from functools import partial

from quack_norris.logging import logger
from quack_norris.core.llm.types import LLM, Embedder, ModelConnectionSpec, ChatMessage, Tool, LLMResponse


# Registry for provider -> connection class
_MODEL_CONNECTION_REGISTRY = {}

def register_model_connector(*provider_names):
    def decorator(cls):
        for name in provider_names:
            _MODEL_CONNECTION_REGISTRY[name] = cls
        return cls
    return decorator


class ModelConnector(object):    
    def get_models(self) -> list[str]:
        raise NotImplementedError()

    def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[Tool] = [],
        system_prompt: str = "",
        remove_thoughts: bool = True,
        stream: bool = True,
    ) -> LLMResponse:
        raise NotImplementedError()
    
    def embeddings(self, model: str, input: str | list[str]) -> list[list[float]]:
        raise NotImplementedError()


class ModelProvider(object):
    _connections: dict[str, ModelConnector] = {}
    _models: dict[str, str] = {}

    @staticmethod
    def load_config(config: dict[str, ModelConnectionSpec] | None) -> None:
        if config is None:
            config = {
                "Ollama": ModelConnectionSpec(
                    api_endpoint="http://localhost:11434",
                    api_key="ollama",
                    provider="ollama",
                    model="AUTODETECT",
                    config={}
                ),
            }

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(ModelProvider._add_connection, config=conn, connection_name=name)
                for name, conn in config.items()
            ]
            # Store the models temporarily so we can add them in the order of the config
            # in case the user intentionally overwrites some connections, we can map that
            results = {}
            for future in concurrent.futures.as_completed(futures):
                name, connection, models = future.result()  # Raise exceptions if any
                ModelProvider._connections[name] = connection
                results[name] = models
            for name in config:
                ModelProvider._models.update(**results[name])
        logger.info(f"{len(ModelProvider._models.keys())} LLMs initialized (via {len(ModelProvider._connections.keys())} connections)")

    @staticmethod
    def _add_connection(config: ModelConnectionSpec, connection_name: str) -> tuple[str, ModelConnector, dict[str, str]]:
        models: dict[str, str] = {}
        logger.info(f"Connecting LLM: {connection_name}")
        provider = config["provider"]
        if provider in _MODEL_CONNECTION_REGISTRY:
            connection_cls = _MODEL_CONNECTION_REGISTRY[provider]
            connection = connection_cls(**config)
            models = {k: connection_name for k in connection.get_models()}
        else:
            raise NotImplementedError(f"No ModelConnector registered for provider '{provider}', known connectors for {list(_MODEL_CONNECTION_REGISTRY.keys())}.")
        return connection_name, connection, models

    @staticmethod
    def get_models() -> list[str]:
        return list(ModelProvider._models.keys())
    
    @staticmethod
    def get_llm(model: str) -> LLM:
        if model not in ModelProvider._models:
            raise RuntimeError(f"Invalid model name `{model}`, no such model available.")
        connection = ModelProvider._connections[ModelProvider._models[model]]
        return partial(connection.chat, model=model)

    @staticmethod
    def get_embedder(model: str) -> Embedder:
        if model not in ModelProvider._models:
            raise RuntimeError(f"Invalid model name `{model}`, no such model available.")
        connection = ModelProvider._connections[ModelProvider._models[model]]
        return partial(connection.embeddings, model=model)


# Dynamically import all model connection implementations
current_dir = os.path.dirname(__file__)
for path in glob.glob(os.path.join(current_dir, "model_connection_*.py")):
    logger.debug(f"Importing model connection from {path}")
    module_name = os.path.splitext(os.path.basename(path))[0]
    importlib.import_module(f".{module_name}", package=__package__)
