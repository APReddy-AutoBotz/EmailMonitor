"""One fixed bounded stdin→stdout command, exclusively inside the parser sandbox."""

import json
import os
import sys
from pathlib import Path

from emailmonitor.extraction.xml_retained import MAX_ENVELOPE
from emailmonitor.parsing.xml_protocol import parse_input


def main() -> None:
    try:
        fields = dict(
            line.split(":", 1)
            for line in Path("/proc/self/status").read_text().splitlines()
            if ":" in line
        )
        if (
            os.environ.get("EM_ISOLATION_DIAGNOSTIC") != "synthetic-test-only"
            or os.geteuid() != 65532
            or sorted(p.name for p in Path("/sys/class/net").iterdir()) != ["lo"]
            or int(fields["CapEff"].strip(), 16) != 0
            or fields["NoNewPrivs"].strip() != "1"
            or fields["Seccomp"].strip() != "2"
        ):
            raise ValueError("Isolation required")
        observed = parse_input(sys.stdin.buffer)
        output = (
            json.dumps(
                {
                    "profile": "network-none-parser-v1",
                    "observation": observed.model_dump(mode="json"),
                },
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
            + b"\n"
        )
        if len(output) > MAX_ENVELOPE:
            raise ValueError("Bounded output required")
        sys.stdout.buffer.write(output)
    except Exception:
        # Untrusted XML and parser exceptions never become diagnostics.
        sys.stderr.write("XML_PARSER_REFUSED\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
