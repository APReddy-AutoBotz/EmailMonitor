"""Explicit runtime ownership; importing scope types performs no assembly I/O."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from emailmonitor.runtime.assembly import (
        RuntimeAssemblyError,
        RuntimeBundle,
        RuntimeCleanupError,
        TestRuntimeConfig,
        owned_test_runtime,
    )

__all__ = [
    "RuntimeAssemblyError",
    "RuntimeBundle",
    "RuntimeCleanupError",
    "TestRuntimeConfig",
    "owned_test_runtime",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    return getattr(import_module("emailmonitor.runtime.assembly"), name)
