/*
 * #2426 - a FILTER that goes from matching nothing back to matching again fills
 * only its first cell. The spill never comes back.
 *
 * BACK-FILLED. This fix was committed earlier without a test; the audit in
 * UPSTREAM_TRIAGE.md explains why that matters. This is the test it should have
 * had.
 *
 * The spill is rescheduled by addToVolatileArrays, and calcTree only called it
 * when the parsed formula still had both aca and ca set. But _checkDirty - which
 * runs immediately before, on the same cell - is what recalculates the formula,
 * and recalculating a dynamic array that has collapsed to a single cell clears
 * exactly those two flags. So by the time the condition was evaluated the
 * evidence it needed was gone, and the cell that had just started matching again
 * was never scheduled to re-expand.
 *
 * The fix samples the flags into bWasCollapsedDynamicArray *before* _checkDirty
 * and accepts either the before or the after state.
 *
 * This extracts the real block out of Workbook.js by anchoring on the
 * _checkDirty() call, which is present in both versions, so BASELINE=1 exercises
 * the real old code rather than failing to find something.
 *
 *   node issue-2426-dynamic-array-respill-test.js      -> passes
 *   BASELINE=1 node issue-2426-...-test.js             -> fails, at ede98d9619^
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'cell/model/Workbook.js';
/* A back-filled test cannot use HEAD as its baseline: HEAD already contains the fix,
 * so the test would pass both ways and prove nothing. It ran green against HEAD on the
 * first try here, which is exactly the trap. The baseline is the commit before the fix
 * landed - ede98d9619 "fix(dynamic arrays): reschedule the spill when a FILTER starts
 * matching again". Override with BASE_REF if you are testing somewhere else. */
const BASE_REF = process.env.BASE_REF || 'ede98d9619^';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

/* The one _checkDirty() that is followed by an addToVolatileArrays guard. */
let at = -1;
for (let i = source.indexOf('oCell._checkDirty();'); i !== -1;
     i = source.indexOf('oCell._checkDirty();', i + 1)) {
	if (source.slice(i, i + 700).includes('addToVolatileArrays')) { at = i; break; }
}
assert.notStrictEqual(at, -1, 'the _checkDirty/addToVolatileArrays block was not found');

/* The fix samples the flags into a const just above; HEAD has no such line. Take it
 * in when it is there, so the patched block is extracted whole. A plain backward
 * line-scan will not do it: the declaration spans four lines and its continuations
 * do not look like declarations. */
let start = at;
const sampleAt = source.lastIndexOf('const oFormulaBefore', at);
if (sampleAt !== -1 && at - sampleAt < 600) {
	start = source.lastIndexOf('\n', sampleAt) + 1;
}

/* Extend past the closing brace of the if that follows. */
const ifAt = source.indexOf('if (', at);
let depth = 0, end = -1;
for (let i = source.indexOf('{', ifAt); i < source.length; i++) {
	if (source[i] === '{') depth++;
	else if (source[i] === '}' && --depth === 0) { end = i + 1; break; }
}
const block = source.slice(start, end);
assert.ok(block.includes('addToVolatileArrays'), 'extracted the wrong block');

/* --- stubs --- */
function makeCell(opts) {
	const parsed = {
		aca: opts.acaBefore, ca: opts.caBefore,
		getDynamicRef: () => opts.isDynamic,
		getArrayFormulaRef: () => false,
	};
	return {
		formulaParsed: parsed,
		/* Recalculating a collapsed dynamic array clears the very flags the old
		 * condition was about to look at. That is the whole defect. */
		_checkDirty() { parsed.aca = opts.acaAfter; parsed.ca = opts.caAfter; },
	};
}

function run(opts) {
	const scheduled = [];
	const t = { addToVolatileArrays: (f) => scheduled.push(f) };
	const oCell = makeCell(opts);
	const AscCommonExcel = { bIsSupportDynamicArrays: true };
	new Function('oCell', 't', 'AscCommonExcel', '"use strict";' + block)(oCell, t, AscCommonExcel);
	return scheduled.length;
}

/* --- the defect: it was a spilled dynamic array, recalculation collapsed the flags --- */
assert.strictEqual(
	run({ isDynamic: true, acaBefore: true, caBefore: true, acaAfter: false, caAfter: false }), 1,
	'a dynamic array whose flags are cleared by _checkDirty must still be rescheduled - ' +
	'otherwise a FILTER that starts matching again fills only its first cell (#2426)');

/* --- still scheduled when the flags survive --- */
assert.strictEqual(
	run({ isDynamic: true, acaBefore: true, caBefore: true, acaAfter: true, caAfter: true }), 1,
	'the ordinary case must keep working');

/* --- and when only the after-state has them --- */
assert.strictEqual(
	run({ isDynamic: true, acaBefore: false, caBefore: false, acaAfter: true, caAfter: true }), 1,
	'a formula that becomes a spilled array must be scheduled');

/* --- never scheduled when it is not a dynamic array at all --- */
assert.strictEqual(
	run({ isDynamic: false, acaBefore: true, caBefore: true, acaAfter: true, caAfter: true }), 0,
	'a plain formula must not be put on the volatile list');

/* --- nor when it was never spilled and still is not --- */
assert.strictEqual(
	run({ isDynamic: true, acaBefore: false, caBefore: false, acaAfter: false, caAfter: false }), 0,
	'a dynamic array that is not spilling must not be scheduled');

console.log('ok - a collapsed dynamic array is still rescheduled after recalculation');
