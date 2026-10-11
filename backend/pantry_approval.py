
import pandas as pd
from pathlib import Path

data_folder = Path(__file__).parent / "data"
pledges_file = data_folder / "pledges.csv"


def handle_pantry_reply(pantry_id, pledge_id, reply):

    pledges = pd.read_csv(pledges_file)

    match = (
        (pledges["pantry_id"] == pantry_id)
        & (pledges["pledge_id"] == pledge_id)
        & (pledges["status"] == "pending")
    )

    if not match.any():
        return "No matching pending pledge found."

    reply = reply.strip().upper()

    if reply == "YES":
        new_status = "approved"

    elif reply == "NO":
        new_status = "rejected"

    else:
        return "Please reply YES or NO."

    pledges.loc[match, "status"] = new_status

    pledges.to_csv(pledges_file, index=False)

    return f"Pledge {pledge_id} has been {new_status}."
