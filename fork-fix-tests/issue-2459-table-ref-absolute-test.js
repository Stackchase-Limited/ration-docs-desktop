/*
 * #2459 (found while working on it) - Format as table through the dialog saved
 * the table as <table ref="$H$2:$J$6"> with <autoFilter ref="$H$2:$J$5">. A
 * table/autofilter ref with $ markers is not a cell-range ST_Ref, and Excel
 * repairs the file on open. Without the options object the same table saved as
 * ref="H2:J6".
 *
 * Cause: asc_getAddFormatTableOptions() returns its range as an absolute name
 * (AutoFilters.getAddFormatTableOptions -> addRange.getAbsName(), "$H$2:$J$5").
 * The real UI hands that options object straight to asc_addAutoFilter (web-apps
 * Toolbar.js _setTableFormat with TableOptionsDialog.getSettings().range), and
 * so does pivot "show details". AutoFilters._getFilterInfoByAddTableProps
 * (cell/model/autofilters.js) parsed it with g_oRangeCache.getAscRange and
 * clone()d it; Range.prototype.clone (cell/utils/utils.js) copies refType1 and
 * refType2, so the table Ref kept the absolute flags and BinaryTableWriter's
 * Ref.getName() wrote them into the file (also through the history record that
 * x2t replays for the desktop save, since redo re-runs the same function).
 *
 * This extracts by brace matching the real _getFilterInfoByAddTableProps and
 * the real Range constructor / clone / getName / _getName / getType / setAbs /
 * isAbsCol / isAbsRow / isOneCell / referenceType, and checks that the
 * filterRange it returns for options with range "$H$2:$J$5" names itself
 * "H2:J5" (and "H2:J6" when a header row is added).
 * Stubbed: g_oRangeCache.getAscRange is a tiny A1 parser that sets the $ flags
 * with the real setAbs, as the real cache does (checked in a headless editor:
 * the table Ref came out as "$H$2:$J$6"); the worksheet has no merges and no
 * other tables.
 * NOT claimed here: the full editor + x2t save flow (verified separately in a
 * headless editor with the real desktop save, see the commit message).
 *
 * RD_REPO overrides the sdkjs checkout; BASELINE=1 reads the sources from
 * BASE_REF and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the fix commit (re-pinned by the integrator after
// cherry-picking). Never HEAD: once the fix lands HEAD carries it.
const BASE_REF = process.env.BASE_REF || 'd7a83a802a^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

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
/* `marker` ends with "function"; returns "(args) { body }" */
function fn(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return matched(text, at + marker.length);
}

const utils = read('cell/utils/utils.js');
const autofilters = read('cell/model/autofilters.js');

/* --- the real Asc.Range --- */
const referenceTypeSrc = matched(utils, utils.indexOf('var referenceType = ') + 'var referenceType = '.length);
const ctorSrc = fn(utils, 'function Range');
const methods = ['clone', 'getName', '_getName', 'getType', 'setAbs', 'isAbsCol', 'isAbsRow', 'isOneCell'];
const AscCommonExcel = { g_R1C1Mode: false, g_ActiveCell: { c1: 0, r1: 0 } };
const c_oAscSelectionType = { RangeCells: 1, RangeCol: 2, RangeRow: 3, RangeMax: 4 };
const g_oCellAddressUtils = {
	colnumToColstr(n) { let s = ''; for (; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; },
};
const Range = new Function('AscCommonExcel', 'c_oAscSelectionType', 'g_oCellAddressUtils', 'gc_nMaxCol0', 'gc_nMaxRow0',
	'"use strict"; var referenceType = ' + referenceTypeSrc + '; function Range' + ctorSrc + '\n' +
	methods.map(m => 'Range.prototype.' + m + ' = function' + fn(utils, 'Range.prototype.' + m + ' = function') + ';').join('\n') +
	'\nreturn Range;')(AscCommonExcel, c_oAscSelectionType, g_oCellAddressUtils, 16383, 1048575);
const Asc = { Range };

/* g_oRangeCache.getAscRange stub: "$H$2:$J$5" -> Range with the $ flags set by the real setAbs */
const colNum = s => [...s].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0) - 1;
AscCommonExcel.g_oRangeCache = {
	getAscRange(s) {
		const m = /^(\$?)([A-Z]+)(\$?)(\d+):(\$?)([A-Z]+)(\$?)(\d+)$/.exec(s);
		const r = new Range(colNum(m[2]), +m[4] - 1, colNum(m[6]), +m[8] - 1);
		r.setAbs(!!m[3], !!m[1], !!m[7], !!m[5]);
		return r;
	},
};

/* Sanity: the extracted Range does what the bug needs it to do */
{
	const r = AscCommonExcel.g_oRangeCache.getAscRange('$H$2:$J$5');
	assert.strictEqual(r.getName(), '$H$2:$J$5', 'the stub cache must hand out an absolute range');
	assert.strictEqual(r.clone().getName(), '$H$2:$J$5', 'clone keeps the $ flags (this is the trap)');
	assert.strictEqual(new Range(7, 1, 9, 4).getName(), 'H2:J5');
}

/* --- the real _getFilterInfoByAddTableProps --- */
const infoSrc = fn(autofilters, '_getFilterInfoByAddTableProps: function ');
assert.ok(infoSrc.includes('asc_getRange()'), 'extracted the wrong _getFilterInfoByAddTableProps');
const getFilterInfo = new Function('Asc', 'AscCommonExcel', '"use strict"; return function' + infoSrc)(Asc, AscCommonExcel);

const autoFilters = {
	worksheet: {
		nColsCount: 100, nRowsCount: 100,
		expandRangeByMerged(r) { return r; },
		getMergedByCell() { return null; },
	},
	_isTablePartsContainsRange() { return null; },
	expandRange() { throw new Error('options give a range: must not expand'); },
};
const options = (range, isTitle) => ({ asc_getRange: () => range, asc_getIsTitle: () => isTitle });

/* --- the defect --- */
for (const [isTitle, want] of [[true, 'H2:J5'], [false, 'H2:J6']]) {
	const info = getFilterInfo.call(autoFilters, new Range(0, 0, 0, 0), options('$H$2:$J$5', isTitle), true);
	assert.strictEqual(info.filterRange.getName(), want,
		`table Ref from the Format-as-table options must be a plain range (got "${info.filterRange.getName()}", ` +
		`saved as <table ref="${info.filterRange.getName()}">)`);
	assert.strictEqual(info.rangeWithoutDiff.getName(), 'H2:J5', 'the history copy of the range must be plain too');
	assert.strictEqual(info.addNameColumn, !isTitle);
}

/* The same function without options (selection) keeps working */
{
	const info = getFilterInfo.call(autoFilters, new Range(7, 1, 9, 4), true, true);
	assert.strictEqual(info.filterRange.getName(), 'H2:J5');
}

/* A relative name in the options is unchanged */
{
	const info = getFilterInfo.call(autoFilters, new Range(0, 0, 0, 0), options('B3:F7', true), true);
	assert.strictEqual(info.filterRange.getName(), 'B3:F7');
}

console.log('ok - a table made from Format-as-table options gets a plain (non-$) Ref');
