
import pandas as pd
import random
from pathlib import Path

# Location where CSV files will be saved
data_folder = Path(__file__).parent / "data"
data_folder.mkdir(exist_ok=True)

# Empty list to store our pantry records
pantries = []

# Generate 10 fictional pantries
for i in range(1, 11):
    pantry = {
        "pantry_id": i,
        "pantry_name": f"Demo Pantry {i}",
        "address": f"{100 + i} Example St, Chapel Hill, NC",
        "contact_phone": f"919-555-{1000 + i}"
    }

    pantries.append(pantry)

#list of dictionaries into a DataFrame
pantries_df = pd.DataFrame(pantries)

# make csv
pantries_df.to_csv(data_folder / "pantries.csv", index=False)

print("Generated 10 pantries!")
print(pantries_df.head())

##

donors = []

for i in range(1, 31):
    donor = {
        "donor_id": i,
        "donor_name": f"Demo Donor {i}",
        "address": f"{200 + i} Sample Rd, Chapel Hill, NC",
        "phone_number": f"919-555-{2000 + i}"
    }

    donors.append(donor)

donors_df = pd.DataFrame(donors)

donors_df.to_csv(
    data_folder / "donors.csv",
    index=False
)

print("Generated 30 donors!")
print(donors_df.head())

random.seed(42)

food_items = [
    ("Canned beans", "cans"),
    ("Rice", "bags"),
    ("Pasta", "boxes"),
    ("Peanut butter", "jars"),
    ("Canned vegetables", "cans"),
    ("Canned fruit", "cans"),
    ("Oatmeal", "containers"),
    ("Canned tuna", "cans"),
    ("Shelf-stable milk", "cartons"),
    ("Cereal", "boxes")
]

inventory = []
inventory_id = 1

for pantry_id in range(1, 11):

    for food_name, unit in food_items:

        record = {
            "inventory_id": inventory_id,
            "pantry_id": pantry_id,
            "food_item": food_name,
            "quantity_on_hand": random.randint(10, 200),
            "target_quantity": random.randint(200, 400),
            "unit": unit,
            "last_updated": "2026-10-10"
        }

        inventory.append(record)
        inventory_id += 1

inventory_df = pd.DataFrame(inventory)

inventory_df.to_csv(
    data_folder / "inventory.csv",
    index=False
)

print("Generated 100 inventory records")
print(inventory_df.head())



print("\nDataset sizes:")
print("Pantries:", pantries_df.shape)
print("Donors:", donors_df.shape)
print("Inventory:", inventory_df.shape)



pledges = []

statuses = ["pending", "approved", "rejected", "delivered"]

random.seed(100)

for i in range(1, 31):
    food_name, unit = random.choice(food_items)

    pledge = {
        "pledge_id": i,
        "donor_id": i,
        "pantry_id": random.randint(1, 10),
        "food_item": food_name,
        "quantity": random.randint(10, 100),
        "unit": unit,
        "available_date": random.choice([
            "2026-10-10",
            "2026-10-11",
            "2026-10-12"
        ]),
        "status": random.choice(statuses)
    }

    pledges.append(pledge)

pledges_df = pd.DataFrame(pledges)

pledges_df.to_csv(
    data_folder / "pledges.csv",
    index=False
)

print("Generated 30 donation pledges")
print(pledges_df.head())

