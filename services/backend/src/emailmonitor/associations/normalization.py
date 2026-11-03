"""Conservative syntax/domain normalization; no network/mailbox validation."""

import hashlib
import re
from typing import Literal

import idna
from pydantic import BaseModel, ConfigDict, Field

ATOM = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")


class Address(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    raw_address: str = Field(min_length=1, max_length=320)
    normalized_address: str | None
    comparison_key: str = Field(min_length=1, max_length=384)
    syntax_status: Literal["valid", "invalid", "unsupported"]
    reason: Literal["ascii_dot_atom_idna", "malformed", "smtp_utf8", "quoted_or_literal"]
    domain_status: Literal["not_checked"] = "not_checked"
    delivery_status: Literal["unverified"] = "unverified"
    outreach_eligibility: Literal["not_assessed"] = "not_assessed"


def normalize(raw: str) -> Address:
    if type(raw) is not str or not 1 <= len(raw) <= 320:
        raise ValueError("Bounded observed address required")
    fallback = "raw:" + hashlib.sha256(raw.encode(errors="surrogatepass")).hexdigest()

    def refusal(status: Literal["invalid", "unsupported"], reason: str) -> Address:
        return Address.model_validate(
            {
                "raw_address": raw,
                "normalized_address": None,
                "comparison_key": fallback,
                "syntax_status": status,
                "reason": reason,
            }
        )

    if raw.count("@") != 1 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in raw):
        return refusal("invalid", "malformed")
    local, domain = raw.split("@")
    if (
        not local
        or not domain
        or len(local.encode(errors="surrogatepass")) > 64
        or domain.endswith(".")
    ):
        return refusal("invalid", "malformed")
    if any(ord(c) > 127 for c in local):
        return refusal("unsupported", "smtp_utf8")
    if local.startswith('"') or domain.startswith("["):
        return refusal("unsupported", "quoted_or_literal")
    if ATOM.fullmatch(local) is None:
        return refusal("invalid", "malformed")
    try:
        ascii_domain = idna.encode(domain, uts46=True, transitional=False, std3_rules=True).decode()
    except idna.IDNAError:
        return refusal("invalid", "malformed")
    if "." not in ascii_domain or len(ascii_domain) > 253:
        return refusal("invalid", "malformed")
    normalized = local + "@" + ascii_domain.lower()
    if len(normalized.encode()) > 254:
        return refusal("invalid", "malformed")
    return Address(
        raw_address=raw,
        normalized_address=normalized,
        comparison_key=normalized,
        syntax_status="valid",
        reason="ascii_dot_atom_idna",
    )
