"""Offline adapter tests: no API keys, network calls or real iMessages."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from pantrypulse_engine import PantryPulse
from pantrypulse_gemini import parse_donation, should_interpret


class GeminiAdapterTests(unittest.TestCase):
    def test_uses_search_results_and_preserves_recommendations(self):
        matches = [{"pantry_id": 2, "pantry_name": "Demo", "reason": "needed"}]
        with patch('search.search', return_value={
            "donation": {"food_item": "Canned beans", "quantity": 24, "unit": "cans"},
            "matches": matches, "message": "Options",
        }) as search:
            message = 'I have 24 unopened cans of beans in 27514 for 2026-10-14 12:00-16:00'
            parsed = parse_donation(message)
        search.assert_called_once_with(message)
        self.assertEqual(parsed.items[0]["recommendations"], matches)
        self.assertEqual(parsed.zip_code, '27514')
        self.assertEqual(parsed.window, '2026-10-14 12:00-16:00')
        self.assertTrue(parsed.packaging_verified)

    def test_detects_only_donation_intake(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            pd.DataFrame([{'pantry_id':1,'pantry_name':'Demo','address':'Fictional','contact_phone':'555'}]).to_csv(path/'pantries.csv', index=False)
            pd.DataFrame([{'pantry_id':1,'food_item':'Canned beans','quantity_on_hand':0,'target_quantity':100,'unit':'cans'}]).to_csv(path/'inventory.csv', index=False)
            app=PantryPulse(path)
            app.on_message(handle='donor',space_id='s',message_id='1',text='JOIN DONOR')
            # Finish/reset guided registration before testing an unsolicited donation.
            app.lookup('participants', handle='donor')['step'] = ''
            self.assertTrue(should_interpret(app,'donor','I have 24 cans of beans'))
            self.assertFalse(should_interpret(app,'donor','STATUS'))
            self.assertFalse(should_interpret(app,'donor','Hi'))
            self.assertFalse(should_interpret(app,'donor','ACCEPT 104'))
            self.assertFalse(should_interpret(app,'stranger','I have 24 cans of beans'))

if __name__=='__main__':unittest.main()
