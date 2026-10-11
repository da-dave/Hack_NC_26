"""Offline conversation tests: real CSV ranking, mocked Gemini, no iMessages."""
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pantrypulse_engine import PantryPulse, TZ, stamp
from search import DonationItem, gemini_parse, search


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        pd.DataFrame([dict(pantry_id=i, pantry_name=f"Pantry {i}", address=f"{i} Example St, Chapel Hill, NC",
                           contact_phone=f"919555100{i}") for i in range(1, 5)]).to_csv(self.path / "pantries.csv", index=False)
        pd.DataFrame([dict(pantry_id=i, food_item="Canned beans", quantity_on_hand=0,
                           target_quantity=need, unit="cans") for i, need in enumerate([40, 110, 70, 20], 1)]).to_csv(self.path / "inventory.csv", index=False)
        pd.DataFrame([dict(donor_id=1, donor_name="Known Donor", address="201 Sample Rd, Chapel Hill, NC",
                           phone_number="919-555-2001")]).to_csv(self.path / "donors.csv", index=False)
        self.app = PantryPulse(self.path)
        self.seq = 0
        self.day = (datetime.now(TZ) + timedelta(days=2)).strftime("%Y-%m-%d")
        self.parser = patch("search.gemini_parse", side_effect=self.parse)
        self.mock_parse = self.parser.start()
        self.addCleanup(self.parser.stop)

    @staticmethod
    def parse(message):
        food = message.split("\nDonor address:")[0]
        quantities = re.findall(r"(\d+(?:\.\d+)?)\s*(?:unopened\s+)?cans", food)
        return DonationItem(food_item="Canned beans", quantity=float(quantities[-1]) if quantities else None, unit="cans")

    def send(self, who, message, key=None):
        self.seq += 1
        self.app.on_message(handle=who, space_id=f"space-{who}", message_id=key or str(self.seq), text=message)

    def register(self, pid, hours="DAILY 00:00-23:59"):
        self.send(f"p{pid}", f"JOIN PANTRY {pid}")
        self.send(f"p{pid}", "27514")
        self.send(f"p{pid}", hours)

    def offer(self, who="donor", quantity=24):
        self.send(who, "JOIN DONOR")
        self.send(who, f"{quantity} unopened cans of beans")
        p = self.app.lookup("participants", handle=who)
        if p["step"] == "donation_address":
            self.send(who, "201 Sample Rd, Chapel Hill, NC")
        if p["step"] == "donation_zip":
            self.send(who, "27514")
        self.send(who, self.day + " 12:00-15:00")
        return self.app.tables["donations"][-1]

    def test_full_flow_uses_saved_backups_then_completes_on_accept(self):
        for pid in range(1, 5): self.register(pid)
        d = self.offer()
        self.assertEqual(d["status"], "awaiting_choice")
        self.assertFalse(self.app.tables["offers"])
        self.assertEqual([p["pantry_id"] for p in json.loads(d["recommendations"])], [2, 3, 1])
        self.send("donor", "PROCEED")
        self.assertEqual(self.app.tables["offers"][-1]["pantry_id"], "2")
        # Change inventory after search. Backup sequencing must not rerank it.
        self.app.seed_inventory.loc[self.app.seed_inventory["pantry_id"] == "1", "target_quantity"] = "999"
        self.send("p2", f"PASS {d['id']}")
        self.assertEqual(self.app.tables["offers"][-1]["pantry_id"], "3")
        self.send("p3", f"ACCEPT {d['id']}")
        self.assertEqual(d["status"], "completed")
        self.assertEqual(d["pantry_id"], "3")
        self.assertFalse(d["received"])
        self.assertEqual(self.app.need("3", "Canned beans"), 46)
        self.assertTrue(any("201 Sample Rd" in row["text"] and row["recipient"] == "p3" for row in self.app.tables["outbox"]))

    def test_search_runs_only_after_missing_details_collected(self):
        self.register(1)
        self.send("donor", "JOIN DONOR")
        self.send("donor", "beans")
        self.assertEqual(self.app.lookup("participants", handle="donor")["step"], "donation_quantity")
        self.send("donor", "24 cans")
        self.send("donor", "201 Sample Rd, Chapel Hill, NC")
        self.send("donor", "27514")
        self.send("donor", self.day)
        self.send("donor", "1-4pm")
        self.mock_parse.assert_not_called()
        self.send("donor", "YES")
        self.mock_parse.assert_called_once()
        message = self.mock_parse.call_args.args[0]
        for field in ("24 cans", "201 Sample Rd", "27514", self.day, "unopened"):
            self.assertIn(field, message)
        self.assertFalse(self.app.tables["offers"])

    def test_known_donor_address_is_reused_and_persisted(self):
        self.register(1)
        d = self.offer("+19195552001")
        self.assertEqual(d["donor_name"], "Known Donor")
        self.assertEqual(d["address"], "201 Sample Rd, Chapel Hill, NC")
        self.app = PantryPulse(self.path)
        self.assertEqual(self.app.lookup("participants", handle="+19195552001")["address"], d["address"])

    def test_explicit_address_overrides_profile(self):
        self.register(1)
        self.send("+19195552001", "JOIN DONOR")
        self.send("+19195552001", f"24 unopened cans of beans; address: 123 New Rd, Chapel Hill NC 27514; {self.day} 12:00-15:00")
        self.assertEqual(self.app.tables["donations"][-1]["address"], "123 New Rd, Chapel Hill NC 27514")

    def test_proceed_backup_survives_restart(self):
        for pid in (1, 2, 3): self.register(pid)
        d = self.offer()
        self.app = PantryPulse(self.path)
        self.send("donor", "PROCEED 2")
        self.assertEqual(self.app.tables["offers"][-1]["pantry_id"], "3")
        self.app = PantryPulse(self.path)
        self.send("p3", f"PASS {d['id']}")
        self.assertEqual(self.app.tables["offers"][-1]["pantry_id"], "1")

    def test_duplicate_proceed_and_accept_do_not_duplicate_offers(self):
        self.register(1)
        d = self.offer()
        self.send("donor", "PROCEED", key="proceed")
        self.send("donor", "PROCEED", key="proceed")
        self.send("donor", "PROCEED")
        self.send("p1", f"ACCEPT {d['id']}")
        self.send("p1", f"ACCEPT {d['id']}")
        self.assertEqual(len(self.app.tables["offers"]), 1)
        self.assertEqual(d["status"], "completed")

    def test_timeout_uses_next_suggestion(self):
        for pid in (1, 2, 3): self.register(pid)
        d = self.offer()
        self.send("donor", "PROCEED")
        self.app.tables["offers"][-1]["expires"] = stamp(datetime.now(TZ) - timedelta(minutes=1))
        self.app.pending()
        self.assertEqual(self.app.tables["offers"][-1]["pantry_id"], "3")
        self.assertEqual(d["status"], "offered")

    def test_exhaustion_never_contacts_fourth_pantry(self):
        for pid in range(1, 5): self.register(pid)
        d = self.offer()
        self.send("donor", "PROCEED")
        for pid in (2, 3, 1): self.send(f"p{pid}", f"PASS {d['id']}")
        self.assertEqual(d["status"], "unmatched")
        self.assertEqual(len(self.app.tables["offers"]), 3)

    def test_wrong_pantry_and_other_donor_cannot_act(self):
        for pid in (1, 2): self.register(pid)
        d = self.offer()
        self.send("other", "JOIN DONOR")
        self.send("other", f"PROCEED {d['id']} 1")
        self.assertFalse(self.app.tables["offers"])
        self.send("donor", "PROCEED")
        self.send("p1", f"ACCEPT {d['id']}")
        self.assertEqual(d["status"], "offered")

    def test_cancel_closes_pending_offer(self):
        self.register(1)
        d = self.offer()
        self.send("donor", "PROCEED")
        self.send("donor", f"CANCEL {d['id']}")
        self.send("p1", f"ACCEPT {d['id']}")
        self.assertEqual(d["status"], "cancelled")
        self.assertEqual(self.app.tables["offers"][-1]["status"], "cancelled")

    def test_no_registered_or_open_pantry_returns_no_matches(self):
        self.register(1, "DAILY 18:00-20:00")
        d = self.offer()
        self.assertEqual(d["status"], "unmatched")
        self.assertFalse(self.app.tables["offers"])

    def test_search_failure_keeps_details_for_retry(self):
        self.register(1)
        self.mock_parse.side_effect = RuntimeError("model unavailable")
        self.send("donor", "JOIN DONOR")
        self.send("donor", f"24 unopened cans of beans; address: 123 New Rd NC 27514; {self.day} 12:00-15:00")
        self.assertFalse(self.app.tables["donations"])
        self.assertEqual(self.app.lookup("participants", handle="donor")["step"], "donation_retry")
        self.app = PantryPulse(self.path)
        self.mock_parse.side_effect = self.parse
        self.send("donor", "RETRY")
        self.assertEqual(len(self.app.tables["donations"]), 1)

    def test_pledges_are_unused_and_committed_offers_reduce_search_need(self):
        for pid in (1, 2): self.register(pid)
        pd.DataFrame([dict(pantry_id=2, food_item="Canned beans", unit="cans", quantity=9999, status="approved")]).to_csv(self.path / "pledges.csv", index=False)
        self.assertEqual(self.app.need("2", "Canned beans"), 110)
        d = self.offer(quantity=90)
        self.send("donor", "PROCEED")
        self.send("p2", f"ACCEPT {d['id']}")
        second = self.offer()
        self.assertEqual(json.loads(second["recommendations"])[0]["pantry_id"], 1)

    def test_receipt_is_optional_and_idempotent(self):
        self.register(1)
        d = self.offer()
        self.send("donor", "PROCEED")
        self.send("p1", f"ACCEPT {d['id']}")
        self.send("p1", f"RECEIVED {d['id']}")
        received = d["received"]
        self.send("p1", f"RECEIVED {d['id']}")
        self.assertEqual(d["received"], received)
        self.assertEqual(self.app.need("1", "Canned beans"), 16)
        self.assertEqual(self.app.seed_inventory.iloc[0]["quantity_on_hand"], "0")

    def test_pantry_profiles_use_database_names_and_allow_more_than_two(self):
        for pid in range(1, 5): self.register(pid)
        self.assertEqual(len([p for p in self.app.tables["participants"] if p["role"] == "pantry"]), 4)
        p = self.app.lookup("participants", handle="p3")
        self.assertEqual(p["name"], "Pantry 3")
        self.assertIn("3 Example St", p["address"])
        self.send("other", "JOIN PANTRY 3")
        self.assertFalse(self.app.lookup("participants", handle="other")["pantry_id"])

    def test_invalid_choice_and_multiple_waiting_offers(self):
        self.register(1)
        d1 = self.offer()
        d2 = self.offer()
        self.send("donor", "PROCEED")
        self.send("donor", f"PROCEED {d1['id']} 9")
        self.assertFalse(self.app.tables["offers"])
        self.send("donor", f"PROCEED {d2['id']} 1")
        self.assertEqual(self.app.tables["offers"][-1]["donation_id"], d2["id"])

    def test_no_shortage_fallback_can_be_accepted(self):
        self.register(1)
        inventory = pd.read_csv(self.path / "inventory.csv")
        inventory["quantity_on_hand"] = inventory["target_quantity"]
        inventory.to_csv(self.path / "inventory.csv", index=False)
        self.app = PantryPulse(self.path)
        d = self.offer()
        self.assertEqual(json.loads(d["recommendations"])[0]["reason"], "fallback")
        self.send("donor", "PROCEED")
        self.send("p1", f"ACCEPT {d['id']}")
        self.assertEqual(d["status"], "completed")

    def test_bridge_message_route_collects_then_searches_and_delivers_outbox(self):
        import importlib
        import sys
        with patch("pantrypulse_engine.PantryPulse", return_value=self.app):
            sys.modules.pop("pantrypulse_service", None)
            service = importlib.import_module("pantrypulse_service")
        self.register(1)
        handler = object.__new__(service.Handler)
        responses = []
        handler.respond = lambda payload, code=200: responses.append((payload, code))
        handler.path = "/message"
        payload = dict(handle="donor", space_id="s", message_id="http-1", text="JOIN DONOR")
        handler.read_json = lambda: payload
        handler.do_POST()
        payload = dict(handle="donor", space_id="s", message_id="http-2", text=
                       f"24 unopened cans of beans; address: 201 Example Rd NC 27514; {self.day} 12:00-15:00")
        handler.do_POST()
        handler.do_POST()  # duplicated webhook must not call Gemini again
        self.mock_parse.assert_called_once()
        self.assertFalse(self.app.tables["offers"])
        payload = dict(handle="donor", space_id="s", message_id="http-3", text="PROCEED")
        handler.do_POST()
        handler.path = "/pending"
        handler.do_GET()
        pending = responses[-1][0]["messages"]
        self.assertTrue(any(row["recipient"] == "p1" and row["space_id"] == "space-p1"
                            and "TEST OFFER" in row["text"] for row in pending))
        self.assertTrue(all(code == 200 for _, code in responses))

    def test_pantry_can_match_database_phone(self):
        self.send("+19195551003", "JOIN PANTRY")
        self.send("+19195551003", "27514")
        self.send("+19195551003", "9am-5pm")
        self.assertEqual(self.app.lookup("participants", handle="+19195551003")["pantry_id"], "3")

    def test_missing_gemini_quantity_never_creates_offer(self):
        self.register(1)
        self.mock_parse.return_value = DonationItem(food_item="Canned beans", quantity=None, unit="cans")
        self.mock_parse.side_effect = None
        self.send("donor", "JOIN DONOR")
        self.send("donor", f"24 unopened cans of beans; address: 201 Example Rd NC 27514; {self.day} 12:00-15:00")
        self.assertFalse(self.app.tables["donations"])
        self.assertEqual(self.app.lookup("participants", handle="donor")["step"], "donation_retry")

    def test_declined_packaging_creates_no_offer(self):
        self.send("donor", "JOIN DONOR")
        for text in ("24 cans of beans", "201 Sample Rd, NC", "27514", self.day + " 12:00-15:00", "NO"):
            self.send("donor", text)
        self.assertFalse(self.app.tables["donations"])
        self.mock_parse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
