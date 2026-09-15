/*
 * #2296 - "Inconsistent Date Format and Date Bug in Spreadsheet".
 *
 * The reporter types dates into General cells and gets two different display
 * formats for what is the same date, and occasionally a cell full of "#####".
 *
 * FormatParser.parseDate (common/NumFormat.js) recognises a spelled-out month in
 * either position. Both positions produce the same serial number, but not the
 * same number format:
 *
 *     "5 Mar 2025"   -> d-mmm-yy   -> 5-Mar-25
 *     "Mar 5 2025"   -> dd-mmm-yy  -> 05-Mar-25
 *
 * The month-first branch is the newer one: c1c802d637 ("[se] Fix bug 21211",
 * 2024-06-14) added support for "October 11, 2008" and wrote "dd-mmm-yy" into
 * it, while the month-second branch it was copied from says "d-mmm-yy". Nothing
 * else in the function distinguishes the two - the two-element month-first case
 * ("Mar 5") in the very same branch still yields "d-mmm". So a column sized for
 * 5-Mar-25 overflows into ##### as soon as one of the entries happens to be
 * typed month-first, which is the reporter's second symptom.
 *
 * This extracts the real FormatParser (constructor, prototype and the file-local
 * helpers it closes over) by brace matching, plus the real en-US culture record,
 * and drives parseDate directly.
 *
 * BASELINE=1 re-reads common/NumFormat.js from git and must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'common/NumFormat.js';
// Pinned to the parent of the commit that landed this fix. It must NOT default to
// HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
// and the test passes forever while testing nothing.
const BASE_REF = process.env.BASE_REF || '8ad35f24cc^';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function grab(signature) {
	const at = source.indexOf(signature);
	assert.notStrictEqual(at, -1, 'not found in ' + REL + ': ' + signature);
	return matched(source, at);
}

/* --- the real code under test --- */
const ctorSrc = grab('function FormatParser()');
const protoAt = source.indexOf('FormatParser.prototype =');
assert.notStrictEqual(protoAt, -1, 'FormatParser.prototype not found');
const protoSrc = matched(source, source.indexOf('{', protoAt));
assert.ok(protoSrc.includes('parseDate: function'), 'extracted the wrong object');
assert.ok(protoSrc.includes('_parseDateFromArray: function'), 'extracted the wrong object');

/* file-local helpers parseDate/_parseDateFromArray close over */
const helpers = [
	grab('function escapeRegExp(string)'),
	grab('function isDMY(cultureInfo)'),
	grab('function isYMD(cultureInfo)'),
	grab('function getShortDateFormat(opt_cultureInfo)'),
	grab('function getShortDateMonthFormat(')
].join('\n');

/* the real en-US culture record out of g_aCultureInfos */
const cultureLine = source.split('\n').find(l => l.indexOf('LCID: 1033') !== -1);
assert.ok(cultureLine, 'en-US culture record not found');
const enUS = JSON.parse(JSON.stringify(
	(new Function('return (' + matched(cultureLine, cultureLine.indexOf('{')) + ')'))()
));
assert.strictEqual(enUS.Name, 'en-US');
assert.strictEqual(enUS.ShortDatePattern, '205'); // m/d/yyyy

/* --- stubs --- */
const AscCommon = { bDate1904: false };
const AscCommonExcel = {
	parseNum: function (v) { return !isNaN(parseFloat(v)) && isFinite(v); }
};
const Asc = {
	isNumberInfinity: function () { return true; },
	c_oAscNumFormatType: {
		General: 0, Number: 1, Scientific: 2, Percent: 3, Currency: 4, Date: 5,
		Time: 6, Fraction: 7, Text: 8, Custom: 9, Accounting: 10, LongDate: 11
	}
};

const build = new Function(
	'AscCommon', 'AscCommonExcel', 'Asc', 'g_oDefaultCultureInfo',
	'"use strict";\n' +
	ctorSrc + '\n' +
	'FormatParser.prototype = ' + protoSrc + ';\n' +
	helpers + '\n' +
	'return FormatParser;'
);
const FormatParser = build(AscCommon, AscCommonExcel, Asc, enUS);
const parser = new FormatParser();

function parse(text) {
	const res = parser.parseDate(text, enUS);
	assert.ok(res, 'parseDate refused to recognise ' + JSON.stringify(text));
	return res;
}

/* --- 1. the defect: one date, two formats --- */
{
	const monthSecond = parse('5 Mar 2025');
	const monthFirst = parse('Mar 5 2025');

	assert.strictEqual(monthSecond.value, monthFirst.value,
		'both spellings must be the same day');

	assert.strictEqual(monthFirst.format, monthSecond.format,
		'"Mar 5 2025" and "5 Mar 2025" are the same date and must be shown the ' +
		'same way - this is #2296 (got ' + JSON.stringify(monthFirst.format) +
		' vs ' + JSON.stringify(monthSecond.format) + ')');

	assert.strictEqual(monthFirst.format, 'd-mmm-yy',
		'the day-month-year format for a spelled-out month is d-mmm-yy; dd-mmm-yy ' +
		'is a character wider and overflows a column sized for the other spelling');
}

/* --- 2. every month-first spelling the reporter tried agrees --- */
{
	const spellings = [
		'Mar 5 2025', 'Mar 5, 2025', 'March 5 2025', 'March 5, 2025',
		'mar 5 2025', 'march 5, 2025'
	];
	const reference = parse('5 Mar 2025');
	for (const text of spellings) {
		const got = parse(text);
		assert.strictEqual(got.format, reference.format,
			JSON.stringify(text) + ' must use the same format as "5 Mar 2025"');
		assert.strictEqual(got.value, reference.value,
			JSON.stringify(text) + ' must be the same day as "5 Mar 2025"');
	}
}

/* --- 3. a different month, so this is not one hard-coded string --- */
{
	const a = parse('January 31 2026');
	const b = parse('31 January 2026');
	assert.strictEqual(a.format, b.format, 'January must agree with itself too');
	assert.strictEqual(a.value, b.value);
	assert.strictEqual(a.format, 'd-mmm-yy');
}

/* --- 4. nothing else moved ---
 * The month-second branch, the two-element cases and the purely numeric path
 * must keep the formats they already had. */
{
	assert.strictEqual(parse('5 Mar 2025').format, 'd-mmm-yy');
	assert.strictEqual(parse('5-Mar-2025').format, 'd-mmm-yy');
	assert.strictEqual(parse('Mar 5').format, 'd-mmm');
	assert.strictEqual(parse('5 Mar').format, 'd-mmm');
	assert.strictEqual(parse('Mar 2025').format, 'mmm-yy');
	assert.strictEqual(parse('3/5/2025').format, 'm/d/yyyy');
	assert.strictEqual(parse('3/5/2025').value, parse('Mar 5 2025').value,
		'the serial number must not have moved');
}

/* --- 5. invalid dates are still rejected --- */
{
	assert.strictEqual(parser.parseDate('Feb 29 2025', enUS), null,
		'2025 is not a leap year');
	assert.strictEqual(parser.parseDate('Mar 32 2025', enUS), null);
}

console.log('ok - "Mar 5 2025" and "5 Mar 2025" now format alike as d-mmm-yy');
