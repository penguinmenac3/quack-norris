from typing import Any
import json
import os


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.loads(f.read())


def read_config(config_name: str, overwrites: list[str] = []) -> Any:
    if not config_name.endswith(".json"):
        raise RuntimeError("Invalid config file format. Config must be of type json.")

    config = {}
    code_home_config_path = os.path.join(os.path.dirname(__file__), "..", "configs", config_name)
    if os.path.exists(code_home_config_path):
        config.update(**_load_json(code_home_config_path))
    home_config_path = os.path.expanduser("~/.config/quack_norris/").replace("/", os.sep)
    user_home_config_path = os.path.join(home_config_path, config_name)
    if os.path.exists(user_home_config_path):
        config.update(**_load_json(user_home_config_path))
    if os.path.exists(config_name):
        config.update(**_load_json(config_name))

    for arg in overwrites:
        if not arg.startswith("--"):
            print("Invalid argument, you can only overwrite config fields with --name=value")
            continue
        arg = arg[2:]
        if "=" not in arg:
            config[arg] = True
        else:
            key, value = arg.split("=")
            config[key] = type(config[key])(value)
    if config["debug"]:
        print(json.dumps(config, indent=2))
    return config


def write_config(config_name: str, content: Any) -> None:
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
