"""Runs only inside the reviewed network-none diagnostic container.

No credentials, live destinations, shell input or host socket are consumed.
"""

import errno
import json
import os
import socket
from pathlib import Path

from emailmonitor.config import Settings
from emailmonitor.discovery.search import parse_search
from emailmonitor.discovery.state import DiscoveryState, advance
from emailmonitor.extraction.html import parse_article
from emailmonitor.parsing.fixture import observe_fixture


def main() -> None:
    if os.environ.get("EM_ISOLATION_DIAGNOSTIC") != "synthetic-test-only":
        raise RuntimeError("Explicit diagnostic environment required")
    if os.geteuid() == 0:
        raise RuntimeError("Parser must be unprivileged")
    interfaces = sorted(path.name for path in Path("/sys/class/net").iterdir())
    if interfaces != ["lo"]:
        raise RuntimeError("Expected a network-none namespace")
    status = Path("/proc/self/status").read_text()
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    if int(fields["CapEff"].strip(), 16) != 0:
        raise RuntimeError("Capabilities must be dropped")
    if fields["NoNewPrivs"].strip() != "1" or fields["Seccomp"].strip() != "2":
        raise RuntimeError("Default seccomp and no-new-privileges required")
    # Reserved documentation destinations only. Real metadata/source endpoints
    # are never probed. Kernel rejection plus namespace/config evidence is recorded.
    outcomes: list[int] = []
    for family, target in (
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as stream:
            stream.settimeout(0.2)
            result = stream.connect_ex(target)
            if result not in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EAFNOSUPPORT):
                raise RuntimeError("Network-level denial not established")
            outcomes.append(result)
    payload = b'<p>synthetic parser observation</p><script>throw Error("must stay inert")</script>'
    observed = observe_fixture(Settings(environment="test", fixture_mode=True), payload)
    if observed.visible_text != "synthetic parser observation":
        raise RuntimeError("Inert byte observation failed")
    settings = Settings(environment="test", fixture_mode=True)
    state = DiscoveryState(
        status="pending",
        reason="first_page",
        next_url="https://synthetic.publisher.example/search-page-1.html",
    )
    for number in (1, 2):
        url = f"https://synthetic.publisher.example/search-page-{number}.html"
        page = parse_search(
            settings, url, Path(f"/app/fixtures/search-page-{number}.html").read_bytes()
        )
        state = advance(state, page, 2, 500)
    if (
        not state.discovery_complete
        or len(state.articles) != 4
        or state.duplicates != 1
        or state.raw_entries != 5
    ):
        raise RuntimeError("Actual network-none discovery parser failed")
    articles = {
        name: parse_article(
            settings,
            "https://synthetic.publisher.example/" + name,
            Path("/app/fixtures", name).read_bytes(),
        )
        for name in ("article-a.html", "article-b.html", "tooltip.html", "no-contact.html")
    }
    if [(a.first, a.corresponding) for a in articles["article-a.html"].authors] != [
        (True, None),
        (False, True),
    ] or [c.raw_address for c in articles["article-a.html"].candidates] != [
        "alex.chen@example.org"
    ]:
        raise RuntimeError("Actual isolated article-A observations failed")
    if [(a.first, a.corresponding) for a in articles["article-b.html"].authors] != [
        (True, True),
        (False, True),
    ] or [c.raw_address for c in articles["article-b.html"].candidates] != [
        "ravi.das@example.org",
        "noor.ibrahim@example.org",
    ]:
        raise RuntimeError("Actual isolated article-B observations failed")
    if (
        articles["tooltip.html"].status != "requires_browser"
        or articles["tooltip.html"].candidates
        or articles["no-contact.html"].status != "no_contact"
    ):
        raise RuntimeError("Unresolved/absent contact was fabricated")
    print(
        json.dumps(
            {
                "diagnostic": "network-none-parser",
                "network_errno": outcomes,
                "interfaces": interfaces,
                "digest": observed.digest,
                "contact_extraction": True,
                "article_observations": {
                    name: {
                        "status": value.status,
                        "authors": len(value.authors),
                        "candidates": len(value.candidates),
                        "digest": value.content_digest,
                    }
                    for name, value in articles.items()
                },
                "discovery": state.model_dump(),
            }
        )
    )


if __name__ == "__main__":
    main()
