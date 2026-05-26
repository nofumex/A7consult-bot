from __future__ import annotations

import re


PHONE_ALLOWED_RE = re.compile(r"^[+\d\s\-()]+$")


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not PHONE_ALLOWED_RE.match(value):
        return None

    has_plus = value.startswith("+")
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10:
        return None
    return f"+{digits}" if has_plus else digits


def clean_text(raw: str | None, max_len: int = 4000) -> str:
    value = (raw or "").strip()
    return value[:max_len]


def parse_positive_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    value = int(digits)
    return value if value > 0 else None
