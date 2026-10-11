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
- Distance
- Donation acceptance policies
- Pickup or drop-off availability

Deterministic matching rules rank eligible pantries. AI helps interpret the input but does not independently decide whether food is safe or acceptable.

### 4. Photon coordinates the offer

Foodbridge uses **Photon Spectrum** to send an offer to an opted-in pantry through iMessage.

**Example:**

> Food offer #104: 24 unopened cans of beans available for drop-off before 6 PM.
>
> Reply ACCEPT 104 or PASS 104.

If the pantry declines or doesn't respond before the deadline, Foodbridge can offer the donation to the next eligible pantry.

### 5. Donation is reserved

When a pantry accepts, the backend reserves the donation for that pantry, preventing it from being assigned twice.

Photon notifies the donor and provides the agreed handoff details.

### 6. Donation is completed

After the pantry confirms receipt, Foodbridge marks the donation as completed and updates its records.

## System Architecture

| Component     | Technology            | Responsibility                                                  |
| ------------- | --------------------- | --------------------------------------------------------------- |
| Messaging     | Photon Spectrum       | Two-way communication with donors and pantries                  |
| AI processing | Google Gemini         | Extract structured donation information from natural language   |
| Backend       | TypeScript / Node.js  | Matching logic, offer sequencing, and donation state management |
| Database      | Supabase / PostgreSQL | Store pantry needs, donations, offers, and statuses             |
| Dashboard     | Next.js / React       | View donations, pantry needs, and matching activity             |

### Donation Lifecycle

**Submitted → Validated → Matched → Offered → Accepted → Reserved → Delivered → Completed**

An offer can also be declined or expire, allowing the system to try another eligible pantry.

If no suitable pantry accepts, the donor is notified.

## Core MVP Features

Our HackNC prototype focuses on one complete, functional donation workflow:

1. **Natural-language donation intake** — Donors describe available food without filling out a complex form.
2. **AI-powered data extraction** — Gemini converts donation descriptions into structured records.
3. **Needs-based pantry matching** — The backend ranks eligible pantries using stored needs and matching rules.
4. **Two-way messaging with Photon** — Pantries receive offers and respond with simple commands.
5. **Automatic offer progression** — Declined or expired offers can be routed to another pantry.
6. **Donation status tracking** — The system tracks offers, reservations, and completed donations.
7. **Basic dashboard** — Demonstrates matching decisions and donation progress.

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
2. Gemini extracts the item, quantity, location, and availability.
3. Foodbridge identifies multiple eligible pantries.
4. The first pantry receives a Photon message and replies `PASS 104`.
5. The system contacts the next pantry.
6. The second pantry replies `ACCEPT 104`.
7. Foodbridge reserves the donation and confirms the handoff with the donor.
8. The pantry confirms receipt, completing the donation.

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

Start the backend with `.venv/bin/python backend/pantrypulse_service.py`, then
run `npx tsx src/index.ts` from `photon-test` (with the Spectrum dependencies
installed). `src/pantrypulse.ts` uses the same flow. Configure `GEMINI_API_KEY`
and the Spectrum project credentials in your environment or `.env`.

A donor texts `JOIN DONOR`, then a message such as `24 unopened cans of beans`.
The bridge sends the description to `backend/search.py`, which parses the item
and recommends up to three pantries. The backend collects missing ZIP,
drop-off day/time, and packaging confirmation, then sends the numbered pantry
options. Guided `DONATE` intake uses the same pantry recommendation logic.

Reply `PROCEED 2` to choose option 2, or `PROCEED 104 2` to choose option 2 for
donation 104 when several donations are pending. `PROCEED` alone selects option
1 when exactly one donation is awaiting a choice. No pantry receives an offer
until the donor chooses. Choices are saved across backend restarts.

The selected pantry must be registered in the Photon demo, open during the
handoff window, and have enough remaining need for the donation. Otherwise the
donor can choose another option or cancel. The existing pantry commands
`ACCEPT <id>`, `PASS <id>`, and `RECEIVED <id>` continue to work; a pass or offer
expiry still advances to the next eligible pantry as before. Search currently
parses one food item per message.
