from typing import Any, Callable
import json
import os

from quack_norris.logging import logger


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.loads(f.read())


class Config:
    def __init__(self, config_name: str, overwrites: dict[str, Any] = {}):
        if not config_name.endswith(".json"):
            raise RuntimeError("Invalid config file format. Config must be of type json.")
        self._data = {}
        self._name = config_name
        self._overwrites = overwrites
        self._update_handlers: list[Callable] = []
        
        self._read()

    @property
    def code_home_path(self) -> str:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "configs"))
    
    @property
    def user_home_path(self) -> str:
        home_config_path = os.path.expanduser("~/.config/quack-norris/").replace("/", os.sep)
        return os.path.abspath(home_config_path)
    
    @property
    def local_path(self) -> str:
        return os.path.abspath("./")

    def _read(self):
        logger.info("Loading config")
        config = {}
        # Load from code home, user home, and local paths (overwrite in that order)
        for path in [self.code_home_path, self.user_home_path, self.local_path]:
            full_path = os.path.join(path, self._name)
            if os.path.exists(full_path):
                config.update(**_load_json(full_path))
        config.update(**self._overwrites)
        if config.get("debug", False):
            print(json.dumps(config, indent=2))
        self._data = config
        
        # Notify all handlers of the config update
        for handler in self._update_handlers:
            handler()
    
    def add_update_handler(self, handler: Callable) -> None:
        self._update_handlers.append(handler)

    def save(self) -> None:
        home_config_path = os.path.expanduser("~/.config/quack_norris/")
        user_home_config_path = os.path.join(home_config_path, self._name)
        path = self._name
        if os.path.exists(self._name):
            path = self._name
        elif os.path.exists(user_home_config_path):
            path = user_home_config_path
        else:
            raise FileNotFoundError(f"Config not found in a writable place: {self._name}")

        content = json.dumps(self._data, indent=4)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # Magic methods to behave like a dict
    def __getitem__(self, key: str) -> Any:
        return self._data.get(key, None)
    
    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)
    
    def __contains__(self, key: object) -> bool:
        return key in self._data
    
    def __delitem__(self, key: str) -> None:
        if key in self._data:
            del self._data[key]
    
    def __len__(self) -> int:
        return len(self._data)

    def to_dict(self) -> dict[str, Any]:
        return self._data.copy()
    
    def __str__(self) -> str:
        return json.dumps(self._data, indent=2)
