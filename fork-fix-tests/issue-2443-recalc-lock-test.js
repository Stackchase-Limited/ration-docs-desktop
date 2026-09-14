/*
 * #2443 - a spreadsheet stopped recalculating and could not be saved after the
 * user adjusted a table's column structure. Formulas went blank with no error
 * shown, and a freshly typed "=SUM(A2+1)" was blank too.
 *
 * The row and column structure operations suspend recalculation across their
 * body: DependencyGraph.lockRecal() raises a counter, and calcTree() returns
 * immediately while that counter is above zero (Workbook.js, "if
 * (this.lockCounter > 0) { callback && callback(); return; }"). The matching
 * unlockRecal() sat at the end of the function with nothing between them to
 * survive a throw - so one exception anywhere in those bodies left the counter
 * stuck above zero and the workbook unable to recalculate for the rest of the
 * session. Nothing reports that state, which is why there is no error to see.
 *
 * This extracts the real Worksheet.prototype._insertColsBefore and the real
 * lockRecal/unlockRecal/lockRecalExecute by brace matching, forces a throw at
 * the first call the body makes, and checks the counter comes back to zero.
 *
 * BASELINE=1 runs it against HEAD, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'cell/model/Workbook.js';
const BASE_REF = process.env.BASE_REF || 'HEAD';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

/* Brace-match forward from the first '{' at or after `from`. */
function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

/* An object-literal method: `name: function(args) { ... }` */
function member(name) {
	const at = source.indexOf(`\t\t${name}: function(`);
	assert.notStrictEqual(at, -1, `${name} not found`);
	const sig = source.slice(at, source.indexOf('{', at));
	const args = sig.slice(sig.indexOf('(') + 1, sig.lastIndexOf(')'));
	const body = matched(source, source.indexOf('{', at));
	return { args, body };
}

const lockRecal = member('lockRecal');
const unlockRecal = member('unlockRecal');
const isLockRecal = member('isLockRecal');
const lockRecalExecute = member('lockRecalExecute');

const fnAt = source.indexOf('Worksheet.prototype._insertColsBefore=function');
assert.notStrictEqual(fnAt, -1, '_insertColsBefore not found');
const insertColsBefore = matched(source, source.indexOf('(', fnAt));
assert.ok(insertColsBefore.includes('lockRecal()'), 'extracted the wrong function');
assert.ok(insertColsBefore.includes('renameDependencyNodes'), 'extracted the wrong function');

/* --- the real DependencyGraph lock, rebuilt from the extracted members --- */
function makeGraph() {
	const g = { lockCounter: 0, calcTreeCalls: 0 };
	g.calcTree = function () { g.calcTreeCalls++; };
	g.lockRecal = new Function('"use strict"; return function(' + lockRecal.args + ') ' + lockRecal.body)().bind(g);
	g.unlockRecal = new Function('"use strict"; return function(' + unlockRecal.args + ') ' + unlockRecal.body)().bind(g);
	g.isLockRecal = new Function('"use strict"; return function(' + isLockRecal.args + ') ' + isLockRecal.body)().bind(g);
	g.lockRecalExecute = new Function('"use strict"; return function(' + lockRecalExecute.args + ') ' + lockRecalExecute.body)().bind(g);
	return g;
}

/* Sanity: the extracted lock behaves as the file says it does. */
{
	const g = makeGraph();
	assert.strictEqual(g.isLockRecal(), false);
	g.lockRecal();
	assert.strictEqual(g.isLockRecal(), true, 'lockRecal must raise the counter');
	g.unlockRecal();
	assert.strictEqual(g.isLockRecal(), false, 'unlockRecal must lower it');
	assert.strictEqual(g.calcTreeCalls, 1, 'releasing the last lock recalculates');
	g.lockRecal();
	g.unlockRecal(true);
	assert.strictEqual(g.isLockRecal(), false);
	assert.strictEqual(g.calcTreeCalls, 1, 'unlockRecal(true) must not recalculate');
}

/* --- stubs for everything _insertColsBefore touches before the forced throw --- */
const BOOM = new Error('forced failure inside the structure change');
function makeWorksheet(graph) {
	return {
		workbook: { dependencyFormulas: graph, bUndoChanges: false, bRedoChanges: false },
		renameDependencyNodes() { throw BOOM; },
	};
}
const Asc = { Range: function (c1, r1, c2, r2) { Object.assign(this, { c1, r1, c2, r2 }); } };
const AscCommon = {
	History: { Create_NewPoint() {}, LocalChange: false, Add() {} },
	CellBase: function (row, col) { this.row = row; this.col = col; },
};
const gc_nMaxRow0 = 1048575;
const gc_nMaxCol0 = 16383;

const insertCols = new Function(
	'Asc', 'AscCommon', 'gc_nMaxRow0', 'gc_nMaxCol0',
	'"use strict"; return function' + insertColsBefore
)(Asc, AscCommon, gc_nMaxRow0, gc_nMaxCol0);

/* --- the defect --- */
{
	const g = makeGraph();
	const ws = makeWorksheet(g);
	assert.throws(() => insertCols.call(ws, 0, 1), /forced failure/,
		'the stub must make the real body throw');
	assert.strictEqual(g.lockCounter, 0,
		`recalculation is still locked after the failure (lockCounter=${g.lockCounter}); ` +
		'every formula in the workbook would stay blank for the rest of the session');
	assert.strictEqual(g.calcTreeCalls, 0,
		'a failed structure change must not recalculate over a half-updated model');

	/* And the workbook must recalculate again afterwards. */
	g.lockRecal();
	g.unlockRecal();
	assert.strictEqual(g.calcTreeCalls, 1, 'the next edit must recalculate normally');
}

/* --- lockRecalExecute, same defect --- */
{
	const g = makeGraph();
	assert.throws(() => g.lockRecalExecute(() => { throw BOOM; }), /forced failure/);
	assert.strictEqual(g.lockCounter, 0,
		`lockRecalExecute left recalculation locked (lockCounter=${g.lockCounter})`);

	/* The success path is unchanged: it still recalculates once. */
	const h = makeGraph();
	let ran = false;
	h.lockRecalExecute(() => { ran = true; });
	assert.ok(ran, 'the callback must still run');
	assert.strictEqual(h.lockCounter, 0);
	assert.strictEqual(h.calcTreeCalls, 1, 'the success path must still recalculate');
}

console.log('ok - a throw inside a structure change releases the recalculation lock');
