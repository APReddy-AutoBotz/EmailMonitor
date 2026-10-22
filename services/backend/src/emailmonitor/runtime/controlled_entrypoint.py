"""Fixed installed container entrypoint. Bootstrap bytes are never worker logs."""

import os
import sys
import time
from pathlib import Path


def require_confinement() -> None:
    fields = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if (
        os.geteuid() != 65532
        or int(fields["CapEff"].strip(), 16) != 0
        or fields["NoNewPrivs"].strip() != "1"
        or fields["Seccomp"].strip() != "2"
        or Path("/var/run/docker.sock").exists()
        or Path("/run/docker.sock").exists()
        or Path("/run/podman/podman.sock").exists()
    ):
        raise ValueError("Controlled worker confinement required")


def main() -> int:
    worker = controller = channel = None
    status = 1
    incoming = outgoing = None
    try:
        if sys.argv[1:]:
            raise ValueError("Fixed controlled worker command required")
        require_confinement()
        incoming = os.dup(0)
        outgoing = os.dup(1)
        # No application import or logging can write into the capability after this.
        with open(os.devnull, "r+b", buffering=0) as null:
            for fd in (0, 1, 2):
                os.dup2(null.fileno(), fd)
        from emailmonitor.runtime.controlled_channel import ControlledChannel
        from emailmonitor.runtime.worker import ServiceRuntimeConfig, ServiceWorker

        channel = ControlledChannel.from_pipes(incoming, outgoing)
        incoming = outgoing = None  # Channel now owns both duplicates.
        frame = channel.pipe.receive(time.monotonic() + 20)
        if (
            set(frame) != {"kind", "config"}
            or frame["kind"] != "bootstrap"
            or type(frame["config"]) is not str
            or len(frame["config"].encode()) > 16384
        ):
            raise ValueError("Bounded controlled bootstrap required")
        config = ServiceRuntimeConfig.model_validate_json(frame["config"])
        if (
            config.model_dump_json() != frame["config"]
            or config.profile != "controlled-xml-service-reference"
        ):
            raise ValueError("Controlled profile required")
        worker = ServiceWorker(config, controlled_channel=channel)
        controller = worker.application.Worker(
            pool="solo",
            concurrency=1,
            loglevel="CRITICAL",
            without_gossip=True,
            without_mingle=True,
            without_heartbeat=True,
            redirect_stdouts=False,
            quiet=True,
        )
        controller.start()
        if controller.exitcode not in (None, 0):
            raise RuntimeError("Controlled worker failed")
        worker.signal_wake.require_clean()
        status = 0
    except Exception:
        status = 1
    finally:
        for descriptor in (incoming, outgoing):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    status = 1
        for owned, method in ((controller, "stop"), (worker, "close"), (channel, "close")):
            if owned is not None:
                try:
                    getattr(owned, method)()
                except Exception:
                    status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
