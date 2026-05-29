---
schema_version: 2
project_id: trip-planner-skill
name: Trip Planner Skill
title: Trip Planner Skill
repo_path: /Users/viacheslavkuznetsov/Desktop/Projects/trip-planner-skill
repo_url: github.com/kuzds/trip-planner-skill
visibility: public
status: mvp-complete
scale: XS
primary_stack: [Claude Code skill, Markdown, JS extractors]
last_updated: 2026-05-28
tasks_next: "Задачи теперь в Linear: project trip-planner (team KYZ) — https://linear.app/kyzdes/project/trip-planner-7398870781ce. P0: KYZ-200 (recall $TRIP_PLANNER_HOME), KYZ-201 (script paths под плагином). Эта таблица заморожена для истории."
---

# Context Map: Trip Planner Skill

> Оперативная карта проекта для AI-агентов. Читай перед началом работы.

---

## Что это за проект

**Trip Planner** — скилл для Claude Code, который автоматически извлекает данные о перелётах и отелях из российских тревел-сайтов (Aviasales, Ostrovok) и генерирует self-contained HTML-маршрут с экспортом в XLSX/PDF.

**Тип:** prompt-based skill (нет исполняемого кода — только `SKILL.md` с инструкциями и JS-сниппетами).

**Репозиторий:** `~/Desktop/Projects/trip-planner-skill/`
**GitHub:** `github.com/kuzds/trip-planner-skill`
**Лицензия:** MIT

---

## Структура файлов

```
trip-planner-skill/
├── skills/trip-planner/
│   ├── SKILL.md          ← ЯДРО: workflow (Recall + Step 0–9) + JS-экстракторы
│   ├── assets/template.html
│   ├── references/transfers.md
│   └── scripts/
│       ├── export_trip.py     ← HTML → XLSX + PDF
│       └── trip_registry.py   ← Память о поездках (recall/record), stdlib-only
├── example-output.html   ← Эталонный HTML-вывод (Турция, июнь 2026, 448 строк)
├── README.md             ← Публичная документация для GitHub
├── PRD.md                ← Product Requirements Document
├── DOCS.md               ← Техническая документация (см. §7 — Память о поездках)
├── context-map.md        ← Этот файл (v2 schema)
├── .claude-plugin/plugin.json
├── hooks/hooks.json      ← SessionStart auto-update
└── scripts/auto-update.sh

# Память о поездках (создаётся при первом использовании, ВНЕ каталога плагина):
~/.trip-planner/{trips.json, trips.md}   ← override через $TRIP_PLANNER_HOME
```

### Читай первым при задаче

| Задача | Файл |
|--------|------|
| Изменить логику извлечения | `SKILL.md` → JS Extractors |
| Изменить дизайн вывода | `example-output.html` |
| Бизнес-требования / roadmap | `PRD.md` |
| Техническая глубина | `DOCS.md` |
| История проблем и решений | `context-map.md` (этот файл) |

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
| Aviasales (short) | `avs.io/*` | WebFetch → 301 redirect | Цена, маршрут, авиакомпания из URL + t-string с unix-таймстемпами |
| Aviasales (full) | `aviasales.ru/*` | Chrome + JS | Рейсы, время, багаж, продавцы, цены |
| Ostrovok | `corp.ostrovok.ru/hotel/*` | Chrome + JS | Отель, номера, цены, рейтинги, отмена |
| TripAdvisor | через Ostrovok DOM | JS extractor | Ссылка, рейтинг/5, кол-во отзывов |

---

## Known Issues

| ID | Area | Severity | Symptom | Status | Agent-Ready | Rule |
|----|------|----------|---------|--------|-------------|------|
| KI-01 | data/ostrovok | high | Ostrovok + WebFetch возвращает пустой shell (SPA) | wontfix | yes | Использовать ТОЛЬКО Chrome MCP, без исключений |
| KI-02 | data/aviasales | low | Popup Aviasales скроллится — мультисегмент: первый leg виден сразу, остальные нужно проскроллить | open → Linear KYZ-210 | partial | Для multi-leg рейса вызвать scroll в JS-экстракторе |
| KI-03 | data/aviasales | medium | `avs.io` short-link ≠ конкретный билет — поисковый hint, реальная цена может отличаться | open | yes | Сверять `expected_price` из URL с реальной ценой на странице билета |
| KI-04 | data/ostrovok | low | Ostrovok двухфазная загрузка — первые 2-3 секунды title === "Загрузка отеля..." | wontfix | yes | Ждать пока `document.title !== "Загрузка отеля..."` (2-3 сек) |
| KI-05 | export/xlsx | low | XLSX-экспорт зависит от SheetJS CDN — требует интернета | open | yes | При offline-режиме откатиться на Python+openpyxl (см. KI-08) |
| KI-06 | data/transfers | medium | Трансферная таблица покрывает только Турцию — Греция, Египет, Таиланд не реализованы | resolved | yes | `references/transfers.md` теперь покрывает Турцию, Танзанию, Грецию, Египет, ОАЭ |
| KI-07 | tooling/edit | high | `Edit`-tool падает на JS-секциях HTML с unicode escape (`→` рендерится как `→` в Read, но на диске литерал) | resolved | yes | Задокументировано в SKILL.md Gotchas; использовать Python-script или Write tool, не Edit |
| KI-08 | export/pdf | medium | `window.print()` PDF-кнопка в HTML не работает через Chrome MCP — `file://` конвертируется в `https://file:///` | resolved | yes | `scripts/export_trip.py` через `chrome --headless --print-to-pdf` — Step 6.5 в SKILL.md |
| KI-09 | browser/mcp | medium | Браузер-расширение Claude отваливается при долгих сессиях | resolved | yes | Step 0 в SKILL.md: tabs_context_mcp в самом начале, без retry-loop |
| KI-10 | data/aviasales | low | t-string Aviasales содержит unix-timestamps сегментов мульти-leg рейса, но не парсится скиллом | open → Linear KYZ-209 | yes | При мульти-leg рейсе декодировать t-string для длины пересадки и точных времён сегментов |
| KI-11 | architecture/html | medium | 4 секции HTML дублируют данные (table, XLSX-функция, PDF-функция, summary) — рассинхронизация при правках | open → Linear KYZ-206 | partial | При итерации использовать Python script, который правит все 4 секции атомарно; долгосрочно — JSON single-source-of-truth (T-11) |
| KI-12 | data/dates | low | Дни недели для дат вычисляются вручную, риск ошибки | resolved | yes | Документировано в Step 6: `toLocaleDateString('ru-RU', {weekday:'long'})` или Python datetime |
| KI-13 | data/output | low | JS-экстрактор может вернуть `[BLOCKED: Cookie/query string data]` если в JSON-выводе есть session ID | resolved | yes | Документировано в JS Extractors: не включать `location.href`/`document.cookie` в output |
| KI-14 | data/aviasales | low | Скилл не умел искать рейс из текста без готовой ссылки | resolved | yes | Aviasales URL-конструктор `{ORIGIN}{DDMM}{DESTINATION}{N_PAX}` в Step 1 |
| KI-15 | data/ostrovok | low | Скилл не умел искать отель по названию города без готовой ссылки | resolved | yes | Ostrovok search-by-city flow в Step 1 + JS-экстрактор для списка отелей |
| KI-16 | performance | low | Sequential MCP calls в 3-5× медленнее batched | resolved | yes | Документировано в workflow и Step 2: использовать `browser_batch` для последовательностей |
| KI-17 | tooling/scripts | low | Скрипты в SKILL.md адресуются относительно репо (`skills/trip-planner/scripts/...`) — при установке как плагин путь другой | open → Linear KYZ-201 | yes | Под плагином использовать `${CLAUDE_PLUGIN_ROOT}/skills/trip-planner/scripts/...`; касается `export_trip.py` (Step 6.5) и `trip_registry.py` (Step 9) |

---

## Decisions

| ID | Date | Area | Decision | Rationale | Status | Agent-Ready |
|----|------|------|----------|-----------|--------|-------------|
| D-01 | 2026-04-20 | data/ostrovok | Только Chrome MCP (не WebFetch) для Ostrovok | SPA: WebFetch возвращает пустой shell, Chrome рендерит React | active | yes |
| D-02 | 2026-04-20 | data | JS-экстракторы по тексту, не CSS-селекторам | SPA генерирует хешированные классы, текст стабильнее между релизами | active | yes |
| D-03 | 2026-04-20 | architecture | Self-contained HTML (без сервера) | Один файл, любой браузер, privacy-first, удобно слать попутчику | active | yes |
| D-04 | 2026-04-20 | ux | Цены итого на всех пассажиров, явная подпись `(2 чел.)` | Пользователи часто путаются между per-person и total | active | yes |
| D-05 | 2026-04-20 | data | Скриншот как fallback при сбое JS-экстрактора | Устойчивость к изменениям DOM | active | yes |
| D-06 | 2026-04-25 | export | Default-путь экспорта = Python (openpyxl + Chrome headless), не JS-кнопки в HTML | JS-кнопки требуют user-action и работают только в открытом HTML; Python даёт детерминированный output на Desktop | active | yes |
| D-07 | 2026-04-25 | tooling/edit | HTML с unicode escape sequences правится через Python script, не через Edit-tool | Edit нормализует unicode → теряет совпадения; Python с raw strings не имеет этой проблемы | active | yes |
| D-08 | 2026-04-25 | flight-selection | При наличии 2+ вариантов с разным trade-off (price/time/airline) — представить пользователю на выбор, не угадывать | В сессии 2026-04-25 выбран Аэрофлот 17:10 vs S7 09:55 без согласования; могло пойти не так | active | yes |
| D-09 | 2026-05-14 | architecture/skill | Перейти от моно-SKILL.md к `assets/` + `references/` + `scripts/` структуре | Файл рос до 234 строк и стал монолитом; разделение даёт progressive disclosure и переиспользуемые скрипты | active | yes |
| D-10 | 2026-05-14 | export | `scripts/export_trip.py` — официальный путь для XLSX+PDF из готового HTML | Парсит HTML через bs4, пишет XLSX через openpyxl, PDF через `chrome --headless --print-to-pdf` — детерминированно и без user-action | active | yes |
| D-11 | 2026-05-14 | feature | Step 8 (опциональный Vercel deploy) — встроенная фича скилла | Пользователь дважды просил публичный URL после генерации; естественное продолжение workflow | active | yes |
| D-12 | 2026-05-28 | architecture/memory | Персистентная память о поездках: `trips.json` (canonical) + `trips.md` (mirror) в `~/.trip-planner/` (override `$TRIP_PLANNER_HOME`), управляется stdlib-only `trip_registry.py`; recall перед Step 0, record на Step 9 | Скилл был stateless — ни один агент не знал историю поездок. Память ВНЕ каталога плагина, т.к. `claude plugin update` стирает файлы плагина; stdlib-only, чтобы recall/record не падали из-за pip-зависимостей; single-writer-скрипт даёт единую схему для всех агентов | active | yes |
| D-13 | 2026-05-28 | process/tracking | Linear — основной живой трекер задач (project trip-planner, team KYZ). `context-map.md` хранит Decisions + Known Issues + архитектуру + Session Log как память; таблица Tasks заморожена | Нужен единый трекер для нескольких агентов; дублирование задач в md и Linear = дрейф. KI остаются здесь как память, но открытые → заводятся issue в Linear со ссылкой | active | yes |

---

## Tasks / Next Work

> ⚠️ **Active task tracking moved to Linear** — project **trip-planner** (https://linear.app/kyzdes/project/trip-planner-7398870781ce), team `KYZ`, on 2026-05-28. This table is **frozen for history** — do **not** add new tasks here; create them in Linear. Open items were migrated: T-02→KYZ-211, T-03→KYZ-213, T-04→KYZ-214, T-05→KYZ-207, T-09→KYZ-209, T-11→KYZ-206, T-12→KYZ-212; plus the memory-hardening backlog KYZ-200…KYZ-205, KYZ-208, KYZ-215…KYZ-218.

| ID | Priority | Area | Task | Status | Owner | Agent-Ready | Validation | Source |
|----|----------|------|------|--------|-------|-------------|------------|--------|
| T-01 | P3 | data/transfers | Добавить трансферы для Греции, Египта, Таиланда | done | claude | yes | Покрыто `references/transfers.md`: Турция, Танзания, Греция, Египет, ОАЭ | author |
| T-02 | P2 | feature | Multi-flight comparison: 2-3 варианта в одной таблице | todo | - | partial | Пользователь видит side-by-side сравнение цен/времени | author |
| T-03 | P3 | ui | Поддержка EUR/USD в выводе цен | todo | - | partial | Тогл валюты в HTML, цены пересчитываются | author |
| T-04 | P3 | data | Booking.com как дополнительный источник отелей | todo | - | no | Параллельный JS-экстрактор + сравнение цен с Ostrovok | author |
| T-05 | P2 | architecture | JSON-кэш маршрута для обновления без повторного скрейпинга | todo | - | partial | Изменение даты не требует повторного захода на Aviasales/Ostrovok | author |
| T-06 | P0 | skill | Добавить в SKILL.md gotcha про unicode-escape + рекомендацию Python-script для правок JS-блоков | done | claude | yes | Gotcha в SKILL.md + правило использовать Write/Python вместо Edit | KI-07 |
| T-07 | P0 | skill | Добавить Step 6.5 в SKILL.md: экспорт XLSX/PDF через Python+Chrome headless как primary path | done | claude | yes | `scripts/export_trip.py` + Step 6.5 в SKILL.md, протестировано на Turkey trip | KI-08 |
| T-08 | P0 | skill | Добавить Step 0 в SKILL.md: browser disconnect protocol (проверить → попросить переподключить, не retry-loop) | done | claude | yes | Step 0 в SKILL.md, явное правило «не уходить в retry-loop» | KI-09 |
| T-09 | P1 | skill | t-string parser для Aviasales: декодировать unix-timestamps сегментов мульти-leg рейса | todo | claude | yes | На DLM→ESB→VKO достаём длину стыковки в Анкаре без захода в браузер | KI-10 |
| T-10 | P1 | skill | Auto-расчёт дней недели через Python `datetime` или JS `Date` | done | claude | yes | Документировано в Step 6 — `toLocaleDateString` / `strftime` | KI-12 |
| T-11 | P2 | architecture | Перевести example-output.html на JSON single-source-of-truth: данные в `<script>` блоке, table/xlsx/pdf генерятся из него | todo | claude | partial | Изменение одной даты требует правки только в одном месте | KI-11 |
| T-12 | P2 | feature | Compare-mode: 2-3 варианта маршрута side-by-side в одном HTML (расширение T-02) | todo | claude | partial | Пользователь видит "Вариант А: 7н, 313k vs Вариант Б: 9н, 380k" | author |
| T-13 | P3 | data | Стоимость трансфера — встроить таблицу средних цен | done | claude | yes | `references/transfers.md` содержит колонку «Approx cost» для всех маршрутов | author |
| T-14 | P1 | skill | Aviasales URL-конструктор для поиска без готовой ссылки | done | claude | yes | Документировано в Step 1; работает для одностор. рейсов | session-2026-05-14 |
| T-15 | P1 | skill | Ostrovok hotel-search-by-city flow + JS-экстрактор для списка | done | claude | yes | Step 1 + extractor; протестировано на Аруше (Tanzania trip) | session-2026-05-14 |
| T-16 | P1 | skill | Step 8: optional Vercel deploy | done | claude | yes | `npx vercel deploy --prod --yes`; протестировано на Turkey + Tanzania | session-2026-05-13 |
| T-17 | P1 | skill | Airline-specific filter / verification flow | done | claude | yes | Документировано в Step 2 + JS-экстрактор `img[alt]`; работало для Oman Air | session-2026-05-13 |
| T-18 | P2 | skill | `browser_batch` adoption — упомянуть в SKILL.md + примеры | done | claude | partial | Workflow at-a-glance + Step 2 callout; примеры пока не вставлены | session-2026-05-14 |
| T-19 | P1 | skill/memory | Память о поездках: recall (перед Step 0) + record (Step 9) + стор `~/.trip-planner/` + `trip_registry.py` | done | claude | yes | `selftest` зелёный; record→list→get→remove + idempotent upsert; HTML auto-capture на example-output.html; CI-шаг добавлен | session-2026-05-28 |

---

## Agent Conflict Protocol

- **JS-экстракторы в SKILL.md** — изменение паттернов поиска может сломать извлечение. Тестируй на реальных страницах Aviasales и Ostrovok перед мержем.
- **example-output.html** — это reference implementation, не просто пример. Изменение дизайна здесь — изменение спецификации. Сначала обнови SKILL.md → потом HTML.
- **Трансферная таблица** — значения времени трансфера должны быть проверены на актуальность (раз в полгода).
- **Edit-tool на HTML** — НЕ ИСПОЛЬЗОВАТЬ для секций с unicode escape (см. D-07). Только Python-script с raw strings.
- **При новых KI/D/T** — добавлять с инкрементальным ID (KI-13, D-09, T-14...), не переиспользовать старые номера даже если они "fixed".

---

## Gotchas

1. **Ostrovok + WebFetch = НИКОГДА.** Только Chrome. Без исключений. (KI-01)
2. **Ostrovok грузится в 2 фазы.** Ждать пока `title !== "Загрузка отеля..."` (KI-04).
3. **`avs.io` ≠ конкретный билет.** Это поисковый запрос с hint-ценой — реальная цена сверяется в браузере (KI-03).
4. **Popup Aviasales скроллится.** Мультисегмент — нужен скролл для остальных legs (KI-02).
5. **Цены — ИТОГО на всех.** Не делить на кол-во пассажиров (D-04).
6. **"23 кг × 1" на 2 пассажиров** = 1 место на двоих → предупреждение пользователю.
7. **Дедлайны отмены** — самый важный datapoint для пользователя. Подсвечивать самый ранний дедлайн.
8. **Unicode escapes в HTML JS-блоках** (`→`) — Edit-tool теряет совпадения. Python script (KI-07, D-07).
9. **PDF через `window.print()`** не тестировался end-to-end — использовать Chrome headless (KI-08, D-06).
10. **Браузер может отвалиться** в долгой сессии — Step 0 проверка перед скрейпингом (KI-09).

---

## Validation Checklist

- [ ] SKILL.md содержит все 7 шагов workflow + Step 0 (browser check) + Step 6.5 (Python export) после T-07/T-08
- [ ] SKILL.md содержит Recall (перед Step 0) + Step 9 (record) + раздел Memory store
- [ ] `trip_registry.py selftest` зелёный; record→list→get→remove roundtrip работает
- [ ] JS-экстракторы работают на тестовых страницах Aviasales и Ostrovok
- [ ] example-output.html открывается в браузере, XLSX скачивается, PDF корректно печатается
- [ ] Трансферная таблица (Турция) актуальна
- [ ] context-map.md проходит `validate_context_map.py` без ошибок (schema_version: 2)

---

## Update Protocol

- **При изменении JS-экстракторов:** тестировать на реальных страницах, фиксировать дату проверки в комментарии экстрактора.
- **При добавлении нового источника:** добавлять Step в SKILL.md + JS-экстрактор + запись в таблицу источников данных.
- **При обнаружении нового бага:** новая строка в Known Issues с инкрементальным ID.
- **При архитектурном выборе:** новая строка в Decisions с датой и обоснованием.
- **При завершении сессии с инсайтами:** добавить запись в Session Log + соответствующие KI/D/T.

---

## Session Log

| Date | Session | Outcome | Findings |
|------|---------|---------|----------|
| 2026-04-20 | Skill creation, GitHub publish | v1.0 released | Initial 6 KI, 5 D, 5 T |
| 2026-04-25 | End-to-end test: Russia → Turkey June 2026 (3 reroutes) | Skill works but 6 frictions found | KI-07..12, D-06..08, T-06..13 |
| 2026-05-05 | Turkey re-plan (27.06-06.07) + Vercel deploy | Confirmed: airline filter, Vercel publish gap | T-16, T-17 |
| 2026-05-07 | Tanzania/Zanzibar one-way plan | Confirmed: hotel-search-by-city + URL constructor gaps | T-14, T-15, KI-13..16 |
| 2026-05-14 | Skill audit + major refactor (via skill-creator) | All P0 closed; `assets/`, `references/`, `scripts/` introduced; new `export_trip.py` working end-to-end | D-09..11, T-01/06/07/08/10/13..18 done |
| 2026-05-28 | Память о поездках (recall + record) | Скилл стал stateful: `trip_registry.py` (stdlib-only), стор `~/.trip-planner/` вне каталога плагина, Recall перед Step 0 + Step 9 record, CI-selftest | D-12, T-19 done, KI-17 |
| 2026-05-28 | Tech-lead review + переход на Linear | Создан Linear-проект trip-planner (KYZ): 4 milestones, 19 issues (KYZ-200…218); таблица Tasks заморожена; начат P0 (KYZ-200/201) | D-13; backlog migrated |
| 2026-05-29 | Автономный прогон бэклога (ветка feat/trip-memory-and-linear) | 14/19 закрыто (In Review): M1 hardening (200–205), M2 epic — JSON-SoT + registry-as-cache + status (206–208), 209 t-string decoder, M4 docs/tests/merge (215–218). Осталось 5: 210/214 (нужен live-браузер), 211/212/213 (design-gated по restraint-преференсу). CI зелёный локально (5 шагов + node) | KI-10/11 закрыты; 12 коммитов |
