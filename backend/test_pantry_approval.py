
import pandas as pd
import tempfile
from pathlib import Path
from unittest.mock import patch

import pantry_approval

with tempfile.TemporaryDirectory() as folder:
    test_file = Path(folder) / "pledges.csv"

    test_pledges = pd.DataFrame([
        {
            "pledge_id": 1,
            "pantry_id": 3,
            "food_item": "Canned beans",
            "status": "pending"
        },
        {
            "pledge_id": 2,
            "pantry_id": 5,
            "food_item": "Rice",
            "status": "pending"
        }
    ])

    test_pledges.to_csv(test_file, index=False)

    with patch.object(pantry_approval, "pledges_file", test_file):

        result = pantry_approval.handle_pantry_reply(3, 1, "NO")
        print(result)

        updated = pd.read_csv(test_file)
        print("\nUpdated pledges:")
        print(updated)
