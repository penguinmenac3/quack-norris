from functools import wraps
from time import time
from uuid import uuid4

from flask import Flask, request
from waitress import serve

from quack_norris.common._types import Message
from quack_norris.server.router import router
from quack_norris.server.user import User, get_users

app = Flask(__name__)


def require_auth(func):
    @wraps(func)
    def decorator(*args, **kwargs):
        api_token = request.headers.get("Authorization")
        if api_token is None:
            return "Invalid Authentication (No token provided)", 401
        if api_token.startswith("Bearer"):
            api_token = " ".join(api_token.split(" ")[1:])
        user = get_users().get(api_token, None)
        if user is None:
            return "Invalid Authentication (Invalid token provided)", 401
        return func(user, *args, **kwargs)
    return decorator


@app.route("/v1/embeddings", methods=["POST"])
@require_auth
def embeddings(user: User):
    data = request.json
    model = data["model"]
    inputs = data["input"]
    if isinstance(inputs, str):
        inputs = [inputs]

    response = router.embeddings(model, inputs, data, user)

    embeds = response.embeds
    if len(embeds) == 1:
        embeds = embeds[0]
    return {
        "object": "list",
        "data": [{"object": "embedding", "embedding": embeds, "index": 0}],
        "model": model,
        "usage": {
            "prompt_tokens": response.prompt_tokens,
            "total_tokens": response.total_tokens,
        },
    }


@app.route("/v1/completions", methods=["POST"])
@require_auth
def completions(user: User):
    data = request.json
    model = data["model"]
    prompt = data["prompt"]
    suffix = data.get("suffix", "")
    if isinstance(prompt, list):
        prompt = prompt[0]

    response = router.complete(model, prompt, data, user)

    return {
        "id": uuid4(),
        "object": "text_completion",
        "created": int(time()),
        "model": model,
        "choices": [
            {
                "text": response.result + suffix,
                "index": 0,
                "logprobs": None,
                "finish_reason": response.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.total_tokens - response.prompt_tokens,
            "total_tokens": response.total_tokens,
        },
    }


@app.route("/v1/chat/completions", methods=["POST"])
@require_auth
def chat_completions(user: User):
    data = request.json
    model = data["model"]
    messages = [
        Message(role=message["role"], content=message["content"])
        for message in data["messages"]
    ]

    response = router.chat(model, messages, data, user)

    return {
        "id": uuid4(),
        "object": "text_completion",
        "created": int(time()),
        "model": model,
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": response.result,
                },
                "text": None,
                "index": 0,
                "logprobs": None,
                "finish_reason": response.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.total_tokens - response.prompt_tokens,
            "total_tokens": response.total_tokens,
        },
    }


def main(host: str, port: int, debug: bool):
    if debug:
        app.run(host, port, debug=debug)
    else:
        print(f"Starting API server on http://{host}:{port}")
        serve(app, host=host, port=port)
