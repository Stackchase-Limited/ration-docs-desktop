/*
 * #2062 - "LaTeX equation input on macOS": with LaTeX input selected, an
 * equation was sometimes not rendered - Current/All -> Professional did
 * nothing and the editor stopped responding.
 *
 * Cause: the LaTeX tokenizer classes every TokenSpace word (\thinsp, \medsp,
 * \thicksp, \nbsp, \hairsp, \emsp, ...) as a space token, but
 * CLaTeXParser.GetSpaceLiteral (word/Math/LaTeXParser.js) only ate "\ " and
 * "\quad". For any other space token it returned without eating it, so the
 * expression loop asked for the same lookahead forever: an endless loop on
 * the UI thread. The professional -> LaTeX writer itself emits "\thicksp"
 * for U+2005, so a Word equation with a thick space hangs on the round trip
 * Linear (LaTeX) -> Professional. Separately, the non-letter spacing
 * commands \, \: \; were left in the equation as literal text ("\,dx" in
 * the issue's own Gaussian-integral sample).
 *
 * This loads the REAL word/Math/mathTypes.js, NamesOfLiterals.js and LaTeXParser.js (whole
 * files) into a vm context with the few editor globals they touch stubbed,
 * and runs the real AscMath.ConvertLaTeXToTokensList on LaTeX strings with a
 * vm timeout, so a hang fails the test instead of freezing it.
 *
 * Claimed: the parser terminates on these inputs and turns each spacing
 * command into one space character; \frac/\int/\sqrt still parse as before.
 * NOT claimed: how the tokens are laid out as math objects (ConvertTokens,
 * not run here), nor anything about keyboard input - real Mac layouts
 * (German/French Option+Shift for \ { }) were checked in headless Chromium
 * and deliver every character, so no key-handling change was needed.
 *
 * RD_REPO overrides the sdkjs checkout (default ../sdkjs). BASELINE=1 reads the
 * sources from BASE_REF (default: parent of the fix commit) and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '599f986ab7^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* --- minimal editor globals used while tokenizing --- */
const ctx = { console };
ctx.window = ctx;
ctx.AscCommon = { convertUTF16toUnicode: s => Array.from(s).map(c => c.codePointAt(0)) };
ctx.AscCommonWord = {};
ctx.AscMath = {};
ctx.reviewtype_Common = 0;
function Same() {}
Same.prototype.IsEqual = function () { return true; };
Same.prototype.Copy = function () { return new this.constructor(); };
ctx.AscWord = { ReviewInfo: Same };
ctx.CMPrp = function CMPrp() {}; ctx.CMPrp.prototype = Object.create(Same.prototype); ctx.CMPrp.prototype.constructor = ctx.CMPrp;
ctx.CTextPr = function CTextPr() {}; ctx.CTextPr.prototype = Object.create(Same.prototype); ctx.CTextPr.prototype.constructor = ctx.CTextPr;
vm.createContext(ctx);

for (const rel of ['vendor/string.js', 'word/Math/mathTypes.js', 'word/Math/NamesOfLiterals.js', 'word/Math/LaTeXParser.js'])
	vm.runInContext(src(rel), ctx, { filename: rel });
assert.strictEqual(typeof ctx.AscMath.ConvertLaTeXToTokensList, 'function');

/* Parse with the real converter; a hang becomes an exception after 3 s. */
function parse(latex) {
	ctx.__in = latex;
	try {
		return vm.runInContext('JSON.stringify(AscMath.ConvertLaTeXToTokensList(__in, null, true), (k, v) => k === "style" ? undefined : v)',
			ctx, { timeout: 3000 });
	} catch (e) {
		if (/timed out/.test(e.message)) return 'HANG';
		throw e;
	}
}
/* All leaf "value" strings of the token tree, in order. */
function values(json) {
	const out = [];
	(function walk(o) {
		if (Array.isArray(o)) o.forEach(walk);
		else if (o && typeof o === 'object') { if (typeof o.value === 'string') out.push(o.value); else walk(o.value); for (const k in o) if (k !== 'value') walk(o[k]); }
	})(JSON.parse(json));
	return out.join('');
}

const failures = [];
function check(latex, expect) {
	const r = parse(latex);
	const got = r === 'HANG' ? 'HANG (endless loop: the editor freezes)' : values(r);
	const ok = got === expect;
	console.log(`${ok ? 'ok  ' : 'FAIL'} ${JSON.stringify(latex)} -> ${JSON.stringify(got)}${ok ? '' : ' expected ' + JSON.stringify(expect)}`);
	if (!ok) failures.push(latex);
}

/* 1. TokenSpace words other than "\ " and "\quad" (the hang). "\thicksp" is
      what the LaTeX writer itself produces for U+2005. */
check('a\\thinsp b', 'a b');
check('a\\medsp b', 'a b');
check('a\\thicksp b', 'a b');
check('a\\nbsp b', 'a b');
check('a\\thickspb', 'a b');

/* 2. non-letter spacing commands from the issue's sample. */
check('e^{-x^2}\\,dx', 'e-x2 dx');
check('a\\:b', 'a b');
check('a\\;b', 'a b');

/* 3. unchanged: plain LaTeX, "\ " and "\quad". */
check('a\\ b', 'a b');
check('a\\quad b', 'a b');
check('\\frac{a}{b}', 'ab');
check('\\sqrt{b^2 - 4ac}', 'b2-4ac');

assert.deepStrictEqual(failures, [], 'LaTeX spacing commands must convert, not hang or stay as text');
console.log('PASS #2062: LaTeX spacing commands convert to spaces without hanging' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
