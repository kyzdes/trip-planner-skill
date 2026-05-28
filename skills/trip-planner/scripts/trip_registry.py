#!/usr/bin/env python3
"""Persistent registry of trips the trip-planner skill has worked on.

This is the skill's memory. The canonical store is `trips.json`; a human-readable
`trips.md` mirror is regenerated on every mutation. Both live in
`$TRIP_PLANNER_HOME` (default `~/.trip-planner/`) — OUTSIDE the plugin directory
on purpose, so they survive `claude plugin update` (which replaces the installed
plugin files) and are shared across every agent and session.

Design rules:
  - Stdlib-only. Recall/record must never fail on a missing pip package.
  - This script is the single writer of both files. Never hand-edit trips.md.
  - Writes are atomic (temp file + os.replace).

Commands:
    record    upsert a trip (keyed by --id); optional --html auto-fills fields
    list      show all trips (human table by default, or --json)
    get       show one trip (--id; --json)
    remove    delete one trip (--id)
    selftest  CI smoke test: record -> list -> get -> remove roundtrip

Examples:
    trip_registry.py record --html ~/Desktop/trip_turkey.html \\
        --destination "Турция" --dates "20–29 июня 2026" \\
        --start 2026-06-20 --end 2026-06-29 --pax 2 --total "≈316 047 ₽"
    trip_registry.py record --id turkey-2026-06 --deploy-url https://x.vercel.app
    trip_registry.py list
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl  # POSIX advisory file locking (macOS/Linux); absent on Windows
except ImportError:  # pragma: no cover
    fcntl = None

SCHEMA_VERSION = 1

# Entry field order — also the order rendered in trips.md / shown by `get`.
FIELDS = [
    "id", "destination", "dates", "start", "end", "origin", "route",
    "pax", "nights", "flights", "hotels", "total", "currency", "status",
    "html_path", "deploy_url", "notes", "created_at", "updated_at",
]


# --------------------------------------------------------------------------- #
# Store location + IO
# --------------------------------------------------------------------------- #
def resolve_home() -> Path:
    """Where the memory lives. `$TRIP_PLANNER_HOME` wins; else ~/.trip-planner/."""
    override = os.environ.get("TRIP_PLANNER_HOME")
    return Path(override).expanduser() if override else Path.home() / ".trip-planner"


def json_path(home: Path) -> Path:
    return home / "trips.json"


def md_path(home: Path) -> Path:
    return home / "trips.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(home: Path) -> dict:
    p = json_path(home)
    if not p.exists():
        return {"version": SCHEMA_VERSION, "trips": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as ex:
        raise SystemExit(f"error: {p} is unreadable ({ex}). Fix or remove it.")
    data.setdefault("version", SCHEMA_VERSION)
    data.setdefault("trips", [])
    return data


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(home: Path, data: dict) -> None:
    """Persist canonical JSON, then regenerate the human-readable mirror."""
    _atomic_write(json_path(home), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(md_path(home), render_md(data))


@contextmanager
def _lock(home: Path):
    """Serialise the read-modify-write so concurrent records can't lose data.

    Best-effort: on platforms without fcntl (Windows) it degrades to no lock.
    """
    home.mkdir(parents=True, exist_ok=True)
    lock_file = open(home / ".lock", "w")
    try:
        if fcntl is not None:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            except OSError:
                pass
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            except OSError:
                pass
        lock_file.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w]+", "-", s, flags=re.UNICODE)
    return s.strip("-") or "trip"


def derive_id(destination: str | None, start: str | None) -> str:
    base = slugify(destination) if destination else "trip"
    if start and re.match(r"^\d{4}-\d{2}", start):
        return f"{base}-{start[:7]}"
    return base


def sort_key(t: dict):
    """Most-recent first; entries without a start date sort last."""
    return (t.get("start") or "", t.get("updated_at") or "")


def _days_between(start: str | None, end: str | None) -> int | None:
    if not (start and end):
        return None
    try:
        d0 = datetime.strptime(start[:10], "%Y-%m-%d")
        d1 = datetime.strptime(end[:10], "%Y-%m-%d")
    except ValueError:
        return None
    n = (d1 - d0).days
    return n if n > 0 else None


# --------------------------------------------------------------------------- #
# HTML auto-capture (best-effort; our own template only)
# --------------------------------------------------------------------------- #
def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def parse_html(path: Path) -> dict:
    """Pull what we can from a trip-planner HTML file. Never raises on bad input.

    Prefers the structured `<script id="trip-data">` JSON single-source-of-truth
    block (current template); falls back to scraping the rendered table/summary
    for older outputs generated before the JSON-SoT refactor.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as ex:
        print(f"warning: could not read {path} ({ex}); using flags only", file=sys.stderr)
        return {}

    m = re.search(
        r'<script id="trip-data" type="application/json"[^>]*>(.*?)</script>',
        text, re.DOTALL | re.IGNORECASE,
    )
    if m:
        try:
            return _parse_from_json(json.loads(m.group(1)))
        except (json.JSONDecodeError, ValueError):
            pass  # malformed JSON → fall back to scraping
    return _parse_legacy(text)


def _split_subtitle(subtitle: str) -> dict:
    out: dict = {}
    clean = _html.unescape(_strip_tags(subtitle)).strip()
    parts = [p.strip() for p in clean.split("·") if p.strip()]
    if parts:
        out["dates"] = parts[0]
    route = next((p for p in parts if "→" in p), None)
    if route:
        out["route"] = route
    return out


def _parse_from_json(data: dict) -> dict:
    out: dict = {}
    meta = data.get("meta", {}) or {}
    dest = meta.get("destination") or meta.get("h1")
    if dest:
        out["destination"] = _html.unescape(_strip_tags(dest)).strip()
    if meta.get("subtitle"):
        out.update(_split_subtitle(meta["subtitle"]))
    summary = data.get("summary") or []
    if summary and summary[0].get("value"):
        out["total"] = _html.unescape(_strip_tags(str(summary[0]["value"]))).strip()
    elif (data.get("totals") or {}).get("total") is not None:
        out["total"] = str(data["totals"]["total"])
    rows = data.get("rows") or []
    flights = sum(1 for r in rows if r.get("type") == "flight")
    hotels = sum(1 for r in rows if r.get("type") == "hotel")
    if flights:
        out["flights"] = flights
    if hotels:
        out["hotels"] = hotels
    return out


def _parse_legacy(text: str) -> dict:
    out: dict = {}
    m = re.search(r"<title>(.*?)</title>", text, re.DOTALL | re.IGNORECASE)
    title = _html.unescape(m.group(1)).strip() if m else None

    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.DOTALL | re.IGNORECASE)
    if h1 and _strip_tags(h1.group(1)).strip():
        out["destination"] = _html.unescape(_strip_tags(h1.group(1))).strip()
    elif title:
        out["destination"] = title

    sub = re.search(r'class="subtitle"[^>]*>(.*?)</', text, re.DOTALL | re.IGNORECASE)
    if sub and _strip_tags(sub.group(1)).strip():
        out.update(_split_subtitle(sub.group(1)))

    val = re.search(r'class="summary-value"[^>]*>(.*?)</', text, re.DOTALL | re.IGNORECASE)
    if val:
        out["total"] = _html.unescape(_strip_tags(val.group(1))).strip()

    out["flights"] = len(re.findall(r'class="[^"]*type-flight', text))
    out["hotels"] = len(re.findall(r'class="[^"]*type-hotel', text))
    # Zero counts are unhelpful as auto-fill; drop them so flags/existing win.
    for k in ("flights", "hotels"):
        if out.get(k) == 0:
            out.pop(k, None)
    return out


# --------------------------------------------------------------------------- #
# Core operations
# --------------------------------------------------------------------------- #
def op_record(home: Path, flags: dict, html: Path | None) -> dict:
    parsed = parse_html(html) if html else {}
    with _lock(home):
        data = load(home)
        trips = data["trips"]

        def pick(key, default=None):
            if flags.get(key) is not None:
                return flags[key]
            if parsed.get(key) is not None:
                return parsed[key]
            return default

        destination = pick("destination")
        start = pick("start")
        explicit_id = bool(flags.get("id"))
        tid = flags.get("id") or derive_id(destination, start)

        existing = next((t for t in trips if t.get("id") == tid), None)

        # Collision guard: a *derived* id that lands on a genuinely different
        # trip (different start date) must not silently overwrite it. An
        # explicit --id always targets that entry, so it's never re-routed.
        if (existing and not explicit_id and start
                and existing.get("start") and existing["start"] != start):
            n = 2
            while any(t.get("id") == f"{tid}-{n}" for t in trips):
                n += 1
            new_tid = f"{tid}-{n}"
            print(
                f"warning: id {tid!r} already used by a trip starting "
                f"{existing['start']}; recording new trip as {new_tid!r} "
                f"(pass --id to update an existing trip)",
                file=sys.stderr,
            )
            tid = new_tid
            existing = None

        base = dict(existing) if existing else {}

        entry: dict = {"id": tid}
        for key in FIELDS:
            if key in ("id", "created_at", "updated_at"):
                continue
            entry[key] = pick(key, base.get(key))

        # html_path defaults to the parsed file if not set explicitly (absolute,
        # so the stored path stays valid regardless of the recording cwd).
        if entry.get("html_path") is None and html is not None:
            entry["html_path"] = os.path.abspath(os.path.expanduser(str(html)))

        # nights auto-computed from dates when not supplied.
        if entry.get("nights") is None:
            entry["nights"] = _days_between(entry.get("start"), entry.get("end"))

        # status defaults to "planned" only on first creation.
        if entry.get("status") is None:
            entry["status"] = base.get("status") or "planned"

        entry["created_at"] = base.get("created_at") or now_iso()
        entry["updated_at"] = now_iso()

        if existing:
            trips[:] = [entry if t.get("id") == tid else t for t in trips]
        else:
            trips.append(entry)

        save(home, data)
        return entry


def op_get(home: Path, tid: str) -> dict | None:
    return next((t for t in load(home)["trips"] if t.get("id") == tid), None)


def op_remove(home: Path, tid: str) -> bool:
    with _lock(home):
        data = load(home)
        before = len(data["trips"])
        data["trips"] = [t for t in data["trips"] if t.get("id") != tid]
        if len(data["trips"]) == before:
            return False
        save(home, data)
        return True


def op_list(home: Path) -> list[dict]:
    return sorted(load(home)["trips"], key=sort_key, reverse=True)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def render_md(data: dict) -> str:
    trips = sorted(data.get("trips", []), key=sort_key, reverse=True)
    lines = [
        "# Trip Planner — память о поездках",
        "",
        "_Auto-generated by `trip_registry.py`. Do not edit by hand — it is "
        "overwritten on every change._",
        "",
        f"Trips: {len(trips)} · Last updated: {now_iso()}",
        "",
    ]
    if not trips:
        lines.append("_No trips recorded yet._")
        return "\n".join(lines) + "\n"

    for t in trips:
        head = " — ".join(x for x in (t.get("destination"), t.get("dates")) if x) or t["id"]
        lines.append(f"## {head}")
        meta = []
        if t.get("status"):
            meta.append(f"**Status:** {t['status']}")
        if t.get("origin"):
            meta.append(f"**From:** {t['origin']}")
        if t.get("route"):
            meta.append(f"**Route:** {t['route']}")
        if meta:
            lines.append(" · ".join(meta))

        counts = []
        for label, key in (("Pax", "pax"), ("Nights", "nights"),
                           ("Flights", "flights"), ("Hotels", "hotels")):
            if t.get(key) is not None:
                counts.append(f"{label}: {t[key]}")
        if counts:
            lines.append(" · ".join(counts))

        if t.get("total"):
            lines.append(f"**Total:** {t['total']}" + (f" {t['currency']}" if t.get("currency") else ""))
        if t.get("html_path"):
            lines.append(f"**HTML:** {t['html_path']}")
        if t.get("deploy_url"):
            lines.append(f"**Deploy:** {t['deploy_url']}")
        if t.get("notes"):
            lines.append(f"**Notes:** {t['notes']}")
        lines.append(
            f"_id: `{t['id']}` · created {t.get('created_at', '?')} · "
            f"updated {t.get('updated_at', '?')}_"
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_list(trips: list[dict]) -> str:
    if not trips:
        return "No trips recorded yet."
    rows = []
    for t in trips:
        rows.append((
            t.get("id", ""),
            t.get("destination", "") or "",
            t.get("dates", "") or "",
            str(t.get("total", "") or ""),
            t.get("status", "") or "",
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    out = []
    for r in rows:
        out.append("  ".join([
            r[0].ljust(widths[0]), r[1].ljust(widths[1]),
            r[2].ljust(widths[2]), r[3].ljust(widths[3]), r[4],
        ]).rstrip())
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _add_record_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--html", type=Path, help="Trip HTML to auto-fill fields from")
    p.add_argument("--id", help="Trip id (else derived from destination + start month)")
    p.add_argument("--destination")
    p.add_argument("--dates", help="Human-readable date range, e.g. '20–29 июня 2026'")
    p.add_argument("--start", help="ISO start date YYYY-MM-DD")
    p.add_argument("--end", help="ISO end date YYYY-MM-DD")
    p.add_argument("--origin")
    p.add_argument("--route")
    p.add_argument("--pax", type=int)
    p.add_argument("--nights", type=int)
    p.add_argument("--flights", type=int)
    p.add_argument("--hotels", type=int)
    p.add_argument("--total", help="e.g. '≈316 047 ₽'")
    p.add_argument("--currency")
    p.add_argument("--status", help="planned | booked | archived (default: planned)")
    p.add_argument("--html-path", dest="html_path", help="Path to the trip HTML on disk")
    p.add_argument("--deploy-url", dest="deploy_url")
    p.add_argument("--notes")


def _flags_from_args(args: argparse.Namespace) -> dict:
    keys = ["id", "destination", "dates", "start", "end", "origin", "route",
            "pax", "nights", "flights", "hotels", "total", "currency",
            "status", "html_path", "deploy_url", "notes"]
    return {k: getattr(args, k, None) for k in keys}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("record", help="Upsert a trip into memory")
    _add_record_flags(pr)

    pl = sub.add_parser("list", help="List all recorded trips")
    pl.add_argument("--json", action="store_true")

    pg = sub.add_parser("get", help="Show one trip")
    pg.add_argument("--id", required=True)
    pg.add_argument("--json", action="store_true")

    prm = sub.add_parser("remove", help="Delete one trip")
    prm.add_argument("--id", required=True)

    sub.add_parser("selftest", help="CI smoke test (uses a temp store)")

    args = parser.parse_args(argv)
    home = resolve_home()

    if args.cmd == "record":
        entry = op_record(home, _flags_from_args(args), args.html)
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "list":
        trips = op_list(home)
        if args.json:
            print(json.dumps(trips, ensure_ascii=False, indent=2))
        else:
            print(render_list(trips))
            print(f"\nStore: {json_path(home)}")
        return 0

    if args.cmd == "get":
        entry = op_get(home, args.id)
        if entry is None:
            print(f"No trip with id {args.id!r}", file=sys.stderr)
            return 1
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "remove":
        ok = op_remove(home, args.id)
        print("removed" if ok else f"no trip with id {args.id!r}")
        return 0 if ok else 1

    if args.cmd == "selftest":
        return _selftest()

    return 2


def _selftest() -> int:
    """record -> list -> get -> idempotent update -> remove, in a temp store."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TRIP_PLANNER_HOME"] = tmp
        home = resolve_home()

        e = op_record(home, {
            "id": None, "destination": "Турция", "dates": "20–29 июня 2026",
            "start": "2026-06-20", "end": "2026-06-29",
            "route": "MOW → IST → DLM → VKO", "pax": 2,
            "flights": None, "hotels": None, "total": "≈316 047 ₽",
            "origin": None, "currency": None, "status": None,
            "html_path": None, "deploy_url": None, "nights": None,
            "notes": "1 место багажа на двоих DLM→VKO",
        }, None)
        assert e["id"] == "турция-2026-06", e["id"]
        assert e["nights"] == 9, e["nights"]
        assert e["status"] == "planned", e["status"]
        created = e["created_at"]

        assert json_path(home).exists(), "trips.json not written"
        assert md_path(home).exists(), "trips.md not written"
        json.loads(json_path(home).read_text(encoding="utf-8"))  # valid JSON

        rows = op_list(home)
        assert len(rows) == 1, rows

        got = op_get(home, "турция-2026-06")
        assert got and got["total"] == "≈316 047 ₽", got

        # Idempotent update: same id, attach deploy URL, preserve created_at.
        e2 = op_record(home, {
            "id": "турция-2026-06", "deploy_url": "https://x.vercel.app",
            "destination": None, "dates": None, "start": None, "end": None,
            "origin": None, "route": None, "pax": None, "nights": None,
            "flights": None, "hotels": None, "total": None, "currency": None,
            "status": None, "html_path": None, "notes": None,
        }, None)
        assert e2["deploy_url"] == "https://x.vercel.app", e2
        assert e2["created_at"] == created, "created_at must be preserved"
        assert e2["total"] == "≈316 047 ₽", "existing fields must survive update"
        assert len(op_list(home)) == 1, "update must not duplicate"

        # Collision guard: a different trip (different start) in the same
        # destination+month must not overwrite — it gets a suffixed id.
        e3 = op_record(home, {
            "id": None, "destination": "Турция", "dates": "1–5 июня 2026",
            "start": "2026-06-01", "end": "2026-06-05",
            "origin": None, "route": None, "pax": 2, "nights": None,
            "flights": None, "hotels": None, "total": None, "currency": None,
            "status": None, "html_path": None, "deploy_url": None, "notes": None,
        }, None)
        assert e3["id"] == "турция-2026-06-2", e3["id"]
        assert len(op_list(home)) == 2, "collision must add, not overwrite"
        assert op_remove(home, "турция-2026-06-2") is True

        assert op_remove(home, "турция-2026-06") is True
        assert op_get(home, "турция-2026-06") is None
        assert op_remove(home, "турция-2026-06") is False

    print("selftest: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
