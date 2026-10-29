"""Classify exact retained ISO-shaped text without supplying a date or type."""

import re
from datetime import date
from typing import Literal

DatePrecision = Literal["year", "month", "day", "unrecognized"]


def retained_date_precision(raw: str) -> DatePrecision:
    """Report lexical precision only; never normalize or infer missing fields."""
    if re.fullmatch(r"[0-9]{4}", raw):
        return "year" if int(raw) > 0 else "unrecognized"
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}", raw):
        year, month = (int(part) for part in raw.split("-"))
        return "month" if year > 0 and 1 <= month <= 12 else "unrecognized"
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        try:
            date.fromisoformat(raw)
        except ValueError:
            return "unrecognized"
        return "day"
    return "unrecognized"
