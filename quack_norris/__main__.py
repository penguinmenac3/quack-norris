import os
import json
from quack_norris.core import LLM
from quack_norris.servers import serve_openai_api
from quack_norris.servers.proxy_chat_handler import make_proxy_handlers
from quack_norris.agents.agent_chat_handler import make_agent_handlers


def main(work_dir=None):
    # Define paths
    if work_dir is None:
        home = os.path.expanduser("~")
        work_dir = os.path.join(home, ".config/quack-norris")
    config_path = os.path.join(work_dir, "config.json")

    # Read the config
    print("Loading config")
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = json.load(f)
    else:
        print(f"No config found. Create a `{work_dir}/config.json`.")
        exit(1)
    
    # Setup environment variables from config
    print("Initializing LLMs")
    llm = LLM.from_config(config)

    handlers = {}
    print("Creating Proxies")
    handlers.update(make_proxy_handlers(config, llm))
    print("Creating Agents")
    handlers.update(make_agent_handlers(config, llm, work_dir, config_path))
    print("Starting server")
    serve_openai_api(handlers=handlers, port=11435)


if __name__ == "__main__":
    main()
