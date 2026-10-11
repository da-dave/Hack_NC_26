

import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
import pandas as pd
from pydantic import BaseModel



load_dotenv(Path(__file__).parent / ".env")

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

class Donation(BaseModel):
    food_item: str
    quantity: int
    unit: str
    available_date: str




message = "I have 50 cans of beans to donate tomorrow."




response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=(
        "Extract the food item, quantity, unit, and "
        "available date from this donation message. "
        "For food_item, use the exact category 'Canned beans' "
        "when the donor mentions canned beans. "
        "Keep relative dates like 'tomorrow' as written. "
        f"Message: {message}"
    ),
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=Donation
    )
)



print("\nGemini extracted donation data:")
print(response.text)



donation = Donation.model_validate_json(response.text)

print("\nDonor wants to donate:")
print(donation.quantity, donation.unit, "of", donation.food_item)



data_folder = Path(__file__).parent / "data"

pantries = pd.read_csv(data_folder / "pantries.csv")
inventory = pd.read_csv(data_folder / "inventory.csv")
pledges = pd.read_csv(data_folder / "pledges.csv")




approved = pledges[pledges["status"] == "approved"]

approved_totals = approved.groupby(
    ["pantry_id", "food_item", "unit"],
    as_index=False
)["quantity"].sum()

approved_totals = approved_totals.rename(
    columns={"quantity": "approved_quantity"}
)




combined = pd.merge(
    inventory,
    pantries,
    on="pantry_id"
)

combined = pd.merge(
    combined,
    approved_totals,
    on=["pantry_id", "food_item", "unit"],
    how="left"
)

combined["approved_quantity"] = (
    combined["approved_quantity"].fillna(0)
)

combined["projected_shortage"] = (
    combined["target_quantity"]
    - combined["quantity_on_hand"]
    - combined["approved_quantity"]
).clip(lower=0)



matches = combined[
    (combined["food_item"].str.lower() == donation.food_item.lower())
    & (combined["unit"].str.lower() == donation.unit.lower())
    & (combined["projected_shortage"] > 0)
]

matches = matches.sort_values(
    by="projected_shortage",
    ascending=False
)

top_three = matches.head(3)


print("\nTop 3 recommended pantries:")

if top_three.empty:
    print("No matching pantries found.")
else:
    for _, pantry in top_three.iterrows():
        print(
            pantry["pantry_name"],
            "- Needs",
            int(pantry["projected_shortage"]),
            donation.unit
        )
