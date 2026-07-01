#!/usr/bin/env node
/* Smoke test for the JSON single-source-of-truth template render/build functions.
 *
 * Loads assets/template.html, evaluates the pure builders (the block between the
 * `=== pure builders ===` markers), and asserts:
 *   - the baseline (Turkey example) renders unchanged and shows none of the
 *     opt-in compare/currency UI;
 *   - alternatives / variants / currency render only when the data carries them.
 *
 * Node stdlib only. Run: node skills/trip-planner/scripts/test_template.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const tpl = path.join(__dirname, '..', 'assets', 'template.html');
const html = fs.readFileSync(tpl, 'utf8');

const T = JSON.parse(html.match(/<script id="trip-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const region = html.match(/\/\* === pure builders[\s\S]*?=== end pure builders === \*\//)[0];
const B = {};
eval(region + '\nObject.assign(B,{tableRowsHtml,summaryHtml,notesHtml,variantsHtml,budgetHtml,fxControlHtml,convertMoney,fmtMoney,altsHtml,xlsxAoa,pdfBodyHtml});');

let failed = 0;
const cnt = (s, re) => (s.match(re) || []).length;
const ok = (cond, msg) => { console.log((cond ? 'ok  ' : 'FAIL') + ' - ' + msg); if (!cond) failed++; };
const norm = s => s.replace(/\s/g, ' '); // normalise nbsp for comparison

// ---- baseline (the bundled Turkey example) ----
const base = B.tableRowsHtml(T);
ok(cnt(base, /<tr /g) === 10, 'baseline: 10 rows');
ok(cnt(base, /type-flight/g) === 4 && cnt(base, /type-hotel/g) === 3, 'baseline: 4 flights / 3 hotels');
ok(B.xlsxAoa(T).length === 15, 'baseline: XLSX head+10+blank+3 totals');
ok(cnt(B.pdfBodyHtml(T), /class="item /g) === 10, 'baseline: 10 PDF cards');
const f = T.rows.filter(r => r.type === 'flight').reduce((a, r) => a + r.priceNum, 0);
ok(f === T.totals.flights, 'baseline: priceNum sum == totals.flights (SoT consistent)');
ok(!base.includes('class="alts"'), 'baseline: no alternatives rendered');
ok(B.variantsHtml(T) === '', 'baseline: no variants card');
ok(B.budgetHtml(T) === '', 'baseline: no budget card (no budget field)');
ok(B.fxControlHtml(T) === '', 'baseline: no currency control (no meta.fx)');

// ---- opt-in features (KYZ-211/212/213) ----
const S = {
  meta: { title: 'X', fx: { EUR: 0.0099, USD: 0.0108 } },
  rows: [{
    type: 'flight', title: 'MOW → IST', price: '48 991 ₽', priceNum: 48991,
    alternatives: [{ operator: 'S7', time: '09:55', price: '47 000 ₽', note: 'вечером' },
                   { operator: 'Turkish', time: '13:40', price: '52 300 ₽' }],
  }],
  summary: [{ value: '~316 047 ₽', label: 'Итого', rub: 316047 }],
  variants: [{ label: 'Вариант А', total: '313 558 ₽', nights: 10, note: '18–28 июня' },
             { label: 'Вариант Б', total: '354 928 ₽', nights: 9 }],
  budget: {
    title: 'Смета', items: [
      { label: 'Перелёты', value: '48 991 ₽', rub: 48991 },
      { label: 'Виза', sub: '$50/чел', value: 'не включена' },
    ], total: { label: 'ИТОГО', value: '~316 047 ₽', rub: 316047 },
  },
  totals: {},
};
const sr = B.tableRowsHtml(S);
ok(cnt(sr, /class="alt"/g) === 2, '211: two alternative sub-lines');
ok(sr.includes('<b>S7</b>') && sr.includes('вечером'), '211: alternative content present');
const vh = B.variantsHtml(S);
ok(cnt(vh, /summary-item/g) === 2 && vh.includes('Вариант А') && vh.includes('10 ноч.'), '212: two variant cards');
const fc = B.fxControlHtml(S);
ok(fc.includes('RUB') && fc.includes('EUR') && fc.includes('USD'), '213: currency select RUB+EUR+USD');
ok(B.summaryHtml(S).includes('data-rub="316047"'), '213: summary value convertible');
const bh = B.budgetHtml(S);
ok(cnt(bh, /budget-row/g) === 3 && bh.includes('budget-total'), 'budget: 2 items + highlighted total');
ok(bh.includes('data-rub="48991"') && bh.includes('$50/чел'), 'budget: line convertible + sub-label');
ok(norm(B.convertMoney(48991, 0.0099, 'EUR')) === '485 €', '213: 48991 RUB -> 485 EUR');
ok(norm(B.fmtMoney(316047, 'RUB')) === '316 047 ₽', '213: RUB thousands formatting');

console.log(failed ? `\n${failed} FAILED` : '\nall template checks passed');
process.exit(failed ? 1 : 0);
