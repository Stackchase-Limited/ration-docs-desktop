/*
 * #2459 follow-up: files already saved with ref="$H$2:$J$6" heal on open.
 *
 * Before b29329506b a table made from the Format-as-table options was saved with
 * absolute markers in <table ref> and <autoFilter ref> (see
 * issue-2459-table-ref-absolute-test.js). That fix stops new damage, but the
 * reader kept the $ flags of files already written that way: Range.clone() and
 * getName() carry them, so every re-save wrote the invalid ref again.
 *
 * This runs the real readers - the c_oSer_TablePart.Ref branch of the binary
 * table reader (cell/model/Serialize.js) and AutoFilter.prototype.setStringRef
 * (cell/model/WorkbookElems.js, also used by the xlsx and JSON readers) - with a
 * range parser that keeps $ flags the way g_oRangeCache does, and checks the
 * ranges they produce are plain.
 *
 * BASELINE=1 reads both files at BASE_REF (parent of the fix) and must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed the fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '8d79c79bb1^';
const read = (rel) => process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, rel), 'utf8');

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

const ser = read('cell/model/Serialize.js');
const at = ser.indexOf('if ( c_oSer_TablePart.Ref == type )');
assert.notStrictEqual(at, -1, 'table Ref reader not found - the extractor needs updating');
const tableRefStmt = ser.slice(at, ser.indexOf('else if', at));
const wbe = read('cell/model/WorkbookElems.js');
const at2 = wbe.indexOf('AutoFilter.prototype.setStringRef = function');
assert.notStrictEqual(at2, -1, 'setStringRef not found - the extractor needs updating');
const setStringRef = matched(wbe, at2);

// A1 range parser that keeps absolute flags, as g_oRangeCache.getAscRange does
function getAscRange(s) {
	const m = /^(\$?)([A-Z]+)(\$?)(\d+):(\$?)([A-Z]+)(\$?)(\d+)$/.exec(s);
	if (!m) return null;
	return { text: s, absolute: !!(m[1] || m[3] || m[5] || m[7]) };
}
const AscCommonExcel = { g_oRangeCache: { getAscRange } };
const AscCommon = { parserHelp: { parse3DRef: () => null } };

let failures = 0;
const check = (ok, what) => { console.log(`  ${ok ? 'ok  ' : 'FAIL'}  ${what}`); if (!ok) failures++; };

// table reader
const oTable = {};
const stream = { GetString2LE: () => '$H$2:$J$6' };
// eslint-disable-next-line no-new-func
new Function('c_oSer_TablePart', 'type', 'oTable', 'AscCommonExcel', 'length', 'stream', tableRefStmt.replace(/this\.stream/g, 'stream') + ';')
	.call(null, { Ref: 0 }, 0, oTable, AscCommonExcel, 0, stream);
check(oTable.Ref && !oTable.Ref.absolute, `<table ref="$H$2:$J$6"> reads as a plain range (got ${oTable.Ref && oTable.Ref.text})`);

// autofilter reader
function AutoFilter() {}
// eslint-disable-next-line no-new-func
new Function('AutoFilter', 'AscCommonExcel', 'AscCommon', setStringRef + ';')(AutoFilter, AscCommonExcel, AscCommon);
const af = new AutoFilter();
af.setStringRef('$H$2:$J$5');
check(af.Ref && !af.Ref.absolute, `<autoFilter ref="$H$2:$J$5"> reads as a plain range (got ${af.Ref && af.Ref.text})`);
af.setStringRef('B3:F6');
check(af.Ref && af.Ref.text === 'B3:F6', 'a plain ref is read unchanged');

if (process.env.BASELINE) console.log(`BASELINE (${BASE_REF}): the $ cases must FAIL`);
console.log(failures ? `FAIL #2459: ${failures} check(s) failed` : 'PASS #2459: table and autofilter refs saved with $ heal on open');
process.exit(failures ? 1 : 0);
