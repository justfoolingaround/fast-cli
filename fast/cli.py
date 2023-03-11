import asyncio
import sys

import click
from rich.console import Console
from rich.traceback import install

from .speedtest import FastClientSpeedTestRich

install(show_locals=True, word_wrap=True, suppress=[click])


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

    # Please note that the speeds shown by Fast.com may not be indicative of maximum speeds
    # you can achieve with your ISP or a service.

    console = Console(stderr=True)

    fastcom_client = FastClientSpeedTestRich(
        console=console,
        bits=bits,
    )

    data = await fastcom_client.fastcom_client.fetch_urls(url_count=url_count)
    client = data["client"]

    if not private:
        console.print(
            f"Server reported client @ {client['location']['city']}, {client['location']['country']} [{client['ip']}]."
        )

    targets = data["targets"]

    await (
        fastcom_client.run(
            targets=targets,
            connections=connections,
            download_time_limit=time_limit,
            upload_time_limit=time_limit,
        )
    )


if __name__ == "__main__":
    __fastcom_speedtesting__(standalone_mode=False)
