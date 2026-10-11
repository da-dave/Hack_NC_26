"""Intake recognition must never confuse donor metadata with food quantities."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pantrypulse_gemini import offer_fields

class IntakeTests(unittest.TestCase):
    def test_explicit_fields(self):
        fields = offer_fields('DONATE 24 unopened cans of beans; address: 201 Sample Rd NC 27514; 2026-10-14 12:00-16:00')
        self.assertEqual(fields['quantity'], 24)
        self.assertEqual(fields['address'], '201 Sample Rd NC 27514')
        self.assertEqual(fields['zip'], '27514')
        self.assertEqual(fields['start'], '2026-10-14T12:00')
        self.assertEqual(fields['packaging'], 'unopened')

    def test_address_and_zip_are_not_food_quantity(self):
        fields = offer_fields('I have beans at 201 Sample Rd, NC 27514')
        self.assertNotIn('quantity', fields)

    def test_negated_sealed_claim_needs_confirmation(self):
        self.assertNotIn('packaging', offer_fields('24 cans of beans, not sealed'))

if __name__ == '__main__': unittest.main()
