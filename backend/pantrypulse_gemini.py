"""Lightweight intake checks; Gemini and pantry ranking run only after intake."""
from __future__ import annotations
import re


def offer_fields(text: str) -> dict:
    """Recognize explicit fields without guessing unstated donor information."""
    fields = {"description": re.sub(r"^DONATE\s+", "", text.strip(), flags=re.I)}
    # Food quantities must have a food unit, so address/ZIP/date digits don't count.
    quantity = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:unopened\s+|sealed\s+)?(?:cans?|boxes?|bags?|jars?|containers?|pounds?|lbs?|lb|kg)\b", text, re.I)
    if quantity:
        fields["quantity"] = float(quantity.group(1))
    address = re.search(r"(?:address\s*[:=]\s*|\bat\s+)(\d+\s+[^;\n]+)", text, re.I)
    if address:
        fields["address"] = address.group(1).strip()
    zip_code = re.search(r"(?<!\d)(\d{5})(?!\d)", text)
    if zip_code:
        fields["zip"] = zip_code.group(1)
    window = re.search(r"\b(\d{4}-\d{2}-\d{2})\s+((?:[01]\d|2[0-3]):[0-5]\d)-((?:[01]\d|2[0-3]):[0-5]\d)\b", text)
    if window:
        fields.update(start=f"{window[1]}T{window[2]}", end=f"{window[1]}T{window[3]}")
    if re.search(r"\b(?:unopened|sealed)\b", text, re.I) and not re.search(r"\b(?:not|opened|unsealed)\b", text, re.I):
        fields["packaging"] = "unopened"
    return fields
