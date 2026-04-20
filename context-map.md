---
title: Trip Planner Skill
scale: XS
stack: Claude Code skill (prompt-only, no runtime code)
status: v1.0-released
tasks_next: "Greece/Egypt/Thailand transfers, multi-flight comparison"
last_updated: 2026-04-20
---

# Context Map: Trip Planner Skill

> Оперативная карта проекта для AI-агентов. Читай перед началом работы.

---

## Что это за проект

**Trip Planner** — скилл для Claude Code, который автоматически извлекает данные о перелётах и отелях из российских тревел-сайтов и генерирует красивый HTML-маршрут с экспортом.

**Тип:** prompt-based skill (нет исполняемого кода — только `SKILL.md` с инструкциями и JS-сниппетами).

**Репозиторий:** `~/Desktop/Projects/trip-planner-skill/`
**GitHub:** `github.com/kuzds/trip-planner-skill`
**Лицензия:** MIT

---

## Структура файлов

```
trip-planner-skill/
├── SKILL.md              ← ЯДРО: инструкции + JS-экстракторы + 7-шаговый workflow
├── example-output.html   ← Эталонный HTML-вывод (Турция, июнь 2026, 448 строк)
├── README.md             ← Публичная документация для GitHub
├── PRD.md                ← Product Requirements Document
├── DOCS.md               ← Техническая документация
├── context-map.md        ← Этот файл
└── .superset/
    └── config.json       ← Конфигурация хуков (пока пустая)
```

### Читай первым при задаче

| Задача | Файл |
|--------|------|
| Изменить логику извлечения | `SKILL.md` → JS Extractors |
| Изменить дизайн вывода | `example-output.html` |
| Бизнес-требования / roadmap | `PRD.md` |
| Техническая глубина | `DOCS.md` |

---

## Как работает (кратко)

```
Пользователь бросает ссылки avs.io + corp.ostrovok.ru
         ↓
SKILL.md активируется (триггер по URL-паттернам)
         ↓
Step 1: Парсинг ссылок и текста
Step 2: WebFetch(avs.io) → redirect URL → Chrome → JS extractor → данные перелёта
Step 3: Chrome → Ostrovok SPA → JS extractor → данные отеля + TripAdvisor
Step 4: Вставка строк трансферов (встроенная таблица для Турции)
Step 5: Проверка логистики (gaps, timing, baggage, deadlines)
Step 6: Генерация self-contained HTML → ~/Desktop/trip_*.html
Step 7: Отчёт пользователю
```

---

## Источники данных

| Источник | URL-паттерн | Метод | Что извлекается |
|----------|------------|-------|-----------------|
| Aviasales (short) | `avs.io/*` | WebFetch → 301 redirect | Цена, маршрут, авиакомпания из URL |
| Aviasales (full) | `aviasales.ru/*` | Chrome + JS | Рейсы, время, багаж, продавцы, цены |
| Ostrovok | `corp.ostrovok.ru/hotel/*` | Chrome + JS | Отель, номера, цены, рейтинги, отмена |
| TripAdvisor | через Ostrovok DOM | JS extractor | Ссылка, рейтинг/5, кол-во отзывов |

---

## Known Issues

| # | Проблема | Статус | Заметка |
|---|----------|--------|---------|
| 1 | Ostrovok + WebFetch = пустой shell | design | ТОЛЬКО Chrome MCP, без исключений |
| 2 | Popup Aviasales скроллится | known | Мультисегмент: первый leg виден, нужен скролл |
| 3 | avs.io ≠ конкретный билет | known | Поисковый hint, реальная цена может отличаться |
| 4 | Ostrovok двухфазная загрузка | known | Ждать title !== "Загрузка отеля..." (2-3 сек) |
| 5 | SheetJS CDN зависимость | design | XLSX-экспорт требует интернета |
| 6 | Трансферы только для Турции | open | Греция, Египет, Таиланд — не реализованы |

---

## Decisions

| # | Решение | Причина |
|---|---------|---------|
| 1 | Только Chrome MCP (не WebFetch) для Ostrovok | SPA: WebFetch возвращает пустой shell |
| 2 | JS-экстракторы по тексту, не CSS-селекторам | SPA генерирует хешированные классы, текст стабильнее |
| 3 | Self-contained HTML (без сервера) | Один файл, любой браузер, privacy-first |
| 4 | Цены итого на всех пассажиров | Пользователи часто путаются — явная подпись "(2 чел.)" |
| 5 | Скриншот как fallback при сбое JS | Устойчивость к изменениям DOM |

---

## Tasks / Next Work

- [ ] Добавить трансферы для Греции, Египта, Таиланда
- [ ] Multi-flight comparison (2-3 варианта в одной таблице)
- [ ] Поддержка EUR/USD в выводе
- [ ] Booking.com как дополнительный источник отелей
- [ ] JSON-кэш для возможности обновления без повторного скрейпинга

---

## Agent Conflict Protocol

- **JS-экстракторы в SKILL.md** — изменение паттернов поиска может сломать извлечение. Тестируй на реальных страницах.
- **example-output.html** — это reference implementation, не просто пример. Изменение дизайна здесь — изменение спецификации.
- **Трансферная таблица** — значения времени трансфера должны быть проверены на актуальность.

---

## Gotchas

1. **Ostrovok + WebFetch = НИКОГДА.** Только Chrome. Без исключений.
2. **Ostrovok грузится в 2 фазы.** Ждать пока title !== "Загрузка отеля..."
3. **avs.io ≠ конкретный билет.** Это поисковый запрос с hint-ценой.
4. **Popup Aviasales скроллится.** Мультисегмент — нужен скролл для остальных legs.
5. **Цены — ИТОГО на всех.** Не делить на кол-во пассажиров.
6. **"23 кг × 1" на 2 пассажиров** = 1 место на двоих → предупреждение.
7. **Дедлайны отмены** — самый важный datapoint для пользователя.

---

## Validation Checklist

- [ ] SKILL.md содержит все 7 шагов workflow
- [ ] JS-экстракторы работают на тестовых страницах Aviasales и Ostrovok
- [ ] example-output.html открывается в браузере и XLSX/PDF работают
- [ ] Трансферная таблица (Турция) актуальна

---

## Update Protocol

При изменении JS-экстракторов: тестируй на реальных страницах, фиксируй дату проверки. При добавлении нового источника: добавляй Step в SKILL.md + JS-экстрактор + запись в таблицу источников данных.
