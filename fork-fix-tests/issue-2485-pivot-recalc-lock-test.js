/*
 * Found while triaging #2485 (GETPIVOTDATA not recalculated after a pivot refresh;
 * the reported case did not reproduce - see UPSTREAM_TRIAGE.md).
 *
 * The three pivot-change paths in cell/api.js - asc_refreshAllPivots,
 * _changePivotWithLockExt and _changePivotAndConnectedByPivotCacheWithLock - take
 * the recalculation lock (dependencyFormulas.lockRecal) and a history transaction
 * around the pivot change, and release both only on the normal path. A throw in
 * the change (a pivot refresh over odd source data, say) left lockCounter > 0:
 * calcTree() returns early while it is held, so every formula in the workbook
 * stopped recalculating for the rest of the session, silently - the #2443
 * failure mode, there fixed in lockRecalExecute and the row/column paths.
 *
 * This extracts the three real functions and the real lockRecal/unlockRecal
 * (cell/model/Workbook.js), runs each with a pivot change that throws, and checks
 * the exception still reaches the caller with the lock released and the
 * transaction closed; and that the normal path still recalculates once.
 *
 * BASELINE=1 reads cell/api.js at BASE_REF (parent of the fix) and must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed the fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'd2d908d3b7^';
const read = (rel, git) => git
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
const api = read('cell/api.js', !!process.env.BASELINE);
const wb = read('cell/model/Workbook.js', false);

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function grab(text, sig) {
	const at = text.indexOf(sig);
	if (at === -1) throw new Error('not found - the extractor needs updating: ' + sig);
	return matched(text, at);
}

const lockSrc = grab(wb, 'lockRecal: function()') + ',\n' + grab(wb, 'unlockRecal: function(notCalc, callback)');
const names = ['asc_refreshAllPivots', '_changePivotWithLockExt', '_changePivotAndConnectedByPivotCacheWithLock'];
const protoSrc = names.map(n => grab(api, `spreadsheet_api.prototype.${n} = function`) + ';').join('\n');

const c_oAscError = { ID: { No: 0, PivotOverlap: 1 }, Level: { NoCritical: 0 } };
function make() {
	const History = { depth: 0, Create_NewPoint() {}, StartTransaction() { this.depth++; }, EndTransaction() { this.depth--; } };
	const dep = eval('({ lockCounter: 0, calcs: 0, calcTree(cb) { this.calcs++; cb && cb(); },\n' + lockSrc + '})');
	function spreadsheet_api() {}
	// eslint-disable-next-line no-new-func
	new Function('spreadsheet_api', 'History', 'c_oAscError', protoSrc)(spreadsheet_api, History, c_oAscError);
	const pivot = { checkRefresh: () => 0, Get_Id: () => 'p1', refresh() {}, getPivotTablesConnectedByPivotCache() { return [pivot]; } };
	const t = new spreadsheet_api();
	Object.assign(t, {
		wbModel: { dependencyFormulas: dep, forEach(f) { f({ pivotTables: [pivot] }); }, getPivotTableById: () => pivot },
		collaborativeEditing: { getGlobalLock: () => false }, canEdit: () => true,
		sendEvent() {}, _isLockedPivot: (p, cb) => cb(true), _isLockedPivotAndConnectedByPivotCache: (p, cb) => cb(true),
		_changePivotEndCheckError: () => true, updateWorksheetByPivotTable() {},
		throwIt: true,
		_changePivot(p, conf, fit, onAction) { if (this.throwIt) throw new Error('boom'); onAction && onAction({}, p); return { error: 0, warning: 0 }; },
	});
	return { t, dep, History, pivot };
}
const calls = {
	asc_refreshAllPivots: (t) => t.asc_refreshAllPivots(),
	_changePivotWithLockExt: (t, p) => t._changePivotWithLockExt(p, false, false, function () {}),
	_changePivotAndConnectedByPivotCacheWithLock: (t, p) => t._changePivotAndConnectedByPivotCacheWithLock(p, false,
		function () { return t._changePivot(p); }, function () {}, false),
};

let failures = 0;
const check = (ok, what) => { console.log(`  ${ok ? 'ok  ' : 'FAIL'}  ${what}`); if (!ok) failures++; };
for (const n of names) {
	console.log(n);
	let m = make(), threw = false;
	try { calls[n](m.t, m.pivot); } catch (e) { threw = e.message === 'boom'; }
	check(threw, 'a throw in the pivot change still reaches the caller');
	check(m.dep.lockCounter === 0, `recalculation lock released after the throw (lockCounter=${m.dep.lockCounter})`);
	check(m.History.depth === 0, `history transaction closed after the throw (depth=${m.History.depth})`);
	m = make(); m.t.throwIt = false;
	calls[n](m.t, m.pivot);
	check(m.dep.lockCounter === 0 && m.dep.calcs === 1 && m.History.depth === 0, 'normal path: lock released, recalculated once, transaction closed');
}
if (process.env.BASELINE) console.log(`BASELINE (${BASE_REF}): the throw cases must FAIL`);
console.log(failures ? `FAIL #2485: ${failures} check(s) failed` : 'PASS #2485: pivot changes release the recalculation lock when they throw');
process.exit(failures ? 1 : 0);
