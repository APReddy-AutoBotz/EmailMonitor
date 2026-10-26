"""Numeric-only progress for the fixed installed XML pytest consumer."""

import os
from pathlib import Path
from typing import Any

from backend_outcome import KEY, Progress


def pytest_configure(config: Any) -> None:
    path = os.environ.get(KEY)
    if path:
        config.pluginmanager.register(Progress(Path(path)), "owned-xml-progress")
