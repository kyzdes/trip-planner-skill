---
name: trip-planner
description: "Build travel itineraries from Aviasales and Ostrovok — extract flight/hotel data and compile a self-contained HTML with XLSX/PDF export and optional Vercel deploy. Triggers on avs.io / aviasales.ru / corp.ostrovok.ru links (even pasted without explanation), on Russian travel terms (отпуск, поездка, перелёт, отель, бронирование, маршрут), and on planning a trip with dates/destinations. Also remembers previously planned trips across sessions in ~/.trip-planner/ (recall past trips first, record each when done), so it triggers on 'какие поездки я уже планировал', 'покажи прошлые маршруты', 'what trips have I planned'."
---

# Trip Planner

Build travel itineraries from Aviasales and Ostrovok. The job: take raw input (URLs, free-text, or screenshots), open the sites in a real browser, pull structured data, sanity-check logistics, and produce one self-contained HTML file the user can share, print, or deploy.

## Trigger Contexts

- User pastes `avs.io/*`, `aviasales.ru/*`, or `corp.ostrovok.ru/*` links (even without text)
- User describes a trip with dates and destinations
- User asks to compare options, check prices, swap a hotel, or recompute totals
- User shares screenshots of Aviasales/Ostrovok
- User uses Russian travel terms: `отпуск`, `поездка`, `перелёт`, `отель`, `бронирование`, `маршрут`, `обнови таблицу`, `добавь рейс`, `проверь цены`

## Workflow at a glance

```
Recall  → Load past-trip memory (run before Step 0; see "Recall" below)
Step 0  → Browser readiness check (do NOT skip)
Step 1  → Parse user input (URLs, text, screenshots)
Step 2  → Extract flight data (Aviasales, two-phase)
Step 3  → Extract hotel data (Ostrovok, browser-only)
Step 4  → Add transfers (see references/transfers.md)
Step 5  → Run logistics checks
Step 6  → Generate self-contained HTML (use assets/template.html)
Step 6.5→ Optional: Python export (XLSX + PDF) via scripts/export_trip.py
Step 7  → Present results to user
Step 8  → Optional: deploy to Vercel
Step 9  → Record the trip to memory (scripts/trip_registry.py)
```

Use `mcp__claude-in-chrome__browser_batch` whenever the next 2+ steps are independent navigates/JS-calls. Batched round-trips are ~3–5× faster than sequential.

---

## Recall: past trips (run this first)

This skill has a persistent memory of every trip it has planned. **Before** the browser check — recall has no browser dependency, and it answers pure history questions on its own — read the trip registry:

```bash
# honours $TRIP_PLANNER_HOME; defaults to ~/.trip-planner
cat "${TRIP_PLANNER_HOME:-$HOME/.trip-planner}/trips.json" 2>/dev/null || echo "no trips yet"
```

What to do with it:

- **History questions** ("какие поездки я уже планировал?", "покажи прошлые маршруты") — answer straight from the registry; no scraping needed.
- **Duplicate detection** — if the user's new request matches an existing trip (same destination + overlapping dates), say so and offer to **update that trip** (reuse its `html_path`, re-run the relevant steps) instead of starting from scratch.
- **Context** — past origins, airlines, and notes are useful priors ("last Turkey trip you flew Aeroflot MOW→IST").
- **Status** — each trip has a `status`: `planned` (default), `booked` (committed — be careful suggesting changes), or `archived` (past/closed — de-emphasise; don't surface unless asked). Set it with `trip_registry.py status --id <id> --set booked|archived`. Archived trips sort last in the registry.

If the file doesn't exist, there's no history yet — proceed silently to Step 0. The store is shared across **all** agents and sessions and persists on disk (see **Memory store** below).

---

## Step 0: Browser readiness check

Once you've recalled past trips (above) and the task needs scraping, **this is the first browser action** — call `mcp__claude-in-chrome__tabs_context_mcp` with `createIfEmpty: true` before any navigate/extract. This serves three purposes:

1. **Verifies the Claude-in-Chrome MCP is alive.** If the call errors, the user's extension is disconnected. Don't loop — tell them once: *"Чтобы продолжить, переподключи расширение Claude in Chrome (значок в правом верхнем углу браузера)."* Then stop and wait.
2. **Gives you a valid `tabId`** for the rest of the session. Reuse it; never invent IDs.
3. **Shows you what's already open** so you can avoid opening a 7th tab for a search you already did.

Why this matters: the MCP can disconnect silently during long sessions, and every downstream tool call will fail until reconnected. Catching it at Step 0 saves 20 retries.

---

## Step 1: Parse Input

Scan the user's message for:

- **Aviasales short links** (`avs.io/*`) — 301-redirect to `aviasales.ru/search/*`. The redirect URL itself is signal: `expected_price`, `expected_price_currency`, route code in path (e.g., `MOW2706IST2`), airline code in `t=` param (first 2 chars: `SU`=Aeroflot, `TK`=Turkish, `WY`=Oman Air).
- **Ostrovok hotel links** (`corp.ostrovok.ru/hotel/*`) — dates and guest count are in URL params.
- **Dates, cities, guests, airline preferences** in free text.
- **Screenshots** — if the user shares Aviasales/Ostrovok screenshots, read data visually.

### Aviasales URL constructor (when no link is given)

If the user describes a route in free text ("ищи Москва → Стамбул 27 июня на двоих"), build the search URL yourself:

```
https://www.aviasales.ru/search/{ORIGIN}{DDMM}{DESTINATION}{N_PAX}
```

- `ORIGIN`/`DESTINATION` — IATA city or airport code (`MOW`, `LED`, `IST`, `ZNZ`, `JRO`)
- `DDMM` — departure date, day-month with leading zeros (`2706` for 27 June)
- `N_PAX` — adult passenger count (`2`)

Examples: `MOW2706IST2`, `IST2906NAV2`, `MOW0309ZNZ2`, `DLM0607MOW2`.

For round-trips Aviasales also accepts `{ORIGIN}{DDMM}{DESTINATION}{DDMM_BACK}{N_PAX}`, but for multi-city use separate one-way searches — it's simpler and the prices line up better.

### Ostrovok hotel search (when no link is given)

If the user names a city without a URL, navigate to:

```
https://ostrovok.ru/hotel/{country-slug}/{city-slug}/?dates=DD.MM.YYYY-DD.MM.YYYY&guests=N
```

Examples: `/hotel/turkey/istanbul/`, `/hotel/tanzania/arusha/`, `/hotel/uae/dubai/`. From the result list, extract candidates with `a[href*="/hotel/{country-slug}/"]` and pick by rating + reviews + price (see Hotel search extractor below).

**Island/multi-town destinations** — Ostrovok uses the main town's slug, not the island name. If a tourist label (`santorini`, `mykonos`, `bali`) returns a 404, try the main town slug instead: Santorini → **thira**, Mykonos → **mykonos_town**, Bali → **denpasar** or **ubud**. The page title will confirm you landed on the right city ("Отели в Фире…" for Thira).

---

## Step 2: Extract Flight Data (Aviasales)

Aviasales is an SPA. `WebFetch` only returns shell HTML. Two phases:

### Phase A — Quick data from redirect URL

`WebFetch` on the `avs.io` link returns a 301 with the full `aviasales.ru` URL. Parse `expected_price` and route info from URL params — this gives you a price hint before opening a browser. Compare it later with the real ticket price; if they diverge by >15%, mention it to the user.

**Decode the `t=` param for segment times + layovers (no browser).** The redirect URL's `t=` string encodes every segment (`[airline][dep unix][arr unix][flight][orig][dest]`). Run the bundled decoder to get departure/arrival times and connection durations for multi-leg flights without opening the page:

```bash
python3 "${CLAUDE_SKILL_DIR:-skills/trip-planner}/scripts/parse_tstring.py" "<aviasales URL or t-string>"
```

It returns `segments` (UTC times, duration) and `layovers` (`is_layover` = gap < 24h at a shared airport — distinguishes a real connection from a round-trip's two directions). Use it to fill layover durations in the table without a browser round-trip.

### Phase B — Full data from browser

1. Navigate the link with `mcp__claude-in-chrome__navigate` (batch with the next JS-extract via `browser_batch` if you can).
2. Wait ~3–4 seconds inside a `setTimeout` Promise — Aviasales hydrates results progressively.
3. Run the flight extractor (below).
4. For multi-segment flights, scroll inside the popup or click into the "Details" view; the first leg is visible by default.

### Airline-specific filter / verification

If the user asks for a specific airline ("только Oman Air", "Turkish Airlines"), don't trust the "Оптимальный" label. Verify by reading airline logo `alt` text:

```javascript
const airlines = [...document.querySelectorAll('img[alt]')]
  .map(i => i.alt).filter(a => a && a.length < 30 && /^[A-ZА-Я]/.test(a));
[...new Set(airlines)];
```

Two-letter airline codes (`WY` = Oman Air, `SU` = Aeroflot, `TK` = Turkish, `EK` = Emirates, `EY` = Etihad, `QR` = Qatar) appear in the `t=` URL param and `img.avs.io/pics/al_square/{CODE}@...` image sources.

### What to extract per flight

- Route (airport codes + city names)
- Date, departure time, arrival time, duration
- Airline, flight type (regular / charter — charter has a distinct badge)
- Stops: count, layover airports, layover duration
- Baggage: hand luggage (weight × count), checked (weight × count), included / add-on cost
- Refund / exchange policy
- Price + seller list with individual seller prices

---

## Step 3: Extract Hotel Data (Ostrovok)

Ostrovok is also an SPA. `WebFetch` returns only config JS — **never** use it. Browser only.

1. Navigate to the hotel URL.
2. Wait until `document.title !== 'Загрузка отеля...'` — the page loads in two phases (shell first, then room data). 5–7 seconds is the safe wait. Scraping earlier gives zero rooms.
3. Run the room price extractor (see below).
4. For TripAdvisor data and Ostrovok rating, use the meta extractor.

### What to extract per hotel

- Name, stars, address, city
- Check-in / check-out times
- Room types — name, size, bed, meal plan, cancellation policy + **exact deadline date**, price, payment method
- Ostrovok rating + review count
- TripAdvisor rating (out of 5) + review count + TripAdvisor URL

---

## Step 4: Transfers

Insert transfer rows between airports and hotels. Reference times live in `references/transfers.md` — read only the region(s) you need. The table covers Turkey, Tanzania, Greece, Egypt, UAE.

If the trip is in a country not covered, estimate from public sources (Google Maps, hotel website) and explicitly tell the user you used a rough estimate.

---

## Step 5: Logistics Checks

Flag these in the output:

- **Accommodation gaps** — a night with no hotel (late arrival + hotel starts next day → mark as risk).
- **Check-in too early** — flight arrives before hotel check-in, accounting for transfer time. Usually fine if the hotel front desk is 24/7, but flag it.
- **Check-out too late** — flight departs and there isn't enough time for checkout + transfer + airport buffer (90 min domestic, 2h international).
- **Baggage mismatches** — `23 kg × 1` on a 2-passenger booking = one bag for two people. Always flag.
- **Non-refundable bookings** — show the deadline prominently; sort the notes by deadline (earliest first).
- **Tight layovers** — under 60 min international or 45 min domestic.
- **Airline-specific baggage on return** — return-leg airlines often allow less baggage than outbound (e.g. AJet 10 kg vs Aeroflot 23 kg). Compare and warn.

---

## Step 6: Generate HTML

Save to `~/Desktop/trip_[destination]_[dates].html`. The file must be **self-contained** — inline CSS, no external stylesheets, two export buttons (XLSX, PDF), data inline.

**Reference template:** `assets/template.html` in this skill. Copy its structure verbatim, then fill in trip-specific data. Don't redesign the CSS from scratch each time.

### Single source of truth: the `trip-data` JSON block

The template is data-driven. **Edit only the `<script id="trip-data" type="application/json">` block** — the route table, the summary card, the notes list, and both export buttons (XLSX, PDF) are all rendered from it by the page's JS. Do **not** hand-write `<tr>` rows or duplicate values into the XLSX/PDF functions; that's the old 4-section duplication that caused drift (KI-11). Change a date once, in the JSON, and every view updates.

JSON shape (see the template for the full example):

- `meta` — `title`, `h1`, `destination`, `subtitle`, `updated`, `xlsxFile`, `pdfTitle`, `pdfH1`, `pdfSubtitle`, `pdfNotes[]`.
- `rows[]` — one object per itinerary line: `type` (`flight`/`hotel`/`transfer`), `date`, `dateNote`, `title`, `sub`, `time`, `timeNote`, `details`, `detailsNote`, `rating` (`{ta, taReviews, taReviewsNum, ostrovok, taUrl}` or omit), `price`, `priceNum`, `links[]` (`{label, url}`), `x{}` (XLSX-only columns: `date, route, duration, operator, klass, meal, cancel, baggage`), and PDF helpers `day` (header on the first row of a day), `pdfTitle`, `pdfTime`, `pdfDetails`.
- `summary[]` — `{value, label}` cards (add `rub` as a number to make a card convertible by the currency toggle). `totals` — `{flights, hotels, total}` numbers (XLSX subtotal rows). Keep `priceNum`s consistent with `totals` (they should sum up).
- `notes[]` — HTML strings.

**Optional compare / currency fields (all off by default — omit them and the output is unchanged):**

- `rows[].alternatives[]` — `{operator, time, price, note}` other flight options for that leg; rendered as muted sub-lines under the chosen flight (KYZ-211). Use when presenting 2-3 options for the user to pick (D-08).
- top-level `variants[]` — `{label, total, nights, note}` whole-route options; rendered as stacked summary cards ("Вариант А / Б") (KYZ-212).
- `meta.fx` — `{EUR: <eur_per_rub>, USD: …}` with **live** rates fetched at generation time; adds a currency toggle that recomputes prices from each `priceNum` / summary `rub` (KYZ-213). Omit if you don't have current rates.

Because the table is rendered client-side, the trip data also lives in this JSON for tooling: `trip_registry.py` and `export_trip.py` read the `trip-data` block directly (with a fallback to scraping older, pre-refactor outputs).

### Auto-compute weekdays — don't guess

For each date, compute the weekday from the date itself instead of hand-mapping:

```javascript
// In the HTML <script>:
new Date('2026-06-27').toLocaleDateString('ru-RU', {weekday: 'long'})
// → "суббота"
```

Or, when generating the HTML from Python, use `datetime.strptime(d, '%d.%m.%Y').strftime('%A')` with locale set to `ru_RU.UTF-8`.

### Table structure

- Color-coded rows: blue (`#0071e3`) = flights, green (`#34c759`) = hotels, orange (`#ff9500`) = transfers, grey (`#b0b0b0`) = TBD/placeholder rows.
- Columns: `#`, Type, Date (+ weekday), Description, Time/Check-in-out, Details, Rating (TripAdvisor + Ostrovok for hotels), Price (2 чел.), Links.
- Hotel rows link to both Ostrovok and TripAdvisor.

### Summary card

Total, flights subtotal, hotels subtotal, trip duration, night count.

### Notes card

Logistics warnings, price disclaimers, baggage notes, cancellation deadlines (earliest first).

### XLSX export button

Use SheetJS (`https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js`). All data in flat columns with separate columns for TripAdvisor rating, review count, Ostrovok rating, booking URL, TripAdvisor URL. **Important: the XLSX button only works if the user opens the HTML in a real browser and clicks it.** For end-to-end automation use Step 6.5.

### PDF export button

Opens a new window with mobile-optimized card layout (max-width 420px), grouped by day, no prices (sharing-friendly), auto-triggers `window.print()`. Use `break-inside: avoid` for cards. Same caveat: requires user click.

---

## Step 6.5: Python export (when end-to-end automation is needed)

If the user wants the XLSX and PDF as files on disk without clicking buttons, run `scripts/export_trip.py`:

```bash
python3 "${CLAUDE_SKILL_DIR:-skills/trip-planner}/scripts/export_trip.py" \
    --html ~/Desktop/trip_destination_dates.html \
    --out-dir ~/Desktop/
```

This produces a real `.xlsx` (via `openpyxl`, no SheetJS) and a real `.pdf` (via `chrome --headless --print-to-pdf`) from the same source HTML. See the script's `--help` for options.

Why bother: the HTML buttons require user-action and don't work end-to-end in scripted flows. The Python path is the default for "I want everything ready to share."

---

## Step 7: Present Results

Tell the user:

- What was found (flight count, hotel count, total)
- Any logistics issues, sorted by severity
- Price changes vs. shared link expectations (if you compared with `expected_price`)
- Path to the HTML file (and XLSX/PDF if Step 6.5 ran)

When you've offered multiple comparable options (e.g. two flights with different price/time/airline trade-offs), **present them and ask the user to pick**, don't auto-choose. Choosing silently has burned past sessions.

---

## Step 8: Optional — deploy to Vercel

If the user asks to share a public link ("задеплой", "выложи", "deploy this"):

```bash
mkdir -p /tmp/trip-deploy
cp ~/Desktop/trip_*.html /tmp/trip-deploy/index.html
cd /tmp/trip-deploy
npx -y vercel@latest deploy --prod --yes
```

Vercel returns both a project alias (e.g. `https://<project>.vercel.app`) and a deployment URL. Use the project alias — it's stable and shorter. Verify it returns 200 before reporting success.

If the user is not logged in, `vercel whoami` will tell you. They'll need to run `vercel login` themselves (interactive).

---

## Step 9: Record the trip to memory

Once the HTML exists (Step 6) and you've presented it (Step 7), write the trip to the persistent registry so future agents recall it. Pass `--html` to auto-fill what can be parsed (destination, route, dates, total, flight/hotel counts) and add explicit flags for the rest:

```bash
python3 "${CLAUDE_SKILL_DIR:-skills/trip-planner}/scripts/trip_registry.py" record \
    --html ~/Desktop/trip_turkey_2026-06.html \
    --destination "Турция" --dates "20–29 июня 2026" \
    --start 2026-06-20 --end 2026-06-29 \
    --route "MOW → IST → NAV → DLM → VKO" --pax 2 \
    --total "≈316 047 ₽" \
    --notes "1 место багажа на двоих на DLM→VKO; Cave Suites Adult Only +12"
```

Rules:

- **Idempotent upsert by `--id`.** Omit `--id` and it's derived from destination + start month (`турция-2026-06`). Re-running with the same id updates the entry — it never duplicates and `created_at` is preserved.
- **After a Vercel deploy (Step 8)**, re-run `record` with the same id plus `--deploy-url https://<project>.vercel.app` to attach the public link.
- **Updating an existing trip** (the duplicate case from Recall) — record with the same id; only the fields you pass change.
- Explicit flags always override values parsed from `--html`.

> Path note: `${CLAUDE_SKILL_DIR}` is the absolute path to **this skill's** directory, set by Claude Code regardless of the current working directory — it's the portable way to call bundled scripts (works the same whether the skill is installed as a plugin or run from the repo). The `:-skills/trip-planner` fallback covers running from the repo root in development. Use this same form for `export_trip.py` (Step 6.5). Do **not** use `${CLAUDE_PLUGIN_ROOT}` here — that points at the plugin root, not the skill subdirectory.

---

## Memory store

Where the recalled/recorded data lives:

- **Location:** `~/.trip-planner/` by default; override with `$TRIP_PLANNER_HOME`.
- **Files:** `trips.json` (canonical, machine-managed) and `trips.md` (human-readable mirror, **auto-generated** — never hand-edit it).
- **Outside the plugin dir on purpose.** The plugin auto-updates (`claude plugin update` replaces its files), so anything stored inside the skill folder would be wiped. The registry survives updates and is shared by every agent and session.
- **Single writer.** Only `scripts/trip_registry.py` writes these files (atomic writes, consistent schema). To read, just `cat` the JSON; to change anything, use the script.
- **Per-trip fields:** `id`, `destination`, `dates`, `start`, `end`, `origin`, `route`, `pax`, `nights`, `flights`, `hotels`, `total`, `currency`, `status` (planned/booked/archived), `html_path`, `deploy_url`, `notes`, `data` (cached structured trip — see below), `created_at`, `updated_at`.
- **Cached structure → update without re-scraping.** Recording from a JSON-SoT HTML (`--html`) also caches that trip's `trip-data` block under `data`. To change a date or swap a hotel later, you don't need the browser: either edit the `trip-data` block in the existing HTML (all views re-render from it), or regenerate the file from memory with `render`:

```bash
python3 "${CLAUDE_SKILL_DIR:-skills/trip-planner}/scripts/trip_registry.py" render --id turkey-2026-06 --out ~/Desktop/trip_turkey_2026-06.html
```

Other commands: `list` (human table or `--json`), `get --id <id>`, `remove --id <id>`, `render --id <id> [--out <path>]`, `status --id <id> --set planned|booked|archived`.

---

## JS Extractors

Tested JavaScript snippets for `mcp__claude-in-chrome__javascript_tool`. They work on the live DOM of Aviasales and Ostrovok and are resilient to hashed CSS class names because they match on text content.

**Important:** never include `location.href`, `document.cookie`, or any session-id-bearing string in the JSON you return — the MCP blocks output containing those and you get `[BLOCKED: Cookie/query string data]` instead of your data.

### Flight extractor (Aviasales search results)

```javascript
new Promise(resolve => setTimeout(() => {
  const results = [];
  document.querySelectorAll('*').forEach(el => {
    const text = el.textContent.trim();
    if ((text.includes('в пути') || text.includes('в полёте')) && text.includes('₽') && text.length < 600 && text.length > 50) {
      results.push(text.substring(0, 500));
    }
  });
  const baggage = [];
  document.querySelectorAll('*').forEach(el => {
    const text = el.textContent.trim();
    if ((text.includes('багаж') || text.includes('кладь') || text.includes('Добавить багаж')) && text.length < 200) {
      baggage.push(text);
    }
  });
  resolve(JSON.stringify({
    title: document.title,
    flights: [...new Set(results)].slice(0, 6),
    baggage: [...new Set(baggage)].slice(0, 5)
  }, null, 2));
}, 4000))
```

### Airline list (for "только Oman Air" cases)

```javascript
const airlines = [...new Set(
  [...document.querySelectorAll('img[alt]')]
    .map(i => i.alt)
    .filter(a => a && a.length < 30 && a.length > 1)
)];
JSON.stringify(airlines, null, 2);
```

### Baggage cost check (Aviasales)

```javascript
const results = [];
document.querySelectorAll('*').forEach(el => {
  const text = el.textContent.trim();
  if (text.includes('Добавить багаж') && text.includes('₽') && text.length < 100) results.push(text);
  if (text.includes('Выбрать багаж') && text.length < 100) results.push(text);
  if (text === 'Без багажа' || (text.includes('багаж') && text.includes('кг') && text.length < 50)) results.push(text);
});
JSON.stringify([...new Set(results)], null, 2);
```

### Hotel rooms (Ostrovok)

```javascript
new Promise(resolve => setTimeout(() => {
  const rooms = [];
  document.querySelectorAll('*').forEach(el => {
    const text = el.textContent.trim();
    if (text.includes('₽') && text.length > 30 && text.length < 700) {
      if (text.match(/\d[\s ]?\d{3,}\s*₽/) &&
          (text.includes('Double') || text.includes('Single') || text.includes('Standard') ||
           text.includes('Twin') || text.includes('номер') || text.includes('Queen'))) {
        rooms.push(text.substring(0, 500));
      }
    }
  });
  resolve(JSON.stringify({
    title: document.title,
    rooms: [...new Set(rooms)].slice(0, 12)
  }, null, 2));
}, 6000))
```

### Hotel search by city (Ostrovok index page)

```javascript
const seen = new Set();
const results = [];
document.querySelectorAll('a[href*="/hotel/"]').forEach(a => {
  const slug = a.getAttribute('href').split('?')[0];
  if (seen.has(slug)) return;
  seen.add(slug);
  const card = a.closest('[class*="Card"], [class*="card"], li, article, div[class*="result"]');
  if (card) {
    const text = card.textContent.trim();
    if (text.length > 100 && text.length < 600) {
      results.push({ slug, summary: text.substring(0, 400) });
    }
  }
});
JSON.stringify(results.slice(0, 12), null, 2);
```

### Hotel meta + TripAdvisor (Ostrovok hotel page)

```javascript
const tripadvisor = [];
document.querySelectorAll('a[href*="tripadvisor"]').forEach(a => {
  const img = a.querySelector('img[alt]');
  tripadvisor.push({
    href: a.href.split('?')[0],
    rating: img ? img.alt : null
  });
});
const ratings = [];
document.querySelectorAll('*').forEach(el => {
  if (el.textContent.trim().match(/^\d[.,]\d$/) && el.textContent.trim().length <= 3) {
    const parent = el.parentElement;
    if (parent && parent.textContent.includes('отзыв')) {
      ratings.push({ rating: el.textContent.trim(), context: parent.textContent.trim().substring(0, 100) });
    }
  }
});
JSON.stringify({ tripadvisor: tripadvisor.slice(0, 3), ratings: ratings.slice(0, 3) }, null, 2);
```

### Quick scan alternatives (`find` tool)

When JS is overkill, use `mcp__claude-in-chrome__find`:

- Prices: `"цена стоимость ₽ рублей номер"`
- TripAdvisor: `"TripAdvisor tripadvisor rating отзыв"`
- Baggage: `"багаж добавить багаж стоимость"`
- Airlines: `"Oman Air Turkish Airlines Aeroflot"`

---

## Gotchas

Non-obvious behaviors discovered through real usage. Read this list before scraping.

- **Ostrovok + WebFetch = never.** SPA returns config-only shell. Browser is the only path. (KI-01)
- **Aviasales shared links do fresh searches.** The `avs.io` link doesn't preserve a specific ticket — it opens a search with the price as a hint. Real available flights and prices may differ from when the link was created. Always re-check on the live page. (KI-03)
- **Ostrovok loads in two phases.** Wait until `document.title !== 'Загрузка отеля...'` (≈5 sec) — scraping the shell gives zero rooms. (KI-04)
- **Aviasales popups scroll.** Multi-segment flights show only the first leg by default. Scroll inside the popup to see connections, layover times, second segment. (KI-02)
- **Prices are totals, not per-person.** Both sites show the figure for the requested passenger count. Don't divide. (D-04)
- **Charter flights** carry a special badge. They often have different baggage rules and no refunds. Always flag.
- **Baggage counts can mismatch passenger count.** `23 kg × 1` on a 2-pax booking = one bag for two people. Always flag.
- **Cancellation deadlines** are the single most actionable datapoint when the user is deciding whether to book now. Sort by earliest deadline and put them at the top of the Notes card.
- **Cookie/session strings break JS-tool output.** If your `JSON.stringify` includes `location.href`, `document.cookie`, or any session ID, the MCP returns `[BLOCKED: Cookie/query string data]` instead of your data. Strip those before serialising.
- **Browser MCP can disconnect.** A long session may drop the extension. Step 0 catches it; if it happens mid-session, surface the issue to the user immediately, don't retry-loop. (KI-09)
- **Edit-tool struggles with unicode-escaped JS inside HTML.** Characters like `→`, `₽`, `&rarr;` in `<script>` blocks confuse the Edit tool's matching. For HTML/JS surgery use a Python script with raw strings, or rewrite the file with the Write tool. (KI-07 / D-07)
- **`chrome --headless --print-to-pdf` is the reliable PDF path.** The `window.print()` button in the HTML works for humans but doesn't work end-to-end via the MCP (`file://` URLs get mangled). Use `scripts/export_trip.py`. (KI-08)
- **`browser_batch` is significantly faster** for predictable sequences (navigate → wait → JS-extract → screenshot). Batch them whenever the next 2+ steps are independent. The MCP nudges you toward batches; listen.
- **Prefer ARK to JRO for Arusha-bound trips** — ARK is in town, JRO is ~50 km out. Bigger airport, but worse logistics for "land and sleep" use cases.
- **Trip memory lives in `~/.trip-planner/`, outside the plugin dir.** It survives `claude plugin update` and is shared across agents/sessions. Never store it inside the skill folder, and never hand-edit `trips.md` (it's regenerated from `trips.json` on every write). Read it at Recall; write it at Step 9.

---

## When in doubt

If a comparable trade-off appears (two flights, two hotels, two routings), present both options to the user with the trade-off named ("Аэрофлот 41к / прямой / днём  vs S7 47к / прямой / вечером — какой берём?") instead of silently picking. Past sessions burned trust by auto-choosing in ambiguous cases.

If a JS extractor returns nothing or partial data, fall back to a screenshot — the user can read the popup directly, and you can describe what you see. The screenshot fallback is also useful when the DOM structure changes between releases.
