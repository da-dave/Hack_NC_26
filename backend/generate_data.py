
import pandas as pd
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

# Convert list of dictionaries into a DataFrame
pantries_df = pd.DataFrame(pantries)

# Save to CSV
pantries_df.to_csv(data_folder / "pantries.csv", index=False)

print("Generated 10 pantries!")
print(pantries_df.head())
