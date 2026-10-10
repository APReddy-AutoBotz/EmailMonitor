"""Celery CLI import target; only explicit synthetic loopback configuration is accepted."""

from emailmonitor.jobs.broker import from_environment

app = from_environment()
