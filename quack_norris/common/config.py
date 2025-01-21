import os
import json


def read_config(config_name: str) -> any:
    home_config_path = os.path.expanduser("~/.config/quack_norris/").replace("/", os.sep)
    user_home_config_path = os.path.join(home_config_path, config_name)
    code_home_config_path = os.path.join(os.path.dirname(__file__), "..", "configs", config_name)
    path = ""
    if os.path.exists(config_name):
        path = config_name
    elif os.path.exists(user_home_config_path):
        path = user_home_config_path
    elif os.path.exists(code_home_config_path):
        path = code_home_config_path
    else:
        print(f"FAILED to find config: {config_name}")
        raise FileNotFoundError(
            "Config not found anywhere:\n"
            + f"  {config_name}\n  {user_home_config_path}\n  {code_home_config_path}"
        )
    print(f"Reading Config: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = f.read()
    if config_name.endswith(".json"):
        data = json.loads(data)
    return data


def write_config(config_name: str, content: str):
    home_config_path = os.path.expanduser("~/.config/quack_norris/")
    user_home_config_path = os.path.join(home_config_path, config_name)
    path = config_name
    if os.path.exists(config_name):
        path = config_name
    elif os.path.exists(user_home_config_path):
        path = user_home_config_path
    else:
        raise FileNotFoundError(f"Config not found in a writable place: {config_name}")

    if config_name.endswith(".json"):
        content = json.dumps(content, indent=4)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
