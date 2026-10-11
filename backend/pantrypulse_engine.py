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
    "donations": ["id", "donor", "item", "quantity", "unit", "zip", "start", "end", "packaging", "status", "pantry_id", "created", "recommendations"],
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

    def eligible_profile(self):
        used = {p["pantry_id"] for p in self.tables["participants"] if p["pantry_id"]}
        # Two seeded test pantries; subsequent registrations intentionally blocked.
        for pid in ("1", "2"):
            if pid not in used and (self.seed_pantries["pantry_id"] == pid).any():
                return pid
        return None

    def start_pantry(self, p):
        if p["pantry_id"]:
            self.notify(p["handle"], f"Already registered as pantry #{p['pantry_id']}. Reply STATUS PANTRY or INVENTORY.")
        elif not self.eligible_profile():
            self.notify(p["handle"], "The two demo pantry slots are filled. You can still use JOIN DONOR.")
        else:
            p["step"] = "pantry_name"
            p["draft"] = "{}"
            self.notify(p["handle"], "PantryPulse demo registration: What is your pantry name?")

    def finish_pantry(self, p, draft):
        pid = self.eligible_profile()
        if not pid:
            self.notify(p["handle"], "No remaining seeded pantry profiles. Registration not completed.")
            p["step"] = ""
            return
        p.update(role="pantry", pantry_id=pid, name=draft["name"], address=draft["address"], zip=draft["zip"], hours=draft["hours"], step="", draft="{}")
        self.notify(p["handle"], f"Registered {p['name']} (TEST pantry #{pid}). You can receive offers AND donate. Inventory uses seeded profile #{pid}. Reply INVENTORY or STATUS PANTRY. Do not use this fictional setup for real food deliveries.")

    def onboarding(self, p, text: str):
        draft = json.loads(p["draft"] or "{}")
        step = p["step"]
        if step == "pantry_name":
            if len(text) < 2:
                self.notify(p["handle"], "Please provide a pantry name.")
                return
            draft["name"] = text
            p["step"] = "pantry_address"
            self.notify(p["handle"], "What is the TEST pantry's street address? (Fictional address only for demo.)")
        elif step == "pantry_address":
            if len(text) < 7:
                self.notify(p["handle"], "Please enter a full sample street address.")
                return
            draft["address"] = text
            p["step"] = "pantry_zip"
            self.notify(p["handle"], "What is the pantry ZIP code (5 digits)?")
        elif step == "pantry_zip":
            if not re.fullmatch(r"\d{5}", text):
                self.notify(p["handle"], "Enter a five-digit ZIP code, e.g. 27514.")
                return
            draft["zip"] = text
            p["step"] = "pantry_hours"
            self.notify(p["handle"], "When can you receive donations? Reply 9am-5pm (every day for this demo).")
        elif step == "pantry_hours":
            if HOURS_RE.fullmatch(text.upper()):
                draft["hours"] = text.upper()
            else:
                try:
                    a, b = parse_time_window(datetime.now(TZ).date(), text)
                    if a.date() != b.date():
                        raise ValueError("Overnight hours not supported")
                    draft["hours"] = f"DAILY {a:%H:%M}-{b:%H:%M}"
                except ValueError:
                    self.notify(p["handle"], "Please reply 9am-5pm, or DAILY 09:00-17:00.")
                    return
            self.finish_pantry(p, draft)
        p["draft"] = json.dumps(draft)

    def begin_donation(self, p):
        p["step"] = "donation_item"
        p["draft"] = "{}"
        self.notify(p["handle"], "Describe one food donation, including quantity (example: 24 unopened cans of beans), or enter just the food name for guided entry.")

    def _finish_donation_time(self, p, draft, a, b):
        """Return done, next (ask packaging), or invalid."""
        if a >= b or b <= datetime.now(TZ) + timedelta(minutes=self.buffer_minutes):
            self.notify(p["handle"], "That time has passed or is too soon. Choose a later time.")
            return "invalid"
        draft["start"], draft["end"] = stamp(a), stamp(b)
        if draft.get("packaging") == "unopened":
            if draft.get("items"):
                for item in draft["items"]:
                    self.create_donation(p["handle"], {**draft, **item})
            else:
                self.create_donation(p["handle"], draft)
            p["step"], p["draft"] = "", "{}"
            return "done"
        p["step"] = "donation_packaging"
        self.notify(p["handle"], "Are the items unopened and shelf-stable? Reply YES or NO.")
        return "next"

    def donation_intake(self, p, text):
        draft = json.loads(p["draft"] or "{}")
        step = p["step"]
        if step == "donation_item":
            item = canonical(text)
            inventory_names = {x.lower(): x for x in self.seed_inventory["food_item"].tolist()}
            if item.lower() not in inventory_names:
                self.notify(p["handle"], "That item isn't in our demo inventory categories. Try Canned beans, Rice, Pasta, Peanut butter, Canned vegetables, Canned fruit, Oatmeal, Canned tuna, Shelf-stable milk, or Cereal.")
                return
            draft["item"] = inventory_names[item.lower()]
            units = self.seed_inventory[self.seed_inventory["food_item"].str.lower() == item.lower()]["unit"]
            draft["unit"] = units.iloc[0]
            p["step"] = "donation_quantity"
            self.notify(p["handle"], f"How many {draft['unit']}?")
        elif step == "donation_quantity":
            if not text.isdigit() or int(text) < 1:
                self.notify(p["handle"], "Please enter a positive whole number (e.g. 24).")
                return
            draft["quantity"] = int(text)
            p["step"] = "donation_zip"
            self.notify(p["handle"], "What is your ZIP code? (5 digits)")
        elif step == "donation_zip":
            if not re.fullmatch(r"\d{5}", text):
                self.notify(p["handle"], "Please enter a five-digit ZIP code (e.g. 27514).")
                return
            draft["zip"] = text
            if draft.get("start") and draft.get("end"):
                result = self._finish_donation_time(
                    p, draft, parse_dt(draft["start"]), parse_dt(draft["end"])
                )
                if result != "next":
                    return
            else:
                p["step"] = "donation_day"
                self.notify(p["handle"], "Which day can you drop off? Reply TODAY or TOMORROW.")
        elif step == "donation_day":
            # Keep old single-message 24-hour format for existing tests/testers.
            legacy = DATE_RE.fullmatch(text)
            if legacy:
                try:
                    day = parse_day(legacy.group(1))
                    a, b = parse_time_window(day, f"{legacy.group(2)}-{legacy.group(3)}")
                except ValueError:
                    self.notify(p["handle"], "Please reply TODAY, TOMORROW, or a date like 10/12.")
                    return
                if self._finish_donation_time(p, draft, a, b) != "next":
                    return
            else:
                try:
                    day = parse_day(text)
                except ValueError:
                    self.notify(p["handle"], "Which day? Reply TODAY or TOMORROW (or 10/12).")
                    return
                draft["day"] = day.isoformat()
                p["step"] = "donation_time"
                self.notify(p["handle"], "What time? Reply 1-4pm, or just 2pm (one-hour window).")
        elif step == "donation_time":
            if not draft.get("day"):
                # Recover an unfinished intake saved before this update.
                p["step"] = "donation_day"
                self.notify(p["handle"], "Which day? Reply TODAY or TOMORROW.")
                p["draft"] = json.dumps(draft)
                return
            try:
                a, b = parse_time_window(parse_day(draft["day"]), text)
            except ValueError:
                self.notify(p["handle"], "Reply with a time like 1-4pm or 2pm (include am/pm).")
                return
            if self._finish_donation_time(p, draft, a, b) != "next":
                return
        elif step == "donation_packaging":
            if text.upper() not in ("YES", "NO"):
                self.notify(p["handle"], "Please reply YES or NO.")
                return
            p["step"] = ""
            p["draft"] = "{}"
            if text.upper() == "NO":
                self.notify(p["handle"], "This MVP accepts only unopened shelf-stable donations. No donation was created.")
                return
            # Gemini can extract multiple independently matched items.
            # The scripted intake still supports one-item donations.
            draft["packaging"] = "unopened"
            if draft.get("items"):
                for item in draft["items"]:
                    self.create_donation(p["handle"], {**draft, **item})
            else:
                self.create_donation(p["handle"], draft)
            return
        p["draft"] = json.dumps(draft)

    def on_parsed_intake(self, *, handle: str, space_id: str,
                         message_id: str, items: list[dict],
                         zip_code: str = "", window: str = "",
                         packaging_verified: bool = False):
        """Start guided intake from Gemini output; save state across messages.

        Gemini extracts; this backend validates categories, quantities, units,
        and preserves search.py recommendations for the donor to choose.
        """
        key = f"{space_id}|{message_id}"
        if self.lookup("inbox", message_key=key):
            return
        p = self.part(handle, space_id)
        if p["role"] not in ("donor", "pantry"):
            self.notify(handle, "Please JOIN DONOR or JOIN PANTRY first.")
        else:
            accepted = []
            names = {str(x).lower(): str(x) for x in self.seed_inventory["food_item"].tolist()}
            for item in items:
                name = canonical(str(item.get("item", "")))
                if name.lower() not in names:
                    raise ValueError(f"Unsupported food category: {name}. Reply DONATE to use guided entry.")
                value = float(item.get("quantity") or 0)
                if not value.is_integer() or value <= 0:
                    raise ValueError("Please provide a positive whole-number quantity.")
                record = self.seed_inventory[self.seed_inventory["food_item"].str.lower() == name.lower()].iloc[0]
                canonical_unit = str(record["unit"])
                given_unit = str(item.get("unit") or "").strip()
                if given_unit and given_unit.casefold() != canonical_unit.casefold():
                    raise ValueError(f"For {name}, please use quantities in {canonical_unit}.")
                accepted.append({"item": names[name.lower()], "quantity": int(value), "unit": canonical_unit,
                                 **({"recommendations": item["recommendations"]} if "recommendations" in item else {})})
            if not accepted:
                raise ValueError("No recognizable donated items. Reply DONATE to use guided entry.")
            draft = {"items": accepted}
            if packaging_verified:
                draft["packaging"] = "unopened"
            if zip_code and re.fullmatch(r"\d{5}", zip_code):
                draft["zip"] = zip_code
            if window and DATE_RE.fullmatch(window):
                m = DATE_RE.fullmatch(window)
                a = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}").replace(tzinfo=TZ)
                b = datetime.fromisoformat(f"{m.group(1)}T{m.group(3)}").replace(tzinfo=TZ)
                if a < b and b > datetime.now(TZ) + timedelta(minutes=self.buffer_minutes):
                    draft.update(start=stamp(a), end=stamp(b))
            if not draft.get("zip"):
                p["step"] = "donation_zip"
                question = "What's your five-digit ZIP code?"
            elif not draft.get("start"):
                p["step"] = "donation_day"
                question = "Which day can you drop off? Reply TODAY or TOMORROW."
            elif not draft.get("packaging"):
                p["step"] = "donation_packaging"
                question = "Are all items unopened and shelf-stable? Reply YES or NO."
            else:
                p["step"] = ""
                question = ""
                for item in accepted:
                    self.create_donation(handle, {**draft, **item})
            p["draft"] = json.dumps(draft) if question else "{}"
            self.notify(handle, f"I understood: " + ", ".join(
                f"{x['quantity']} {x['unit']} {x['item']}" for x in accepted
            ) + (". " + question if question else ". Donation(s) recorded."))
        self.tables["inbox"].append({"message_key": key})
        self.save()

    def create_donation(self, donor: str, fields: dict):
        item = canonical(str(fields.get("item", "")))
        qty = int(fields.get("quantity", 0))
        zip_code = str(fields.get("zip", ""))
        start = parse_dt(str(fields.get("start", "")))
        end = parse_dt(str(fields.get("end", "")))
        packaging = str(fields.get("packaging", "unopened")).lower()
        matching = self.seed_inventory[self.seed_inventory["food_item"].str.lower() == item.lower()]
        if matching.empty or qty <= 0 or not re.fullmatch(r"\d{5}", zip_code) or not (start < end) or end <= datetime.now(TZ) + timedelta(minutes=self.buffer_minutes) or packaging not in ("unopened", "sealed"):
            raise ValueError("Invalid donation item, quantity, ZIP, drop-off window, or packaging")
        unit = matching.iloc[0]["unit"]
        donation = {"id": self.next_id("donations"), "donor": donor, "item": item, "quantity": str(qty), "unit": unit, "zip": zip_code, "start": stamp(start), "end": stamp(end), "packaging": packaging, "status": "searching", "pantry_id": "", "created": stamp(), "recommendations": ""}
        self.tables["donations"].append(donation)
        self.notify(donor, f"Donation #{donation['id']}: {qty} {unit} of {item}. Drop-off {start.strftime('%b %d %I:%M %p')}–{end.strftime('%I:%M %p')} ET. Choose a pantry from the options below.")
        from search import DonationItem, find_best_pantries, format_message
        recommendations = fields.get("recommendations")
        if recommendations is None:
            recommendations = find_best_pantries(item, self.dir)
        donation["recommendations"] = json.dumps(recommendations)
        donation["status"] = "awaiting_choice" if recommendations else "unmatched"
        self.notify(donor, f"Donation #{donation['id']} pantry options:\n" + format_message(
            DonationItem(food_item=item, quantity=qty, unit=unit), recommendations
        ) + (f"\nFor this donation, you can also reply PROCEED {donation['id']} <option number>." if recommendations else ""))
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
        # Existing demo pledges approved but not delivered count against projected shortage.
        pledges_path = self.dir / "pledges.csv"
        if pledges_path.exists():
            seeded_pledges = pd.read_csv(pledges_path, dtype=str, keep_default_na=False)
            for _, old in seeded_pledges.iterrows():
                if old.get("pantry_id") == pantry_id and old.get("food_item", "").lower() == item.lower() and old.get("unit") == row["unit"] and old.get("status") == "approved":
                    base -= int(old["quantity"])
        # Both reserved and completed donations count toward fulfilled needs.
        for d in self.tables["donations"]:
            if d["pantry_id"] == pantry_id and d["item"].lower() == item.lower() and d["status"] in ("reserved", "completed"):
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
        if (not receiver or not self.pantry_open(receiver, parse_dt(donation["start"]), parse_dt(donation["end"]))
                or self.need(pid, donation["item"]) < int(donation["quantity"])):
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
        options = []
        for p in self.tables["participants"]:
            if p["role"] != "pantry" or not p["pantry_id"] or p["pantry_id"] in attempted: continue
            if not self.pantry_open(p, parse_dt(donation["start"]), parse_dt(donation["end"])): continue
            available = self.need(p["pantry_id"], donation["item"])
            if available >= int(donation["quantity"]):
                options.append((available, p["pantry_id"], p))
        options.sort(key=lambda x: (-x[0], int(x[1])))
        if not options:
            donation["status"] = "unmatched"
            self.notify(donation["donor"], f"No remaining participating demo pantries can accept all of donation #{donation['id']}. Reply STATUS for details.")
            return
        _, pid, p = next((option for option in options if option[1] == preferred_id), options[0])
        expiry = min(now + timedelta(minutes=self.offer_minutes), parse_dt(donation["end"]) - timedelta(minutes=self.buffer_minutes))
        if expiry <= now:
            donation["status"] = "expired"
            self.notify(donation["donor"], f"Not enough time remains to coordinate donation #{donation['id']}.")
            return
        offer = {"id": self.next_id("offers"), "donation_id": donation["id"], "pantry_id": pid, "status": "pending", "created": stamp(now), "expires": stamp(expiry), "resolved": "", "reminded": ""}
        self.tables["offers"].append(offer)
        donation["status"] = "offered"
        donation["pantry_id"] = ""
        self.notify(p["handle"], f"PANTRYPULSE TEST OFFER #{donation['id']}\n{donation['quantity']} {donation['unit']} of {donation['item']} (unopened). Donor ZIP {donation['zip']}. Available {parse_dt(donation['start']).strftime('%b %d %I:%M %p')}–{parse_dt(donation['end']).strftime('%I:%M %p')} ET.\nReply ACCEPT {donation['id']} or PASS {donation['id']}. Offer valid until {expiry.strftime('%I:%M %p')} ET.")

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
            self.notify(p["handle"], f"Declined #{donation_id}; moving to the next eligible pantry.")
            self.next_offer(d)
            return
        # Recheck shortage at acceptance; another reservation could have claimed capacity.
        if self.need(p["pantry_id"], d["item"]) < int(d["quantity"]):
            offer["status"] = "declined"
            self.notify(p["handle"], f"Offer #{donation_id} no longer fits current inventory needs.")
            self.next_offer(d)
            return
        d.update(status="reserved", pantry_id=p["pantry_id"])
        self.notify(p["handle"], f"Reserved donation #{donation_id}. Once you receive it, text RECEIVED {donation_id}.")
        days, span = p["hours"].split(" ")
        a, b = span.split("-")
        # The allowed handoff is the INTERSECTION, not the full donor window.
        safe_from = max(parse_dt(d["start"]).strftime("%H:%M"), a)
        safe_to = min(parse_dt(d["end"]).strftime("%H:%M"), b)
        self.notify(d["donor"], f"Donation #{donation_id} ACCEPTED by {p['name']} (SIMULATED PANTRY).\nDemo address: {p['address']}, {p['zip']}.\nYour originally stated drop-off window: {parse_dt(d['start']).strftime('%b %d %I:%M %p')}–{parse_dt(d['end']).strftime('%I:%M %p')} ET.\nPantry can receive within this window: {safe_from}–{safe_to} ET.\nDo NOT travel to this fictional demo address.")

    def received(self, p, donation_id):
        d = self.lookup("donations", id=donation_id)
        if not d or d["pantry_id"] != p["pantry_id"] or d["status"] != "reserved":
            self.notify(p["handle"], f"No reserved donation #{donation_id} is awaiting receipt for your pantry.")
            return
        d["status"] = "completed"
        self.notify(p["handle"], f"Donation #{donation_id} marked received. Projected inventory has been updated.")
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
        self.notify(p["handle"], "TEST inventory (seed baseline + reservations/receipts):\n" + "\n".join(lines))

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
            self.notify(handle, "PantryPulse: JOIN DONOR, JOIN PANTRY, DONATE, PROCEED <option>, STATUS DONATIONS, STATUS PANTRY, INVENTORY, CANCEL <id>, EDIT <id>, ACCEPT <id>, PASS <id>, RECEIVED <id>.")
        elif upper == "JOIN PANTRY":
            self.start_pantry(p)
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
        else:
            self.notify(handle, "I didn't understand. Text DONATE to start a donation, STATUS to see activity, or HELP for commands. Conversational Gemini parsing connects separately.")
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
                except (ValueError, TypeError, OverflowError) as e: errors.append(str(e))
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
