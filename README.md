# Trip Planner Skill for Claude Code

A Claude Code skill that extracts flight and hotel data from **Aviasales** and **Ostrovok**, compiles it into a polished travel itinerary with XLSX and mobile PDF export.

## What It Does

Drop your Aviasales and Ostrovok links into Claude Code and get:

- A color-coded HTML itinerary with all flight times, hotel details, baggage info, and TripAdvisor ratings
- Logistics analysis (timing conflicts, accommodation gaps, baggage mismatches)
- XLSX export with 18 data columns
- Mobile-friendly PDF for sharing (no prices, just the plan with clickable links)
- **Persistent trip memory** — every itinerary is recorded to `~/.trip-planner/`, so any agent using the skill (in any later session) knows what trips you've already planned, can avoid re-planning duplicates, and can answer "what trips have I planned?" without re-scraping

## Example Output

![Example itinerary](https://github.com/user-attachments/assets/placeholder)

The skill generates a self-contained HTML file like `example-output.html` included in this repo.

## Supported Sites

| Site | What It Extracts |
|------|-----------------|
| **Aviasales** (`avs.io/*`, `aviasales.ru/*`) | Flight times, airlines, baggage (included/add-on cost), charter flags, seller prices, refund policy |
| **Ostrovok** (`corp.ostrovok.ru/*`) | Hotel name/stars, all room types with prices, meal plans, cancellation deadlines, check-in/out times |
| **TripAdvisor** (via Ostrovok) | Rating, review count, direct link |

## Installation

### Option 1: Plugin marketplace (recommended)

The skill ships as a Claude Code plugin via the `kyzdes/claude-skills` marketplace. In Claude Code:

```
/plugin marketplace add kyzdes/claude-skills
/plugin install trip-planner@claude-skills
```

It then auto-updates on session start. Restart Claude Code (or `/reload-plugins`) after the first install.

### Option 2: Manual (development)

```bash
git clone https://github.com/kuzds/trip-planner-skill.git
ln -s "$(pwd)/trip-planner-skill/skills/trip-planner" ~/.claude/skills/trip-planner
```

## Requirements

- **Claude Code** with browser automation (Claude in Chrome extension)
- The skill uses `mcp__claude-in-chrome__*` tools to navigate SPAs that don't work with simple HTTP fetches

## Usage

Just paste your links:

```
вот перелёты и отели на июнь:
https://avs.io/lsP4
https://corp.ostrovok.ru/hotel/turkey/istanbul/mid8668983/adelmar_hotel_istanbul/...
https://avs.io/lruq
https://corp.ostrovok.ru/hotel/turkey/goreme/mid7475285/cappadocia_cave_suites/...
```

The skill triggers automatically and:
1. Opens each link in Chrome
2. Extracts structured data (prices, times, baggage, ratings)
3. Checks logistics (timing conflicts, gaps)
4. Generates an HTML file on your Desktop

You can also share screenshots from Aviasales/Ostrovok and ask to update specific parts of the itinerary.

## How It Works

Both Aviasales and Ostrovok are SPAs that return empty shells to simple HTTP requests. The skill uses browser automation to:

1. **Aviasales**: First fetches the `avs.io` redirect URL (contains encoded price/route data), then opens the page in Chrome where the ticket popup loads with full details. Battle-tested JS extractors pull flight segments, seller prices, and baggage info from the DOM.

2. **Ostrovok**: Navigates to the hotel page, waits for the SPA to hydrate (title changes from "Loading..." to hotel name), then extracts room listings with prices, TripAdvisor links, and ratings.

3. **Transfers**: Estimates common airport-to-hotel transfer times (Turkey routes built-in).

4. **Output**: Generates a single self-contained HTML file with inline CSS, SheetJS for XLSX export, and a print-optimized mobile layout for PDF.

## File Structure

```
trip-planner-skill/
├── skills/trip-planner/
│   ├── SKILL.md              # Skill instructions + JS extractors + workflow
│   ├── assets/template.html  # Reference HTML output template
│   ├── references/           # Transfer times, etc. (progressive disclosure)
│   └── scripts/
│       ├── export_trip.py    # HTML → XLSX + PDF (deterministic export)
│       └── trip_registry.py  # Persistent trip memory (recall / record)
├── example-output.html       # Reference HTML output
└── README.md

# Trip memory (created on first use, OUTSIDE the plugin so it survives updates):
~/.trip-planner/
├── trips.json                # Canonical registry of planned trips
└── trips.md                  # Human-readable mirror (auto-generated)
```

## License

MIT
