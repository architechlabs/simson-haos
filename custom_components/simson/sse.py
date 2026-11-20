"""Read a Server-Sent Events stream. Pure Python, no Home Assistant needed."""

from __future__ import annotations

import random
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass

MAX_DATA_BYTES = 64 * 1024
MAX_LINE_BYTES = 70 * 1024


class SseError(ValueError):
    """The stream sent something larger or stranger than the protocol allows."""


@dataclass(frozen=True)
class SseMessage:
    event: str
    id: str | None
    data: str
    retry: int | None = None


async def parse_sse(chunks: AsyncIterable[bytes]) -> AsyncIterator[SseMessage]:
    """Yield one message per blank-line-terminated block.

    Comments (lines starting with ":") are keep-alives and are skipped. A block
    without data is not a message, except that its id is still remembered by
    the caller through the next message.
    """
    buffer = b""
    event, ident, data, retry = "message", None, [], None
    size = 0

    async for chunk in chunks:
        buffer += chunk
        if len(buffer) > MAX_LINE_BYTES and b"\n" not in buffer:
            raise SseError("line too long")
        while True:
            cut = buffer.find(b"\n")
            if cut < 0:
                break
            raw, buffer = buffer[:cut], buffer[cut + 1 :]
            line = raw.rstrip(b"\r").decode("utf-8", errors="replace")
            if line == "":
                if data:
                    yield SseMessage(event, ident, "\n".join(data), retry)
                event, ident, data, retry, size = "message", ident, [], None, 0
                continue
            if line.startswith(":"):
                continue
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "event":
                event = value or "message"
            elif name == "data":
                size += len(value) + 1
                if size > MAX_DATA_BYTES:
                    raise SseError("message too large")
                data.append(value)
            elif name == "id":
                if "\x00" not in value:
                    ident = value
            elif name == "retry" and value.isdigit():
                retry = int(value)


def backoff_seconds(attempt: int, *, jitter: float | None = None) -> float:
    """Seconds to wait before reconnecting: 1, 2, 4 ... capped at 60, plus up to 25% jitter."""
    base = min(60.0, float(2 ** max(0, min(attempt, 6))))
    spread = random.random() if jitter is None else jitter
    return base * (1 + 0.25 * spread)
