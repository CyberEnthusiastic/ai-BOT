"""Retry decorator with exponential back-off and graceful degradation.

Usage
-----
    from nova.utils.retry import retry, with_fallbacks

    @retry(max_attempts=3, base_delay=1.0)
    async def call_api():
        ...

    # Fallback chain: try each provider in order
    result = await with_fallbacks(
        [elevenlabs_speak, openai_tts_speak, sapi_speak],
        text="Hello",
    )
"""

from __future__ import annotations

import asyncio
import functools
import random
from typing import Any, Callable, Coroutine, Sequence, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    jitter: bool = True,
) -> Callable[[F], F]:
    """Decorator: retry an async function with exponential back-off + jitter.

    Parameters
    ----------
    max_attempts:
        Total number of attempts (including the first).
    base_delay:
        Initial delay in seconds before the first retry.
    max_delay:
        Cap for the computed delay.
    exceptions:
        Only retry on these exception types.
    jitter:
        Add ±25 % random jitter to avoid thundering-herd.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    if jitter:
                        delay *= 1.0 + random.uniform(-0.25, 0.25)
                    print(
                        f"[Retry] {fn.__name__} attempt {attempt}/{max_attempts} "
                        f"failed: {exc}. Retrying in {delay:.1f}s…"
                    )
                    await asyncio.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


async def with_fallbacks(
    providers: Sequence[Callable[..., Coroutine[Any, Any, Any]]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Try each callable in *providers* in order; return the first success.

    Raises the last exception if all providers fail.

    Example
    -------
        result = await with_fallbacks(
            [elevenlabs, openai_tts, sapi],
            text="Hello",
        )
    """
    last_exc: Exception | None = None
    for provider in providers:
        try:
            return await provider(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            print(f"[Fallback] {getattr(provider, '__name__', provider)} failed: {exc}")

    if last_exc:
        raise last_exc
    raise RuntimeError("No providers supplied to with_fallbacks()")
