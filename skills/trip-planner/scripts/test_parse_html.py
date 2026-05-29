#!/usr/bin/env python3
"""Fixture tests for trip_registry HTML auto-capture (`parse_html`).

Stdlib `unittest` only — run directly or via `python3 -m unittest`. Covers the
JSON single-source-of-truth path (against the bundled template) and the legacy
table-scrape fallback (against an inline fixture), so neither regresses.

    python3 skills/trip-planner/scripts/test_parse_html.py
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("trip_registry", _HERE / "trip_registry.py")
reg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reg)

# A pre-refactor output: no trip-data block, data only in the rendered table.
LEGACY_HTML = """<!DOCTYPE html><html><head><title>Отпуск в Грузии — Май 2027</title></head>
<body>
<h1>Отпуск в Грузии</h1>
<p class="subtitle">3 &mdash; 9 мая 2027 &middot; на двоих &middot; Тбилиси &rarr; Батуми</p>
<table id="tripTable"><tbody>
<tr class="type-flight"><td>1</td></tr>
<tr class="type-hotel"><td>2</td></tr>
<tr class="type-flight"><td>3</td></tr>
</tbody></table>
<div class="summary-grid"><div class="summary-item">
<div class="summary-value">~180 000 &#8381;</div></div></div>
</body></html>"""


class JsonPath(unittest.TestCase):
    def setUp(self):
        self.got = reg.parse_html(reg.template_path())

    def test_clean_destination(self):
        self.assertEqual(self.got["destination"], "Турция")  # meta.destination, not the h1

    def test_route_and_dates(self):
        self.assertIn("→", self.got["route"])
        self.assertIn("2026", self.got["dates"])

    def test_total(self):
        self.assertIn("316 047", self.got["total"])

    def test_counts(self):
        self.assertEqual(self.got["flights"], 4)
        self.assertEqual(self.got["hotels"], 3)

    def test_extract_trip_data(self):
        data = reg.extract_trip_data(reg.template_path())
        self.assertIsNotNone(data)
        self.assertEqual(len(data["rows"]), 10)


class LegacyFallback(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
        self.tmp.write(LEGACY_HTML)
        self.tmp.close()
        self.got = reg.parse_html(Path(self.tmp.name))

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_prefix_stripped(self):
        self.assertEqual(self.got["destination"], "Грузии")  # "Отпуск в " dropped

    def test_route_and_total(self):
        self.assertIn("→", self.got["route"])
        self.assertIn("180 000", self.got["total"])

    def test_counts(self):
        self.assertEqual(self.got["flights"], 2)
        self.assertEqual(self.got["hotels"], 1)


class CleanDestinationUnit(unittest.TestCase):
    def test_prefixes(self):
        self.assertEqual(reg._clean_destination("Поездка в Японию"), "Японию")
        self.assertEqual(reg._clean_destination("Trip to Italy"), "Italy")
        self.assertEqual(reg._clean_destination("Турция"), "Турция")  # untouched


if __name__ == "__main__":
    unittest.main(verbosity=2)
