"""Literal address finding and conservative author attribution, shared by parsers.

Two rules keep this truthful:

1. **Literal or nothing.** ``find_addresses`` returns only complete ASCII
   addresses bounded on both sides by non-address characters. A token that
   touches a non-ASCII letter (``müller@uni.de``), another ``@``, or exceeds
   RFC length bounds is rejected entirely; it is never sliced into a shorter,
   different address. Internationalised (SMTPUTF8) addresses are unsupported
   and reported as nothing rather than corrupted.

2. **A person, not a word.** An address is attributed to an author only by
   (a) an adjacent parenthetical label that is the author's initials, full
   or initial+surname name form, or exactly their surname; or (b) a person
   form — given name or initial followed by the surname, or "Surname, Given" —
   in the text that belongs to that address. A bare surname in running text
   ("Brown University", "Johns Hopkins") never attributes. Lists are read in
   their own direction: "Name: address" or "address, Name".

Everything here is linear in the input size up to small per-author constants.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

# Characters that may form a local part when scanning running text. RFC 5322 allows
# more symbols, but in documents '*', '|', '#', '!' and similar are footnote markers
# or separators; they end the token instead of joining it. (Explicit <email> values
# and mailto: hrefs are validated by clean_address, which keeps the full RFC set.)
_ASCII_LOCAL = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-'")
_ASCII_DOMAIN = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
_EMAIL_FULL = re.compile(
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,63}"
)
_PARTICLES = frozenset(
    {
        "de",
        "da",
        "das",
        "do",
        "dos",
        "di",
        "del",
        "della",
        "van",
        "von",
        "der",
        "den",
        "le",
        "la",
        "du",
        "ter",
        "ten",
        "bin",
        "al",
        "el",
        "y",
        "mac",
        "st",
        "st.",
    }
)
_TITLES = re.compile(r"^(?:prof\.?|dr\.?|mr\.?|ms\.?|mrs\.?|professor|doctor)\s+", re.IGNORECASE)
MAX_LABEL = 80
MAX_FOLLOWING = 200


def clean_address(value: str) -> str | None:
    """Return the literal address if ``value`` is exactly one address after trimming."""
    text = value.strip()
    if text.lower().startswith("mailto:"):
        text = text[7:]
    text = text.strip().strip("<>()[]{}\"'").rstrip(".,;:").strip()
    if len(text) > 320 or not _EMAIL_FULL.fullmatch(text):
        return None
    local, _, domain = text.rpartition("@")
    if len(local) > 64 or len(domain) > 253:
        return None
    return text


# Characters that render inside a word: an address touching one of these was split
# by typesetting (soft hyphen, zero-width space, non-breaking hyphen, curly
# apostrophe). Rejecting keeps us from returning only the part after/before it.
JOINERS = frozenset("\u00ad\u200b\u200c\u200d\u2060\ufeff\u2010\u2011\u2019\u02bc")
INVISIBLE = "\u00ad\u200b\u200c\u200d\u2060\ufeff"


def strip_invisible(value: str) -> str:
    """Remove characters that do not render (soft hyphen, zero-width): the displayed
    text is unchanged. Used only on explicit <email> element content."""
    return value.translate({ord(c): None for c in INVISIBLE})


def _is_word_char(char: str) -> bool:
    # Superscript/subscript digits and other 'No' numbers are footnote markers, not
    # part of an address: "¹js@uni.example" is "js@uni.example" after marker ¹.
    if char == "_":
        return True
    return char.isalnum() and unicodedata.category(char) != "No"


def find_addresses(text: str) -> list[tuple[int, str]]:
    """Complete literal ASCII addresses as (start, address), in order; linear time."""
    found: list[tuple[int, str]] = []
    position = text.find("@")
    floor = 0
    while position != -1:
        start = position
        while start > floor and position - start <= 64 and text[start - 1] in _ASCII_LOCAL:
            start -= 1
        end = position + 1
        while end < len(text) and end - position <= 254 and text[end] in _ASCII_DOMAIN:
            end += 1
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        capped = end - position > 254 or (
            position - start > 64 and start > floor and text[start - 1] in _ASCII_LOCAL
        )
        # Reject rather than slice: a neighbour that could continue the token
        # (another address char, a non-ASCII letter, or another '@').
        bad_edge = (
            before
            and (
                before in _ASCII_LOCAL
                or before == "@"
                or before in JOINERS
                or _is_word_char(before)
            )
        ) or (after and (after == "@" or after in JOINERS or _is_word_char(after)))
        candidate = text[start:end]
        while candidate.endswith((".", "-")):
            candidate = candidate[:-1]
        leading = 0
        while candidate[leading : leading + 1] in (".", "'", "`"):
            leading += 1
        candidate = candidate[leading:]
        address = None if bad_edge or capped else clean_address(candidate)
        if address is not None and _looks_run_on(address):
            address = None
        if address is not None:
            found.append((start + leading, address))
            floor = start + leading + len(address)
        else:
            floor = max(floor, end)
        position = text.find("@", position + 1)
    return found


def _looks_run_on(address: str) -> bool:
    """'smith@x.edu.Phone' or 'js@uni.eduTel' — a word glued onto the domain."""
    labels = address.rsplit("@", 1)[1].split(".")
    last = labels[-1]
    if re.search(r"[a-z][A-Z]", last):
        return True  # a word glued onto the top-level domain: "eduTel"
    return (
        len(labels) >= 3
        and last[:1].isupper()
        and last[1:].islower()
        and all(label == label.lower() for label in labels[:-1])
    )


@dataclass(frozen=True)
class Person:
    key: int
    display_name: str


def _split_name(display_name: str) -> tuple[str, str] | None:
    """(given, surname) from 'Given [Middle] [particles] Surname' or 'Surname, Given'."""
    name = _TITLES.sub("", display_name.strip())
    if "," in name:
        surname, _, given = name.partition(",")
        surname, given = surname.strip(), given.strip()
    else:
        tokens = name.split()
        if len(tokens) < 2:
            return None
        cut = len(tokens) - 1
        while cut > 1 and tokens[cut - 1].lower() in _PARTICLES:
            cut -= 1
        given, surname = " ".join(tokens[:cut]), " ".join(tokens[cut:])
    if not given or not surname or len(surname) < 2:
        return None
    return given, surname


@lru_cache(maxsize=4096)
def _patterns(display_name: str) -> tuple[re.Pattern[str], re.Pattern[str]] | None:
    """(person-form pattern, exact-surname pattern) for one author."""
    parts = _split_name(display_name)
    if parts is None:
        return None
    given, surname = parts
    first_given = given.split()[0]
    surname_re = r"\s+".join(re.escape(t) for t in surname.split())
    initial = re.escape(first_given[0].upper())
    # An initial is an upper-case letter standing alone ("J", "J.", "J.-L."), so
    # titles such as "Dr", "Mr", "Ms" or words like "to" can never act as one.
    single = r"(?:\.|(?![A-Za-z]))"
    initials = rf"{initial}{single}(?:\s?-?[A-Z]{single})?"
    start = r"(?<![\w\-.])"  # not inside a hyphenated or dotted token ("M.-J. Kim")
    # The given name keeps its capital ("May", "MAY"), so the word "may" in running
    # text is not a given name; tokens between given name and surname must look like
    # name parts (capitalised word or initial), so "Kate Brown and John Smith" never
    # reads as "Kate ... Smith".
    given_cased = re.escape(first_given[0].upper()) + (
        f"(?i:{re.escape(first_given[1:])})" if len(first_given) > 1 else ""
    )
    particles = "|".join(sorted(re.escape(p) for p in _PARTICLES if p.isalpha()))
    middle = rf"(?:\s+(?:[A-Z][\w'\-]{{0,20}}\.?|[A-Z]\.|(?:{particles}))){{0,2}}?"
    forward = (
        rf"{start}(?:{given_cased}(?![\w])|{initials})"
        rf"{middle}\s+(?i:{surname_re})(?!\w)"
    )
    inverted = rf"{start}(?i:{surname_re}),?\s+(?:{given_cased}(?![\w])|{initial}\.)(?!\w)"
    person = re.compile(f"(?:{forward})|(?:{inverted})")
    exact = re.compile(rf"^{surname_re}$", re.IGNORECASE)
    return person, exact


def initial_variants(display_name: str) -> frozenset[str]:
    parts = _split_name(display_name)
    tokens = [t for t in re.split(r"[\s.,]+", display_name) if t]
    if not tokens:
        return frozenset()
    variants = {
        "".join(p[0] for t in tokens for p in t.split("-") if p).upper(),
        "".join(t[0] for t in tokens).upper(),
    }
    if parts is not None:
        given, surname = parts
        variants.add("".join(t[0] for t in given.split()).upper() + surname[0].upper())
        variants.add((given[0] + surname.split()[-1][0]).upper())
    return frozenset(v for v in variants if 2 <= len(v) <= 6)


def _people_in(segment: str, people: Sequence[Person]) -> list[int]:
    hits: list[int] = []
    for person in people:
        compiled = _patterns(person.display_name)
        if compiled and compiled[0].search(segment):
            hits.append(person.key)
    return hits


def _label_owner(content: str, people: Sequence[Person]) -> int | None:
    stripped = _TITLES.sub("", content.strip()).strip(" .,;:")
    letters = re.sub(r"[\s.\-]", "", stripped)
    # Initials only when written as initials: upper case, or dotted single letters.
    looks_initial = (
        letters.isalpha()
        and 2 <= len(letters) <= 6
        and (letters.isupper() or re.fullmatch(r"(?:\w\.\s*-?\s*){2,6}", stripped) is not None)
    )
    exact_hits = [
        p.key
        for p in people
        if (compiled := _patterns(p.display_name)) and compiled[1].match(stripped)
    ]
    person_hits = _people_in(stripped, people)
    initial_hits = (
        [p.key for p in people if letters.upper() in initial_variants(p.display_name)]
        if looks_initial
        else []
    )
    candidates = set(exact_hits) | set(person_hits) | set(initial_hits)
    return next(iter(candidates)) if len(candidates) == 1 else None


_ROLE_LABEL = re.compile(
    r"^\s*(?:\*|†|‡|corresponding(?:\s+authors?)?|corresp\.?|equal\s+contribution|"
    r"e-?mail|primary\s+contact|lead\s+contact)\s*$",
    re.IGNORECASE,
)
_INITIALS_BEFORE_EMAIL = re.compile(
    r"(?<![\w.])([A-Z]\.(?:\s?-?[A-Z]\.){1,4})\s*\(\s*e-?mail\s*:?\s*$"
)
MAX_WINDOW = 300


def _trailing_label(text: str, end: int) -> tuple[str, int] | None:
    match = re.match(rf"\s*\(([^()]{{1,{MAX_LABEL}}})\)", text[end : end + MAX_LABEL + 8])
    if not match:
        return None
    return match.group(1), end + match.end()


def attribute_spans(
    text: str,
    spans: Sequence[tuple[int, int]],
    people: Sequence[Person],
    window_start: int = 0,
) -> list[tuple[int | None, Literal["initials", "name"] | None]]:
    """Owner of each address span ``(start, end)`` in ``text`` (spans in order).

    Returns one ``(person key | None, kind)`` per span; ``None`` means unmatched.
    """
    results: list[tuple[int | None, Literal["initials", "name"] | None]] = [(None, None)] * len(
        spans
    )
    if not spans or not people:
        return results
    label_ends: list[int] = []
    unlabelled: list[int] = []
    for index, (_start, end) in enumerate(spans):
        label = _trailing_label(text, end)
        if label is None or _ROLE_LABEL.match(label[0]):
            # No label, or a role-only label such as "(corresponding author)" that
            # names nobody: decide from the surrounding text instead.
            label_ends.append(label[1] if label else end)
            unlabelled.append(index)
            continue
        owner = _label_owner(label[0], people)
        letters = re.sub(r"[\s.\-]", "", label[0])
        kind: Literal["initials", "name"] = (
            "initials" if letters.isalpha() and letters.isupper() and len(letters) <= 6 else "name"
        )
        results[index] = (owner, kind if owner is not None else None)
        label_ends.append(label[1])
    if not unlabelled:
        return results

    def preceding(index: int) -> str:
        lo = label_ends[index - 1] if index > 0 else window_start
        lo = max(lo, spans[index][0] - MAX_WINDOW)  # bounded work per address
        return text[lo : spans[index][0]]

    def following(index: int) -> str:
        hi = spans[index + 1][0] if index + 1 < len(spans) else label_ends[index] + MAX_FOLLOWING
        hi = min(hi, label_ends[index] + MAX_WINDOW)
        return text[label_ends[index] : hi]

    # Nature style: "... addressed to A.B. (email: ab@x) or C.D. (email: cd@y)".
    for i in list(unlabelled):
        match = _INITIALS_BEFORE_EMAIL.search(preceding(i))
        if not match:
            continue
        token = re.sub(r"[\s.\-]", "", match.group(1))
        hits = [p.key for p in people if token in initial_variants(p.display_name)]
        if len(hits) == 1:
            results[i] = (hits[0], "initials")
            unlabelled.remove(i)
    if not unlabelled:
        return results

    # A person already identified by a label owns that labelled address; the same
    # name in neighbouring text ("a@x; Kate Jones, kj@y (K.J.)") is not reused.
    labelled_owners = {owner for owner, _kind in results if owner is not None}
    pre = {
        i: [k for k in _people_in(preceding(i), people) if k not in labelled_owners]
        for i in unlabelled
    }
    post = {
        i: [k for k in _people_in(following(i), people) if k not in labelled_owners]
        for i in unlabelled
    }
    pre_count = sum(1 for i in unlabelled if len(pre[i]) == 1)
    post_count = sum(1 for i in unlabelled if len(post[i]) == 1)
    # "a@x, John Smith; b@y, Kate Jones" reads address-first; otherwise name-first.
    chosen = post if post_count > pre_count else pre
    for i in unlabelled:
        hits = chosen[i]
        if len(hits) == 1:
            results[i] = (hits[0], "name")
    return results


_CORRESPONDENCE_WORDING = re.compile(
    r"\bcorrespond(?:ence|ing)\b|\baddress(?:ed)?\s+correspondence\b|✉", re.IGNORECASE
)
# A mail label introduces an e-mail clause: "E-mail:", "Emails:", "E-mail of
# co-author:", "Other authors' e-mail addresses:", "Electronic mail:", "Mail:",
# "Courriel:". It needs its colon, so link text reading "Email" or names such as
# "Royal Mail Group" are not labels; an inline "(e-mail: ...)" right before the
# address (Nature style) is not a clause break.
_MAIL_WORD = r"(?:e-?mails?|electronic\s+mail|mail|courriel|correo(?:\s+electr[oó]nico)?)"
_MAIL_LABEL = re.compile(
    rf"(?<![\w\-(])(?<!\(\s){_MAIL_WORD}(?:\s+address(?:es)?|\s+of\s+[\w\-' ]{{1,30}}?)?\s*:",
    re.IGNORECASE,
)
_SOLE_EMAIL_SENTENCE = re.compile(rf"^\s*{_MAIL_WORD}(?:\s+address)?\s*:\s*$", re.IGNORECASE)
# Words ending in '.' that do not end a sentence.
_ABBREVIATIONS = frozenset(
    {
        "prof",
        "dr",
        "mr",
        "ms",
        "mrs",
        "mx",
        "st",
        "jr",
        "sr",
        "inc",
        "ltd",
        "co",
        "corp",
        "dept",
        "univ",
        "inst",
        "et",
        "al",
        "tel",
        "fax",
        "ph",
        "no",
        "vol",
        "pp",
        "eg",
        "ie",
        "etc",
        "vs",
        "ave",
        "rd",
        "blvd",
        "fig",
        "ref",
        "approx",
    }
)
_PERIOD_SPACE = re.compile(r"(\b\w{2,}|\))\.\s+(?=[A-Z0-9*(])")


def _sentence_breaks(segment: str) -> list[re.Match[str]]:
    return [
        m
        for m in _PERIOD_SPACE.finditer(segment)
        if m.group(1).lower().replace(".", "") not in _ABBREVIATIONS
    ]


def asserts_correspondence(text: str, offset: int) -> bool:
    """True when correspondence wording governs the address at ``offset``.

    The wording must precede the address within the same clause: no mail label
    and no sentence boundary in between. One exception mirrors common layouts
    ("Correspondence: A, Dept, Univ. Email: a@x"): a single following sentence
    that is just "Email:" + exactly one address. Shared lists such as
    "Corresponding author. E-mail addresses: a (A), b (B)" assert nothing.
    """
    before = text[max(0, offset - 600) : offset]
    last = None
    for match in _CORRESPONDENCE_WORDING.finditer(before):
        last = match.end()
    if last is None:
        return False
    segment = before[last:]
    boundaries = _sentence_breaks(segment)
    label = _MAIL_LABEL.search(segment)
    if not boundaries and not label:
        return True
    if len(boundaries) != 1:
        return False
    tail = segment[boundaries[0].end() :]
    if not _SOLE_EMAIL_SENTENCE.match(tail):
        return False
    # The e-mail sentence must hold exactly one address.
    later = _sentence_breaks(text[offset : offset + 400])
    stop = offset + later[0].start() if later else min(len(text), offset + 400)
    return text.count("@", offset - len(tail), stop) == 1


def owner_from_label(content: str, people: Sequence[Person]) -> int | None:
    """Owner named by a label-like text (initials, name form or exact surname)."""
    return _label_owner(content, people)
