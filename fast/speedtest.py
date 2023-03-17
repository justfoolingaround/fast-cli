import asyncio
from hashlib import md5
from itertools import cycle

import aiohttp
import humanize
import yarl
from rich.live import Live
from rich.text import Text

from .api import NFFastClient
from .async_buffer import buffered_reader
from .utils import ServerwiseContext, fetch_formatted_data, share


class FastClientSpeedtest:
    def __init__(self, loop=None, session: "aiohttp.ClientSession" = None):

        self.loop = loop or asyncio.get_event_loop()
        self.session = session or aiohttp.ClientSession(loop=self.loop)

        self.fastcom_client = NFFastClient(self.session)
        self.ctxs: "list[ServerwiseContext]" = []

    async def poll_metrics(self, ctx: ServerwiseContext, sent: bool = False):
        raise NotImplementedError()

    async def reset_metrics(self):
        raise NotImplementedError()

    async def finalise_metrics(self):
        raise NotImplementedError()

    @property
    def download_speed(self):
        return sum(
            (ctx.bytes_recv / (ctx.last_bytes_recv_poll - ctx.bytes_recv_start))
            if ctx.bytes_recv_start
            and (ctx.last_bytes_recv_poll - ctx.bytes_recv_start)
            else 0
            for ctx in self.ctxs
        )

    @property
    def upload_speed(self):
        return sum(
            (ctx.bytes_sent / (ctx.last_bytes_sent_poll - ctx.bytes_sent_start))
            if ctx.bytes_sent_start
            and (ctx.last_bytes_sent_poll - ctx.bytes_sent_start)
            else 0
            for ctx in self.ctxs
        )

    @property
    def lowest_latency(self):
        return (
            (
                min(ctx.download_latency for ctx in self.ctxs)
                if self.download_speed
                else min(ctx.upload_latency for ctx in self.ctxs)
            )
            if self.ctxs
            else 0
        )

    async def download_into_ctx(
        self, ctx: ServerwiseContext, size: int = 26214400, time_limit: float = 10.0
    ):
        ctx.bytes_recv_start = self.loop.time()
        upto = ctx.bytes_recv_start + time_limit

        for _ in range((size // 26214400) + 1):
            byte_recv_loop_time = self.loop.time()
            byte_recv_local = 0

            async with self.session.get(ctx.url) as response:

                ctx.download_latency = self.loop.time() - byte_recv_loop_time

                async for data in response.content.iter_chunked(1024):

                    recv_length = len(data)

                    ctx.bytes_recv += recv_length
                    byte_recv_local += recv_length

                    self.loop.create_task(self.poll_metrics(ctx))

                    if self.loop.time() > upto or byte_recv_local >= size:
                        return

    async def upload_into_ctx(
        self, ctx: ServerwiseContext, size: int = 26214400, time_limit: float = 10.0
    ):

        ctx.bytes_sent_span = time_limit

        future = asyncio.Future()

        task = self.loop.create_task(
            self.session.post(
                ctx.url,
                data=buffered_reader(
                    ctx,
                    size,
                    self.loop.time(),
                    self.loop,
                    future,
                    poll=self.poll_metrics,
                ),
                headers={
                    "Content-Length": str(size),
                },
            ).__aenter__()
        )

        future.add_done_callback(task.cancel)
        await future

    async def run(
        self,
        targets: list,
        do_download: bool = True,
        do_upload: bool = True,
        connections: int = 1,
        *,
        download_size: int = 26214400,
        download_time_limit: float = 10.0,
        upload_size: int = 26214400,
        upload_time_limit: float = 10.0,
    ):

        if not do_download and not do_upload:
            raise ValueError(
                "You need to specify at least one of do_download and do_upload."
            )

        assigned = 0
        target_cycle = cycle(targets)

        while assigned < connections:
            target = next(target_cycle)

            parsed_url = yarl.URL(target["url"])

            parsed_url = parsed_url.with_path(
                parsed_url.path + f"/range/0-26214400"
            ).with_query(parsed_url.query)

            ctx = ServerwiseContext(
                name=", ".join(target["location"].values()),
                url=parsed_url,
                bytes_recv_span=download_time_limit,
                bytes_sent_span=upload_time_limit,
            )

            self.ctxs.append(ctx)
            assigned += 1

        if do_download:
            await asyncio.gather(
                *(
                    self.download_into_ctx(ctx, download_size, download_time_limit)
                    for ctx in self.ctxs
                )
            )

        if do_upload:
            await asyncio.gather(
                *(
                    self.upload_into_ctx(ctx, upload_size, upload_time_limit)
                    for ctx in self.ctxs
                )
            )

        await self.session.close()
        await self.finalise_metrics()


class FastClientSpeedTestRich(FastClientSpeedtest):

    signs = {"upload": "↑", "download": "↓"}

    def __init__(
        self,
        console,
        bits,
        private,
        share,
        less_verbose,
        loop=None,
        session: "aiohttp.ClientSession" = None,
    ):
        self.console = console
        self.active_live = None

        self.bits = bits
        self.private = private

        self.share = share
        self.less_verbose = less_verbose

        super().__init__(loop, session)

    async def poll_metrics(self, ctx: ServerwiseContext, sent: bool = False):

        if sent:
            ctx.last_bytes_sent_poll = self.loop.time()
        else:
            ctx.last_bytes_recv_poll = self.loop.time()

        if self.active_live is None:
            self.active_live = Live(console=self.console, auto_refresh=True).__enter__()

        event = "upload" if sent else "download"
        latency = ctx.upload_latency if sent else ctx.download_latency

        now = self.loop.time()

        if not latency:
            if any(
                ctx.upload_latency if sent else ctx.download_latency
                for ctx in self.ctxs
            ):
                return

            return self.active_live.update(
                f"Waiting for a {event} connection to establish."
            )

        completes_in = (
            (ctx.bytes_sent_span - (now - ctx.bytes_sent_start))
            if sent
            else (ctx.bytes_recv_span - (now - ctx.bytes_recv_start))
        )

        if sent:

            db_by_dt = self.upload_speed

            _, peak_send_rate = ctx.peak_send_rate
            if peak_send_rate < db_by_dt:
                ctx.peak_send_rate = now - ctx.bytes_sent_start, db_by_dt

        else:
            db_by_dt = self.download_speed

            _, peak_recv_rate = ctx.peak_recv_rate
            if peak_recv_rate < db_by_dt:
                ctx.peak_recv_rate = now - ctx.bytes_recv_start, db_by_dt

        if self.bits:
            db_by_dt *= 8

        speed_data = []

        if self.download_speed:
            text = f"{self.signs['download']} {humanize.naturalsize(self.download_speed * (8 if self.bits else 1), binary=self.bits)}/s"
            if not sent:
                text = f"[green]{text}[/]"
            else:
                text = f"[dim]{text}[/]"

            speed_data.append(text)

        if self.upload_speed:
            text = f"{self.signs['upload']} {humanize.naturalsize(self.upload_speed  * (8 if self.bits else 1), binary=self.bits)}/s"

            if sent:
                text = f"[green]{text}[/]"
            else:
                text = f"[dim]{text}[/]"

            speed_data.append(text)

        suffix = ""

        if not self.less_verbose:
            suffix = (
                f" \[connections: {len(self.ctxs)}"
                f", completes in {humanize.naturaldelta(completes_in)}"
                f", connection latency: {latency * 1000:.2f}ms"
                f"]"
            )

        self.active_live.update(" ".join(speed_data) + suffix)

    async def reset_metrics(self, update_with="\r"):
        if self.active_live is not None:
            self.active_live.update(update_with)
            self.active_live.__exit__(None, None, None)
            self.active_live = None

    async def finalise_metrics(self):
        if not (self.download_speed or self.upload_speed):
            return await self.reset_metrics("Nothing to report.")

        speed_data = []
        traffic_data = []

        latency_data = []
        lowest_latency = 0

        if self.download_speed:

            lowest_latency = min(self.ctxs, key=lambda ctx: ctx.download_latency)
            highest_latency = max(self.ctxs, key=lambda ctx: ctx.download_latency)
            average_latency = sum(ctx.download_latency for ctx in self.ctxs) / len(
                self.ctxs
            )
            peak_at, peak = max(
                (ctx.peak_recv_rate for ctx in self.ctxs), key=lambda x: x[1]
            )
            total = sum(ctx.bytes_recv for ctx in self.ctxs)

            data = fetch_formatted_data(
                self.signs["download"],
                lowest_latency.download_latency,
                highest_latency.download_latency,
                lowest_latency.name,
                highest_latency.name,
                average_latency,
                total,
                peak,
                peak_at,
                self.download_speed,
                self.bits,
                self.private,
                self.less_verbose,
            )

            latency_data.append(data.latency)
            speed_data.append(data.speed)
            traffic_data.append(data.traffic)

        if self.upload_speed:

            lowest_latency = min(self.ctxs, key=lambda ctx: ctx.upload_latency)
            highest_latency = max(self.ctxs, key=lambda ctx: ctx.upload_latency)
            average_latency = sum(ctx.upload_latency for ctx in self.ctxs) / len(
                self.ctxs
            )
            peak_at, peak = max(
                (ctx.peak_send_rate for ctx in self.ctxs), key=lambda x: x[1]
            )
            total = sum(ctx.bytes_sent for ctx in self.ctxs)

            data = fetch_formatted_data(
                self.signs["upload"],
                lowest_latency.upload_latency,
                highest_latency.upload_latency,
                lowest_latency.name,
                highest_latency.name,
                average_latency,
                total,
                peak,
                peak_at,
                self.upload_speed,
                self.bits,
                self.private,
                self.less_verbose,
            )

            latency_data.append(data.latency)
            speed_data.append(data.speed)
            traffic_data.append(data.traffic)

        await self.reset_metrics(Text(" ".join(speed_data)))

        if not self.less_verbose:

            self.console.print("Latency (server response time):")

            for line in latency_data:
                self.console.print("\t" + line)

            self.console.print("Traffic:")

            for line in traffic_data:
                self.console.print("\t" + line)

        if self.share:
            self.console.print(
                f"Shareable url: {await share(self.download_speed, self.upload_speed, self.lowest_latency, private_mode=self.private)}"
            )
