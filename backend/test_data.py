
import pandas as pd
from pathlib import Path

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

combined["shortage"] = (
    combined["target_quantity"]
    - combined["quantity_on_hand"]
).clip(lower=0)

combined["projected_shortage"] = (
    combined["shortage"]
    - combined["approved_quantity"]
).clip(lower=0)

beans = combined[combined["food_item"] == "Canned beans"]

beans = beans.sort_values(
    by="projected_shortage",
    ascending=False
)

print("\nPantries ranked by projected canned bean shortages:")

print(beans[
    [
        "pantry_name",
        "shortage",
        "approved_quantity",
        "projected_shortage"
    ]
].to_string(index=False))

