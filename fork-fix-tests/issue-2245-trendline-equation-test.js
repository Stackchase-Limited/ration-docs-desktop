/*
 * #2245 - the equation a trendline prints on a chart.
 *
 * The reporter's P.S. is the visible half: "use - instead of + when b in kx + b is
 * negative". CTrendLine.fillEquationContent glued the intercept on with a hard-coded
 * " + ", so a negative intercept printed as "y = 2x + -3.5".
 *
 * Reading the same function turned up three more defects in the polynomial branch and
 * in the rounding helper:
 *
 *  - r() rounded with `(dVal * 10000 + 0.5 >> 0) / 10000`. `>>` coerces to int32, so
 *    any coefficient from 214748.3648 up wraps round the 32-bit boundary and the label
 *    shows a completely different number - a slope of 1e6 printed as 141006.5408. The
 *    same shift also truncated negatives towards zero, so -3.54997 printed as -3.5499.
 *
 *  - the polynomial branch took Math.abs of every coefficient but only emitted a sign
 *    for nC > 0, so a negative leading coefficient lost its minus: -2x2 + 3x printed
 *    as 2x2 + 3x.
 *
 *  - coefficients are ordered highest power first, so the last one is the constant
 *    term with exponent 0. The branch appended "x" to every term and only skipped the
 *    superscript, so the constant printed as "4x": y = 2x2 + 3x + 4 came out as
 *    y = 2x2 + 3x + 4x.
 *
 * All four corrupt the number the reader sees, silently.
 *
 * The headline request on the issue - a control to raise the number of digits shown -
 * is a feature and is not implemented here; r() still rounds to four decimals.
 *
 * This extracts the real CTrendLine.fillEquationContent by brace matching and drives
 * it against stubbed runs, reading the TRENDLINE_TYPE_* values out of the real
 * SerializeChart.js rather than inventing them.
 *
 * BASELINE=1 runs it against HEAD, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'common/Drawings/Format/ChartFormat.js';
// Pinned to the parent of the commit that landed this fix. It must NOT default to
// HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
// and the test passes forever while testing nothing.
const BASE_REF = process.env.BASE_REF || 'd9795582c1^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

const source = read(REL);

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

const at = source.indexOf('CTrendLine.prototype.fillEquationContent = function(oDrawingContent)');
assert.notStrictEqual(at, -1, 'CTrendLine.fillEquationContent not found');
const fnSrc = matched(source, source.indexOf('(', at + 'CTrendLine.prototype.fillEquationContent = function'.length - 8));
assert.ok(fnSrc.includes('recalculatePositionText'), 'extracted the wrong function');

/* --- the real trendline type numbers, not made-up ones --- */
const chartSrc = read('common/SerializeChart.js');
const TYPE = {};
['EXP', 'LINEAR', 'LOG', 'MOVING_AVG', 'POLY', 'POWER'].forEach(function (name) {
	const m = new RegExp('var TRENDLINE_TYPE_' + name + ' = (\\d+);').exec(chartSrc);
	assert.ok(m, 'TRENDLINE_TYPE_' + name + ' not found in SerializeChart.js');
	TYPE[name] = parseInt(m[1], 10);
});

/* --- 0. the premise: coefficients run highest power first, constant last ---
 * ChartsDrawer._dispRSquared evaluates the fit, and it is the only place that says out
 * loud what the order is. If that changes, the exponent assertions below are measuring
 * nothing. */
{
	const drawerSrc = read('common/Charts/ChartsDrawer.js');
	const rsqAt = drawerSrc.indexOf('_dispRSquared: function (catVals, valVals, coefficients, type)');
	assert.notStrictEqual(rsqAt, -1, '_dispRSquared not found');
	const rsqSrc = matched(drawerSrc, rsqAt);
	assert.ok(/coefficients\[coefficients\.length - 1\]/.test(rsqSrc),
		'the last coefficient is no longer the constant term - this test needs rewriting');
	assert.ok(/for \(let i = coefficients\.length - 2; i >= 0; i--\)[\s\S]{0,200}Math\.pow\(xVal, power\)[\s\S]{0,80}power\+\+/.test(rsqSrc),
		'the powers no longer count up as the index counts down - this test needs rewriting');
}

/* --- stubs --- */
const SUPER = 'superscript';

function ParaRun() { this.parts = []; this.vertAlign = null; }
ParaRun.prototype.AddText = function (s) { this.parts.push(s); };
ParaRun.prototype.SetVertAlign = function (v) { this.vertAlign = v; };

const AscWord = { ParaRun: ParaRun };
const AscCommon = { vertalign_SuperScript: SUPER };
const AscFormat = {
	TRENDLINE_TYPE_EXP: TYPE.EXP,
	TRENDLINE_TYPE_LINEAR: TYPE.LINEAR,
	TRENDLINE_TYPE_LOG: TYPE.LOG,
	TRENDLINE_TYPE_MOVING_AVG: TYPE.MOVING_AVG,
	TRENDLINE_TYPE_POLY: TYPE.POLY,
	TRENDLINE_TYPE_POWER: TYPE.POWER,
};

const fillEquationContent = new Function(
	'AscWord', 'AscCommon', 'AscFormat', '"use strict"; return function' + fnSrc
)(AscWord, AscCommon, AscFormat);

/* Render what the label would read. A superscripted run is written ^(...) so the
 * exponent is visible in the assertion instead of silently colliding with the digits
 * next to it. */
function equation(nType, aCoefficients) {
	const runs = [];
	const oParagraph = { AddToContentToEnd: function (oRun) { runs.push(oRun); } };
	const oDrawingContent = { Content: [oParagraph] };
	const trendline = {
		parent: { isSeries: true },
		trendlineType: nType,
		getChartSpace: function () {
			return {
				chartObj: {
					recalculatePositionText: function () { return { coefficients: aCoefficients }; }
				}
			};
		}
	};
	fillEquationContent.call(trendline, oDrawingContent);
	return runs.map(function (oRun) {
		const s = oRun.parts.join('');
		return oRun.vertAlign === SUPER ? '^(' + s + ')' : s;
	}).join('');
}

/* --- 1. the reporter's P.S.: a negative intercept --- */
assert.strictEqual(equation(TYPE.LINEAR, [2, -3.5]), 'y = 2x - 3.5',
	'a negative intercept printed as "+ -3.5" - this is #2245');
assert.strictEqual(equation(TYPE.LINEAR, [2, 3.5]), 'y = 2x + 3.5',
	'a positive intercept must be unchanged');
assert.strictEqual(equation(TYPE.LINEAR, [2, 0]), 'y = 2x',
	'a zero intercept must still be dropped');
assert.strictEqual(equation(TYPE.LINEAR, [-2, -3.5]), 'y = -2x - 3.5',
	'a negative slope keeps its own sign');
assert.strictEqual(equation(TYPE.LOG, [2, -3.5]), 'y = 2ln(x) - 3.5',
	'the logarithmic equation joins its intercept the same way');

/* --- 2. the 32-bit wrap in r() --- */
assert.strictEqual(equation(TYPE.LINEAR, [1000000, 0]), 'y = 1000000x',
	'a slope of 1e6 wrapped round int32 and printed 141006.5408 - the label was simply ' +
	'a different number from the data');
assert.strictEqual(equation(TYPE.LINEAR, [214748.3648, 0]), 'y = 214748.3648x',
	'the first coefficient at the int32 boundary');
assert.strictEqual(equation(TYPE.LINEAR, [214748.3647, 0]), 'y = 214748.3647x',
	'and the last one below it, which always worked');

/* --- 3. rounding a negative must not truncate towards zero --- */
assert.strictEqual(equation(TYPE.LINEAR, [-3.54997, 0]), 'y = -3.55x',
	'-3.54997 rounds to -3.55, not -3.5499');
assert.strictEqual(equation(TYPE.LINEAR, [3.54997, 0]), 'y = 3.55x',
	'and the positive side must be unchanged');

/* --- 4. polynomial: the leading sign, and the constant term --- */
assert.strictEqual(equation(TYPE.POLY, [2, 3, 4]), 'y = 2x^(2) + 3x + 4',
	'the constant term takes no x - it used to print as "4x"');
assert.strictEqual(equation(TYPE.POLY, [-2, 3, 4]), 'y = -2x^(2) + 3x + 4',
	'a negative leading coefficient lost its minus entirely');
assert.strictEqual(equation(TYPE.POLY, [-2, -3, -4]), 'y = -2x^(2) - 3x - 4',
	'every following term already carried its sign and must keep it');
assert.strictEqual(equation(TYPE.POLY, [2, 0, 4]), 'y = 2x^(2) + 4',
	'a zero coefficient is still skipped');
assert.strictEqual(equation(TYPE.POLY, [0, -3, 4]), 'y = -3x + 4',
	'when the leading term is dropped the next one becomes the first and must not be ' +
	'printed as a dangling " - "');
assert.strictEqual(equation(TYPE.POLY, [1, 2, 3, 4]), 'y = 1x^(3) + 2x^(2) + 3x + 4',
	'a cubic: only exponents above 1 get a superscript');

/* --- 5. the branches that were already right must not move --- */
assert.strictEqual(equation(TYPE.EXP, [0.5, 2]), 'y = 2e^(0.5x)');
assert.strictEqual(equation(TYPE.POWER, [0.5, 2]), 'y = 2x^(0.5)');
assert.strictEqual(equation(TYPE.MOVING_AVG, [1, 2]), '',
	'a moving average has no equation');

/* --- 6. no coefficients at all: the function must bail, not throw --- */
{
	const runs = [];
	const oParagraph = { AddToContentToEnd: function (oRun) { runs.push(oRun); } };
	const trendline = {
		parent: { isSeries: true },
		trendlineType: TYPE.LINEAR,
		getChartSpace: function () {
			return { chartObj: { recalculatePositionText: function () { return null; } } };
		}
	};
	fillEquationContent.call(trendline, { Content: [oParagraph] });
	assert.strictEqual(runs.length, 0, 'nothing may be written when there is no fit');
}

console.log('ok - trendline equations print the sign, the constant term and the number they fitted');
