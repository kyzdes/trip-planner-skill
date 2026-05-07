---
name: trip-planner
description: "Extract flight and hotel data from Aviasales and Ostrovok, compile into a polished travel itinerary with XLSX/PDF export. Use this skill whenever the user shares avs.io or aviasales.ru links, corp.ostrovok.ru hotel links, or discusses planning a trip — even if they just paste links without explanation. Also triggers on Russian travel terms: отпуск, поездка, перелёт, отель, бронирование, маршрут. Handles multi-leg itineraries, logistics analysis, price tracking, and TripAdvisor ratings."
---

# Trip Planner

Build travel itineraries from Aviasales and Ostrovok links. The core job: take raw links, open them in the browser, pull structured data, check logistics, and produce a single HTML file the user can share or print.

## Trigger Contexts

- User pastes `avs.io/*`, `aviasales.ru/*`, or `corp.ostrovok.ru/*` links (even without any text)
- User describes a trip plan with dates and destinations
- User asks to compare flight/hotel options or check prices
- User says "обнови таблицу", "добавь рейс", "поменяй отель", "проверь цены"
- User shares screenshots from Aviasales or Ostrovok (extract data from the image)

## Step 1: Parse Input

Scan the user's message for:
- **Aviasales short links** (`avs.io/*`) — these 301-redirect to `aviasales.ru/search/*`. The redirect URL itself is gold: `expected_price`, `expected_price_currency`, route code in path (e.g., `MOW2206IST2`), airline code in `t=` param (first 2 chars: `SU`=Aeroflot, `TK`=Turkish Airlines).
- **Ostrovok hotel links** (`corp.ostrovok.ru/hotel/*`) — dates and guest count are in the URL params.
- **Dates, destinations, guest count, preferences** mentioned in free text.
- **Screenshots** — if the user shares Aviasales/Ostrovok screenshots, read the data visually.

## Step 2: Extract Flight Data (Aviasales)

Aviasales is an SPA — `WebFetch` gets only the shell HTML. Two-phase approach:

**Phase A — Quick data from redirect URL:**
Use `WebFetch` on the `avs.io` link. It returns a 301 with the full `aviasales.ru` URL. Parse `expected_price` and route info from the URL params. This gives you a price estimate and route even before opening the browser.

**Phase B — Full data from browser:**
1. Open the link with `mcp__claude-in-chrome__navigate`. Wait 2 seconds.
2. The shared link usually auto-opens a ticket detail popup. Run the flight JS extractor (see below).
3. If JS returns empty, take a screenshot — the popup is visible and readable.
4. For multi-segment flights, scroll down inside the popup to see connections.

**What to extract per flight:**
- Route (airport codes and city names)
- Date, departure time, arrival time, duration
- Airline, flight type (regular / charter)
- Stops: count, airports, layover duration
- Baggage: hand luggage (weight × count), checked (weight × count), included or add-on cost
- Refund/exchange policy
- Price + seller list with individual prices

## Step 3: Extract Hotel Data (Ostrovok)

Ostrovok is also an SPA. `WebFetch` returns only config JS — completely useless. Browser is required.

1. Navigate to the hotel URL. Wait 2–3 seconds — the page title changes from "Загрузка отеля..." to the hotel name when ready.
2. Run the hotel JS extractor (see below), or use `mcp__claude-in-chrome__find` for a quick scan.
3. For TripAdvisor data, use the TripAdvisor JS extractor.

**What to extract per hotel:**
- Name, stars, address, city
- Check-in / check-out times
- All room types with: name, size, bed type, meal plan, cancellation policy + deadline, price, payment method
- Ostrovok rating + review count
- TripAdvisor: URL, rating (out of 5), review count

## Step 4: Estimate Transfers

Add transfer rows between airports and hotels. Use these reference times:

| Route | Duration |
|-------|----------|
| Istanbul IST → city center | 1–1.5h |
| Nevşehir NAV → Göreme | 20–30 min |
| Dalaman DLM → Fethiye | 1–1.5h |
| Dalaman DLM → Marmaris | 1.5h |
| Antalya AYT → Kemer | 1h |
| Antalya AYT → Side | 1.5h |
| Antalya AYT → Alanya | 2.5h |

## Step 5: Check Logistics

Look for these problems and flag them in the output:
- **Accommodation gaps** — nights with no hotel booked (e.g., late arrival, hotel starts next day)
- **Check-in too early** — flight arrives before hotel check-in, accounting for transfer time
- **Check-out too late** — flight departs and there's not enough time for checkout + transfer + 2h airport buffer
- **Baggage mismatches** — fewer checked bags than passengers
- **Non-refundable bookings** — highlight deadlines prominently

## Step 6: Generate HTML

Save to `~/Desktop/trip_[destination]_[dates].html`. The file must be self-contained (inline CSS, no external stylesheets) with two export buttons.

**Table structure:**
- Color-coded rows: blue (`#0071e3`) = flights, green (`#34c759`) = hotels, orange (`#ff9500`) = transfers
- Columns: #, Type, Date, Description, Time/Check-in-out, Details, Rating (TripAdvisor + Ostrovok for hotels), Price, Links
- Each hotel row links to both Ostrovok and TripAdvisor

**Summary card:** Total, flights subtotal, hotels subtotal, trip duration, night count.

**Notes card:** Logistics warnings, price disclaimers, baggage notes, cancellation deadlines.

**XLSX export:** Use SheetJS (`https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js`). Include all data in flat columns with separate columns for TripAdvisor rating, review count, Ostrovok rating, booking URL, TripAdvisor URL.

**PDF export:** Opens a new window with a mobile-optimized card layout (max-width 420px). Cards grouped by day. No prices — only links, times, details, ratings. Auto-triggers `window.print()`. Use `break-inside: avoid` for cards.

See `example-output.html` in this skill's directory for the reference implementation.

## Step 7: Present Results

Tell the user:
- What was found (flight count, hotel count, total)
- Any logistics issues
- Price changes vs. shared link expectations
- Path to the HTML file

---

## JS Extractors

Tested JavaScript snippets for `mcp__claude-in-chrome__javascript_tool`. These work against the live DOM of Aviasales and Ostrovok as of April 2026.

### Flight extractor (Aviasales — ticket popup)

```javascript
const results = [];
document.querySelectorAll('*').forEach(el => {
  const text = el.textContent.trim();
  if ((text.includes('в пути') || text.includes('в полёте')) && text.includes('₽') && text.length < 600 && text.length > 50) {
    results.push(text.substring(0, 500));
  }
});
const sellers = [];
document.querySelectorAll('*').forEach(el => {
  const text = el.textContent.trim();
  if (text.includes('₽') && (text.includes('Купить') || text.includes('Ищем на')) && text.length < 200) {
    sellers.push(text);
  }
});
const baggage = [];
document.querySelectorAll('*').forEach(el => {
  const text = el.textContent.trim();
  if ((text.includes('багаж') || text.includes('кладь') || text.includes('Добавить багаж')) && text.length < 200) {
    baggage.push(text);
  }
});
JSON.stringify({ flights: results.slice(0, 5), sellers: sellers.slice(0, 5), baggage: baggage.slice(0, 5) }, null, 2);
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
JSON.stringify(results, null, 2);
```

### Room prices (Ostrovok)

```javascript
const rooms = [];
document.querySelectorAll('*').forEach(el => {
  const text = el.textContent.trim();
  if (text.includes('₽') && text.includes('номер') && text.length > 50 && text.length < 500) {
    if (text.match(/\d[\s\u00a0]\d{3}\s*₽/)) {
      rooms.push(text.substring(0, 400));
    }
  }
});
const unique = [...new Set(rooms)];
JSON.stringify(unique.slice(0, 15), null, 2);
```

### Specific room type (Ostrovok)

```javascript
// Replace ROOM_NAME before running
const ROOM_NAME = 'Standard Double Room';
const results = [];
document.querySelectorAll('*').forEach(el => {
  const text = el.textContent.trim();
  if (text.includes(ROOM_NAME) && text.includes('₽') && text.length < 500) {
    results.push(text.substring(0, 400));
  }
});
JSON.stringify(results.slice(0, 5), null, 2);
```

### Hotel meta + TripAdvisor (Ostrovok)

```javascript
const tripadvisor = [];
document.querySelectorAll('a[href*="tripadvisor"]').forEach(a => {
  const img = a.querySelector('img[alt]');
  tripadvisor.push({
    href: a.href,
    text: a.textContent.trim().substring(0, 100),
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

### Quick scan alternatives (using `find` tool)

When JS is overkill, use `mcp__claude-in-chrome__find`:
- Prices: `"цена стоимость ₽ рублей номер"`
- TripAdvisor: `"TripAdvisor tripadvisor rating отзыв"`
- Baggage: `"багаж добавить багаж стоимость"`

---

## Gotchas

These are non-obvious behaviors discovered through real usage:

- **Ostrovok never works with WebFetch.** It's an SPA that returns only config JS. Always use the browser. No exceptions.
- **Aviasales shared links do fresh searches.** The `avs.io` link doesn't preserve a specific ticket — it opens a search with the price as a hint. The actual available flights and prices may differ from when the link was created.
- **Wait after Ostrovok navigation.** The page loads in two phases: first the shell (title "Загрузка отеля..."), then the room data. If you scrape too early, you get zero rooms. Wait until the title changes to the hotel name, or just sleep 2–3 seconds.
- **Aviasales ticket popups scroll.** Multi-segment flights show only the first leg initially. Scroll down inside the popup to see connections, layover times, and the second segment.
- **Prices are always for all passengers.** Both sites show totals for the requested passenger count, not per-person. Don't divide.
- **Charter flights** have a special badge on Aviasales. These often have different baggage rules and no refunds. Always flag them.
- **Baggage counts matter.** "23 kg × 1" on a 2-passenger booking means one bag for two people. Flag this mismatch.
- **Cancellation deadlines** are the most actionable data point for users deciding whether to book now. Show them prominently.
