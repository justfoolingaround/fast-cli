import asyncio
import os

from .utils import ServerwiseContext


async def buffered_reader(
    ctx: ServerwiseContext,
    size: int,
    upto: float,
    start: float,
    loop: asyncio.AbstractEventLoop,
    *,
    chunk_size: int = 1024,
    poll=None
):

    ctx.upload_latency = loop.time() - start
    ctx.bytes_sent_start = loop.time()

    while ctx.bytes_sent < size and loop.time() < upto:
        pending_bytes = os.urandom(min(size - ctx.bytes_sent, chunk_size))
        ctx.bytes_sent += len(pending_bytes)

        if poll is not None:
            ctx.last_bytes_sent_poll = loop.time()
            loop.create_task(poll(ctx, sent=True))

        yield pending_bytes
