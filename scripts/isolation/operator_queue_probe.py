"""Host-only passive observation of one exact disposable synthetic broker queue."""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from emailmonitor.jobs.queues import phase_queue
from kombu import Connection
from operator_ui_protocol import completion_queue_counts


def observe(broker_url: str, namespace: str) -> dict[str, int] | None:
    """Whole child-process deadline covers retries, stalled reads and handshake time."""
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--owned-probe"],
            input=json.dumps({"broker_url": broker_url, "namespace": namespace}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=0.5,
            check=False,
        )
        if result.returncode != 0 or len(result.stdout) > 128:
            return None
        value = json.loads(result.stdout)
        if type(value) is not dict or set(value) != {"ready", "consumers"}:
            return None
        return completion_queue_counts(value["ready"], value["consumers"])
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return None


def main() -> None:
    if os.environ.get("EM_REQUIRE_OPERATOR_UI") != "true" or sys.argv[1:] != ["--owned-probe"]:
        raise ValueError("Explicit disposable operator CI required")
    raw = sys.stdin.buffer.read(2049)
    if len(raw) > 2048:
        raise ValueError("Bounded synthetic probe configuration required")
    value = json.loads(raw)
    if type(value) is not dict or set(value) != {"broker_url", "namespace"}:
        raise ValueError("Exact synthetic probe configuration required")
    url, namespace = value["broker_url"], value["namespace"]
    if type(url) is not str or type(namespace) is not str:
        raise ValueError("Synthetic strings required")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "pyamqp"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port not in (None, 5672)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Existing loopback disposable broker only")
    queue_name = phase_queue(namespace, "parse")
    with Connection(
        url,
        connect_timeout=0.1,
        transport_options={"read_timeout": 0.1, "write_timeout": 0.1},
    ) as connection:
        connection.ensure_connection(max_retries=0, timeout=0.2)
        channel = connection.channel()
        try:
            queue = channel.queue_declare(queue=queue_name, passive=True)
            result = completion_queue_counts(queue.message_count, queue.consumer_count)
            sys.stdout.write(json.dumps(result))
        finally:
            channel.close()


if __name__ == "__main__":
    main()
