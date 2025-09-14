from typing import Any, Callable, Coroutine
from collections import defaultdict

GraphResult = dict[str, Any] | None
NodeResult = GraphResult | tuple[str, GraphResult] | str
RunFunction = Callable[[dict], Coroutine[Any, Any, NodeResult]]

DEBUG = False


async def _run_with_retries(function, max_retries, **kwargs):
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    e = RuntimeError(f"Execution failed after {max_retries} retries.")
    for _ in range(max_retries + 1):
        try:
            return await function(**kwargs)
        except Exception as exc:
            e = exc
    raise e


def template_formatting(template: str, shared: dict, **kwargs) -> str:
    """
    Fill a template string using keys from shared and kwargs.

    A template string looks like this "Hello {user}!".
    Where `user` can be either provided in shared or kwargs.
    """
    context = {**shared, **kwargs}
    try:
        return template.format(**context)
    except KeyError as e:
        missing = e.args[0]
        raise KeyError(f"Missing key '{missing}' for template formatting.") from e


class Node:
    """
    A nodes in a micro-graph allows connection to other nodes by using `then`
    and the `run` defines what happens when a node is executed.
    """

    def __init__(self, run: RunFunction | None = None, max_retries: int = 0, max_visits=-1):
        self._next_nodes: dict[str, Node] = {}
        self._max_retries = max_retries
        self._max_visits = max_visits
        self._visits = 0
        if run is not None:
            self.run = run  # type: ignore

    def then(self, default: "Node", **kwargs) -> "Node":
        self._next_nodes["default"] = default
        self._next_nodes.update(kwargs)
        return default

    async def run(self, shared: dict, **kwargs) -> NodeResult:
        return None

    async def start(self, shared: dict, **kwargs) -> GraphResult:
        visits: dict[Node, int] = defaultdict(int)
        node = self
        while node is not None:
            # Run node with guard against too many visits / loops
            if node._max_visits > 0 and visits[node] >= node._max_visits:
                raise RuntimeError(f"Exceeding max_visits for node: {node}")
            node._visits = visits[node]  # Allow nodes to avoid reaching max_visits via behaviour
            action, result = self._normalize_result(
                await _run_with_retries(node.run, node._max_retries, shared=shared, **kwargs)
            )
            visits[node] += 1
            if DEBUG:
                print(f"DEBUG: Next Action: `{action}`; Result: {result}")
            # Prepare next node execution
            kwargs = result or {}
            if action in node._next_nodes:
                node = node._next_nodes[action]
            elif action == "default":
                return result
            else:
                raise KeyError(
                    f"Action '{action}' not found in next nodes: {list(node._next_nodes.keys())}"
                )
        raise RuntimeError("This should never be reached!")

    def _normalize_result(self, result):
        if isinstance(result, tuple):
            action, result = result
        elif isinstance(result, str):
            action, result = result, {}
        else:
            action, result = "default", result
        return action.lower(), result


def node(max_retries=0, max_visits=-1):
    def wrapper(fun: RunFunction) -> Node:
        node = Node(run=fun, max_retries=max_retries, max_visits=max_visits)
        node.__doc__ = fun.__doc__
        return node

    return wrapper
