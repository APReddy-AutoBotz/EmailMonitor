"""Runs only inside the reviewed network-none diagnostic container.

No credentials, live destinations, shell input or host socket are consumed.
"""

import errno
import hashlib
import json
import logging
import os
import socket
from pathlib import Path

from emailmonitor.config import Settings
from emailmonitor.discovery.search import parse_search
from emailmonitor.discovery.state import DiscoveryState, advance
from emailmonitor.extraction.html import parse_article
from emailmonitor.extraction.pdf import PdfLimits, parse_pdf
from emailmonitor.extraction.pdf_fixture import DIGESTS as PDF_DIGESTS
from emailmonitor.extraction.sciencedirect import parse_article as parse_xml
from emailmonitor.extraction.xml_retained import XML_IDENTIFIER
from emailmonitor.fetching.safety import FetchDenied
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
            if result not in (
                errno.ENETUNREACH,
                errno.EHOSTUNREACH,
                errno.EAFNOSUPPORT,
            ):
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
        for name in (
            "article-a.html",
            "article-b.html",
            "tooltip.html",
            "no-contact.html",
        )
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
    # One disposable parser process; library diagnostics cannot echo source text.
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    pdfs = {}
    for name, expected_digest in PDF_DIGESTS.items():
        data = Path("/app/fixtures/pdf", name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_digest:
            raise RuntimeError("Authored PDF manifest mismatch")
        pdfs[name] = parse_pdf(settings, "https://synthetic.publisher.example/" + name, data)
    if [(a.first, a.corresponding) for a in pdfs["article-a.pdf"].authors] != [
        (True, None),
        (False, True),
    ]:
        raise RuntimeError("Actual isolated PDF role mapping failed")
    if (
        pdfs["article-a.pdf"].candidates[0].author_positions != [2]
        or pdfs["article-a.pdf"].candidates[0].evidence[0].anchor != (50, 110)
        or pdfs["article-a.pdf"].candidates[0].evidence[0].page != 2
    ):
        raise RuntimeError("Actual PDF page/fragment evidence failed")
    if [c.raw_address for c in pdfs["article-b.pdf"].candidates] != [
        "ravi.das@example.org",
        "noor.ibrahim@example.org",
    ]:
        raise RuntimeError("Actual isolated two-column PDF failed")
    if (
        pdfs["wrapped.pdf"].authors[0].display_name != "Eva Müller"
        or pdfs["wrapped.pdf"].candidates[0].raw_address != "eva.mueller@example.org"
        or pdfs["wrapped.pdf"].candidates[0].reconstruction != "adjacent_line_wrap"
    ):
        raise RuntimeError("Actual encoded/wrapped PDF evidence failed")
    if pdfs["ambiguous.pdf"].candidates[0].author_positions or any(
        a.corresponding is not None for a in pdfs["ambiguous.pdf"].authors
    ):
        raise RuntimeError("Ambiguous PDF identity guessed")
    if pdfs["no-contact.pdf"].status != "no_contact" or pdfs["no-contact.pdf"].candidates:
        raise RuntimeError("Support/reference PDF contact fabricated")
    for name, reason in (
        ("encrypted.pdf", "encrypted"),
        ("corrupt.pdf", "corrupt"),
        ("scanned.pdf", "image_only_or_no_extractable_text"),
    ):
        if (
            pdfs[name].status != "unsupported"
            or pdfs[name].reason != reason
            or pdfs[name].complete_scan
        ):
            raise RuntimeError("Unsafe PDF input incorrectly completed")
    if (
        pdfs["page-cap.pdf"].status != "partial"
        or pdfs["page-cap.pdf"].complete_scan
        or pdfs["page-cap.pdf"].pages_inspected != 4
        or pdfs["page-cap.pdf"].pages_total != 5
    ):
        raise RuntimeError("PDF page cap incorrectly claimed full coverage")
    if (
        parse_pdf(
            settings,
            "https://synthetic.publisher.example/article-a.pdf",
            b"%PDF-" + b"x" * 262144,
        ).reason
        != "byte_cap"
    ):
        raise RuntimeError("PDF byte ceiling not enforced")
    if (
        parse_pdf(
            settings,
            "https://synthetic.publisher.example/article-a.pdf",
            Path("/app/fixtures/pdf/article-a.pdf").read_bytes(),
            limits=PdfLimits(max_stream_bytes=64),
        ).reason
        != "resource_limit"
    ):
        raise RuntimeError("Actual PDF stream ceiling not enforced")
    xml_data = Path("/app/fixtures/xml/sciencedirect-article.xml").read_bytes()
    xml = parse_xml(xml_data, XML_IDENTIFIER)
    if xml.status != "observed" or len(xml.authors) != 3 or len(xml.candidates) != 2:
        raise RuntimeError("Isolated XML observations failed")
    for hostile in (
        b'<!DOCTYPE x [<!ENTITY remote SYSTEM "http://192.0.2.1/">]><x>&remote;</x>',
        b'<!DOCTYPE x [<!ENTITY a "1234"><!ENTITY b "&a;&a;">]><x>&b;</x>',
        b"<x>" * 50 + b"</x>" * 50,
        b"<x>" + b"a" * 1048577 + b"</x>",
        b"x" * 2097153,
    ):
        try:
            parse_xml(hostile, XML_IDENTIFIER)
        except FetchDenied:
            pass
        else:
            raise RuntimeError("Isolated hostile XML was not refused")
    print(
        json.dumps(
            {
                "diagnostic": "network-none-parser",
                "network_errno": outcomes,
                "interfaces": interfaces,
                "digest": observed.digest,
                "contact_extraction": True,
                "xml_observations": {
                    "authors": len(xml.authors),
                    "candidates": len(xml.candidates),
                    "digest": xml.content_digest,
                    "hostile_refusals": 5,
                },
                "pdf_resource_caps": True,
                "pdf_observations": {
                    name: {
                        "status": value.status,
                        "reason": value.reason,
                        "authors": len(value.authors),
                        "candidates": len(value.candidates),
                        "pages_inspected": value.pages_inspected,
                        "pages_total": value.pages_total,
                        "digest": value.content_digest,
                        "ocr": value.ocr_implemented,
                    }
                    for name, value in pdfs.items()
                },
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
