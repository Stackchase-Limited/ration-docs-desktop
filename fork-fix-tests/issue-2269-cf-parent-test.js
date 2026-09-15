/*
 * #2269 - conditional formatting stops applying once a file is closed and
 * reopened. The rules are all still present, over the right ranges, with the
 * right formula; they just never evaluate. Editing any cell makes them appear.
 *
 * Two callers reach CFormulaCF.prototype.init. The evaluation path in
 * Worksheet._updateConditionalFormatting passes a
 * CConditionalFormattingFormulaParent - that is what a relative reference in the
 * rule resolves against, and what buildDependencies() needs. Serialize.js calls
 * CConditionalFormatting.initRules(ws) while loading the file, and reaches init
 * with no parent.
 *
 * Before 5d44c3d3d3 ("[se] By bug 74483", 2025-10-17) the load path did not call
 * init at all, so the first call was the parented one. That commit made the load
 * path call it, to correct and reassemble the stored text - and the `if (!this._f)`
 * guard then swallowed the parented call that arrived later. The rule kept a
 * formula with no parent and no dependencies for the rest of the session.
 *
 * This extracts the real constructor and the real init by brace matching and
 * drives them in the order the application does: load first, then evaluate.
 *
 * BASELINE=1 runs it against HEAD, where it must fail.
 *
 * Note for anyone tempted to run this with BASE_REF=5d44c3d3d3^ as a control: it
 * fails there too, and that means nothing. The old load path never called init at
 * all, so feeding init(ws) to it exercises a sequence that could not occur. The
 * premise is asserted directly instead, below - that the load path as it stands
 * does reach init with a ws and no parent.
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
const BASE_REF = process.env.BASE_REF || '280811aeca^';

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

const ctorAt = source.indexOf('function CFormulaCF()');
assert.notStrictEqual(ctorAt, -1, 'CFormulaCF constructor not found');
const ctorSrc = matched(source, ctorAt);

const initAt = source.indexOf('CFormulaCF.prototype.init = function (ws, opt_parent)');
assert.notStrictEqual(initAt, -1, 'CFormulaCF.init not found');
const initSrc = matched(source, source.indexOf('(', initAt + 'CFormulaCF.prototype.init = function'.length - 8));
assert.ok(initSrc.includes('buildDependencies'), 'extracted the wrong function');

/* --- stubs --- */
let built = 0;               // parserFormula instances created
function makeEnv() {
	built = 0;
	const parsers = [];
	function parserFormula(text, parent, ws) {
		this.Formula = text;
		this.parent = parent;
		this.ws = ws;
		this.depsBuilt = 0;
		built++;
		parsers.push(this);
	}
	parserFormula.prototype.parse = function (a, b, parseResult) {
		// The stored text needs reassembling - this is what 5d44c3d3d3 added.
		if (parseResult) parseResult.needAssemble = true;
		return true;
	};
	parserFormula.prototype.assemble = function () { return 'ASSEMBLED(' + this.Formula + ')'; };
	parserFormula.prototype.buildDependencies = function () { this.depsBuilt++; };

	function ParseResult() { this.needCorrect = false; this.needAssemble = false; }

	const AscCommonExcel = { parserFormula, ParseResult };
	const CFormulaCF = new Function('AscCommonExcel', '"use strict"; return ' + ctorSrc)(AscCommonExcel);
	CFormulaCF.prototype.init = new Function(
		'AscCommonExcel', '"use strict"; return function' + initSrc
	)(AscCommonExcel);
	return { CFormulaCF, parsers };
}

const WS = { name: 'sheet' };
function parent(tag) { return { tag: tag, isCfParent: true }; }

/* --- 0. the premise: the load path reaches init with a ws and no parent ---
 * CConditionalFormatting.initRules(ws) is what Serialize.js calls while reading the
 * file (Serialize.js: "oConditionalFormatting.initRules(oWorksheet)"), and it reaches
 * the rule elements through CConditionalFormattingRule.updateConditionalFormatting.
 * If that stops being true, the rest of this test is measuring nothing. */
{
	const updAt = source.indexOf('CConditionalFormattingRule.prototype.updateConditionalFormatting = function');
	assert.notStrictEqual(updAt, -1, 'updateConditionalFormatting not found');
	const updSrc = matched(source, source.indexOf('(', updAt + 60));
	assert.ok(/\.init\s*&&\s*[\w.[\]]+\.init\(ws\)/.test(updSrc) || /\.init\(ws\)/.test(updSrc),
		'the load path no longer calls init(ws) - this test needs rewriting');
}

/* --- 1. the defect: load, then evaluate --- */
{
	const { CFormulaCF } = makeEnv();
	const f = new CFormulaCF();
	f.Text = '=$B$1';

	f.init(WS);                        // Serialize.js -> initRules(ws), no parent
	const afterLoad = f.Text;

	const p = parent('evaluation');
	f.init(WS, p);                     // _updateConditionalFormatting, with a parent

	assert.strictEqual(f._f.parent, p,
		'the rule formula has no parent after load, so a relative reference in it ' +
		'cannot resolve and the rule never evaluates - this is #2269');
	assert.strictEqual(f._f.depsBuilt, 1,
		'buildDependencies() was never called, so the rule is never recalculated');

	/* The load-time text correction that 5d44c3d3d3 added must survive. */
	assert.strictEqual(afterLoad, 'ASSEMBLED(=$B$1)',
		'the stored text must still be corrected and reassembled at load');
}

/* --- 2. evaluating repeatedly must not rebuild every time --- */
{
	const { CFormulaCF } = makeEnv();
	const f = new CFormulaCF();
	f.Text = '=$B$1';
	f.init(WS);
	f.init(WS, parent('first'));
	const afterFirst = f._f;
	const builtAfterFirst = built;

	f.init(WS, parent('second'));
	f.init(WS, parent('third'));

	assert.strictEqual(f._f, afterFirst,
		'the first parented caller must win and be kept - the parent object is created ' +
		'afresh on every update, so rebuilding per call would never stop');
	assert.strictEqual(built, builtAfterFirst, 'no further parsers may be built');
	assert.strictEqual(f._f.depsBuilt, 1, 'dependencies must be built exactly once');
}

/* --- 3. parented first (a rule created in the session), then an unparented call --- */
{
	const { CFormulaCF } = makeEnv();
	const f = new CFormulaCF();
	f.Text = '=$B$1';
	const p = parent('created');
	f.init(WS, p);
	const first = f._f;
	f.init(WS);                        // must not discard the good one
	assert.strictEqual(f._f, first, 'an unparented call must not rebuild a parented formula');
	assert.strictEqual(f._f.parent, p, 'and must not lose the parent');
	assert.strictEqual(f._f.depsBuilt, 1);
}

/* --- 4. a rule never evaluated keeps working as before --- */
{
	const { CFormulaCF } = makeEnv();
	const f = new CFormulaCF();
	f.Text = '=A1';
	f.init(WS);
	assert.ok(f._f, 'load must still leave a usable formula object');
	assert.strictEqual(f._f.depsBuilt, 0, 'with no parent there are no dependencies to build');
}

console.log('ok - a rule loaded from file is reparented and gets its dependencies built');
