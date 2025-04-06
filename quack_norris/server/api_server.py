from time import time
from uuid import uuid4
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from quack_norris.common._types import (
    ChatMessage,
    ChatCompletionRequest,
    OllamaChatCompletionRequest,
)
from quack_norris.common.quack_norris import QuackNorris

DEBUG = False

app = FastAPI(title="QuackNorris-Server")
quack = QuackNorris()

# Add CORS middleware
origins = [
    "http://localhost:5173",  # Your frontend's origin
    "http://localhost",  # Allow from localhost (useful for development)
    "*",  # (Use with caution - see notes below)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Specify allowed methods
    allow_headers=["*"],  # Specify allowed headers (use with caution)
    allow_credentials=True,  # Allow cookies (if needed)
)

# def require_auth(func):
#     @wraps(func)
#     def decorator(*args, **kwargs):
#         api_token = request.headers.get("Authorization")
#         if api_token is None:
#             return "Invalid Authentication (No token provided)", 401
#         if api_token.startswith("Bearer"):
#             api_token = " ".join(api_token.split(" ")[1:])
#         user = get_users().get(api_token, None)
#         if user is None:
#             return "Invalid Authentication (Invalid token provided)", 401
#         return func(user, *args, **kwargs)
#     return decorator


# @app.route("/v1/embeddings", methods=["POST"])
# @require_auth
# def embeddings(user: User):
#     print(f"[v1/embeddings] {request.json}")
#     data = request.json
#     if data is None or "model" not in data or "input" not in data:
#         return "Invalid request data.", 400
#     model = data["model"]
#     inputs = data["input"]
#     if isinstance(inputs, str):
#         inputs = [inputs]

#     response = router.embeddings(model, inputs, data, user)

#     embeds = response.embeds
#     if len(embeds) == 1:
#         embeds = embeds[0]
#     return {
#         "object": "list",
#         "data": [{"object": "embedding", "embedding": embeds, "index": 0}],
#         "model": model,
#         "usage": {
#             "prompt_tokens": response.prompt_tokens,
#             "total_tokens": response.total_tokens,
#         },
#     }


def _wrap_openai_chat_generator(stream, model):
    for i, token in enumerate(stream):
        chunk = {
            "id": i,
            "object": "chat.completion.chunk",
            "created": int(time()),
            "model": model,
            "choices": [{"delta": {"content": token, "role": "assistant"}}],
        }
        if DEBUG:
            print(f"CHUNK: {json.dumps(chunk)}")
        yield f"data: {json.dumps(chunk)}\n\n"
    if DEBUG:
        print("CHUNK: [DONE]")
    yield "data: [DONE]\n\n"


@app.post("/chat/completions")
def openai_chat_completions(request: ChatCompletionRequest):
    if DEBUG:
        print(f"REQUEST: {request}")
    reason = "stop"
    try:
        response = quack.chat(request)
    except RuntimeError as e:
        response = str(e)
        reason = "error"
    if not isinstance(response, str):
        return StreamingResponse(
            _wrap_openai_chat_generator(response, request.model), media_type="text/event-stream"
        )
    response = {
        "id": str(uuid4()),
        "object": "chat.completion",
        "model": request.model,
        "created": int(time()),
        "choices": [
            {"finish_reason": reason, "message": ChatMessage(role="assistant", content=response)}
        ],
    }
    if DEBUG:
        print(f"RESPONSE: {json.dumps(response)}")
    return response


def _wrap_ollama_chat_generator(stream, model):
    for token in stream:
        chunk = {
            "model": model,
            "created": str(time()),
            "message": {
                "role": "assistant",
                "content": token,
                "images": None,
            },
            "done": False,
        }
        if DEBUG:
            print(f"{json.dumps(chunk)}")
        yield f"{json.dumps(chunk)}\n"
    final_chunk = {
        "model": model,
        "created": str(time()),
        "message": {
            "role": "assistant",
            "content": "",
            "images": None,
        },
        "done": True,
        "done_reason": "stop",
    }
    if DEBUG:
        print(f"{json.dumps(final_chunk)}")
    yield f"{json.dumps(final_chunk)}\n"


@app.post("/api/chat")
def ollam_chat_completions(request: OllamaChatCompletionRequest):
    if DEBUG:
        print(f"REQUEST: {request}")
    reason = "stop"
    try:
        response = quack.chat(request)
    except RuntimeError as e:
        response = str(e)
        reason = "error"
    if not isinstance(response, str):
        return StreamingResponse(
            _wrap_ollama_chat_generator(response, request.model),
            media_type="application/x-ndjson",
            headers={"Transfer-Encoding": "chunked"},
        )
    response = {
        "model": request.model,
        "created_at": str(time()),
        "message": {"role": "assistant", "content": response},
        "done": True,
        "done_reason": reason,
    }
    if DEBUG:
        print(f"RESPONSE: {json.dumps(response)}")
    return response


@app.get("/api/tags")
def models():
    response = {"models": [{"name": model, "details": {}} for model in quack.get_models()]}
    if DEBUG:
        print(f"RESPONSE: {json.dumps(response)}")
    return response
