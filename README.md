# Foodbridge

**Connecting food donors with the pantries that need their donations most, through AI-powered matching and everyday messaging.**

*Built for HackNC 2026 | Community Track*

## The Problem

Food insecurity and food waste exist side by side.

Individuals, businesses, and organizations often have surplus food they are willing to donate. Meanwhile, food pantries have specific, changing inventory needs.

The challenge is connecting the two efficiently.

- **Donors** may not know which nearby pantry needs their food or can accept it.
- **Pantries** may receive donations that don't match their current needs.
- **Coordination** often requires phone calls, emails, and manual follow-ups.
- **Timing matters:** a pantry may be unable to accept a donation even when the food itself is useful.

The result is a coordination gap between available food and community demand.

## Our Solution

**Food is an AI-assisted food donation matching and coordination platform that connects donors with nearby food pantries through two-way messaging.**

Instead of requiring donors to research pantries individually, Foodbridge lets them describe what they have available in natural language.

The system structures the donation information, identifies suitable pantries based on their stated needs and acceptance requirements, and contacts them through **Photon's Spectrum messaging framework**.

Pantries can accept or decline offers directly through a message. Once a pantry accepts, the donor receives the handoff details.

**Our goal is to make donating food as simple as sending a message.**

## How It Works

### 1. Donor submits a donation

A donor describes their available food, quantity, location, and delivery availability.

**Example:**

> I have 24 unopened cans of beans in Chapel Hill. I can drop them off before 6 PM.

### 2. AI structures the donation

Google Gemini converts the natural-language description into structured data:

- Food item and category
- Quantity
- Location
- Availability window
- Relevant handling or eligibility details

If important information is missing, the system asks the donor for clarification.

### 3. Foodbridge finds suitable pantries

The backend compares the donation against pantry profiles and their stated needs.

Matching considers:

- Requested food categories
- Quantity and capacity
- Pickup or drop-off availability

Deterministic matching rules rank eligible pantries. AI helps interpret the input but does not independently decide whether food is safe or acceptable.

### 4. Photon coordinates the offer

Foodbridge first sends the donor the best pantry and up to two backups. Once the donor replies `PROCEED` or `PROCEED <option>`, **Photon Spectrum** sends the offer to the selected opted-in pantry through iMessage.

**Example:**

> Food offer #104: 24 unopened cans of beans available for drop-off before 6 PM.
>
> Reply ACCEPT 104 or PASS 104.

If the pantry declines or doesn't respond before the deadline, Foodbridge can offer the donation to the next eligible pantry.

### 5. Acceptance completes the offer

When a pantry replies `ACCEPT <id>`, the offer is completed and the donor gets
handoff details. `PASS <id>` or a timeout automatically contacts the next saved
backup from search. No new ranking is performed during fallback.

`RECEIVED <id>` is an optional delivery confirmation; acceptance already completes
the coordination workflow. Accepted offers reduce projected shortages, while
physical stock on hand remains the inventory CSV's recorded value.

## System Architecture

| Component | Implementation | Responsibility |
| --- | --- | --- |
| Messaging | Photon Spectrum / TypeScript | Forward incoming messages; deliver queued backend replies |
| Intake and state | Python JSON bridge / PantryPulse engine | Collect missing fields, save choices, sequence offers |
| Search | Python / Gemini / pandas | Parse the complete offer and rank pantry inventory needs |
| Storage | CSV files in `backend/data` | Pantry and donor profiles, inventory, donations, offers, inbox/outbox |

There is no Supabase connection or dashboard implementation in this repository.
The pantry data has no coordinates, so ranking uses remaining inventory need,
registered messaging conversations, and receiving hours; it does not calculate distance.

**Collecting details → Search → Awaiting donor choice → Offered → Completed on acceptance**

A rejection or timeout advances through the saved suggestions. Exhausting the
suggestions marks the offer unmatched and notifies the donor.

## Core MVP Features

Our HackNC prototype focuses on one complete, functional donation workflow:

1. **Natural-language donation intake** — Donors describe available food without filling out a complex form.
2. **AI-powered data extraction** — Gemini converts donation descriptions into structured records.
3. **Needs-based pantry matching** — The backend ranks eligible pantries using stored needs and matching rules.
4. **Two-way messaging with Photon** — Pantries receive offers and respond with simple commands.
5. **Automatic offer progression** — Declined or expired offers can be routed to another pantry.
6. **Donation status tracking** — The system tracks donor choices, pending offers, acceptance and optional receipt.
7. **Persistent conversations** — Intake details, choices and pending offers survive backend restarts.

For the hackathon, pantry profiles and inventory needs may use clearly labeled sample data. Real-world deployment would require participating pantries to maintain or verify their needs.

## What Makes Foodbridge Different?

Foodbridge is not intended to be another food pantry directory.

Traditional directories help donors **find organizations**. Foodbridge aims to help donors **coordinate an actual donation** based on what an organization currently needs.

Its defining features are:

- **Needs-based matching:** Donation offers are compared with specific pantry requests rather than sent indiscriminately.
- **Messaging-first interaction:** Pantries can respond without learning another dashboard.
- **Automated coordination:** The system manages offer progression, deadlines, and confirmations.
- **Natural-language accessibility:** Donors can describe available food conversationally.

The central innovation is combining structured matching with a familiar, two-way communication channel.

## Demo Scenario

Our demonstration follows a single donation from start to finish:

1. A donor offers 24 cans of beans through a message.
2. Photon collects missing quantity, donor address, ZIP, drop-off window and packaging details.
3. Gemini parses the complete offer and search ranks the participating pantries.
4. The donor replies `PROCEED` to choose the best option.
5. The first pantry receives an offer and replies `PASS 104`.
6. The system contacts the next saved backup.
7. That pantry replies `ACCEPT 104`, completing the offer and notifying the donor.
8. The pantry may optionally confirm physical receipt.

This demonstrates not only finding a potential match, but also coordinating acceptance and tracking the result.

## Scope and Safety

The initial prototype focuses on **unopened, shelf-stable food donations** and **opted-in pantry partners**.

Foodbridge does not independently certify food safety, guarantee pantry availability, arrange transportation, or verify that a donation has been delivered without confirmation.

Food acceptance decisions remain with participating pantries. Donor contact and location details should be shared only as necessary for an agreed handoff.

## Future Development

Potential extensions include:

- Live pantry inventory and needs management
- Business and grocery-store donation integrations
- Recurring donations and automated matching
- Transportation and volunteer coordination
- Support for additional messaging channels
- Donation impact analytics
- Pantry-mediated distribution to individual households

## Our Vision

**A community where usable food reaches the people who need it, with less guesswork, less coordination overhead, and fewer missed opportunities to help.**

Foodbridge brings donors and food pantries together by turning a simple message into a coordinated donation.


### Run the Photon donor-choice flow

From the repository root, start the Python bridge:

```sh
.venv/bin/python backend/pantrypulse_service.py
```

In a second terminal, install and start the Photon agent:

```sh
cd photon-test
npm install
npm start
```

The start script loads the repository root `.env`.
`photon-test/src/pantrypulse.ts` is the same agent. `echo-backup.ts` is only an
old echo demo.
Configure `GEMINI_API_KEY`, optional `GEMINI_MODEL`, `SPECTRUM_PROJECT_ID` and
`SPECTRUM_PROJECT_SECRET` in `.env` or the environment.

A pantry uses `JOIN PANTRY <ID>` to link its messaging conversation to a profile
in `pantries.csv`, then supplies missing ZIP and receiving hours. `JOIN PANTRY`
alone can match the sender's phone number against `contact_phone`. All seeded
profiles are supported; only registered pantries open during the donation window
are suggested, so Photon has a conversation in which to deliver each offer.

A donor texts `JOIN DONOR`, then describes one food donation. Photon collects
missing quantity/unit, address, ZIP, drop-off day/time and unopened shelf-stable
confirmation before sending the entire assembled offer to `search.py`. Known
donor name/address are loaded from `donors.csv` by phone number; new or corrected
details persist in `pp_participants.csv` and each donation record.

Search returns the best pantry and up to two ordered backups. Reply `PROCEED`
for option 1, `PROCEED 2` for option 2, or `PROCEED 104 2` when several donations
are awaiting a choice. No pantry gets an offer until the donor proceeds. A
rejection or timeout follows the remaining saved suggestions in order; it does
not contact a fourth pantry. `ACCEPT <id>` completes the offer. A pantry can
accept more than its listed shortage, including a no-shortage fallback; its
acceptance is the final decision.

### Storage and pledges

| File | Use |
| --- | --- |
| `pantries.csv` | Pantry IDs, names, addresses and contact phones |
| `inventory.csv` | Recorded stock, target quantities and food units |
| `donors.csv` | Existing donor names, addresses and phone numbers |
| `pp_participants.csv` | Live donor/pantry identities, conversations and unfinished intake |
| `pp_donations.csv` | Offers, donor addresses, saved suggestions, chosen pantry and completion status |
| `pp_offers.csv` | Each pantry attempt, acceptance/rejection and timeout |
| `pp_inbox.csv`, `pp_outbox.csv` | Message deduplication and queued replies |
| `pledges.csv` | Legacy sample data; unused by the active workflow |

`pledges.csv` is unnecessary for this workflow: donations and offer attempts
already store those commitments. It is preserved as historical sample data but
is not subtracted from inventory needs. Both search and the engine subtract
accepted/completed offers once when computing projected shortage. Acceptance
does not claim the food was physically delivered or change stock on hand.

Run offline workflow tests with `.venv/bin/python -m unittest discover -s tests`.
