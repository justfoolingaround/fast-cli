import asyncio
from hashlib import md5
from itertools import cycle

import aiohttp
import humanize
import yarl
from rich.live import Live

from .api import NFFastClient
from .async_buffer import buffered_reader
from .utils import ServerwiseContext

SPEEDTEST_NET_BASE = "https://www.speedtest.net/"
SPEEDTEST_NY_SERVER_ID = 10562


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

                    ctx.last_bytes_recv_poll = self.loop.time()
                    self.loop.create_task(self.poll_metrics(ctx))

                    if self.loop.time() > upto or byte_recv_local >= size:
                        return

    async def upload_into_ctx(
        self, ctx: ServerwiseContext, size: int = 26214400, time_limit: float = 10.0
    ):

        ctx.bytes_sent_start = self.loop.time()
        upto = ctx.bytes_sent_start + time_limit

        task = self.loop.create_task(
            self.session.post(
                ctx.url,
                data=buffered_reader(
                    ctx,
                    size,
                    upto,
                    ctx.bytes_sent_start,
                    self.loop,
                    poll=self.poll_metrics,
                ),
                headers={
                    "Content-Length": str(size),
                },
            ).__aenter__()
        )

        await asyncio.sleep(upto - self.loop.time())

        task.cancel()

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
        loop=None,
        session: "aiohttp.ClientSession" = None,
    ):
        self.console = console
        self.active_live = None

        self.bits = bits
        self.private = private

        self.share = share

        super().__init__(loop, session)

    async def poll_metrics(self, ctx: ServerwiseContext, sent: bool = False):

        if self.active_live is None:
            self.active_live = Live(console=self.console, auto_refresh=True).__enter__()

        event = "upload" if sent else "download"
        latency = ctx.upload_latency if sent else ctx.download_latency

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
            (ctx.bytes_sent_span - (self.loop.time() - ctx.bytes_sent_start))
            if sent
            else (ctx.bytes_recv_span - (self.loop.time() - ctx.bytes_recv_start))
        )

        if sent:
            db_by_dt = self.upload_speed
        else:
            db_by_dt = self.download_speed

        if self.bits:
            db_by_dt *= 8

        self.active_live.update(
            f"{self.signs[event]} {humanize.naturalsize(db_by_dt, binary=self.bits)}/s "
            f"\[connections: {len(self.ctxs)}"
            f", completes in {humanize.naturaldelta(completes_in)}"
            f", connection latency: {latency * 1000:.2f}ms"
            f"]"
        )

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

        if self.bits:
            db_by_dt = self.download_speed * 8
        else:
            db_by_dt = self.download_speed

        if self.download_speed:

            lowest_latency = min(self.ctxs, key=lambda ctx: ctx.download_latency)
            highest_latency = max(self.ctxs, key=lambda ctx: ctx.download_latency)
            average_latency = sum(ctx.download_latency for ctx in self.ctxs) / len(
                self.ctxs
            )

            latency_delta_string = (
                f", farthest: {highest_latency.name}, nearest: {lowest_latency.name}"
                if not self.private
                else ""
            )

            latency_data.append(
                f"{self.signs['download']} {lowest_latency.download_latency * 1000:.2f}-{highest_latency.download_latency * 1000:.2f}ms (Average: {average_latency * 1000:.2f}ms{latency_delta_string})"
            )

            speed_data.append(
                f"{self.signs['download']} {humanize.naturalsize(db_by_dt, binary=self.bits)}/s"
            )

            total = sum(ctx.bytes_recv for ctx in self.ctxs)

            traffic_data.append(
                f"{self.signs['download']} {humanize.naturalsize(total, binary=self.bits)} ({total * (1 if not self.bits else 8)} {'bits' if self.bits else 'bytes'})"
            )

        if self.bits:
            upload_db_by_dt = self.upload_speed * 8
        else:
            upload_db_by_dt = self.upload_speed

        if self.upload_speed:

            lowest_upload_latency = min(self.ctxs, key=lambda ctx: ctx.upload_latency)
            highest_upload_latency = max(self.ctxs, key=lambda ctx: ctx.upload_latency)
            average_upload_latency = sum(ctx.upload_latency for ctx in self.ctxs) / len(
                self.ctxs
            )

            latency_delta_string = (
                f", farthest: {highest_upload_latency.name}, nearest: {lowest_upload_latency.name}"
                if not self.private
                else ""
            )

            latency_data.append(
                f"{self.signs['upload']} {lowest_upload_latency.upload_latency * 1000:.2f}-{highest_upload_latency.upload_latency * 1000:.2f}ms (Average: {average_upload_latency * 1000:.2f}ms{latency_delta_string})"
            )

            speed_data.append(
                f"{self.signs['upload']} {humanize.naturalsize(upload_db_by_dt, binary=self.bits)}/s"
            )

            total = sum(ctx.bytes_sent for ctx in self.ctxs)

            traffic_data.append(
                f"{self.signs['upload']} {humanize.naturalsize(total, binary=self.bits)} ({total * (1 if not self.bits else 8)} {'bits' if self.bits else 'bytes'})"
            )

        await self.reset_metrics(" ".join(speed_data))

        self.console.print("Latency (server response time):")

        for line in latency_data:
            self.console.print("\t" + line)

        self.console.print("Traffic:")

        for line in traffic_data:
            self.console.print("\t" + line)

        if self.share:
            speedtest_session = aiohttp.ClientSession()

            if self.private:
                server_id = SPEEDTEST_NY_SERVER_ID
            else:
                async with speedtest_session.get(
                    SPEEDTEST_NET_BASE + "api/js/servers"
                ) as response:
                    server_id = (await response.json() or [{}])[0].get(
                        "id", SPEEDTEST_NY_SERVER_ID
                    )

            download_in_kilos = int(db_by_dt * 8 // 1000)
            upload_in_kilos = int(upload_db_by_dt * 8 // 1000) or 1
            ping = int(lowest_latency.download_latency * 1000)

            data = {
                "serverid": server_id,
                "ping": ping,
                "download": download_in_kilos,
                "upload": upload_in_kilos,
                "hash": md5(
                    f"{ping}-{upload_in_kilos}-{download_in_kilos}-817d699764d33f89c".encode()
                ).hexdigest(),
            }

            headers = {
                "referer": SPEEDTEST_NET_BASE,
                "accept": "application/json",
            }

            if self.private:
                headers["CLIENT-IP"] = "1.1.1.1"

            async with speedtest_session.post(
                SPEEDTEST_NET_BASE + "api/results.php", json=data, headers=headers
            ) as response:
                self.console.print(
                    f"Shareable url: {SPEEDTEST_NET_BASE}result/{(await response.json(content_type=None))['resultid']}"
                )

            await speedtest_session.close()
