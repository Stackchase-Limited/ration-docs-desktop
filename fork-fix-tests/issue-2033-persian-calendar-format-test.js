/*
 * #2033 - "Support for additional calendars (e.g. Persian calendar) in Spreadsheet". Excel
 * shows a date in the Persian (Jalali / Solar Hijri) calendar when the cell's number format
 * carries the calendar in its locale tag: [$-fa-IR,16]yyyy/mm/dd or the hex form
 * [$-160429]yyyy/mm/dd (calendar type 0x16 = Windows CAL_PERSIAN in bits 16-23). Such files
 * opened here showed the Gregorian date (1 Farvardin 1404 as 2025/03/21) - the tag was
 * read only for its LCID (and "fa-IR,16" was even read as LCID 0xFA). Now possible: those
 * formats display Jalali year/month/day, and mmm/mmmm give the Persian month names.
 *
 * Fix (sdkjs common/NumFormat.js): FormatObjBracket keeps the whole locale tag;
 * NumFormat._parseCalendar reads the calendar type from it (",<hex>" after a locale name,
 * which also sets the LCID from the name, or bits 16-23 of a hex LCID); for the Persian
 * type, _parseNumber converts the parsed date with _toPersianDate (Borkowski's algorithm
 * with the leap-year break table, as in jalaali-js). Other calendar types and every format
 * without one are unchanged; cell values (serial numbers) and formulas are untouched.
 *
 * This loads the REAL common/commonDefines.js and common/NumFormat.js into a node vm and
 * formats serial numbers through AscCommon.oNumFormatCache, as the cell renderer does.
 *
 * NOT claimed: typing a Jalali date into a cell (input is still parsed as Gregorian); a
 * UI to pick the calendar (the format is entered as a custom format or comes with the
 * file); Hijri / other calendars; Persian day names (there is no fa-IR culture table, so
 * dddd uses the default culture); the x2t PDF/CSV export paths.
 *
 *   RD_REPO=<sdkjs> (default ../sdkjs).  BASELINE=1 reads BASE_REF -> must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '177bd1c53b^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

const ctx = { console, navigator: { userAgent: '' }, document: {} };
ctx.window = ctx;
vm.createContext(ctx);
for (const f of ['common/commonDefines.js', 'common/NumFormat.js'])
	vm.runInContext(src(f), ctx, { filename: f });

function fmt(format, serial) {
	return ctx.AscCommon.oNumFormatCache.get(format).format(serial, 0, 15).map((x) => x.text).join('');
}

let failures = 0;
function check(what, got, want) {
	const ok = got === want;
	failures += !ok;
	console.log(`  ${what.padEnd(50)} ${JSON.stringify(got).padEnd(26)} ${ok ? 'ok' : 'FAILED (want ' + JSON.stringify(want) + ')'}`);
}

console.log('sdkjs ' + (process.env.BASELINE ? '@ ' + BASE_REF : SDKJS));
// serials: 45658 = 2025-01-01, 45736 = 2025-03-20, 45737 = 2025-03-21 (Nowruz 1404), 28897 = 1979-02-11
check('[$-fa-IR,16]yyyy/mm/dd  2025-01-01', fmt('[$-fa-IR,16]yyyy/mm/dd;@', 45658), '1403/10/12');
check('[$-fa-IR,16]yyyy/mm/dd  2025-03-20 (leap 1403)', fmt('[$-fa-IR,16]yyyy/mm/dd;@', 45736), '1403/12/30');
check('[$-fa-IR,16]yyyy/mm/dd  2025-03-21', fmt('[$-fa-IR,16]yyyy/mm/dd;@', 45737), '1404/01/01');
check('[$-160429]yyyy/mm/dd    1979-02-11', fmt('[$-160429]yyyy/mm/dd', 28897), '1357/11/22');
check('[$-fa-IR,16]d mmmm yyyy 2025-03-21', fmt('[$-fa-IR,16]d mmmm yyyy', 45737), '1 فروردین 1404');
check('[$-fa-IR,16]yy/m/d hh:mm 2025-01-01 18:00', fmt('[$-fa-IR,16]yy/m/d hh:mm', 45658.75), '03/10/12 18:00');
// unchanged
check('yyyy/mm/dd (no calendar)', fmt('yyyy/mm/dd', 45737), '2025/03/21');
check('[$-fa-IR]yyyy/mm/dd (no calendar)', fmt('[$-fa-IR]yyyy/mm/dd', 45737), '2025/03/21');
check('[$-10429]yyyy/mm/dd (calendar 1 = Gregorian)', fmt('[$-10429]yyyy/mm/dd', 45737), '2025/03/21');
check('[$-409]mmmm d, yyyy', fmt('[$-409]mmmm d, yyyy', 45737), 'March 21, 2025');
check('[$-x-sysdate]dddd, mmmm dd, yyyy', fmt('[$-x-sysdate]dddd, mmmm dd, yyyy', 45737), 'Friday, March 21, 2025');

console.log(failures ? '\nFAILED' : '\nok - Persian-calendar number formats show Jalali dates');
process.exit(failures ? 1 : 0);
