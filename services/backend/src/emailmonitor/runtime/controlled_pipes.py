"""Dedicated bounded binary pipes; standard streams must be redirected by the child."""

import json
import math
import os
import selectors
import struct
import time
from typing import Any

from emailmonitor.runtime.controlled_channel import MAX_FRAME, _constant, _float, _pairs


class FramedPipes:
    def __init__(self, incoming: int, outgoing: int, errors: int | None = None) -> None:
        if incoming == outgoing or any(
            type(fd) is not int or fd < 0 for fd in (incoming, outgoing)
        ):
            raise ValueError("Dedicated pipe descriptors required")
        self.incoming, self.outgoing, self.errors = incoming, outgoing, errors
        self.poisoned = False
        self._errors = 0
        self._buffer = bytearray()
        for fd in (incoming, outgoing, errors):
            if fd is not None:
                os.set_inheritable(fd, False)
                os.set_blocking(fd, False)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if self.poisoned or not math.isfinite(deadline) or remaining <= 0:
            raise RuntimeError("Controlled pipe unavailable")
        return remaining

    def _error(self) -> None:
        assert self.errors is not None
        chunk = os.read(self.errors, 4096)
        self._errors += len(chunk)
        if self._errors > 4096:
            raise ValueError("Controlled diagnostic limit")
        if not chunk:
            os.close(self.errors)
            self.errors = None

    def send(self, value: dict[str, Any], deadline: float) -> None:
        try:
            raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("ascii")
            if not 1 <= len(raw) <= MAX_FRAME:
                raise ValueError
            packet = struct.pack("!I", len(raw)) + raw
            offset = 0
            while offset < len(packet):
                with selectors.DefaultSelector() as selector:
                    selector.register(self.outgoing, selectors.EVENT_WRITE)
                    if self.errors is not None:
                        selector.register(self.errors, selectors.EVENT_READ)
                    events = selector.select(self._remaining(deadline))
                    if not events:
                        raise ValueError
                    for key, _ in events:
                        if key.fd == self.outgoing:
                            count = os.write(self.outgoing, packet[offset : offset + 65536])
                            if not count:
                                raise ValueError
                            offset += count
                        else:
                            self._error()
        except Exception:
            self.poisoned = True
            raise RuntimeError("Controlled pipe failed") from None

    def _read(self, count: int, deadline: float) -> bytes:
        while len(self._buffer) < count:
            with selectors.DefaultSelector() as selector:
                selector.register(self.incoming, selectors.EVENT_READ)
                if self.errors is not None:
                    selector.register(self.errors, selectors.EVENT_READ)
                events = selector.select(self._remaining(deadline))
                if not events:
                    raise ValueError
                for key, _ in events:
                    if key.fd == self.incoming:
                        chunk = os.read(self.incoming, min(65536, count - len(self._buffer)))
                        if not chunk:
                            raise ValueError
                        self._buffer.extend(chunk)
                    else:
                        self._error()
        result = bytes(self._buffer[:count])
        del self._buffer[:count]
        return result

    def receive(self, deadline: float) -> dict[str, Any]:
        try:
            count = struct.unpack("!I", self._read(4, deadline))[0]
            if not 1 <= count <= MAX_FRAME:
                raise ValueError
            value = json.loads(
                self._read(count, deadline),
                object_pairs_hook=_pairs,
                parse_constant=_constant,
                parse_float=_float,
            )
            if type(value) is not dict:
                raise ValueError
            return value
        except Exception:
            self.poisoned = True
            raise RuntimeError("Controlled pipe failed") from None

    def close(self) -> None:
        self.poisoned = True
        for fd in {self.incoming, self.outgoing, self.errors}:
            if fd is not None and fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.incoming = self.outgoing = -1
        self.errors = None
