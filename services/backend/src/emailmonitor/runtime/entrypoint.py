"""Installed service worker/publisher entrypoints for preprovisioned test systems.

No login, schema, grants, credentials or source approvals are created here. The
configuration file is operator-supplied, bounded, and never printed. Production
configuration remains refused until its separate identity/deployment gates pass.
"""

import argparse
import sys
from pathlib import Path

from emailmonitor.runtime.service_publisher import publish_service_once
from emailmonitor.runtime.worker import ServiceRuntimeConfig, ServiceWorker


def load_config(path: Path) -> ServiceRuntimeConfig:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_384:
        raise ValueError("Bounded explicit service configuration required")
    with path.open("rb") as source:
        body = source.read(16_385)
    if len(body) > 16_384:
        raise ValueError("Bounded explicit service configuration required")
    return ServiceRuntimeConfig.model_validate_json(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="EmailMonitor bounded service runtime")
    parser.add_argument(
        "command", choices=("api", "worker", "publish-once", "reconcile-once", "check")
    )
    parser.add_argument("--config", type=Path, required=True)
    options = parser.parse_args()
    worker = controller = None
    status = 0
    try:
        if options.command == "api":
            from emailmonitor.runtime.api_entrypoint import ReferenceAPI, run_api

            path = options.config
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
                raise ValueError("Bounded API configuration required")
            with path.open("rb") as source:
                body = source.read(65_537)
            if len(body) > 65_536:
                raise ValueError("Bounded API configuration required")
            run_api(ReferenceAPI.model_validate_json(body))
        else:
            config = load_config(options.config)
            if options.command == "publish-once":
                count = publish_service_once(config)
                print(f"published={count}")
            elif options.command == "check":
                from emailmonitor.runtime.database import ServiceDatabase

                database = ServiceDatabase(config.database_url, config.process)
                try:
                    if database.organization != config.organization:
                        raise ValueError("Service tenant mismatch")
                finally:
                    database.engine.dispose()
                print("service_identity_ready")
            else:
                worker = ServiceWorker(config)
                if options.command == "reconcile-once":
                    print(f"reconciled={worker.reconcile()}")
                else:
                    # Closed options: no prefork sockets, remote control, embedded
                    # beat, arbitrary queues, plugins or caller-selected task module.
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
                        raise RuntimeError("Worker stopped unsuccessfully")
                    # Celery bootstep teardown logs and swallows exceptions.
                    # A wake ownership/cleanup failure must still fail the CLI.
                    worker.signal_wake.require_clean()
    except Exception:
        print("service_runtime_failed", file=sys.stderr)
        status = 1
    finally:
        cleanup_failed = False
        if controller is not None:
            try:
                controller.stop()
            except Exception:
                cleanup_failed = True
        if worker is not None:
            try:
                worker.close()
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            print("service_runtime_cleanup_failed", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
