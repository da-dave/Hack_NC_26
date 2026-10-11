"""PantryPulse hackathon event engine: pandas + CSV; one local Python service.

The seeded pantries.csv and inventory.csv are READ-ONLY. New records use pp_*.csv.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from pantrypulse_time import parse_day, parse_time_window

TZ = ZoneInfo("America/New_York")
SCHEMAS = {
    "participants": ["handle", "space_id", "role", "pantry_id", "name", "address", "zip", "hours", "step", "draft"],
    "donations": ["id", "donor", "item", "quantity", "unit", "zip", "start", "end", "packaging", "status", "pantry_id", "created", "recommendations", "address", "donor_name", "received"],
    "offers": ["id", "donation_id", "pantry_id", "status", "created", "expires", "resolved", "reminded"],
    "inbox": ["message_key"],
    "outbox": ["id", "recipient", "text", "sent"],
}
ALIASES = {
    "beans": "Canned beans", "bean": "Canned beans", "canned beans": "Canned beans",
    "rice": "Rice", "pasta": "Pasta", "noodles": "Pasta",
    "peanut butter": "Peanut butter", "canned vegetables": "Canned vegetables",
    "canned fruit": "Canned fruit", "oats": "Oatmeal", "oatmeal": "Oatmeal",
    "canned tuna": "Canned tuna", "tuna": "Canned tuna",
    "shelf-stable milk": "Shelf-stable milk", "shelf stable milk": "Shelf-stable milk",
    "cereal": "Cereal",
}
HOURS_RE = re.compile(r"^(DAILY|MON-FRI|SAT-SUN)\s+([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$", re.I)
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")


def stamp(dt: datetime | None = None) -> str:
    return (dt or datetime.now(TZ)).isoformat(timespec="seconds")


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(TZ)


def canonical(item: str) -> str:
    cleaned = " ".join(re.sub(r"[^a-z0-9 -]", " ", item.lower()).split())
    return ALIASES.get(cleaned, cleaned.title())


class PantryPulse:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seed_pantries = self._seed("pantries.csv", {"pantry_id", "pantry_name", "address", "contact_phone"})
        self.seed_inventory = self._seed("inventory.csv", {"pantry_id", "food_item", "quantity_on_hand", "target_quantity", "unit"})
        donors_path = self.dir / "donors.csv"
        self.seed_donors = (pd.read_csv(donors_path, dtype=str, keep_default_na=False)
                            if donors_path.exists() else pd.DataFrame())
        self.tables: dict[str, list[dict[str, str]]] = {}
        for name, cols in SCHEMAS.items():
            path = self.dir / f"pp_{name}.csv"
            if path.exists():
                self.tables[name] = pd.read_csv(path, dtype=str, keep_default_na=False).to_dict("records")
                for row in self.tables[name]:
                    for column in cols:
                        row.setdefault(column, "")
            else:
                self.tables[name] = []
                self._write(name)
        self.offer_minutes = int(os.environ.get("PANTRYPULSE_OFFER_MINUTES", "90"))
        self.buffer_minutes = int(os.environ.get("PANTRYPULSE_HANDOFF_BUFFER_MINUTES", "20"))

    def _seed(self, filename: str, cols: set[str]) -> pd.DataFrame:
        path = self.dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing seed file: {path}. Copy it from teammates' backend/data directory.")
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        if not cols.issubset(df.columns):
            raise ValueError(f"{filename} missing {sorted(cols-set(df.columns))}")
        return df

    def _write(self, name: str):
        path = self.dir / f"pp_{name}.csv"
        temp = path.with_suffix(".tmp")
        pd.DataFrame(self.tables[name], columns=SCHEMAS[name]).to_csv(temp, index=False)
        os.replace(temp, path)

    def save(self):
        for name in SCHEMAS:
            self._write(name)

    def lookup(self, name: str, **fields):
        return next((r for r in self.tables[name] if all(str(r.get(k)) == str(v) for k, v in fields.items())), None)

    def by(self, name: str, **fields):
        return [r for r in self.tables[name] if all(str(r.get(k)) == str(v) for k, v in fields.items())]

    def next_id(self, name: str) -> str:
        return str(max([int(x["id"]) for x in self.tables[name]] + ([103] if name == "donations" else [0])) + 1)

    def notify(self, handle: str, body: str):
        if not handle:
            return
        self.tables["outbox"].append({"id": self.next_id("outbox"), "recipient": handle, "text": body, "sent": ""})

    def part(self, handle: str, space_id: str):
        p = self.lookup("participants", handle=handle)
        if not p:
            p = dict.fromkeys(SCHEMAS["participants"], "")
            p.update(handle=handle, space_id=space_id, role="", step="", draft="{}")
            self.tables["participants"].append(p)
        else:
            p["space_id"] = space_id
        return p

    def start_pantry(self, p, requested_id=""):
        if p["pantry_id"]:
            self.notify(p["handle"], f"Already registered as pantry #{p['pantry_id']}.")
            return
        used = {row["pantry_id"] for row in self.tables["participants"] if row["pantry_id"]}
        phone = re.sub(r"\D", "", p["handle"])[-10:]
        profiles = self.seed_pantries
        if requested_id:
            profiles = profiles[profiles["pantry_id"] == requested_id]
        else:
            profiles = profiles[profiles["contact_phone"].map(
                lambda value: re.sub(r"\D", "", value)[-10:]) == phone]
        if profiles.empty:
            self.notify(p["handle"], "Choose your demo pantry profile with JOIN PANTRY <ID>, using the IDs in pantries.csv.")
            return
        row = profiles.iloc[0]
        if row["pantry_id"] in used:
            self.notify(p["handle"], "That pantry profile is already registered.")
            return
        draft = {"pantry_id": row["pantry_id"], "name": row["pantry_name"], "address": row["address"]}
        zip_match = re.search(r"(?<!\d)(\d{5})(?!\d)", row["address"])
        if zip_match:
            draft["zip"] = zip_match[1]
            p["step"] = "pantry_hours"
            question = "When can your pantry receive donations? Reply DAILY 09:00-17:00 or 9am-5pm."
        else:
            p["step"] = "pantry_zip"
            question = "What is your pantry's five-digit ZIP code?"
        p["draft"] = json.dumps(draft)
        self.notify(p["handle"], f"Using {draft['name']} at {draft['address']}. " + question)

    def onboarding(self, p, text):
        draft = json.loads(p["draft"] or "{}")
        if p["step"] == "pantry_zip":
            if not re.fullmatch(r"\d{5}", text):
                self.notify(p["handle"], "Enter a five-digit ZIP code.")
                return
            draft["zip"] = text
            p["step"] = "pantry_hours"
            p["draft"] = json.dumps(draft)
            self.notify(p["handle"], "When can you receive donations? Reply DAILY 09:00-17:00 or 9am-5pm.")
            return
        if p["step"] == "pantry_hours":
            try:
                if HOURS_RE.fullmatch(text.upper()):
                    hours = text.upper()
                    start, end = hours.split()[1].split("-")
                    if start >= end:
                        raise ValueError("Invalid hours")
                else:
                    a, b = parse_time_window(datetime.now(TZ).date(), text)
                    if a.date() != b.date():
                        raise ValueError("Overnight hours not supported")
                    hours = f"DAILY {a:%H:%M}-{b:%H:%M}"
            except ValueError:
                self.notify(p["handle"], "Please reply DAILY 09:00-17:00 or 9am-5pm.")
                return
            if self.lookup("participants", pantry_id=draft["pantry_id"]):
                p["step"], p["draft"] = "", "{}"
                self.notify(p["handle"], "That pantry was registered while you were entering details. Choose another profile.")
                return
            p.update(role="pantry", pantry_id=draft["pantry_id"], name=draft["name"],
                     address=draft["address"], zip=draft["zip"], hours=hours, step="", draft="{}")
            self.notify(p["handle"], f"Registered {p['name']} (demo pantry #{p['pantry_id']}). Reply INVENTORY or STATUS PANTRY.")

    def donor_profile(self, p):
        if self.seed_donors.empty:
            return
        phone = re.sub(r"\D", "", p["handle"])[-10:]
        rows = self.seed_donors[self.seed_donors["phone_number"].map(
            lambda value: re.sub(r"\D", "", value)[-10:]) == phone]
        if not rows.empty:
            row = rows.iloc[0]
            if not p["name"]:
                p["name"] = row["donor_name"]
            if not p["address"]:
                p["address"] = row["address"]

    def begin_donation(self, p):
        if p["role"] == "donor":
            self.donor_profile(p)
        p["step"], p["draft"] = "donation_item", "{}"
        self.notify(p["handle"], "Describe one food donation with its quantity (e.g. 24 unopened cans of beans). Include your address, ZIP and drop-off window if you know them.")

    def advance_intake(self, p, draft):
        if not draft.get("description"):
            step, question = "item", "What food are you donating?"
        elif not draft.get("quantity"):
            step, question = "quantity", "What quantity are you offering? Include the unit, e.g. 24 cans."
        elif not draft.get("address"):
            step, question = "address", "What is your street address, including city and state?"
        elif not draft.get("zip"):
            step, question = "zip", "What is your five-digit ZIP code?"
        elif not draft.get("start"):
            step, question = "day", "Which day can you drop off? Reply TODAY, TOMORROW, or a date."
        elif not draft.get("packaging"):
            step, question = "packaging", "Is the food unopened and shelf-stable? Reply YES or NO."
        else:
            # Persist the collected facts before calling Gemini, so failures are retryable.
            p["draft"] = json.dumps(draft)
            try:
                self.create_donation(p["handle"], draft)
            except Exception as exc:
                print("Donation search failed:", type(exc).__name__)
                p["step"] = "donation_retry"
                self.notify(p["handle"], "I couldn't finish parsing that offer. Reply RETRY to try again, send a corrected food description with quantity, or CANCEL REGISTRATION to stop.")
                return
            p["step"], p["draft"] = "", "{}"
            return
        p["step"], p["draft"] = "donation_" + step, json.dumps(draft)
        self.notify(p["handle"], question)

    def donation_intake(self, p, text):
        from pantrypulse_gemini import offer_fields
        draft = json.loads(p["draft"] or "{}")
        step = p["step"]
        if step in ("donation_item", "donation_retry"):
            if step == "donation_retry" and text.upper() == "RETRY":
                self.advance_intake(p, draft)
                return
            fields = offer_fields(text)
            draft.update(fields)
            if not draft.get("address") and p["role"] == "donor" and p["address"]:
                draft["address"] = p["address"]
            if not draft.get("zip") and p["zip"]:
                draft["zip"] = p["zip"]
            if draft.get("start"):
                try:
                    a = datetime.fromisoformat(draft["start"]).replace(tzinfo=TZ)
                    b = datetime.fromisoformat(draft["end"]).replace(tzinfo=TZ)
                    if a >= b or b <= datetime.now(TZ) + timedelta(minutes=self.buffer_minutes):
                        raise ValueError("Invalid window")
                    draft.update(start=stamp(a), end=stamp(b))
                except ValueError:
                    draft.pop("start", None)
                    draft.pop("end", None)
        elif step == "donation_quantity":
            quantity = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s+([a-zA-Z ]+))?", text)
            if not quantity or float(quantity[1]) <= 0:
                self.notify(p["handle"], "Enter a positive quantity, e.g. 24 cans.")
                return
            draft["quantity"] = float(quantity[1])
            draft["description"] += f"; quantity: {text}"
        elif step == "donation_address":
            if len(text.strip()) < 7 or not re.search(r"\d", text):
                self.notify(p["handle"], "Please enter a street address, including city and state.")
                return
            draft["address"] = text.strip()
            zip_match = re.search(r"(?<!\d)(\d{5})(?!\d)", text)
            if zip_match:
                draft["zip"] = zip_match[1]
        elif step == "donation_zip":
            if not re.fullmatch(r"\d{5}", text):
                self.notify(p["handle"], "Please enter a five-digit ZIP code.")
                return
            draft["zip"] = text
        elif step in ("donation_day", "donation_time"):
            try:
                legacy = DATE_RE.fullmatch(text)
                if legacy:
                    a, b = parse_time_window(parse_day(legacy[1]), f"{legacy[2]}-{legacy[3]}")
                elif step == "donation_day":
                    draft["day"] = parse_day(text).isoformat()
                    p["step"], p["draft"] = "donation_time", json.dumps(draft)
                    self.notify(p["handle"], "What drop-off time? Reply 1-4pm or 2pm.")
                    return
                else:
                    a, b = parse_time_window(parse_day(draft["day"]), text)
                if a >= b or b <= datetime.now(TZ) + timedelta(minutes=self.buffer_minutes):
                    raise ValueError("That window has passed or is too soon.")
                draft.update(start=stamp(a), end=stamp(b))
            except ValueError as exc:
                self.notify(p["handle"], str(exc))
                return
        elif step == "donation_packaging":
            if text.upper() not in ("YES", "NO"):
                self.notify(p["handle"], "Please reply YES or NO.")
                return
            if text.upper() == "NO":
                p["step"], p["draft"] = "", "{}"
                self.notify(p["handle"], "This prototype accepts unopened shelf-stable food. No offer was created.")
                return
            draft["packaging"] = "unopened"
        if draft.get("address") and p["role"] == "donor":
            p["address"] = draft["address"]
        if draft.get("zip"):
            p["zip"] = draft["zip"]
        self.advance_intake(p, draft)

    def create_donation(self, donor: str, fields: dict):
        from search import search
        start, end = parse_dt(str(fields["start"])), parse_dt(str(fields["end"]))
        address, zip_code = str(fields.get("address", "")).strip(), str(fields.get("zip", ""))
        packaging = str(fields.get("packaging", "")).lower()
        if (not address or not re.fullmatch(r"\d{5}", zip_code) or start >= end
                or end <= datetime.now(TZ) + timedelta(minutes=self.buffer_minutes)
                or packaging not in ("unopened", "sealed")):
            raise ValueError("Missing or invalid address, ZIP, drop-off window or packaging")
        description = fields.get("description") or f"{fields.get('quantity', '')} {fields.get('unit', '')} {fields.get('item', '')}"
        message = (f"Food offer: {description}\nDonor address: {address}\nZIP: {zip_code}"
                   f"\nDrop-off: {stamp(start)} to {stamp(end)}\nPackaging: {packaging}")
        eligible_ids = [p["pantry_id"] for p in self.tables["participants"]
                        if p["role"] == "pantry" and p["pantry_id"]
                        and self.pantry_open(p, start, end)]
        result = search(message, data_dir=self.dir, eligible_ids=eligible_ids,
                        committed=self.tables["donations"])
        parsed = result["donation"]
        item = canonical(str(parsed["food_item"]))
        quantity = parsed.get("quantity")
        if quantity is None or float(quantity) <= 0 or not float(quantity).is_integer():
            raise ValueError("Specify a positive whole-number quantity")
        qty = int(quantity)
        matching = self.seed_inventory[self.seed_inventory["food_item"].str.casefold() == item.casefold()]
        unit = str(parsed.get("unit") or "")
        if not matching.empty:
            expected = str(matching.iloc[0]["unit"])
            if unit and unit.casefold() != expected.casefold():
                raise ValueError(f"Use {expected} for {item}")
            unit = expected
        if not unit:
            raise ValueError("Specify the food quantity unit")
        recommendations = result["matches"]
        participant = self.lookup("participants", handle=donor)
        donation = dict.fromkeys(SCHEMAS["donations"], "")
        donation.update(id=self.next_id("donations"), donor=donor, item=item, quantity=str(qty),
                        unit=unit, zip=zip_code, address=address,
                        donor_name=participant["name"] if participant else "",
                        start=stamp(start), end=stamp(end), packaging=packaging,
                        status="awaiting_choice" if recommendations else "unmatched",
                        created=stamp(), recommendations=json.dumps(recommendations))
        self.tables["donations"].append(donation)
        self.notify(donor, f"Donation #{donation['id']} pantry options:\n" + result["message"] +
                    (f"\nYou can also reply PROCEED {donation['id']} <option number>." if recommendations else ""))
        return donation["id"]

    def pantry_open(self, p, start: datetime, end: datetime) -> bool:
        m = HOURS_RE.fullmatch(p["hours"].upper())
        if not m or start.date() != end.date():
            return False
        dayset = m.group(1)
        weekday = start.weekday()
        if dayset == "MON-FRI" and weekday >= 5: return False
        if dayset == "SAT-SUN" and weekday < 5: return False
        start_time = start.strftime("%H:%M")
        end_time = end.strftime("%H:%M")
        open_at = p["hours"].split(" ")[1].split("-")[0]
        close_at = p["hours"].split(" ")[1].split("-")[1]
        # Must be able to receive during SOME part of the donor's window.
        return max(open_at, start_time) < min(close_at, end_time)

    def need(self, pantry_id: str, item: str) -> int:
        rows = self.seed_inventory[(self.seed_inventory["pantry_id"] == pantry_id) & (self.seed_inventory["food_item"].str.lower() == item.lower())]
        if rows.empty: return 0
        row = rows.iloc[0]
        base = max(int(row["target_quantity"]) - int(row["quantity_on_hand"]), 0)
        # Both reserved and completed donations count toward fulfilled needs.
        for d in self.tables["donations"]:
            if d["pantry_id"] == pantry_id and d["item"].lower() == item.lower() and d["unit"] == row["unit"] and d["status"] in ("reserved", "completed"):
                base -= int(d["quantity"])
        return max(base, 0)

    def choose_pantry(self, p, message):
        parts = message.split()
        waiting = [d for d in self.tables["donations"]
                   if d["donor"] == p["handle"] and d["status"] == "awaiting_choice"]
        if len(parts) == 3:
            donation = next((d for d in waiting if d["id"] == parts[1].lstrip("#")), None)
            choice = parts[2]
        elif len(parts) in (1, 2) and len(waiting) == 1:
            donation = waiting[0]
            choice = parts[1] if len(parts) == 2 else "1"
        else:
            self.notify(p["handle"], "Reply PROCEED <donation ID> <option number> to select a pantry for a pending donation.")
            return
        if not donation:
            self.notify(p["handle"], "No donation awaiting your choice has that ID.")
            return
        options = json.loads(donation["recommendations"] or "[]")
        if not choice.isdigit() or not 1 <= int(choice) <= len(options):
            self.notify(p["handle"], f"Choose an option from 1 to {len(options)}.")
            return
        pid = str(options[int(choice) - 1]["pantry_id"])
        receiver = self.lookup("participants", role="pantry", pantry_id=pid)
        if not receiver or not self.pantry_open(receiver, parse_dt(donation["start"]), parse_dt(donation["end"])):
            self.notify(p["handle"], "That pantry isn't registered or can't accept this donation during your window. Choose another option, or CANCEL the donation.")
            return
        self.next_offer(donation, preferred_id=pid)
        if donation["status"] == "offered":
            self.notify(p["handle"], f"Contacting {options[int(choice) - 1]['pantry_name']} for donation #{donation['id']}. I’ll let you know when they respond.")

    def next_offer(self, donation, preferred_id=None):
        now = datetime.now(TZ)
        if parse_dt(donation["end"]) <= now + timedelta(minutes=self.buffer_minutes):
            donation["status"] = "expired"
            self.notify(donation["donor"], f"Donation #{donation['id']} expired before a handoff could be arranged.")
            return
        attempted = {x["pantry_id"] for x in self.by("offers", donation_id=donation["id"])}
        recommendations = json.loads(donation["recommendations"] or "[]")
        if preferred_id is not None:
            # Start at the donor's chosen option; then follow the remaining backups.
            index = next((i for i, row in enumerate(recommendations)
                          if str(row["pantry_id"]) == preferred_id), len(recommendations))
            recommendations = recommendations[index:]
            donation["recommendations"] = json.dumps(recommendations)
        receiver = None
        for candidate in recommendations:
            pid = str(candidate["pantry_id"])
            if pid in attempted:
                continue
            p = self.lookup("participants", role="pantry", pantry_id=pid)
            if p and self.pantry_open(p, parse_dt(donation["start"]), parse_dt(donation["end"])):
                receiver = p
                break
        if not receiver:
            donation["status"] = "unmatched"
            self.notify(donation["donor"], f"No remaining suggested pantries can accept offer #{donation['id']}.")
            return
        p, pid = receiver, receiver["pantry_id"]
        expiry = min(now + timedelta(minutes=self.offer_minutes), parse_dt(donation["end"]) - timedelta(minutes=self.buffer_minutes))
        if expiry <= now:
            donation["status"] = "expired"
            self.notify(donation["donor"], f"Not enough time remains to coordinate donation #{donation['id']}.")
            return
        offer = {"id": self.next_id("offers"), "donation_id": donation["id"], "pantry_id": pid, "status": "pending", "created": stamp(now), "expires": stamp(expiry), "resolved": "", "reminded": ""}
        self.tables["offers"].append(offer)
        donation["status"] = "offered"
        donation["pantry_id"] = ""
        self.notify(donation["donor"], f"Offering donation #{donation['id']} to {p['name']}.")
        self.notify(p["handle"], f"PANTRYPULSE TEST OFFER #{donation['id']}\n{donation['quantity']} {donation['unit']} of {donation['item']} (unopened). Donor {donation['donor_name'] or donation['donor']}. Address: {donation['address']}, {donation['zip']}. Available {parse_dt(donation['start']).strftime('%b %d %I:%M %p')}–{parse_dt(donation['end']).strftime('%I:%M %p')} ET.\nReply ACCEPT {donation['id']} or PASS {donation['id']}. Offer valid until {expiry.strftime('%I:%M %p')} ET.")

    def respond_offer(self, p, command, donation_id):
        d = self.lookup("donations", id=donation_id)
        if not d:
            self.notify(p["handle"], "Donation ID not found.")
            return
        offer = next((o for o in reversed(self.tables["offers"]) if o["donation_id"] == donation_id and o["status"] == "pending"), None)
        if not offer or offer["pantry_id"] != p["pantry_id"] or d["status"] != "offered":
            self.notify(p["handle"], f"No active offer #{donation_id} belongs to your pantry.")
            return
        if parse_dt(offer["expires"]) <= datetime.now(TZ):
            offer.update(status="expired", resolved=stamp())
            self.next_offer(d)
            self.notify(p["handle"], "That offer already expired.")
            return
        offer.update(status="accepted" if command == "ACCEPT" else "declined", resolved=stamp())
        if command == "PASS":
            self.notify(p["handle"], f"Declined #{donation_id}; moving to the next saved suggestion.")
            self.next_offer(d)
            return
        d.update(status="completed", pantry_id=p["pantry_id"])
        self.notify(p["handle"], f"Accepted donation #{donation_id}. The offer is completed. You can optionally confirm delivery with RECEIVED {donation_id}.")
        days, span = p["hours"].split(" ")
        a, b = span.split("-")
        # The allowed handoff is the INTERSECTION, not the full donor window.
        safe_from = max(parse_dt(d["start"]).strftime("%H:%M"), a)
        safe_to = min(parse_dt(d["end"]).strftime("%H:%M"), b)
        self.notify(d["donor"], f"Donation #{donation_id} COMPLETED — accepted by {p['name']} (SIMULATED PANTRY).\nDemo address: {p['address']}, {p['zip']}.\nYour originally stated drop-off window: {parse_dt(d['start']).strftime('%b %d %I:%M %p')}–{parse_dt(d['end']).strftime('%I:%M %p')} ET.\nPantry can receive within this window: {safe_from}–{safe_to} ET.\nDo NOT travel to this fictional demo address.")

    def received(self, p, donation_id):
        d = self.lookup("donations", id=donation_id)
        if not d or d["pantry_id"] != p["pantry_id"] or d["status"] != "completed":
            self.notify(p["handle"], f"No completed offer #{donation_id} is awaiting delivery confirmation for your pantry.")
            return
        if d.get("received"):
            self.notify(p["handle"], f"Donation #{donation_id} was already marked received.")
            return
        d["received"] = stamp()
        self.notify(p["handle"], f"Donation #{donation_id} marked received.")
        self.notify(d["donor"], f"Your donation #{donation_id} was marked received by {p['name']}. Thank you!")

    def cancel(self, p, donation_id):
        d = self.lookup("donations", id=donation_id, donor=p["handle"])
        if not d or d["status"] in ("cancelled", "completed", "expired", "unmatched"):
            self.notify(p["handle"], f"Donation #{donation_id} is not active or does not belong to you.")
            return False
        if d["status"] == "offered":
            for o in self.by("offers", donation_id=donation_id):
                if o["status"] == "pending":
                    o.update(status="cancelled", resolved=stamp())
                    receiver = self.lookup("participants", pantry_id=o["pantry_id"])
                    if receiver: self.notify(receiver["handle"], f"Offer #{donation_id} was cancelled by the donor.")
        if d["status"] == "reserved":
            receiver = self.lookup("participants", pantry_id=d["pantry_id"])
            if receiver: self.notify(receiver["handle"], f"Reserved donation #{donation_id} has been cancelled by the donor.")
        d["status"] = "cancelled"
        self.notify(p["handle"], f"Donation #{donation_id} cancelled.")
        return True

    def status(self, p, selector=""):
        handle = p["handle"]
        if selector == "PANTRY" and p["role"] != "pantry":
            self.notify(handle, "This account is donor-only. Text STATUS DONATIONS.")
            return
        if selector == "PANTRY" or (p["role"] == "pantry" and selector not in ("DONATIONS",)):
            offerings = [o for o in self.tables["offers"] if o["pantry_id"] == p["pantry_id"]]
            lines = [f"{o['donation_id']}: {o['status']}" for o in offerings[-8:]]
            self.notify(handle, f"{p['name']} pantry offers:\n" + ("\n".join(lines) if lines else "No offers yet."))
        else:
            donations = [d for d in self.tables["donations"] if d["donor"] == handle]
            lines = [f"#{d['id']}: {d['quantity']} {d['unit']} {d['item']} — {d['status']}" for d in donations[-8:]]
            self.notify(handle, "Your donations:\n" + ("\n".join(lines) if lines else "No donations yet."))

    def inventory(self, p):
        if not p["pantry_id"]:
            self.notify(p["handle"], "Only pantry accounts can see their pantry inventory.")
            return
        inv = self.seed_inventory[self.seed_inventory["pantry_id"] == p["pantry_id"]]
        lines = [f"{row['food_item']}: {row['quantity_on_hand']} on hand, target {row['target_quantity']}, projected shortage {self.need(p['pantry_id'], row['food_item'])} {row['unit']}" for _, row in inv.iterrows()]
        self.notify(p["handle"], "TEST inventory (seed baseline + accepted offers):\n" + "\n".join(lines))

    def expire_offers(self):
        for o in list(self.tables["offers"]):
            if o["status"] == "pending" and not o.get("reminded") and datetime.now(TZ) >= parse_dt(o["created"]) + (parse_dt(o["expires"]) - parse_dt(o["created"])) / 2:
                p = self.lookup("participants", pantry_id=o["pantry_id"])
                if p:
                    self.notify(p["handle"], f"Reminder: offer #{o['donation_id']} is waiting. Reply ACCEPT {o['donation_id']} or PASS {o['donation_id']} before it expires.")
                o["reminded"] = "yes"
            if o["status"] == "pending" and parse_dt(o["expires"]) <= datetime.now(TZ):
                o.update(status="expired", resolved=stamp())
                d = self.lookup("donations", id=o["donation_id"])
                p = self.lookup("participants", pantry_id=o["pantry_id"])
                if p: self.notify(p["handle"], f"Offer #{o['donation_id']} expired.")
                if d and d["status"] == "offered": self.next_offer(d)
        for d in self.tables["donations"]:
            if d["status"] in ("searching", "awaiting_choice", "offered", "reserved") and parse_dt(d["end"]) <= datetime.now(TZ):
                d["status"] = "expired"
                for o in self.by("offers", donation_id=d["id"]):
                    if o["status"] == "pending": o.update(status="expired", resolved=stamp())
                self.notify(d["donor"], f"Donation #{d['id']} drop-off window ended before confirmed receipt; marked expired. Contact your pantry if the food was delivered.")

    def on_message(self, *, handle: str, space_id: str, message_id: str, text: str):
        key = f"{space_id}|{message_id}"
        if self.lookup("inbox", message_key=key):
            return
        p = self.part(handle, space_id)
        message = text.strip()
        upper = message.upper()
        # Commands that can interrupt a staged conversation.
        if upper == "HELP":
            self.notify(handle, "PantryPulse: JOIN DONOR, JOIN PANTRY <ID>, DONATE, PROCEED <option>, STATUS DONATIONS, STATUS PANTRY, INVENTORY, CANCEL <id>, EDIT <id>, ACCEPT <id>, PASS <id>, RECEIVED <id>.")
        elif re.fullmatch(r"JOIN PANTRY(?: \d+)?", upper):
            self.start_pantry(p, upper.split()[2] if len(upper.split()) == 3 else "")
        elif upper == "JOIN DONOR":
            if p["role"] == "pantry":
                self.notify(handle, "Your pantry account already includes donor privileges. Text DONATE when ready.")
            else:
                p.update(role="donor", step="", draft="{}")
                self.notify(handle, "Welcome to PantryPulse!")
                self.begin_donation(p)
        elif upper == "CANCEL REGISTRATION":
            p.update(step="", draft="{}")
            self.notify(handle, "Registration or intake cancelled. Your account remains unchanged.")
        elif p["step"].startswith("pantry_"):
            self.onboarding(p, message)
        elif upper in ("STATUS", "STATUS DONATIONS", "STATUS PANTRY"):
            self.status(p, upper.replace("STATUS", "").strip())
        elif upper == "INVENTORY":
            self.inventory(p)
        elif re.fullmatch(r"(?:ACCEPT|PASS|RECEIVED)\s+#?\d+", upper):
            cmd, id_text = upper.split()
            id_text = id_text.lstrip("#")
            if p["role"] != "pantry":
                self.notify(handle, "Only a pantry account can accept, pass, or confirm receipt.")
            elif cmd == "RECEIVED":
                self.received(p, id_text)
            else:
                self.respond_offer(p, cmd, id_text)
        elif re.fullmatch(r"(?:CANCEL|EDIT)\s+#?\d+", upper):
            cmd, id_text = upper.split()
            if self.cancel(p, id_text.lstrip("#")) and cmd == "EDIT":
                self.begin_donation(p)
        elif upper in ("CANCEL", "EDIT"):
            self.notify(handle, f"Which donation? Reply {upper} <donation ID> (e.g. {upper} 104).")
        elif not p["role"]:
            self.notify(handle, "Welcome to PantryPulse. Text JOIN DONOR or JOIN PANTRY.")
        elif upper == "PROCEED" or upper.startswith("PROCEED "):
            self.choose_pantry(p, upper)
        elif upper == "DONATE":
            self.begin_donation(p)
        elif p["step"].startswith("donation_"):
            self.donation_intake(p, message)
        elif upper.startswith("DONATE ") or re.search(r"\b(?:donat\w*|have|offer|cans?|boxes?|bags?|beans?|rice|pasta|cereal)\b", message, re.I):
            self.begin_donation(p)
            self.donation_intake(p, message)
        else:
            self.notify(handle, "Text DONATE to start a donation, STATUS to see activity, or HELP for commands.")
        self.tables["inbox"].append({"message_key": key})
        self.save()

    def from_gemini(self, *, handle: str, space_id: str, message_id: str, items: list[dict]):
        key = f"{space_id}|{message_id}"
        if self.lookup("inbox", message_key=key): return
        p = self.part(handle, space_id)
        if p["role"] not in ("donor", "pantry"):
            self.notify(handle, "Please JOIN DONOR or JOIN PANTRY before donating.")
        else:
            errors = []
            for item in items:
                try: self.create_donation(handle, item)
                except (ValueError, TypeError, OverflowError, KeyError) as e: errors.append(str(e))
            if errors: self.notify(handle, f"Some items couldn't be recorded: {'; '.join(errors[:3])}. Please clarify their details.")
        self.tables["inbox"].append({"message_key": key})
        self.save()

    def pending(self):
        self.expire_offers()
        self.save()
        return [dict(x) for x in self.tables["outbox"] if not x["sent"]][:30]

    def ack(self, message_id):
        row = self.lookup("outbox", id=message_id)
        if row:
            row["sent"] = stamp()
            self.save()

    def recipient_space(self, handle):
        p = self.lookup("participants", handle=handle)
        return p["space_id"] if p else ""
