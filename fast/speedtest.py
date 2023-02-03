import asyncio
import dataclasses
import warnings

import aiohttp
import yarl

from .api import NFFastClient


@dataclasses.dataclass
class CurrentSpeedContext:

    target: dict
    latency: float

    byte_recv_loop_time: float
    byte_recv_count: int


class FastClientSpeedtest:
    def __init__(self, loop=None, session: "aiohttp.ClientSession" = None):

        self.loop = loop or asyncio.get_event_loop()
        self.session = session or aiohttp.ClientSession(loop=self.loop)

        self.fastcom_client = NFFastClient(self.session)

        self.bytes_recv_callbacks = []
        self.bytes_sent_callbacks = []

        self.bytes_recv = 0

    def add_mutable_callback(self, callback, mutable, *, warn_for_non_blocking=True):
        if warn_for_non_blocking and not asyncio.iscoroutinefunction(callback):
            warnings.warn(
                f"{callback!r} is not a coroutine function. "
                "This may cause the event loop to block."
            )

        mutable.append(callback)

    def on_bytes_sent(self, callback):
        self.add_mutable_callback(callback, self.bytes_sent_callbacks)

    def on_bytes_recv(self, callback):
        self.add_mutable_callback(callback, self.bytes_recv_callbacks)

    async def run(self, target, size: int = 26214400, time_limit: float = 10.0):

        url = target["url"]
        parsed_url = yarl.URL(url)

        parsed_url = parsed_url.with_path(
            parsed_url.path + f"/range/0-26214400"
        ).with_query(parsed_url.query)

        byte_recv_local = 0
        db_by_dt_local = float("inf")
        initial_down_stream_time = self.loop.time()

        for _ in range((size // 26214400) + 1):
            byte_recv_loop_time = self.loop.time()

            async with self.session.get(parsed_url) as response:

                latency = self.loop.time() - byte_recv_loop_time

                async for data in response.content.iter_chunked(1024):

                    recv_length = len(data)

                    self.bytes_recv += recv_length
                    byte_recv_local += recv_length

                    current_ctx = CurrentSpeedContext(
                        target=target,
                        latency=latency,
                        byte_recv_loop_time=initial_down_stream_time,
                        byte_recv_count=self.bytes_recv,
                    )

                    for callback in self.bytes_recv_callbacks:
                        self.loop.create_task(callback(current_ctx))

                    pure_time = self.loop.time() - initial_down_stream_time - latency

                    db_by_dt_local = (
                        (byte_recv_local / pure_time) if pure_time else float("inf")
                    )

                    if pure_time > time_limit or byte_recv_local >= size:
                        return db_by_dt_local

        return db_by_dt_local
