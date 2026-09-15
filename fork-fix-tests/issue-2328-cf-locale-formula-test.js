/*
 * #2328 - a conditional formatting rule stops matching when the user's locale uses
 * a comma as the decimal separator.
 *
 * correctFromInterface (cell/model/ConditionalFormatting.js) is the conversion
 * applied to a value coming from the rule dialog - asc_setValue1 calls it. For a
 * formula it parsed the text as locale, which is right, and then assembled it back
 * into locale, which is not: the stored Text is supposed to be canonical, and every
 * reader afterwards parses it with the non-locale parse(). So "=A1>0,5" was stored
 * with its comma intact and then read as something else entirely.
 *
 * recalcFormula in the same file makes the distinction correctly - assembleLocale
 * going out to the interface, assemble coming back from it.
 *
 * This extracts the real correctFromInterface by brace matching and drives it with a
 * parserFormula stub that models the two spellings, so the direction of each
 * conversion is what is under test.
 *
 * BASELINE=1 runs against HEAD, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'cell/model/ConditionalFormatting.js';
// Pinned to the parent of the commit that landed this fix. It must NOT default to
// HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
// and the test passes forever while testing nothing.
const BASE_REF = process.env.BASE_REF || 'e3091262fc^';

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

function extract(name) {
	const at = source.indexOf('function ' + name + '(');
	assert.notStrictEqual(at, -1, name + ' not found');
	return source.slice(at, at + matched(source, source.indexOf('(', at)).length +
		(source.indexOf('(', at) - at));
}

const correctSrc = extract('correctFromInterface');
const quotesSrc = extract('addQuotes');
assert.ok(correctSrc.includes('parse(true, true)'), 'extracted the wrong function');

/* --- stubs ---
 * The canonical spelling of the reporter's formula uses a dot and a comma; the
 * German-style interface spelling uses a comma and a semicolon. The stub knows both
 * and reports which one it was asked to produce. */
const CANONICAL = 'A1>0.5';
const LOCALE = 'A1>0,5';

function parserFormula(text) { this.text = text; this.parsed = false; }
parserFormula.prototype.parse = function (local, digitDelim) {
	// Called with local=true: the text is in the user's locale.
	this.parsed = !!(local && digitDelim);
	return this.parsed;
};
parserFormula.prototype.assemble = function () { return CANONICAL; };
parserFormula.prototype.assembleLocale = function () { return LOCALE; };

const AscCommonExcel = { parserFormula: parserFormula, cFormulaFunctionToLocale: {} };
const AscCommon = { g_oFormatParser: { parseDate: function () { return null; } },
                    g_oDefaultCultureInfo: {} };
const Asc = { editor: { wbModel: { getActiveWs: function () { return {name: 'ws'}; } } } };

const correctFromInterface = new Function(
	'AscCommonExcel', 'AscCommon', 'Asc', 'isNumeric', 'addQuotes',
	'"use strict";' + correctSrc + '\nreturn correctFromInterface;'
)(AscCommonExcel, AscCommon, Asc,
  function (v) { return !isNaN(parseFloat(v)) && isFinite(v); },
  new Function('"use strict";' + quotesSrc + '\nreturn addQuotes;')());

/* --- the defect --- */
assert.strictEqual(correctFromInterface('=' + LOCALE), CANONICAL,
	'a formula typed in a comma-decimal locale must be stored canonically; storing it ' +
	'in locale form is #2328 - every reader parses Text with the non-locale parse()');

/* A formula typed in the canonical locale must come back canonical too. */
assert.strictEqual(correctFromInterface('=' + CANONICAL), CANONICAL);

/* Non-formula values must be untouched by this change. */
assert.strictEqual(correctFromInterface('42'), '42', 'a plain number passes through');
assert.strictEqual(correctFromInterface('Not Started'), '"Not Started"',
	'text is quoted, as before');
/* addQuotes doubles quotes only when the value *starts* with one, so this comes
 * back as "say "hi"". That looks wrong and may well be, but it is untouched by
 * this change and is asserted as it actually behaves, so the test notices if it
 * ever moves. */
assert.strictEqual(correctFromInterface('say "hi"'), '"say "hi""',
	'unchanged: quotes are doubled only for a leading quote');

console.log('ok - a formula from the interface is stored canonically, whatever the locale');
