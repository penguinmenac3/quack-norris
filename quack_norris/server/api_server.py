from uuid import uuid4
from time import time
from functools import wraps
from flask import Flask, request

from quack_norris.server._types import Message
from quack_norris.server.user import get_users, User
from quack_norris.server.router import router
from quack_norris.config import read_config


app = Flask(__name__)

def require_auth(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        api_token = request.headers.get("Authorization")
        if api_token is None:
            return "Invalid Authentication", 401
        user = get_users().get(api_token, None)
        if user is None:
            return "Invalid Authentication", 401
        return func(*args, user=user, **kwargs)
    return decorated


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


def main(host: str, port: int):
    app.run(host, port)
