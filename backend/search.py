from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


load_dotenv()

DATA_DIR = Path(__file__).parent / "data"
PANTRIES_CSV = DATA_DIR / "pantries.csv"
INVENTORY_CSV = DATA_DIR / "inventory.csv"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"


class DonationItem(BaseModel):
    """Structured representation of one donated food item."""

    food_item: str = Field(
        description="The donated food item, normalized to match inventory names."
    )
    quantity: Optional[float] = Field(default=None, description="The stated amount; null when missing.")
    unit: Optional[str] = Field(
        default=None,
        description="Unit such as cans, pounds, boxes, bags, jars, etc."
    )


def gemini_parse(message: str) -> DonationItem:
    """Parse one donor message into one structured donation item."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
Parse this food donation message.

There will only be ONE donated food item.

Extract:
- food_item
- quantity
- unit, if stated
If quantity is missing return null. Never treat a ZIP code, address number, or date as food quantity.

Normalize the food name so it can match the inventory database.

Examples:

"210 canned beans"
food_item = "Canned beans"
quantity = 210
unit = "cans"

"15lb of potatoes"
food_item = "Potatoes"
quantity = 15
unit = "lb"

"8 boxes of cereal"
food_item = "Cereal"
quantity = 8
unit = "boxes"

Correct obvious spelling mistakes.
Do not invent information.

Message:
{message}
""".strip()

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DonationItem,
            temperature=0,
        ),
    )

    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")

    return DonationItem.model_validate_json(response.text)


def find_best_pantries(food_item: str, data_dir: Path | None = None,
                       eligible_ids: list[str] | None = None,
                       committed: list[dict] | None = None) -> list[dict]:
    """Rank reachable pantries by remaining need; preserve this order for backups.

    Accepted offers reduce projected need, without changing stock on hand.
    Pantry acceptance is the final decision, including for no-shortage backups.
    """
    pantries = pd.read_csv(data_dir / "pantries.csv" if data_dir else PANTRIES_CSV,
                          dtype=str, keep_default_na=False)
    inventory = pd.read_csv(data_dir / "inventory.csv" if data_dir else INVENTORY_CSV,
                           dtype=str, keep_default_na=False)
    if eligible_ids is not None:
        pantries = pantries[pantries["pantry_id"].isin(eligible_ids)]
    results = []
    for _, pantry in pantries.iterrows():
        rows = inventory[(inventory["pantry_id"] == pantry["pantry_id"]) &
                         (inventory["food_item"].str.casefold() == food_item.strip().casefold())]
        need, unit = 0.0, None
        if not rows.empty:
            row = rows.iloc[0]
            unit = row["unit"]
            need = float(row["target_quantity"]) - float(row["quantity_on_hand"])
            for donation in committed or []:
                if (str(donation["pantry_id"]) == pantry["pantry_id"]
                        and donation["item"].casefold() == food_item.casefold()
                        and donation["unit"].casefold() == (unit or "").casefold()
                        and donation["status"] in ("reserved", "completed")):
                    need -= float(donation["quantity"])
            need = max(need, 0)
        results.append({"pantry_id": int(pantry["pantry_id"]),
                        "pantry_name": pantry["pantry_name"], "address": pantry["address"],
                        "phone": pantry["contact_phone"], "food_item": food_item,
                        "need": need, "unit": unit or "",
                        "reason": "needed" if need > 0 else "fallback"})
    results.sort(key=lambda pantry: (-pantry["need"], pantry["pantry_id"]))
    return results[:3]


def pretty_number(value: float | None) -> str:
    """Display whole numbers without a trailing .0."""
    if value is None:
        return ""

    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def format_message(donation: DonationItem, pantries: list[dict]) -> str:
    """Create the donor-facing Photon message."""
    if not pantries:
        return "No pantries are currently available."

    lines = [f"Donation: {pretty_number(donation.quantity)} {donation.unit or ''} {donation.food_item}"]
    if pantries[0]["reason"] != "needed":
        lines.append(f"No pantry currently lists a need for {donation.food_item}.")
    for index, pantry in enumerate(pantries, start=1):
        lines += ["", f"Option {index}: {pantry['pantry_name']}",
                  f"Address: {pantry['address']}", f"Phone: {pantry['phone']}"]
        if pantry.get("need") is not None:
            lines.append(f"Current need: {pretty_number(pantry['need'])} {pantry['unit']}")
    lines += ["", "Reply PROCEED <option number> to choose a pantry (e.g. PROCEED 1)."]
    return "\n".join(lines)


def search(message: str, data_dir: Path | None = None,
           eligible_ids: list[str] | None = None, committed: list[dict] | None = None) -> dict:
    """Main entry point for the Photon webhook."""
    donation = gemini_parse(message)
    pantries = find_best_pantries(donation.food_item, data_dir, eligible_ids, committed)

    return {
        "donation": donation.model_dump(),
        "matches": pantries,
        "message": format_message(donation, pantries),
    }


if __name__ == "__main__":
    donor_message = input("Donor message: ").strip()
    result = search(donor_message)

    print("\n--- Photon reply ---")
    print(result["message"])

    print("\n--- Full data ---")
    print(result)