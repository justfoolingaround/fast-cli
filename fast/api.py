import base64
import typing as t

import aiohttp

if t.TYPE_CHECKING:
    ...

MAGIC_DIGITS = (
    base64.b64encode(b"asdfasdlfnsdafhasdfhkalf").rstrip(b"=").decode("utf-8")
)


class NFFastClient:

    API_ENDPOINT = "https://api.fast.com/"
    SPEEDTEST_ENDPOINT = API_ENDPOINT + "netflix/speedtest/v2"

    def __init__(self, session: "aiohttp.ClientSession" = None):
        self.session = session or aiohttp.ClientSession()

    async def fetch_urls(self, https="true", url_count=5):

        async with self.session.get(
            self.SPEEDTEST_ENDPOINT,
            params={
                "https": https,
                "urlCount": url_count,
                "token": MAGIC_DIGITS,
            },
        ) as response:
            return await response.json()
