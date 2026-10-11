import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pantrypulse_engine import PantryPulse

TZ = ZoneInfo("America/New_York")


class MVPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        pd.DataFrame([{"pantry_id": "1", "pantry_name": "Demo Pantry 1", "address": "1 Example St", "contact_phone": "555-0001"},
                      {"pantry_id": "2", "pantry_name": "Demo Pantry 2", "address": "2 Example St", "contact_phone": "555-0002"}]).to_csv(self.path / "pantries.csv", index=False)
        pd.DataFrame([{"pantry_id": "1", "food_item": "Canned beans", "quantity_on_hand": 80, "target_quantity": 120, "unit": "cans"},
                      {"pantry_id": "2", "food_item": "Canned beans", "quantity_on_hand": 10, "target_quantity": 120, "unit": "cans"}]).to_csv(self.path / "inventory.csv", index=False)
        self.app = PantryPulse(self.path)
        self.seq = 0

    def tearDown(self):
        self.temp.cleanup()

    def send(self, who, msg):
        self.seq += 1
        self.app.on_message(handle=who, space_id=f"space-{who}", message_id=f"m-{self.seq}", text=msg)

    def register_pantry(self, who):
        self.send(who, "JOIN PANTRY")
        for s in ("TEST PANTRY", "101 Fictional St", "27514", "DAILY 00:00-23:59"):
            self.send(who, s)

    def create(self):
        self.send("donor", "JOIN DONOR")
        self.send("donor", "DONATE")
        self.send("donor", "beans")
        self.send("donor", "24")
        self.send("donor", "27514")
        future = (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
        self.send("donor", future + " 12:00-15:00")
        self.send("donor", "YES")
        d = self.app.tables["donations"][-1]
        self.assertEqual(d["status"], "awaiting_choice")
        self.assertEqual(len(self.app.tables["offers"]), 0)
        # Choose the highest-ranked registered pantry.
        import json
        options = json.loads(d["recommendations"])
        option = next(i for i, row in enumerate(options, 1)
                      if self.app.lookup("participants", role="pantry", pantry_id=str(row["pantry_id"])))
        self.send("donor", f"PROCEED {option}")
        return d

    def test_pantry_registration_roles(self):
        self.register_pantry("a")
        self.register_pantry("b")
        self.assertEqual(self.app.lookup("participants", handle="a")["pantry_id"], "1")
        self.assertEqual(self.app.lookup("participants", handle="b")["pantry_id"], "2")
        self.assertEqual(self.app.lookup("participants", handle="a")["role"], "pantry")
        self.register_pantry("c")
        self.assertEqual(self.app.lookup("participants", handle="c")["pantry_id"], "")

    def test_donation_decline_accept_receipt_and_status(self):
        self.register_pantry("a")
        self.register_pantry("b")
        d = self.create()
        self.assertEqual(d["status"], "offered")
        self.assertEqual(self.app.tables["offers"][0]["pantry_id"], "2") # bigger shortage first
        self.send("a", f"ACCEPT {d['id']}")
        self.assertEqual(d["status"], "offered") # wrong pantry blocked
        self.send("b", f"PASS {d['id']}")
        self.assertEqual(self.app.tables["offers"][-1]["pantry_id"], "1")
        self.send("a", f"ACCEPT {d['id']}")
        self.assertEqual(d["status"], "reserved")
        self.assertEqual(d["pantry_id"], "1")
        self.assertEqual(self.app.need("1", "Canned beans"), 16)
        self.send("a", f"RECEIVED {d['id']}")
        self.assertEqual(d["status"], "completed")
        self.send("donor", "STATUS DONATIONS")
        self.assertTrue(any(d['id'] in x['text'] and x['recipient'] == 'donor' for x in self.app.tables['outbox']))

    def test_donor_can_choose_backup_and_choice_survives_reload(self):
        self.register_pantry("a")
        self.register_pantry("b")
        self.create()
        first = self.app.tables["donations"][-1]
        self.send("donor", "CANCEL " + first["id"])
        self.send("donor", "DONATE")
        for message in ("beans", "24", "27514",
                        (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%d") + " 12:00-15:00", "YES"):
            self.send("donor", message)
        d = self.app.tables["donations"][-1]
        self.app = PantryPulse(self.path)
        d = self.app.lookup("donations", id=d["id"])
        self.send("donor", "PROCEED 9")
        self.assertEqual(d["status"], "awaiting_choice")
        self.send("stranger", f"PROCEED {d['id']} 2")
        self.assertEqual(d["status"], "awaiting_choice")
        self.send("donor", "PROCEED 2")
        self.assertEqual(self.app.tables["offers"][-1]["pantry_id"], "1")
        count = len(self.app.tables["offers"])
        self.send("donor", "PROCEED 2")
        self.assertEqual(len(self.app.tables["offers"]), count)
        self.send("a", f"ACCEPT {d['id']}")
        self.send("a", f"RECEIVED {d['id']}")
        self.assertEqual(d["status"], "completed")

    def test_unregistered_choice_does_not_contact_another_pantry(self):
        self.register_pantry("a")
        d = self.create()
        self.send("donor", "CANCEL " + d["id"])
        self.send("donor", "DONATE")
        for message in ("beans", "24", "27514",
                        (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%d") + " 12:00-15:00", "YES"):
            self.send("donor", message)
        d = self.app.tables["donations"][-1]
        count = len(self.app.tables["offers"])
        self.send("donor", "PROCEED 1")  # pantry 2 is highest-ranked but unregistered
        self.assertEqual(d["status"], "awaiting_choice")
        self.assertEqual(len(self.app.tables["offers"]), count)
        self.send("donor", "PROCEED 2")
        self.assertEqual(d["status"], "offered")
        self.assertEqual(self.app.tables["offers"][-1]["pantry_id"], "1")

    def test_duplicate_event(self):
        self.send("donor", "JOIN DONOR")
        first = len(self.app.tables["outbox"])
        self.app.on_message(handle="donor", space_id="space-donor", message_id="m-1", text="JOIN DONOR")
        self.assertEqual(len(self.app.tables["outbox"]), first)

    def test_donor_can_cancel(self):
        self.register_pantry("a")
        d = self.create()
        self.send("donor", "CANCEL " + d["id"])
        self.assertEqual(d["status"], "cancelled")
        self.assertEqual(self.app.tables["offers"][0]["status"], "cancelled")

    def test_multiple_donations_from_structured_parser(self):
        self.register_pantry("a")
        self.send("donor", "JOIN DONOR")
        date = (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
        items = [{"item": "beans", "quantity": 10, "zip": "27514",
                  "start": f"{date}T12:00:00-04:00", "end": f"{date}T15:00:00-04:00",
                  "packaging": "unopened"},
                 {"item": "beans", "quantity": 10, "zip": "27514",
                  "start": f"{date}T12:00:00-04:00", "end": f"{date}T15:00:00-04:00",
                  "packaging": "unopened"}]
        self.app.from_gemini(handle="donor", space_id="space-donor", message_id="structured-1", items=items)
        self.assertEqual(len(self.app.tables["donations"]), 2)
        self.assertNotEqual(self.app.tables["donations"][0]["id"], self.app.tables["donations"][1]["id"])
        self.app.from_gemini(handle="donor", space_id="space-donor", message_id="structured-1", items=items)
        self.assertEqual(len(self.app.tables["donations"]), 2)

    def test_offer_timeout_goes_to_next_pantry(self):
        self.register_pantry("a")
        self.register_pantry("b")
        d = self.create()
        self.app.tables["offers"][0]["expires"] = (datetime.now(TZ) - timedelta(seconds=1)).isoformat()
        self.app.pending()
        self.assertEqual(self.app.tables["offers"][0]["status"], "expired")
        self.assertEqual(self.app.tables["offers"][1]["status"], "pending")
        self.assertEqual(d["status"], "offered")

    def test_persistence_reload(self):
        self.register_pantry("a")
        d = self.create()
        self.app = PantryPulse(self.path)
        self.assertEqual(self.app.lookup("donations", id=d["id"])["status"], "offered")


if __name__ == "__main__": unittest.main()

# These tests intentionally exercise Gemini's *structured output*, not a live API.
class GeminiHandoffTests(MVPTests):
    def test_parsed_multi_item_intake_and_persistence(self):
        self.register_pantry('a')
        self.register_pantry('b')
        self.send('donor', 'JOIN DONOR')
        items = [
            {'item': 'beans', 'quantity': 10, 'unit': 'cans'},
            {'item': 'Canned beans', 'quantity': 5, 'unit': 'cans'},
        ]
        self.app.on_parsed_intake(handle='donor', space_id='space-donor',
                                  message_id='gemini-multi', items=items)
        p = self.app.lookup('participants', handle='donor')
        self.assertEqual(p['step'], 'donation_zip')
        self.send('donor', '27514')
        future = (datetime.now(TZ) + timedelta(days=1)).strftime('%Y-%m-%d')
        self.send('donor', future + ' 12:00-15:00')
        self.send('donor', 'YES')
        self.assertEqual(len(self.app.tables['donations']), 2)
        self.assertEqual(len(set(d['id'] for d in self.app.tables['donations'])), 2)
        self.app.on_parsed_intake(handle='donor', space_id='space-donor',
                                  message_id='gemini-multi', items=items)
        self.assertEqual(len(self.app.tables['donations']), 2)

    def test_bad_parsed_inventory_unit_rejected(self):
        self.send('donor', 'JOIN DONOR')
        with self.assertRaises(ValueError):
            self.app.on_parsed_intake(handle='donor', space_id='space-donor',
                                      message_id='bad-unit',
                                      items=[{'item':'Canned beans','quantity':5,'unit':'pounds'}])
