import dataclasses

import yarl


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
