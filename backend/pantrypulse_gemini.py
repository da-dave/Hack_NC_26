"""Connect search.py donor parsing and recommendations to guided handoff intake."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedIntake:
    items: list[dict]
    zip_code: str = ""
    window: str = ""
    packaging_verified: bool = False


_COMMAND = re.compile(
    r"^(?:JOIN\s+(?:DONOR|PANTRY)|DONATE$|HELP$|STATUS(?:\s+(?:PANTRY|DONATIONS))?$|"
    r"INVENTORY$|CANCEL(?:\s+.*)?$|EDIT(?:\s+.*)?$|"
    r"ACCEPT\s+.*$|PASS\s+.*$|RECEIVED\s+.*$)$", re.I
)
_DATE_WINDOW = re.compile(r"\b\d{4}-\d{2}-\d{2}\s+(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d\b")
_ZIP = re.compile(r"(?<!\d)(\d{5})(?!\d)")


def should_interpret(app, handle: str, text: str) -> bool:
    p = app.lookup("participants", handle=handle)
    if not p or p.get("role") not in ("donor", "pantry"):
        return False
    if p.get("step") and p["step"] != "donation_item":
        return False
    msg = text.strip()
    if not msg or _COMMAND.fullmatch(msg):
        return False
    # Don't spend model calls on ordinary conversation or stray YES/NO replies.
    return bool(re.search(r"\d", msg) and re.search(
        r"\b(?:donat\w*|have|offer\w*|give|got|beans?|cans?|rice|pasta|"
        r"noodles|peanut butter|cereal|oatmeal|tuna|milk|fruit|vegetables)\b",
        msg, re.I))


def parse_donation(text: str) -> ParsedIntake:
    from search import search
    result = search(text)
    x = result["donation"]
    items = [{"item": x["food_item"], "quantity": x["quantity"],
              "unit": x.get("unit") or "", "recommendations": result["matches"]}]
    zip_match = _ZIP.search(text)
    window_match = _DATE_WINDOW.search(text)
    return ParsedIntake(
        items=items,
        zip_code=zip_match.group(1) if zip_match else "",
        window=window_match.group(0) if window_match else "",
        packaging_verified=bool(re.search(r"\b(?:unopened|sealed)\b", text, re.I)),
    )
