import json
from typing import NamedTuple

from quack_norris.common.config import read_config, write_config


USER_CONFIG_NAME = "users.json"
_users = None


class User(NamedTuple):
    api_key: str
    selected_chat: str
    workdir: str  # where the AI can read and write (also store chat histories)
    data_sources: list[str]  # where the AI can read


def get_users() -> dict[str, User]:
    global _users
    if _users is None:
        try:
            data = read_config(USER_CONFIG_NAME)
            _users = {
                date["api_key"]: User(date["api_key"], date["selected_chat"], date["workdir"], date["data_sources"])
                for date in data
            }
        except json.JSONDecodeError:
            print(f"Failed to decode JSON file: {USER_CONFIG_NAME}")
            _users = {}
        except FileNotFoundError:
            print(f"Failed to find config: {USER_CONFIG_NAME}")
            _users = {}
    return _users


def update_user(user: User, **kwargs):
    global _users
    assert _users is not None
    _users[user.api_key] = user._replace(**kwargs)
    write_config(USER_CONFIG_NAME, list(_users.values()))
