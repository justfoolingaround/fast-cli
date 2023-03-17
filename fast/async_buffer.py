import asyncio
import os

from .utils import ServerwiseContext


async def poll_every(
    ctx: ServerwiseContext,
    loop: asyncio.AbstractEventLoop,
    poll,
    while_,
    *,
    interval: float = 0.5,
):
    while while_():
        await asyncio.sleep(interval)
        loop.create_task(poll(ctx, sent=True))


async def buffered_reader(
    ctx: ServerwiseContext,
    size: int,
    start: float,
    loop: asyncio.AbstractEventLoop,
    future: asyncio.Future,
    *,
    chunk_size: int = 1024,
    poll=None,
):

    while_ = lambda: ctx.bytes_sent < size and loop.time() < (
        start + ctx.bytes_sent_span
    )

    if poll is not None:
        loop.create_task(poll_every(ctx, loop, poll, while_))

    while while_():
        pending_bytes = await asyncio.to_thread(
            os.urandom, min(size - ctx.bytes_sent, chunk_size)
        )
        ctx.bytes_sent += len(pending_bytes)
        yield pending_bytes

        if not ctx.bytes_sent_start:
            ctx.bytes_sent_start = loop.time()

        if not ctx.upload_latency:
            ctx.upload_latency = loop.time() - start

    future.set_result(True)
