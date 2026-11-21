"""Seeded randomised invariant tests for the Open Access parsers.

Invariants checked on thousands of adversarial mixtures (same seed every run):

1. Literal: every reported address occurs verbatim in the input (after the
   format's own entity/URL decoding). Nothing is constructed, completed or sliced.
2. Bounded failure: hostile input raises only ``FetchDenied`` (a safe reason
   code) or returns an observation; no other exception escapes.
3. Consistency: candidate author positions refer to observed authors, and the
   association basis/status agree.
"""

from __future__ import annotations

import html
import random
from urllib.parse import unquote

import pytest
from emailmonitor.extraction.attribution import Person, attribute_spans, find_addresses
from emailmonitor.extraction.citation_meta import parse_citation_page
from emailmonitor.extraction.jats import parse_jats_xml
from emailmonitor.extraction.pdf_contacts import parse_pdf_contacts
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import PmcIdentifier
from pdf_fixture_builder import document

PMC = PmcIdentifier(value="PMC7700001")
SEED = 20261115

NAMES = [
    ("John", "Smith"),
    ("Karen", "Jones"),
    ("Wei", "Li"),
    ("Lan", "Ito"),
    ("Alice", "Brown"),
    ("Joao", "de Souza"),
    ("Pieter", "van der Berg"),
    ("Jürgen", "Müller"),
    ("Jean-Luc", "Picard"),
    ("Mary", "Hopkins"),
    ("Soo-Jin", "Kim"),
    ("Ana", "Silva"),
]
TOKENS = [
    "Correspondence:",
    "Corresponding author:",
    "E-mail:",
    "Email addresses:",
    "Contact:",
    "Department of Surgery,",
    "Brown University,",
    "Johns Hopkins",
    "Universidade de Sao Paulo",
    ";",
    ",",
    ".",
    "and",
    "(",
    ")",
    "*",
    "Tel: +1 555 0100",
    "Fax",
    "—",
    "lab office",
    "(JS)",
    "(K.J.)",
    "(Li)",
    "(Ito)",
    "(J. Smith)",
    "(lab)",
    "Smith",
    "Jones",
    "Wei Li",
    "Karen Jones",
    "John Smith",
    "Joao de Souza",
    "Mr",
    "Prof.",
    "PhD",
    " ",
    "é",
    "ü",
]
ADDRESSES = [
    "smith@x.example",
    "k.jones@y.example",
    "wli@uni.example",
    "lito@lab.example",
    "office@brown.example",
    "_ops@lab.example",
    "a.b-c+d@mail.lab.example",
    "müller@uni.example",
    "{a,b}@grp.example",
    "x@y",
    "@lonely.example",
    "a@b.c",
    "trail@dot.example.",
    "run@on.example.Phone",
    "q@x.example@y.example",
    "UPPER@CASE.EXAMPLE",
]


def _mixture(rng: random.Random, size: int) -> str:
    parts: list[str] = []
    for _ in range(size):
        roll = rng.random()
        if roll < 0.35:
            parts.append(rng.choice(ADDRESSES))
        elif roll < 0.55:
            given, surname = rng.choice(NAMES)
            parts.append(
                rng.choice(
                    [f"{given} {surname}", f"{surname}, {given}", f"{given[0]}. {surname}", surname]
                )
            )
        else:
            parts.append(rng.choice(TOKENS))
    return rng.choice([" ", "", "  "]).join(parts)


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _assert_literal(address: str, source: str) -> None:
    decoded = html.unescape(source)
    assert address in source or address in decoded or address in unquote(decoded), address


def test_find_addresses_reports_only_literal_bounded_tokens() -> None:
    rng = random.Random(SEED)
    for _ in range(3000):
        text = _mixture(rng, rng.randint(1, 12))
        for start, address in find_addresses(text):
            assert text[start : start + len(address)] == address
            before = text[start - 1] if start else " "
            after = text[start + len(address)] if start + len(address) < len(text) else " "
            assert not (before.isalnum() or before in "@_"), (text, address)
            assert not (after.isalnum() or after in "@_"), (text, address)


def test_attribute_spans_only_returns_known_people() -> None:
    rng = random.Random(SEED + 1)
    for _ in range(1500):
        people = [Person(i + 1, f"{g} {s}") for i, (g, s) in enumerate(rng.sample(NAMES, 4))]
        text = _mixture(rng, rng.randint(2, 14))
        spans = [(s, s + len(a)) for s, a in find_addresses(text)]
        results = attribute_spans(text, spans, people)
        assert len(results) == len(spans)
        keys = {p.key for p in people}
        by_key = {p.key: p.display_name for p in people}
        for owner, kind in results:
            assert (owner is None) == (kind is None)
            assert owner is None or owner in keys
            if owner is not None:
                # Never attribute from nothing: the person's surname or initials are present.
                given, _, surname = by_key[owner].rpartition(" ")
                initials = (given[:1] + surname[:1]).upper()
                assert (
                    surname.casefold() in text.casefold()
                    or initials in text.replace(".", "").replace(" ", "").upper()
                ), (text, by_key[owner])


def test_jats_notes_invariants() -> None:
    rng = random.Random(SEED + 2)
    for _ in range(600):
        authors = rng.sample(NAMES, rng.randint(1, 4))
        corresp_attr = ' corresp="yes"'
        contribs = "".join(
            '<contrib contrib-type="author"'
            + (corresp_attr if rng.random() < 0.5 else "")
            + ">"
            + f"<name><surname>{_xml_escape(s)}</surname><given-names>{_xml_escape(g)}"
            + "</given-names></name>"
            + (f"<email>{_xml_escape(rng.choice(ADDRESSES))}</email>" if rng.random() < 0.2 else "")
            + ('<xref ref-type="corresp" rid="c1"/>' if rng.random() < 0.4 else "")
            + "</contrib>"
            for g, s in authors
        )
        note = _mixture(rng, rng.randint(1, 10))
        if rng.random() < 0.5:
            note = "".join(
                f"<email>{_xml_escape(t)}</email>" if "@" in t else _xml_escape(t) + " "
                for t in note.split(" ")
            )
        else:
            note = _xml_escape(note)
        source = (
            "<article><front><article-meta><contrib-group>"
            f'{contribs}</contrib-group><author-notes><corresp id="c1">{note}</corresp>'
            "</author-notes></article-meta></front></article>"
        )
        try:
            obs = parse_jats_xml(source.encode("utf-8"), PMC)
        except FetchDenied:
            continue
        positions = {a.position for a in obs.authors}
        for candidate in obs.candidates:
            _assert_literal(candidate.raw_address, source)
            assert set(candidate.author_positions) <= positions
            assert (candidate.association_basis == "unmatched") == (not candidate.author_positions)


def test_html_page_invariants() -> None:
    rng = random.Random(SEED + 3)
    for _ in range(500):
        authors = rng.sample(NAMES, rng.randint(1, 4))
        metas = "".join(
            f'<meta name="citation_author" content="{html.escape(s)}, {html.escape(g)}">'
            + (
                '<meta name="citation_author_email" content="'
                + html.escape(rng.choice(ADDRESSES))
                + '">'
                if rng.random() < 0.3
                else ""
            )
            for g, s in authors
        )
        body_parts = []
        for token in _mixture(rng, rng.randint(1, 10)).split(" "):
            if "@" in token and rng.random() < 0.7:
                body_parts.append(f'<a href="mailto:{html.escape(token)}">{html.escape(token)}</a>')
            else:
                body_parts.append(html.escape(token))
        wrapper = rng.choice(["p", "div", "footer", "nav", "section", "span"])
        source = (
            f'<html><head><meta name="citation_title" content="T">{metas}</head><body>'
            f"<{wrapper}>{' '.join(body_parts)}</{wrapper}></body></html>"
        )
        try:
            obs = parse_citation_page(source.encode("utf-8"))
        except FetchDenied:
            continue
        positions = {a.position for a in obs.authors}
        for candidate in obs.candidates:
            _assert_literal(candidate.raw_address, source)
            assert set(candidate.author_positions) <= positions
            if wrapper in ("footer", "nav"):
                assert candidate.evidence.kind == "citation_meta"


@pytest.mark.parametrize("seed", range(8))
def test_pdf_line_invariants(seed: int) -> None:
    rng = random.Random(SEED + 100 + seed)
    names = [f"{g} {s}" for g, s in rng.sample(NAMES, 3)]
    lines = []
    for _ in range(6):
        text = _mixture(rng, rng.randint(1, 8))
        lines.append(text.encode("cp1252", errors="ignore").decode("cp1252"))
    data = document([[(72.0, 740.0 - 14 * i, 9.0, t) for i, t in enumerate(lines)]])
    obs = parse_pdf_contacts(data, known_authors=names)
    joined = "\n".join(lines)
    for candidate in obs.candidates:
        assert candidate.raw_address in joined, (candidate.raw_address, joined)
        assert candidate.author_name is None or candidate.author_name in names
