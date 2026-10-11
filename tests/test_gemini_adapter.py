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
    def test_extracts_multiple_items_location_window_packaging(self):
        archive = types.ModuleType('arch.search')
        archive.parse_donor_message = lambda _: SimpleNamespace(
            items=[SimpleNamespace(food_item='Canned beans',quantity=24,unit='cans'),
                   SimpleNamespace(food_item='Pasta', quantity=8, unit='boxes')],
            donor_location='27514', availability='2026-10-14 12:00-16:00',
        )
        with patch.dict(sys.modules, {'arch.search':archive}):
            p = parse_donation('I have 24 unopened cans of beans and 8 boxes of pasta in 27514 for 2026-10-14 12:00-16:00')
        self.assertEqual(len(p.items),2)
        self.assertEqual(p.zip_code,'27514')
        self.assertEqual(p.window,'2026-10-14 12:00-16:00')
        self.assertTrue(p.packaging_verified)

    def test_detects_only_donation_intake(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            pd.DataFrame([{'pantry_id':1,'pantry_name':'Demo','address':'Fictional','contact_phone':'555'}]).to_csv(path/'pantries.csv', index=False)
            pd.DataFrame([{'pantry_id':1,'food_item':'Canned beans','quantity_on_hand':0,'target_quantity':100,'unit':'cans'}]).to_csv(path/'inventory.csv', index=False)
            app=PantryPulse(path)
            app.on_message(handle='donor',space_id='s',message_id='1',text='JOIN DONOR')
            self.assertTrue(should_interpret(app,'donor','I have 24 cans of beans'))
            self.assertFalse(should_interpret(app,'donor','STATUS'))
            self.assertFalse(should_interpret(app,'donor','Hi'))
            self.assertFalse(should_interpret(app,'donor','ACCEPT 104'))
            self.assertFalse(should_interpret(app,'stranger','I have 24 cans of beans'))

if __name__=='__main__':unittest.main()
