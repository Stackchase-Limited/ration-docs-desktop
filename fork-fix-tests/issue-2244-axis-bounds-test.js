/*
 * #2244 - the minimum and maximum of a chart axis were limited to +/-1000000, so a
 * chart of light frequencies (~1e14) could not be scaled at all.
 *
 * The limit was in the UI only: Common.UI.MetricSpinner clamps at
 * "if (number > this.options.maxValue) { number = this.options.maxValue; ... }"
 * (apps/common/main/lib/component/MetricSpinner.js). Nothing in sdkjs bounds a
 * manual axis minimum or maximum.
 *
 * An axis bound is a data value, so it should not be tighter than the data a cell
 * can hold. The new bound is Number.MAX_SAFE_INTEGER, and the two reasons are
 * checked below rather than asserted: it is where integer arithmetic stops being
 * exact, and it stays under 1e21, where JavaScript starts writing numbers in
 * exponential notation that the field cannot read back.
 *
 * BASELINE=1 runs against HEAD, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const WEBAPPS = path.resolve(__dirname, '..', 'web-apps');
// Pinned to the parent of the commit that landed this fix. It must NOT default to
// HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
// and the test passes forever while testing nothing.
const BASE_REF = process.env.BASE_REF || 'b0b8517702^';

const FILES = [
	'apps/spreadsheeteditor/main/app/view/ChartSettingsDlg.js',
	'apps/presentationeditor/main/app/view/ChartSettingsAdvanced.js',
	'apps/pdfeditor/main/app/view/ChartSettingsAdvanced.js',
];

/* Spinners whose value is a point on the axis - these must not be clamped tighter
 * than a cell value. */
const AXIS_VALUE = ['spnMinValue', 'spnMaxValue', 'spnVAxisCrosses', 'spnHAxisCrosses',
                    'spnSparkMinValue', 'spnSparkMaxValue'];

/* Spinners whose value is a count of intervals - these are legitimately bounded and
 * must be left alone, so an over-broad edit is caught. */
const INTERVAL = ['spnMarksInterval', 'spnLabelInterval'];

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', WEBAPPS, 'show', `${BASE_REF}:${rel}`],
			{ encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(WEBAPPS, rel), 'utf8');
}

/* The options block of one spinner: from its assignment to the closing "})". */
function optionsOf(src, name) {
	const re = new RegExp('\\b' + name + '\\b\\s*(?:\\[[^\\]]*\\])?\\s*=\\s*new Common\\.UI\\.MetricSpinner');
	const m = re.exec(src);
	if (!m) return null;
	const end = src.indexOf('})', m.index);
	return src.slice(m.index, end);
}

let checkedAxis = 0, checkedInterval = 0;
for (const rel of FILES) {
	const src = read(rel);
	for (const name of AXIS_VALUE) {
		const block = optionsOf(src, name);
		if (!block) continue;
		checkedAxis++;
		assert.ok(/maxValue\s*:\s*Number\.MAX_SAFE_INTEGER/.test(block),
			`${rel}: ${name} is still clamped - an axis bound must not be tighter than the data (#2244)`);
		assert.ok(/minValue\s*:\s*-Number\.MAX_SAFE_INTEGER/.test(block),
			`${rel}: ${name} minimum is still clamped (#2244)`);
	}
	for (const name of INTERVAL) {
		const block = optionsOf(src, name);
		if (!block) continue;
		checkedInterval++;
		assert.ok(!/MAX_SAFE_INTEGER/.test(block),
			`${rel}: ${name} counts intervals, not data - it should not have been raised`);
	}
}
assert.ok(checkedAxis >= 12, `expected to find the axis spinners, found ${checkedAxis}`);
assert.ok(checkedInterval >= 4, `expected to find the interval spinners, found ${checkedInterval}`);

/* --- why this bound and not a larger one ---
 * MetricSpinner stores its value by concatenation: "this.value = (number + ' ' +
 * unit).trim()". So the bound has to be a number JavaScript still writes as plain
 * digits, or the field cannot read its own value back. */
const plain = (n) => /^-?\d+$/.test(String(n));
assert.ok(plain(1e14), 'the reported case must be expressible as plain digits');
assert.ok(plain(Number.MAX_SAFE_INTEGER), 'the new bound must be plain digits');
assert.ok(!plain(1e21), '1e21 is exponential - the bound has to stay below it');

/* And it is the point where stepping stops being exact. */
assert.strictEqual(Number.MAX_SAFE_INTEGER + 1, Number.MAX_SAFE_INTEGER + 2,
	'beyond MAX_SAFE_INTEGER integers are no longer distinct');

console.log('ok - axis bounds reach %s; %d axis spinners raised, %d interval spinners left alone',
	Number.MAX_SAFE_INTEGER, checkedAxis, checkedInterval);
