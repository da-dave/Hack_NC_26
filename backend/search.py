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


# ----------------------------
# Gemini output structure
# ----------------------------

class DonationItem(BaseModel):
    food_item: str = Field(
        description="The donated food item, normalized to match inventory names."
    )
    quantity: float = Field(
        description="The amount of food being donated."
    )
    unit: Optional[str] = Field(
        default=None,
        description="Unit such as cans, pounds, boxes, bags, jars, etc."
    )


# ----------------------------
# Gemini parsing
# ----------------------------

def gemini_parse(message: str) -> DonationItem:
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

    return DonationItem.model_validate_json(response.text)


# Algo. to find the best pantry

def find_best_pantry(food_item: str):
    pantries = pd.read_csv(PANTRIES_CSV)
    inventory = pd.read_csv(INVENTORY_CSV)

    # Find pantries that track this food item
    matches = inventory[
        inventory["food_item"].str.lower() == food_item.lower()
    ].copy()

    if matches.empty:
        return None

    # Need = desired inventory - current inventory
    matches["need"] = (
        matches["target_quantity"] - matches["quantity_on_hand"]
    )

    # Only keep pantries that actually need more
    matches = matches[matches["need"] > 0]

    if matches.empty:
        return None

    # Pantry with the largest shortage
    best_match = matches.loc[matches["need"].idxmax()]

    # Retrieve pantry contact info
    pantry = pantries[
        pantries["pantry_id"] == best_match["pantry_id"]
    ].iloc[0]

    return {
        "pantry_id": int(pantry["pantry_id"]),
        "pantry_name": pantry["pantry_name"],
        "address": pantry["address"],
        "phone": pantry["contact_phone"],
        "food_item": best_match["food_item"],
        "need": float(best_match["need"]),
        "unit": best_match["unit"],
    }


# Main search function

def search(message: str):
    donation = gemini_parse(message)

    pantry = find_best_pantry(donation.food_item)

    if pantry is None:
        return {
            "match": None,
            "message": (
                f"No pantry currently needs {donation.food_item}."
            ),
        }

    return {
        "donation": donation.model_dump(),
        "match": pantry,
        "message": (
            f"Best match: {pantry['pantry_name']}\n"
            f"Address: {pantry['address']}\n"
            f"Phone: {pantry['phone']}\n"
            f"They currently need {pantry['need']} {pantry['unit']} "
            f"of {pantry['food_item']}."
        ),
    }


# ----------------------------
# Local testing
# ----------------------------

if __name__ == "__main__":
    donor_message = input("Donor message: ").strip()

    result = search(donor_message)

    print("\n--- Result ---")
    print(result["message"])

    print("\n--- Full data ---")
    print(result)