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
    quantity: float = Field(description="The amount of food being donated.")
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


def find_best_pantries(food_item: str) -> list[dict]:
    """
    Return up to 3 pantry options.

    If pantries need the item:
    - option 1 = largest shortage
    - options 2 and 3 = next-largest shortages

    If nobody needs the item:
    - return up to 3 random pantries
    """
    pantries = pd.read_csv(PANTRIES_CSV)
    inventory = pd.read_csv(INVENTORY_CSV)

    matches = inventory[
        inventory["food_item"].astype(str).str.strip().str.lower()
        == food_item.strip().lower()
    ].copy()

    if not matches.empty:
        matches["need"] = (
            matches["target_quantity"] - matches["quantity_on_hand"]
        )

        matches = matches[matches["need"] > 0].copy()

    if not matches.empty:
        matches = matches.sort_values(by="need", ascending=False).head(3)

        results = []

        for _, match in matches.iterrows():
            pantry_rows = pantries[
                pantries["pantry_id"] == match["pantry_id"]
            ]

            if pantry_rows.empty:
                continue

            pantry = pantry_rows.iloc[0]

            results.append(
                {
                    "pantry_id": int(pantry["pantry_id"]),
                    "pantry_name": pantry["pantry_name"],
                    "address": pantry["address"],
                    "phone": pantry["contact_phone"],
                    "food_item": match["food_item"],
                    "need": float(match["need"]),
                    "unit": match["unit"],
                    "reason": "needed",
                }
            )

        return results

    if pantries.empty:
        return []

    random_pantries = pantries.sample(n=min(3, len(pantries)))

    return [
        {
            "pantry_id": int(pantry["pantry_id"]),
            "pantry_name": pantry["pantry_name"],
            "address": pantry["address"],
            "phone": pantry["contact_phone"],
            "food_item": food_item,
            "need": None,
            "unit": None,
            "reason": "random_fallback",
        }
        for _, pantry in random_pantries.iterrows()
    ]


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

    if pantries[0]["reason"] == "needed":
        best = pantries[0]

        lines = [
            "Best option:",
            best["pantry_name"],
            f"Address: {best['address']}",
            f"Phone: {best['phone']}",
            f"Current need: {pretty_number(best['need'])} {best['unit']}",
        ]

        if len(pantries) > 1:
            lines += ["", "Backup options:"]

            for index, pantry in enumerate(pantries[1:], start=1):
                lines += [
                    "",
                    f"Backup {index}:",
                    pantry["pantry_name"],
                    f"Address: {pantry['address']}",
                    f"Phone: {pantry['phone']}",
                    f"Current need: {pretty_number(pantry['need'])} {pantry['unit']}",
                ]

        lines += [
            "",
            "Reply PROCEED if you'd like me to contact the best option.",
        ]

        return "\n".join(lines)

    lines = [
        f"No pantry currently lists a need for {donation.food_item}.",
        "",
        "Here are 3 pantries you could try contacting:",
    ]

    for index, pantry in enumerate(pantries, start=1):
        lines += [
            "",
            f"Option {index}:",
            pantry["pantry_name"],
            f"Address: {pantry['address']}",
            f"Phone: {pantry['phone']}",
        ]

    lines += [
        "",
        "Reply PROCEED if you'd like me to contact the first option.",
    ]

    return "\n".join(lines)


def search(message: str) -> dict:
    """Main entry point for the Photon webhook."""
    donation = gemini_parse(message)
    pantries = find_best_pantries(donation.food_item)

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