import dataclasses
from collections import namedtuple
from hashlib import md5

import aiohttp
import humanize
import yarl

SPEEDTEST_NET_BASE = "https://www.speedtest.net/"
SPEEDTEST_NY_SERVER_ID = 10562


formatted_speedtest_data = namedtuple(
    "formatted_speedtest_data", ("latency", "speed", "traffic")
)


@dataclasses.dataclass
class ServerwiseContext:

    name: str
    url: yarl.URL

    download_latency: float = 0.0
    upload_latency: float = 0.0

    bytes_recv: int = 0
    bytes_sent: int = 0

    last_bytes_recv_poll: float = 0.0
    last_bytes_sent_poll: float = 0.0

    bytes_recv_start: float = 0.0
    bytes_sent_start: float = 0.0

    bytes_recv_span: float = 0.0
    bytes_sent_span: float = 0.0

    peak_recv_rate: tuple[float, float] = 0.0, 0.0
    peak_send_rate: tuple[float, float] = 0.0, 0.0


async def share(download_rate, upload_rate, ping, private_mode=False) -> None:
    """Share the results of a speedtest."""
    speedtest_session = aiohttp.ClientSession()

    if private_mode:
        server_id = SPEEDTEST_NY_SERVER_ID
    else:
        async with speedtest_session.get(
            SPEEDTEST_NET_BASE + "api/js/servers"
        ) as response:
            server_id = (await response.json() or [{}])[0].get(
                "id", SPEEDTEST_NY_SERVER_ID
            )

    download_in_kilos = int(download_rate * 8 // 1000)
    upload_in_kilos = int(upload_rate * 8 // 1000) or 1
    ping = int(ping * 1000)

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

    if private_mode:
        headers["CLIENT-IP"] = "1.1.1.1"

    async with speedtest_session.post(
        SPEEDTEST_NET_BASE + "api/results.php", json=data, headers=headers
    ) as response:
        url = f"{SPEEDTEST_NET_BASE}result/{(await response.json(content_type=None))['resultid']}"

    await speedtest_session.close()

    return url


def fetch_formatted_data(
    icon,
    lowest_latency,
    highest_latency,
    lowest_latency_name,
    highest_latency_name,
    average_latency,
    total_data_metric,
    peak_speed,
    peak_speed_at,
    speed,
    use_bits,
    is_private,
    less_verbose,
):

    if use_bits:
        speed *= 8
        peak_speed *= 8

    latency_delta_string = ""

    if not less_verbose and not is_private:
        latency_delta_string = (
            f", farthest: {highest_latency_name}, nearest: {lowest_latency_name}"
        )

    return formatted_speedtest_data(
        f"{icon} {lowest_latency * 1000:.2f} - {highest_latency * 1000:.2f} ms "
        f"(average: {average_latency * 1000:.2f} ms{latency_delta_string})",
        f"{icon} {humanize.naturalsize(speed, binary=use_bits)}/s"
        + (
            f" (peak: {humanize.naturalsize(peak_speed, binary=use_bits)}/s at {peak_speed_at:.1f} s from start)"
            if not less_verbose
            else ""
        ),
        f"{icon} {humanize.naturalsize(total_data_metric, binary=use_bits)} ({total_data_metric * (1 if not use_bits else 8)} {'bits' if use_bits else 'bytes'})",
    )
