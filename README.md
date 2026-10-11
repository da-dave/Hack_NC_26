# FoodBridge 🍎
### Connecting surplus food with communities that need it.

**HackNC 2026**

## About the Project

FoodBridge is an AI-powered food donation platform that connects people with surplus food to local food pantries in need.

Through a simple text message, donors can offer food without searching for nearby organizations or filling out lengthy forms. Using Google Gemini, FoodBridge interprets donation messages and matches available food with pantries based on their inventory needs.

Our goal is to make food donation more accessible, efficient, and community-driven while helping reduce food waste and food insecurity.

## How It Works

1. **Send a Text:** Donors describe what they want to donate through iMessage.
2. **AI Processing:** Gemini extracts the food type, quantity, and availability.
3. **Smart Matching:** Our backend analyzes pantry inventory and identifies the top three pantries with the greatest need.
4. **Pantry Confirmation:** Pantries can accept or reject incoming donation offers.
5. **Donation Coordination:** The system helps connect donors with pantries to coordinate the donation.

## Tech Stack

- **Python & pandas** — Backend processing, inventory management, and pantry matching
- **Google Gemini API** — Natural language processing and structured donation extraction
- **Pydantic** — Structured data validation
- **Photon / Spectrum** — iMessage integration for donor and pantry communication
- **CSV** — Prototype database for pantry inventory, donors, and donation pledges

## Key Features

- AI-powered donation processing through natural language
- Pantry recommendations based on real-time calculated inventory shortages
- Donation acceptance and rejection workflow
- Text-based communication designed to simplify the donation process
- Scalable matching architecture for future geographic expansion

## Future Development

FoodBridge's initial prototype focuses on Chapel Hill, North Carolina, with plans to expand into surrounding communities and eventually support food donation networks across the country.

Future improvements include location-based matching, partnerships with real food pantries, delivery coordination, and a centralized database for larger-scale operations.

## Our Mission

We believe donating food should be as simple as sending a text.

**Less food wasted. More communities supported.**

---

*Built at HackNC 2026.*
