# Technical Documentation: Trip Planner Skill

## 1. Обзор архитектуры

Trip Planner — это **prompt-based skill** для Claude Code. Скилл не содержит исполняемого кода — всё описано в `SKILL.md` как набор инструкций, JS-сниппетов и правил, которые Claude Code интерпретирует и выполняет в реальном времени.

### Почему prompt-based, а не код?

1. **SPA-сайты** (Aviasales, Ostrovok) невозможно парсить обычным HTTP — они возвращают пустой shell. Нужен браузер.
2. **Claude in Chrome MCP** даёт доступ к реальному DOM после гидратации SPA.
3. **Гибкость** — Claude адаптируется к изменениям DOM, может fallback на скриншот.
4. **Без инфраструктуры** — не нужен сервер, БД, или pipeline. Один файл `SKILL.md` — весь продукт.

---

## 2. Workflow: пошаговый разбор

### Step 1: Парсинг входных данных

Скилл анализирует сообщение пользователя:

```
Вход: "вот перелёты https://avs.io/lsP4 https://avs.io/lruq
       и отели https://corp.ostrovok.ru/hotel/turkey/istanbul/..."
       
Результат:
  flights: [
    { type: "avs.io", url: "https://avs.io/lsP4" },
    { type: "avs.io", url: "https://avs.io/lruq" }
  ]
  hotels: [
    { type: "ostrovok", url: "https://corp.ostrovok.ru/hotel/..." }
  ]
  context: { dates: "июнь", destination: "Турция", guests: 2 }
```

**Детали парсинга Aviasales URL после redirect:**
```
https://aviasales.ru/search/MOW2206IST2?expected_price=48991&expected_price_currency=rub&t=SU1234...

Извлекается:
  - Маршрут: MOW → IST
  - Дата: 22.06
  - Кол-во пассажиров: 2
  - Ожидаемая цена: 48991 RUB
  - Авиакомпания (первые 2 символа t=): SU → Аэрофлот
```

### Step 2: Извлечение данных о перелётах

**Фаза A — WebFetch redirect:**
```
WebFetch("https://avs.io/lsP4")
  → 301 Redirect
  → "https://aviasales.ru/search/MOW2006IST2?expected_price=48991..."
```

**Фаза B — Браузер + JS:**
```
mcp__claude-in-chrome__navigate("https://avs.io/lsP4")
  → wait 2s
  → mcp__claude-in-chrome__javascript_tool(flight_extractor)
  → JSON { flights: [...], sellers: [...], baggage: [...] }
```

**JS-экстрактор перелётов** ищет в DOM элементы, содержащие:
- `"в пути"` или `"в полёте"` + `"₽"` (длина 50-600 символов) — данные о рейсе
- `"₽"` + `"Купить"` или `"Ищем на"` (< 200 символов) — цены продавцов
- `"багаж"` или `"кладь"` или `"Добавить багаж"` (< 200 символов) — информация о багаже

**Экстрактор стоимости багажа** дополнительно проверяет:
- `"Добавить багаж"` + `"₽"` — платный багаж с ценой
- `"Выбрать багаж"` — опциональный багаж
- `"Без багажа"` — багаж не включён
- `"багаж"` + `"кг"` — вес багажа

### Step 3: Извлечение данных об отелях

**Ostrovok НИКОГДА не работает через WebFetch** — это ключевое правило. Только браузер.

```
mcp__claude-in-chrome__navigate("https://corp.ostrovok.ru/hotel/...")
  → wait 2-3s (title: "Загрузка отеля..." → "Hotel Name")
  → mcp__claude-in-chrome__javascript_tool(room_prices_extractor)
  → mcp__claude-in-chrome__javascript_tool(hotel_meta_extractor)
```

**Экстрактор цен номеров** ищет:
- Текст с `"₽"` + `"номер"` (50-500 символов)
- Regex: `/\d[\s\u00a0]\d{3}\s*₽/` — формат цены типа "13 992 ₽"
- Дедупликация через `Set`

**Экстрактор метаданных + TripAdvisor:**
- Все ссылки `<a href*="tripadvisor">` — URL, текст, рейтинг из `alt` атрибута `<img>`
- Рейтинг Ostrovok: текст `^\d[.,]\d$` рядом с `"отзыв"`

### Step 4: Оценка трансферов

Встроенная таблица для Турции:

| Маршрут | Время | Примечания |
|---------|-------|------------|
| IST → центр Стамбула | 1-1.5ч | Такси или Havaist |
| NAV → Göreme | 20-30 мин | Такси от аэропорта |
| DLM → Fethiye | 1-1.5ч | Трансфер/такси |
| DLM → Marmaris | 1.5ч | |
| AYT → Kemer | 1ч | |
| AYT → Side | 1.5ч | |
| AYT → Alanya | 2.5ч | |

Трансфер вставляется между каждым перелётом и отелем с приблизительным временем.

### Step 5: Логистические проверки

**5 типов проверок:**

1. **Accommodation gaps** — цикл по ночам поездки, проверка что каждая покрыта бронированием
2. **Check-in timing** — `arrival_time + transfer_time > check_in_time` → warning
3. **Check-out timing** — `departure_time - checkout_time - transfer_time < 2h` → warning
4. **Baggage mismatch** — `checked_bags_count < passengers_count` → warning
5. **Non-refundable deadlines** — если дедлайн отмены < 14 дней → highlight

### Step 6: HTML-генерация

**Структура файла:**

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <title>Отпуск в [Destination] — [Dates]</title>
  <script src="https://cdn.sheetjs.com/xlsx-0.20.3/.../xlsx.full.min.js"></script>
  <style>/* Inline CSS — ~50 правил */</style>
</head>
<body>
  <div class="container">
    <h1>[Заголовок]</h1>
    <p class="subtitle">[Даты · кол-во · маршрут]</p>
    
    <div class="toolbar">
      <button onclick="downloadXLSX()">Скачать XLSX</button>
      <button onclick="downloadPDF()">Скачать PDF</button>
    </div>
    
    <div class="card"><!-- Таблица маршрута --></div>
    <div class="card"><!-- Summary --></div>
    <div class="card"><!-- Notes --></div>
    
    <p class="updated">Обновлено: [date]</p>
  </div>
  
  <script>
    function downloadXLSX() { /* SheetJS export */ }
    function downloadPDF() { /* window.open + print */ }
  </script>
</body>
</html>
```

**Стилевые решения:**

| Элемент | Стиль |
|---------|-------|
| Шрифты | `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto` |
| Фон страницы | `#f5f5f7` (Apple-style light gray) |
| Карточки | `border-radius: 16px`, `box-shadow: 0 1px 3px rgba(0,0,0,.08)` |
| Перелёт | `border-left: 4px solid #0071e3` (синий) |
| Отель | `border-left: 4px solid #34c759` (зелёный) |
| Трансфер | `border-left: 4px solid #ff9500` (оранжевый) |
| TripAdvisor badge | Зелёный бейдж `#f0fdf0` border `#d4edda`, зелёный текст `#1a7f37` |
| Hover на строках | `background: #fafbff` |
| Цены | `font-weight: 700; font-size: 14px` |
| Время | `font-family: 'SF Mono', Menlo, monospace; font-weight: 600` |

**Responsive:** `@media (max-width: 1000px)` уменьшает padding и font-size.

### Step 7: Экспорт

**XLSX (SheetJS):**
```javascript
// 18 колонок
const headers = ['#', 'Тип', 'Дата', 'Описание', 'Маршрут', 'Время', 
  'В пути', 'Оператор', 'Номер / Класс', 'Питание', 'Условия отмены', 
  'Багаж', 'Цена (2 чел.), ₽', 'TripAdvisor', 'Отзывов', 'Ostrovok', 
  'Ссылка бронирования', 'Ссылка TripAdvisor'];

// Итоговые строки
['', '', '', '', '', '', '', '', '', '', '', 'ИТОГО перелёты:', sum_flights]
['', '', '', '', '', '', '', '', '', '', '', 'ИТОГО отели:', sum_hotels]
['', '', '', '', '', '', '', '', '', '', '', 'ИТОГО:', sum_total]

// Auto-width
ws['!cols'] = [{wch:4},{wch:10},{wch:22},{wch:28},...];
```

**PDF (window.open + print):**
- Новое окно с `max-width: 420px`
- Карточная раскладка вместо таблицы
- Группировка по дням: "20 июня, суббота"
- Цены скрыты — только логистика и ссылки
- CSS `break-inside: avoid` для карточек
- `setTimeout(() => window.print(), 400)` — автопечать

---

## 3. JS-экстракторы: полная справка

### 3.1 Flight Extractor (Aviasales ticket popup)

**Цель:** извлечь данные о рейсе из попапа с деталями билета.

**Как работает:** ищет все DOM-элементы, фильтрует по ключевым словам и длине текста. Три категории:
1. Рейсы — элементы с "в пути"/"в полёте" + "₽" (50-600 символов)
2. Продавцы — элементы с "₽" + "Купить"/"Ищем на" (< 200 символов)
3. Багаж — элементы с "багаж"/"кладь"/"Добавить багаж" (< 200 символов)

**Возвращает:** `{ flights: string[], sellers: string[], baggage: string[] }`

### 3.2 Baggage Cost Check (Aviasales)

**Цель:** определить стоимость дополнительного багажа.

**Триггеры:**
- `"Добавить багаж" + "₽"` (< 100 символов) — платный багаж с ценой
- `"Выбрать багаж"` (< 100 символов) — опция выбора
- `"Без багажа"` — точное совпадение
- `"багаж" + "кг"` (< 50 символов) — информация о весе

### 3.3 Room Prices (Ostrovok)

**Цель:** список всех типов номеров с ценами.

**Фильтр:** текст содержит "₽" + "номер", длина 50-500 символов, regex `/\d[\s\u00a0]\d{3}\s*₽/`.
**Дедупликация:** `new Set()`.
**Возвращает:** до 15 уникальных строк.

### 3.4 Specific Room Type (Ostrovok)

**Цель:** найти конкретный тип номера по названию.

**Требует:** подставить `ROOM_NAME` перед запуском.
**Фильтр:** текст содержит `ROOM_NAME` + "₽", < 500 символов.

### 3.5 Hotel Meta + TripAdvisor (Ostrovok)

**Цель:** рейтинги и ссылки на TripAdvisor.

**TripAdvisor:** `document.querySelectorAll('a[href*="tripadvisor"]')` — href, text, alt img.
**Рейтинги:** элементы с текстом `/^\d[.,]\d$/` рядом с "отзыв".

### 3.6 Quick Scan (без JS)

Альтернатива через `mcp__claude-in-chrome__find`:
- Цены: `"цена стоимость ₽ рублей номер"`
- TripAdvisor: `"TripAdvisor tripadvisor rating отзыв"`
- Багаж: `"багаж добавить багаж стоимость"`

---

## 4. Gotchas и edge cases

### 4.1 Критические

| Проблема | Решение |
|----------|---------|
| Ostrovok + WebFetch = пустой shell | **Всегда** использовать браузер. Без исключений. |
| Ostrovok не загрузился | Ждать пока title !== "Загрузка отеля...". Или sleep 2-3 сек. |
| Aviasales popup не открылся | Ссылка делает свежий поиск — popup может не появиться. Скриншот + визуальное чтение. |
| Multi-segment flights | В попапе Aviasales нужно скроллить вниз для второго сегмента. |

### 4.2 Данные

| Проблема | Решение |
|----------|---------|
| Цены на всех, не per-person | Не делить! Обе площадки показывают итого. |
| "23 кг × 1" на 2 пассажиров | Это 1 место багажа на двоих — флагнуть как предупреждение. |
| Чартеры | Отличные правила багажа, нет возврата. Всегда флагнуть. |
| Shared link ≠ конкретный билет | avs.io делает новый поиск. Цена может отличаться от expected_price. |

### 4.3 DOM-зависимости

JS-экстракторы ищут по **текстовому контенту**, а не по CSS-классам или id. Это делает их более устойчивыми к обновлениям SPA, но:
- Если Aviasales поменяет "в пути" на другую фразу — сломается
- Если Ostrovok поменяет формат цены с "₽" на "руб." — сломается
- **Fallback:** скриншот страницы + визуальное чтение Claude

---

## 5. Установка и настройка

### Symlink (рекомендуется)

```bash
git clone https://github.com/kuzds/trip-planner-skill.git
ln -s "$(pwd)/trip-planner-skill" ~/.claude/skills/trip-planner
```

### Copy

```bash
git clone https://github.com/kuzds/trip-planner-skill.git
cp -r trip-planner-skill ~/.claude/skills/trip-planner
```

### Требования

- **Claude Code** — CLI или Desktop App
- **Claude in Chrome** — MCP extension для управления браузером
- **Chrome** — основной браузер для извлечения данных

### Конфигурация

`.superset/config.json` — пока пустой, зарезервирован для хуков:
```json
{
  "setup": "",
  "teardown": "",
  "run": ""
}
```

---

## 6. Output Reference

### Пример вывода (example-output.html)

**Поездка:** Турция, 20-29 июня 2026, на двоих
**Маршрут:** Москва → Стамбул → Каппадокия → Фетхие → Москва

| # | Тип | Описание | Цена |
|---|-----|----------|------|
| 1 | Перелёт | MOW → IST, Аэрофлот, 6ч, прямой | 48 991 ₽ |
| 2 | Отель | Adelmar Hotel Istanbul 4*, 2 ночи | 13 992 ₽ |
| 3 | Перелёт | IST → NAV, Turkish Airlines, 1ч 20м | 18 727 ₽ |
| 4 | Трансфер | NAV → Göreme, ~20 мин | — |
| 5 | Отель | Cappadocia Cave Suites 5*, 3 ночи | 64 138 ₽ |
| 6 | Перелёт | NAV → IST → DLM, 4ч 15м, 1 пересадка | 24 946 ₽ |
| 7 | Трансфер | DLM → Fethiye, ~1-1.5ч | — |
| 8 | Отель | Jiva Beach Resort 5* AI, 3 ночи | 84 162 ₽ |
| 9 | Трансфер | Fethiye → DLM, ~1-1.5ч | — |
| 10 | Перелёт | DLM → VKO, 4ч 35м, прямой | 61 091 ₽ |

**Итого:** ~316 047 ₽ (перелёты 153 755 ₽ + отели 162 292 ₽)

**Ключевые примечания:**
- DLM → VKO: только 1 место багажа (23 кг) на двоих
- Cappadocia Cave Suites: Adult Only +12, ресепшн 24/7
- Бесплатная отмена Cave Suites до 06.06, Jiva до 23.06

---

## 7. Память о поездках (persistent registry)

Скилл помнит каждую поездку, над которой работал, чтобы **любой** агент с доступом к скиллу понимал, что пользователь уже планировал. Память хранится на диске, а не в сессии.

### Где лежит

- **Каталог:** `~/.trip-planner/` (переопределяется через `$TRIP_PLANNER_HOME`).
- **`trips.json`** — канонический источник (machine-managed).
- **`trips.md`** — человекочитаемое зеркало, **генерируется автоматически** при каждой записи. Руками не править.

**Почему вне каталога плагина:** плагин авто-обновляется (`claude plugin update` заменяет файлы плагина), поэтому всё, что лежало бы внутри `skills/trip-planner/`, стиралось бы при обновлении. Реестр в `~/.trip-planner/` переживает обновления и общий для всех агентов и сессий.

### Скрипт-менеджер: `scripts/trip_registry.py`

Единственный писатель обоих файлов. **Только stdlib** (без pip-зависимостей) — recall/record не должны падать из-за отсутствующего пакета. Записи атомарные (temp-файл + `os.replace`).

| Команда | Назначение |
|---------|-----------|
| `record` | Upsert поездки по `--id` (или производному из destination+месяц). Опциональный `--html` авто-заполняет поля И кэширует структурный `trip-data` блок в `data`. `--data file.json` — задать кэш явно. Идемпотентно; сохраняет `created_at`. Derived-id коллизия с другой поездкой → суффикс + warning (не перезапись). Запись сериализуется через `fcntl.flock`. |
| `list [--json]` | Список всех поездок (таблица или JSON; `data` в JSON-выводе опускается). |
| `get --id ID [--json]` | Одна поездка (включая `data`). |
| `remove --id ID` | Удалить поездку. |
| `render --id ID [--out PATH]` | Перегенерировать HTML поездки из кэшированного `data` — **без повторного скрейпинга**. Требует, чтобы поездка была записана из JSON-SoT HTML (или с `--data`). |
| `status --id ID --set S` | Задать жизненный цикл: `planned` / `booked` / `archived`. Archived сортируются последними; recall их де-приоритизирует. |
| `selftest` | CI-смоук: record → list → get → update → collision → render → remove во временном сторе. |

### Поля записи

`id`, `destination`, `dates`, `start`, `end`, `origin`, `route`, `pax`, `nights` (авто-расчёт из start/end), `flights`, `hotels`, `total`, `currency`, `status` (planned/booked/archived), `html_path`, `deploy_url`, `notes`, `data` (кэш структурного `trip-data` для re-render), `created_at`, `updated_at`.

### HTML auto-capture

`record --html` парсит наш собственный шаблон (regex по `<title>`, `.subtitle`, первому `.summary-value` в карточке «Итого», и счётчику строк `type-flight` / `type-hotel` — те же маркеры, что использует `export_trip.py`). Best-effort: если поле не распарсилось, берётся флаг/существующее значение, скрипт не падает.

### Поток recall / record

```
Recall (перед Step 0): cat ~/.trip-planner/trips.json
  → ответить на вопросы об истории / детектировать дубликат / взять контекст
Step 9 (после Step 6/7): trip_registry.py record --html ... [флаги]
  → после Vercel-деплоя: повторный record с тем же id + --deploy-url
```
