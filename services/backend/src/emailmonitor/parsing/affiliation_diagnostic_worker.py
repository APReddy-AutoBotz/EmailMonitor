"""Explicit private diagnostic guest; no ordinary entrypoint selects this mode."""

import os
import sys
from pathlib import Path

from emailmonitor.parsing.affiliation_diagnostic import diagnose, encode_output
from emailmonitor.parsing.xml_protocol import read_input


def main() -> None:
    try:
        fields = dict(
            line.split(":", 1)
            for line in Path("/proc/self/status").read_text().splitlines()
            if ":" in line
        )
        if (
            sys.argv[1:]
            or os.environ.get("EM_PRIVATE_AFFILIATION_DIAGNOSTIC") != "one-file-private-diagnostic"
            or "EM_PRIVATE_OFFLINE_XML" in os.environ
            or "EM_ISOLATION_DIAGNOSTIC" in os.environ
            or os.geteuid() != 65532
            or sorted(path.name for path in Path("/sys/class/net").iterdir()) != ["lo"]
            or int(fields["CapEff"].strip(), 16) != 0
            or fields["NoNewPrivs"].strip() != "1"
            or fields["Seccomp"].strip() != "2"
        ):
            raise ValueError("Isolation required")
        data, expected = read_input(sys.stdin.buffer)
        sys.stdout.buffer.write(encode_output(diagnose(data, expected)))
    except Exception:
        sys.stderr.write("AFFILIATION_DIAGNOSTIC_REFUSED\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
