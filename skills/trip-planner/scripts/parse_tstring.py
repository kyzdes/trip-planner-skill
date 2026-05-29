#!/usr/bin/env python3
"""Decode an Aviasales `t=` string into flight segments + layovers — no browser.

The `t=` query param on an aviasales.ru/search URL encodes every segment as:

    [AIRLINE 2 letters, only when it changes][DEP unix 10][ARR unix 10][flight no][ORIG 3][DEST 3]

…repeated, then a trailing `_<hash>_<marker>`. Example (round trip MAD↔BCN):

    IB1690520400169052520000 00 80 MAD BCN 1693053000169305810000 00 85 BCN MAD _<hash>_78

This lets the skill read segment times and connection (layover) durations for
multi-leg flights straight from the shared link, without opening the page.

Usage:
    parse_tstring.py "<aviasales URL or raw t-string>"
    parse_tstring.py selftest

Stdlib-only. Times are UTC (the unix values are absolute); a layover is a gap
< 24h at a shared airport (dest of one segment == origin of the next).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone

# AIRLINE? DEP(10) ARR(10) FLIGHT(>=1) ORIG(3) DEST(3)
_SEG = re.compile(r"([A-Z]{2})?(\d{10})(\d{10})(\d+?)([A-Z]{3})([A-Z]{3})")


def tstring_from(arg: str) -> str:
    """Accept a full aviasales URL or a raw t-string; return the t value."""
    m = re.search(r"[?&]t=([^&\s]+)", arg)
    return m.group(1) if m else arg.strip()


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def decode_tstring(t: str) -> list[dict]:
    core = t.split("_", 1)[0]  # drop trailing _hash_marker
    segments: list[dict] = []
    airline: str | None = None
    for m in _SEG.finditer(core):
        a, dep, arr, flight, orig, dest = m.groups()
        if a:
            airline = a
        dep_i, arr_i = int(dep), int(arr)
        segments.append({
            "airline": airline,
            "flight": (f"{airline}{int(flight)}" if airline else str(int(flight))),
            "origin": orig,
            "dest": dest,
            "dep_ts": dep_i,
            "arr_ts": arr_i,
            "dep_utc": _iso(dep_i),
            "arr_utc": _iso(arr_i),
            "duration_min": round((arr_i - dep_i) / 60),
        })
    return segments


def layovers(segments: list[dict]) -> list[dict]:
    out = []
    for a, b in zip(segments, segments[1:]):
        if a["dest"] == b["origin"]:
            gap = round((b["dep_ts"] - a["arr_ts"]) / 60)
            out.append({"airport": a["dest"], "gap_min": gap,
                        "is_layover": 0 < gap < 24 * 60})
    return out


def _selftest() -> int:
    # Real sample from the Travelpayouts Aviasales API docs (round trip MAD↔BCN).
    real = "IB16905204001690525200000080MADBCN16930530001693058100000085BCNMAD_29ee244e5b536fb9099d8ec2ca842b19_78"
    segs = decode_tstring(real)
    assert len(segs) == 2, segs
    assert segs[0]["airline"] == "IB" and segs[0]["flight"] == "IB80", segs[0]
    assert (segs[0]["origin"], segs[0]["dest"]) == ("MAD", "BCN"), segs[0]
    assert segs[1]["airline"] == "IB", "airline carries over to later segments"
    assert (segs[1]["origin"], segs[1]["dest"]) == ("BCN", "MAD"), segs[1]
    assert segs[0]["dep_ts"] == 1690520400 and segs[0]["arr_ts"] == 1690525200
    # Round trip: the BCN gap is weeks, so NOT a layover.
    lo = layovers(segs)
    assert lo and lo[0]["airport"] == "BCN" and lo[0]["is_layover"] is False, lo

    # Synthetic connection TK NAV→IST→DLM with an 80-minute layover at IST.
    syn = "TK171930000017193050000001234NAVIST171930980017193148000005678ISTDLM"
    s2 = decode_tstring(syn)
    assert len(s2) == 2 and s2[0]["flight"] == "TK1234" and s2[1]["flight"] == "TK5678", s2
    lo2 = layovers(s2)
    assert lo2[0] == {"airport": "IST", "gap_min": 80, "is_layover": True}, lo2

    # URL extraction.
    assert tstring_from("https://www.aviasales.ru/search/MAD2807BCN1?t=" + real) == real
    print("parse_tstring selftest: OK")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "selftest":
        return _selftest()
    if not argv:
        print("usage: parse_tstring.py <aviasales-url-or-t-string> | selftest", file=sys.stderr)
        return 2
    segs = decode_tstring(tstring_from(argv[0]))
    if not segs:
        print("no segments decoded — is this an aviasales t-string?", file=sys.stderr)
        return 1
    print(json.dumps({"segments": segs, "layovers": layovers(segs)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
