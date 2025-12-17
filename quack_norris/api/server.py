from time import time
from typing import Any, List, Optional
from uuid import uuid4
import asyncio
import json
import logging

from pydantic import BaseModel
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
import uvicorn

from quack_norris.api.chat_handler import ChatHandlerRegistry
from quack_norris.core.llm.types import ChatMessage
from quack_norris.core.output_writer import OutputWriter
from quack_norris.logging import logger
from quack_norris.config import Config


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    max_tokens: Optional[int] = -1
    stream: Optional[bool] = False
    workspace: Optional[str] = ""


def create_openai_api(config: Config, debug=False) -> FastAPI:
    app = FastAPI(title="OpenAI Server")

    # Set up logging
    logger = logging.getLogger("openai_server")
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Add CORS middleware
    origins = [
        "http://localhost:5173",  # Your frontend's origin
        "http://localhost",  # Allow from localhost (useful for development)
        "*",  # (Use with caution - see notes below)
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    async def _wrap_chat_generator(stream, model):
        i = 0
        async for token in stream:
            chunk = {
                "id": i,
                "object": "chat.completion.chunk",
                "created": int(time()),
                "model": model,
                "choices": [{"delta": {"content": token, "role": "assistant"}}],
            }
            i += 1
            if debug:
                logger.debug(f"CHUNK: {json.dumps(chunk)}")
            yield f"data: {json.dumps(chunk)}\n\n"
        if debug:
            logger.debug("CHUNK: [DONE]")
        yield "data: [DONE]\n\n"

    @app.post("/chat/completions")
    async def chat_completions(request: ChatCompletionRequest):
        if debug:
            logger.debug(f"REQUEST: {request}")
        reason = "stop"
        workspace = request.workspace
        if workspace is None:  # Use default workspace if none provided
            workspace = list(config.get("workspaces", {}).keys())[0]
        if workspace not in config.get("workspaces", {}):  # Use no workspace if invalid provided
            workspace = ""
        try:
            async def generator():
                queue = asyncio.Queue(maxsize=1)

                # Run the graph in a background task
                async def run_graph():
                    output = OutputWriter(queue=queue)
                    try:
                        await ChatHandlerRegistry.get_handler(request.model)(
                            history=request.messages, workspace=workspace, output=output
                        )
                    except Exception as e:
                        await output.default(f"Unexpected error occured:\n\n```\n{e}\n```\n")
                    await output.clear()
                    await queue.put(None)  # Sentinel to signal completion

                asyncio.create_task(run_graph())

                while True:
                    chunk: str | None = await queue.get()
                    if chunk == "":
                        continue
                    if chunk is None:
                        break
                    yield chunk

            response = generator()
        except RuntimeError as e:
            response = str(e)
            reason = "error"
        if request.stream:
            if isinstance(response, str):
                response = [response]
            return StreamingResponse(
                _wrap_chat_generator(response, request.model),
                media_type="text/event-stream",
            )
        if not isinstance(response, str):
            response_str: str = ""
            async for chunk in response:
                response_str += chunk
        else:
            response_str = response
        response_obj = {
            "id": str(uuid4()),
            "object": "chat.completion",
            "model": request.model,
            "created": int(time()),
            "choices": [
                {
                    "finish_reason": reason,
                    "message": ChatMessage(role="assistant", content=response_str),
                }
            ],
        }
        if debug:
            logger.debug(f"RESPONSE: {response_obj}")
        return response_obj

    @app.get("/models")
    def openai_models():
        response = {
            "object": "list",
            "data": [
                {
                    "id": model,
                    "object": "model",
                    "created": time(),
                    "owned_by": "micro-graph",
                }
                for model in ChatHandlerRegistry.list_handlers()
            ],
        }
        if debug:
            logger.debug(f"RESPONSE: {response}")
        return response

    @app.get("/workspaces")
    def openai_workspaces():
        response = list(config.get("workspaces", {}).keys())
        if debug:
            logger.debug(f"RESPONSE: {response}")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        exc_str = f"{exc}".replace("\n", " ").replace("   ", " ")
        logger.error(await request.json())
        logger.error(exc_str)
        content = {"status_code": 10422, "message": exc_str, "data": None}
        return JSONResponse(content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    return app


def serve_openai_api(
    config: Config,
    host: str = "localhost",
    port: int = 8000,
    debug=False,
):
    logger.info("Starting server")
    app = create_openai_api(config=config, debug=debug)
    uvicorn.run(app, host=host, port=port)
