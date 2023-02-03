import asyncio
import sys

import click
import humanize
from rich.console import Console
from rich.live import Live
from rich.traceback import install

install(show_locals=True, word_wrap=True, suppress=[click])

from .speedtest import CurrentSpeedContext, FastClientSpeedtest


def into_asyncio_run(f):
    def wrapper(*args, **kwargs):
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        return asyncio.run(f(*args, **kwargs))

    return wrapper


@click.command()
@click.option(
    "-l",
    "--limit",
    default=26843545600,
    help="Byte limit for testing.",
    type=click.IntRange(2093058, 26843545600, clamp=True, max_open=True, min_open=True),
)
@click.option(
    "-uc",
    "--url-count",
    default=5,
    type=click.IntRange(1, 5, clamp=True, max_open=True, min_open=True),
    help="Number of URLs to fetch.",
)
@click.option(
    "-c",
    "--connections",
    default=5,
    help="Number of connections to use. (5 is optimal)",
)
@click.option(
    "-t", "--time-limit", default=10.0, help="Time limit for testing.", type=float
)
@click.option(
    "-8",
    "--bits",
    is_flag=True,
    help="Use bits instead of bytes for speed calculations.",
)
@click.option(
    "-p",
    "--private",
    is_flag=True,
    help="Use private mode for testing.",
)
@into_asyncio_run
async def __fastcom_speedtesting__(
    limit: int,
    url_count: int,
    connections: int,
    time_limit: float,
    bits: bool,
    private: bool,
):

    unit = "bits" if bits else "bytes"

    loop = asyncio.get_event_loop()

    sys.stderr = sys.__stderr__

    console = Console(stderr=True)
    console.print(
        "Please note that the speeds shown by Fast.com may not be indicative of maximum speeds "
        "you can achieve with your ISP or a service.",
        style="dim yellow",
    )

    fastcom_client = FastClientSpeedtest()

    data = await fastcom_client.fastcom_client.fetch_urls(url_count=url_count)
    client = data["client"]

    if not private:
        console.print(
            f"Server reported client @ {client['location']['city']}, {client['location']['country']} [{client['ip']}]."
        )

    targets = data["targets"]

    if not targets:
        console.print(
            "Could not find any nearby targets to test against at this moment. Please try again later.",
            style="bold red",
        )
        exit(0b10)

    target_count = len(targets)

    if not private:
        console.print(
            f"\tServer reported {target_count} testing location{'s' if target_count >1 else ''} nearby:"
        )

        for target in targets:
            console.print(
                f"\t - {target['location']['city'].rstrip(',').title()}, {target['location']['country']}"
            )

    connection_data = dict()

    with Live(
        "Now downloading content",
        console=console,
        auto_refresh=True,
    ) as live:

        @fastcom_client.on_bytes_recv
        async def on_bytes_recv(ctx: CurrentSpeedContext):

            current_time = loop.time()
            time_from_current = current_time - ctx.byte_recv_loop_time

            db_by_dt = ctx.byte_recv_count / time_from_current
            completes_in = time_limit - time_from_current

            if bits:
                db_by_dt *= 8

            if completes_in < 0:
                completes_in += ctx.latency

            live.update(
                f"Measuring download speed @ {humanize.naturalsize(db_by_dt, binary=bits)}/s "
                f"\[connections: {connections}"
                f", completes in {humanize.naturaldelta(completes_in)}"
                f", connection latency: {ctx.latency * 1000:.2f}ms"
                f"]"
            )

            connection_data.update(
                {
                    (*ctx.target["location"].values(),): ctx.latency,
                }
            )

        gather_task = asyncio.gather(
            *(
                fastcom_client.run(
                    targets[((_ % target_count) or 1) - 1],
                    size=limit // connections,
                    time_limit=time_limit,
                )
                for _ in range(connections)
            )
        )
        start_time = loop.time()

        # NOTE: The bottom value is the most precise and accurate value
        # ...   for the download speed.
        # ...   It uses strictly byte receiving rate from the session.
        clean_download_speed = sum(await gather_task)

        if bits:
            clean_download_speed *= 8

        finish_time = loop.time()
        live.update(
            f"Internet download speed: {humanize.naturalsize(clean_download_speed, binary=bits)}/s ({clean_download_speed:.2f} {unit}/s)."
        )

    await fastcom_client.session.close()

    if not private:
        (highest_place, maximum_latency) = max(
            connection_data.items(), key=lambda x: x[1]
        )
        (lowest_place, minimum_latency) = min(
            connection_data.items(), key=lambda x: x[1]
        )

        console.print(
            f"\tLowest latency: \t{minimum_latency * 1000:.2f}ms \t@ {', '.join(lowest_place)}.",
        )

        console.print(
            f"\tHighest latency: \t{maximum_latency * 1000:.2f}ms \t@ {', '.join(highest_place)}.",
        )

    if start_time + time_limit > finish_time:
        console.print(
            f"Test finished {humanize.naturaldelta(finish_time - start_time)} early! Use `-l` to ensure more accurate results.",
        )

    if bits:
        recv = fastcom_client.bytes_recv * 8
    else:
        recv = fastcom_client.bytes_recv

    clean_download_time = recv / clean_download_speed

    console.print(
        f"Client downloaded {humanize.naturalsize(recv, binary=bits)} ({recv} {unit}) in {humanize.naturaldelta(clean_download_time)} ({clean_download_time:.2f} seconds).",
    )
