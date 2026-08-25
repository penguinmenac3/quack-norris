"""Normalised errors raised by LLM providers.

Provider backends (``openai``, ``httpx``, ``boto3``) each raise their own
exception hierarchy for things like rate limits, bad routes, or dropped
connections. Providers translate those into :class:`LLMAPIError` so the
agent loop and CLI can show one consistent, actionable message instead of
crashing with a raw traceback.
"""

from __future__ import annotations


class LLMAPIError(Exception):
    """A provider API call failed in a way the user can act on.

    Parameters
    ----------
    message:
        Human-readable description of what went wrong, safe to show as-is.
    status_code:
        HTTP status code, if the failure came from an HTTP response.
    retryable:
        True if the failure looks transient (rate limit, timeout, 5xx) and
        simply retrying — or waiting a moment — might succeed.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
