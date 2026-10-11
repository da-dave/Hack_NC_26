"""
search.py

HackNC food donation matching prototype.

Flow:
1. Receive donor's natural-language message.
2. Gemini parses it into structured donation items.
3. Pandas loads pantries.csv + inventory.csv.
4. Deterministic matching ranks pantries by unmet need.
5. Return a Photon-ready donor message plus structured results.

Install:
    pip install pandas google-genai pydantic

Environment:
    export GEMINI_API_KEY="your_key_here"

Expected files:
    data/pantries.csv
    data/inventory.csv
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

import pandas as pd
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent / "data"
PANTRIES_CSV = DATA_DIR / "pantries.csv"
INVENTORY_CSV = DATA_DIR / "inventory.csv"

# Change this if your Gemini account exposes a different model.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


# ---------------------------------------------------------------------------
# Gemini structured output models
# ---------------------------------------------------------------------------

class DonationItem(BaseModel):
    food_item: str = Field(
        description=(
            "Canonical food name. Prefer one of: Canned beans, Rice, Pasta, "
            "Peanut butter, Canned vegetables, Canned fruit, Oatmeal, "
            "Canned tuna, Shelf-stable milk, Cereal."
        )
    )
    quantity: float = Field(description="Amount the donor is offering.")
    unit: Optional[str] = Field(
        default=None,
        description="Unit such as cans, bags, boxes, jars, cartons, containers."
    )


class ParsedDonation(BaseModel):
    items: List[DonationItem]
    donor_location: Optional[str] = Field(
        default=None,
        description="Location/address mentioned by donor, if any."
    )
    availability: Optional[str] = Field(
        default=None,
        description="Delivery date or time window mentioned by donor, if any."
    )


# ---------------------------------------------------------------------------
# Gemini parsing
# ---------------------------------------------------------------------------

def parse_donor_message(message: str) -> ParsedDonation:
    """
    Convert donor English into structured food donation data.

    Gemini ONLY parses the donor message. It does not decide which pantry wins.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Set it before running search.py."
        )

    client = genai.Client(api_key=api_key)

    prompt = f"""
You are parsing a food donation message for a food-pantry matching system.

Extract:
- every donated food item
- quantity
- unit if stated
- donor location if stated
- donor availability / delivery window if stated

Important rules:
- Normalize common wording to these inventory names whenever appropriate:
  Canned beans
  Rice
  Pasta
  Peanut butter
  Canned vegetables
  Canned fruit
  Oatmealu
  Canned tuna
  Shelf-stable milk
  Cereal
- Do not invent quantities.
- If a quantity is unclear, use 1 only if the donor clearly refers to one item/package.
- Do not choose a pantry.
- Return only structured data matching the schema.

Donor message:
{message}
""".strip()

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ParsedDonation,
            temperature=0,
        ),
    )

    return ParsedDonation.model_validate_json(response.text)


# ---------------------------------------------------------------------------
# Food-name normalization
# ---------------------------------------------------------------------------

def normalize_food_name(name: str) -> str:
    """
    Small safety net after Gemini parsing so common synonyms still match CSV data.
    """
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", name.lower()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    aliases = {
        "beans": "Canned beans",
        "bean": "Canned beans",
        "canned bean": "Canned beans",
        "canned beans": "Canned beans",

        "rice": "Rice",

        "pasta": "Pasta",
        "noodles": "Pasta",

        "peanut butter": "Peanut butter",

        "vegetables": "Canned vegetables",
        "veggies": "Canned vegetables",
        "canned vegetables": "Canned vegetables",

        "fruit": "Canned fruit",
        "canned fruit": "Canned fruit",

        "oatmeal": "Oatmeal",
        "oats": "Oatmeal",

        "tuna": "Canned tuna",
        "canned tuna": "Canned tuna",

        "milk": "Shelf-stable milk",
        "shelf stable milk": "Shelf-stable milk",

        "cereal": "Cereal",
    }

    return aliases.get(cleaned, name.strip())


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not PANTRIES_CSV.exists():
        raise FileNotFoundError(f"Missing {PANTRIES_CSV}")

    if not INVENTORY_CSV.exists():
        raise FileNotFoundError(f"Missing {INVENTORY_CSV}")

    pantries = pd.read_csv(PANTRIES_CSV)
    inventory = pd.read_csv(INVENTORY_CSV)

    required_pantry_cols = {
        "pantry_id",
        "pantry_name",
        "address",
        "contact_phone",
    }

    required_inventory_cols = {
        "pantry_id",
        "food_item",
        "quantity_on_hand",
        "target_quantity",
        "unit",
    }

    missing_pantries = required_pantry_cols - set(pantries.columns)
    missing_inventory = required_inventory_cols - set(inventory.columns)

    if missing_pantries:
        raise ValueError(
            f"pantries.csv is missing columns: {sorted(missing_pantries)}"
        )

    if missing_inventory:
        raise ValueError(
            f"inventory.csv is missing columns: {sorted(missing_inventory)}"
        )

    return pantries, inventory


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def calculate_need(row: pd.Series) -> float:
    """
    Current shortage at a pantry.

    Example:
        target = 300 cans
        on hand = 100 cans
        need = 200 cans
    """
    return max(float(row["target_quantity"]) - float(row["quantity_on_hand"]), 0.0)


def score_candidate(need: float, donation_quantity: float) -> float:
    """
    Rank based primarily on how badly the pantry needs this item.

    The score rewards:
    - larger absolute shortage
    - a donation that meaningfully fills that shortage

    This stays deterministic and explainable for a hackathon demo.
    """
    if need <= 0:
        return 0.0

    useful_amount = min(need, donation_quantity)
    coverage = useful_amount / need

    return need + (coverage * 100.0)


def rank_pantries_for_item(
    item: DonationItem,
    pantries: pd.DataFrame,
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    """
    Return pantry candidates for ONE donated item, sorted by highest need.
    """
    canonical_name = normalize_food_name(item.food_item)

    matches = inventory[
        inventory["food_item"].str.lower() == canonical_name.lower()
    ].copy()

    if matches.empty:
        return pd.DataFrame()

    matches["need"] = matches.apply(calculate_need, axis=1)

    # Only recommend places that are actually below target.
    matches = matches[matches["need"] > 0].copy()

    if matches.empty:
        return pd.DataFrame()

    matches["donation_quantity"] = float(item.quantity)
    matches["amount_useful"] = matches["need"].clip(
        upper=float(item.quantity)
    )

    matches["score"] = matches.apply(
        lambda row: score_candidate(
            row["need"],
            float(item.quantity),
        ),
        axis=1,
    )

    matches = matches.merge(
        pantries,
        on="pantry_id",
        how="left",
    )

    matches["requested_food_item"] = canonical_name

    return matches.sort_values(
        ["score", "need"],
        ascending=False,
    )


def find_best_plan(parsed: ParsedDonation) -> dict:
    """
    Build the recommended donation plan.

    Strategy:
    1. Check whether one pantry can use ALL donated item types.
    2. If yes, prefer a single pantry.
    3. If no pantry needs everything, split the donation by item:
       choose the strongest candidate for each food item.

    The result can contain multiple recipient pantries.
    """
    pantries, inventory = load_data()

    ranked_by_item: dict[str, pd.DataFrame] = {}

    for item in parsed.items:
        canonical = normalize_food_name(item.food_item)
        ranked_by_item[canonical] = rank_pantries_for_item(
            item,
            pantries,
            inventory,
        )

    # Remove items for which no pantry currently has a shortage.
    ranked_by_item = {
        name: df
        for name, df in ranked_by_item.items()
        if not df.empty
    }

    if not ranked_by_item:
        return {
            "strategy": "no_match",
            "parsed_donation": parsed.model_dump(),
            "recommendations": [],
        }

    # -----------------------------------------------------------------------
    # First preference: ONE pantry that needs every donated item type.
    # -----------------------------------------------------------------------

    pantry_sets = [
        set(df["pantry_id"].tolist())
        for df in ranked_by_item.values()
    ]

    common_pantries = set.intersection(*pantry_sets) if pantry_sets else set()

    if common_pantries:
        single_pantry_options = []

        for pantry_id in common_pantries:
            total_score = 0.0
            covered_items = []

            for food_name, df in ranked_by_item.items():
                row = df[df["pantry_id"] == pantry_id].iloc[0]

                total_score += float(row["score"])

                covered_items.append({
                    "food_item": food_name,
                    "donation_quantity": float(row["donation_quantity"]),
                    "pantry_need": float(row["need"]),
                    "amount_useful": float(row["amount_useful"]),
                    "unit": row["unit"],
                })

            pantry_row = pantries[
                pantries["pantry_id"] == pantry_id
            ].iloc[0]

            single_pantry_options.append({
                "pantry_id": int(pantry_id),
                "pantry_name": pantry_row["pantry_name"],
                "address": pantry_row["address"],
                "contact_phone": pantry_row["contact_phone"],
                "score": total_score,
                "items": covered_items,
            })

        single_pantry_options.sort(
            key=lambda x: x["score"],
            reverse=True,
        )

        return {
            "strategy": "single_pantry",
            "parsed_donation": parsed.model_dump(),
            "recommendations": single_pantry_options,
        }

    # -----------------------------------------------------------------------
    # Fallback: no pantry needs every item.
    # Choose the strongest pantry separately for each donated item.
    # -----------------------------------------------------------------------

    split_recommendations = []

    for item in parsed.items:
        canonical = normalize_food_name(item.food_item)
        candidates = ranked_by_item.get(canonical)

        if candidates is None or candidates.empty:
            split_recommendations.append({
                "food_item": canonical,
                "status": "no_match",
            })
            continue

        best = candidates.iloc[0]

        split_recommendations.append({
            "food_item": canonical,
            "status": "matched",
            "donation_quantity": float(item.quantity),
            "unit": best["unit"],
            "pantry_id": int(best["pantry_id"]),
            "pantry_name": best["pantry_name"],
            "address": best["address"],
            "contact_phone": best["contact_phone"],
            "pantry_need": float(best["need"]),
            "amount_useful": float(best["amount_useful"]),
            "score": float(best["score"]),
        })

    return {
        "strategy": "split",
        "parsed_donation": parsed.model_dump(),
        "recommendations": split_recommendations,
    }


# ---------------------------------------------------------------------------
# Photon-ready message formatting
# ---------------------------------------------------------------------------

def format_for_photon(plan: dict) -> str:
    """
    Turn the matching result into the text your Photon layer can send to donor.
    """

    strategy = plan["strategy"]

    if strategy == "no_match":
        return (
            "I couldn't find a pantry in our current database that is "
            "below its target inventory for those items."
        )

    if strategy == "single_pantry":
        best = plan["recommendations"][0]

        item_lines = []
        for item in best["items"]:
            qty = pretty_number(item["donation_quantity"])
            need = pretty_number(item["pantry_need"])
            item_lines.append(
                f"- {qty} {item['unit']} of {item['food_item']} "
                f"(pantry shortage: {need} {item['unit']})"
            )

        items_text = "\n".join(item_lines)

        return (
            f"Best match: {best['pantry_name']}\n"
            f"{best['address']}\n\n"
            f"They currently need all of the donated item types:\n"
            f"{items_text}\n\n"
            f"Reply PROCEED if you'd like me to contact this pantry."
        )

    if strategy == "split":
        matched = [
            r for r in plan["recommendations"]
            if r.get("status") == "matched"
        ]

        unmatched = [
            r for r in plan["recommendations"]
            if r.get("status") != "matched"
        ]

        lines = [
            "No single pantry currently needs every donated item, "
            "so the best match is to split the donation:"
        ]

        for index, rec in enumerate(matched, start=1):
            qty = pretty_number(rec["donation_quantity"])
            need = pretty_number(rec["pantry_need"])

            lines.append(
                f"{index}. {rec['food_item']}: {rec['pantry_name']} "
                f"({rec['address']}) needs about {need} {rec['unit']}. "
                f"Your donation is {qty} {rec['unit']}."
            )

        if unmatched:
            names = ", ".join(r["food_item"] for r in unmatched)
            lines.append(
                f"I couldn't find a current match for: {names}."
            )

        unique_pantries = {
            r["pantry_id"]
            for r in matched
        }

        if len(unique_pantries) > 1:
            lines.append(
                "These items would go to different pantries. "
                "Reply PROCEED to contact the recommended pantries."
            )
        else:
            lines.append(
                "Reply PROCEED to contact the recommended pantry."
            )

        return "\n\n".join(lines)

    return "I couldn't create a recommendation."


def pretty_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


# ---------------------------------------------------------------------------
# Main function for the rest of your app
# ---------------------------------------------------------------------------

def search(donor_prompt: str) -> dict:
    """
    Main entry point.

    Your Photon webhook can call:

        result = search(incoming_message)

    Then send:

        result["photon_message"]

    back to the donor.
    """
    parsed = parse_donor_message(donor_prompt)
    plan = find_best_plan(parsed)

    return {
        **plan,
        "photon_message": format_for_photon(plan),
    }


# ---------------------------------------------------------------------------
# Local testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    donor_prompt = input("Donor message: ").strip()

    result = search(donor_prompt)

    print("\n--- Photon reply ---")
    print(result["photon_message"])

    print("\n--- Structured result ---")
    print(result)
