/*
 * DesktopEditors #1364 - "(spreadsheet) copy/paste single cell does not work correctly".
 *
 * What the reporter did (from the issue and the Book2.xlsx follow-up):
 *   1. copy some text from another application,
 *   2. select ONE cell (D4) that holds a formula whose result is the empty
 *      string - it looks empty but is filled yellow,
 *   3. Ctrl+C - the marching-ants border appears,
 *   4. move to E4, Ctrl+V,
 *   5. the text from step 1 comes back, not the formula and not the fill.
 * Selecting two or more cells, they say, works. Upstream reproduced it with
 * that file and filed it internally as 64168; it is still open.
 *
 * So the reading taken here: the failing case is not "one cell" as such, it is
 * "one cell whose DISPLAYED text is empty". That is the only selection shape a
 * sheet copy can produce whose plain-text flavour is the empty string, and it
 * is why an ordinary single cell (which the first upstream triage tried)
 * copies fine while the yellow formula cells do not.
 *
 * This file is a DEMONSTRATION OF AN UNFIXED DEFECT, not a regression test for
 * a landed fix: section 2 fails against the tree as it stands. The one-line
 * change that would make it pass lives in common/clipboard_base.js, which this
 * work was told to leave alone (a fix for #676 has just landed there).
 *
 * What it shows, by running the shipped functions rather than a re-typing of
 * them:
 *
 *  1. cell/model/clipboard.js, CopyProcessorExcel._getTextFromSheet, emits the
 *     separators BETWEEN cells only:
 *
 *         for (var row = bbox.r1; row <= maxRow; ++row) {
 *             if (row !== bbox.r1) { ... addByStr('\r\n') ... }
 *             for (var col = bbox.c1; col <= maxCol; ++col) {
 *                 if (col !== bbox.c1) { ... addByStr('\t') ... }
 *
 *     so any selection of two or more cells is guaranteed a non-empty string
 *     ("\t", "\r\n", ...) even when every cell in it is blank, while a 1x1
 *     selection of a cell that renders empty yields exactly "".
 *
 *  2. common/clipboard_base.js:1246, CClipboardBase.Copy_New - the path the
 *     desktop build takes (engine >= 109, navigator.clipboard present) - then
 *     tests that payload for TRUTHINESS, not for presence:
 *
 *         if (copy_data.data[c_oAscClipboardDataFormat.Text]) {
 *             clipboardData["text/plain"] = new Blob([...], {type: "text/plain"});
 *         }
 *
 *     "" is falsy, so the ClipboardItem is built with no text/plain member at
 *     all. navigator.clipboard.write() replaces the system clipboard with that
 *     item, so after copying such a cell the clipboard carries no plain-text
 *     flavour: every consumer that speaks only text/plain gets nothing from
 *     the copy. Copying any larger selection always carries one.
 *
 * Honest limit of this evidence: text/html and (on this path) image/png ARE
 * still written, and the in-editor paste handler prefers text/html, so this
 * alone does not explain the reporter's in-app paste returning the previous
 * clipboard's text - that needs the clipboard write to be skipped outright,
 * and no such path was found for a 1x1 sheet copy. See the report.
 *
 *   node fork-fix-tests/issue-1364-single-cell-copy-test.js
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL_CB = 'cell/model/clipboard.js';
const REL_BASE = 'common/clipboard_base.js';
const REL_WCP = 'common/wordcopypaste.js';
/* pinned, never HEAD: the tree this was investigated against */
const BASE_REF = process.env.BASE_REF || 'd32100e8a1fe760520a2b43fc46412ab9c7f41f2';

function readGit(rel) {
	return execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 });
}
function readWorking(rel) {
	return fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* ---------------- verbatim extraction by brace matching ---------------- */
function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function grabFn(source, rel, assign) {
	const at = source.indexOf(assign);
	assert.notStrictEqual(at, -1, 'not found in ' + rel + ': ' + assign);
	/* everything after the "function" keyword: "(args) { ... }" */
	return matched(source, at + assign.length);
}
function grabDecl(source, rel, head) {
	const at = source.indexOf(head);
	assert.notStrictEqual(at, -1, 'not found in ' + rel + ': ' + head);
	return matched(source, at);
}

function extract(read) {
	const srcCb = read(REL_CB);
	const srcBase = read(REL_BASE);
	const srcWcp = read(REL_WCP);

	const f = {
		getHtml:                    grabFn(srcCb, REL_CB, 'getHtml: function'),
		getText:                    grabFn(srcCb, REL_CB, 'getText: function'),
		canCopy:                    grabFn(srcCb, REL_CB, 'canCopy: function'),
		_generateHtml:              grabFn(srcCb, REL_CB, '_generateHtml: function'),
		_generateHtmlDocStr:        grabFn(srcCb, REL_CB, '_generateHtmlDocStr: function'),
		_getRangeMaxRowCol:         grabFn(srcCb, REL_CB, '_getRangeMaxRowCol: function'),
		_getSelectedDrawingIndex:   grabFn(srcCb, REL_CB, '_getSelectedDrawingIndex: function'),
		_makeNodesFromCellValueStr: grabFn(srcCb, REL_CB, '_makeNodesFromCellValueStr: function'),
		_getTextFromSheet:          grabFn(srcCb, REL_CB, '_getTextFromSheet: function'),
		checkCopyToClipboard:       grabFn(srcCb, REL_CB, 'Clipboard.prototype.checkCopyToClipboard = function'),
		drawSelectedArea:           grabFn(srcCb, REL_CB, 'Clipboard.prototype.drawSelectedArea = function'),
		Copy_New:                   grabFn(srcBase, REL_BASE, '\n\t\tCopy_New : function'),
		pushData:                   grabFn(srcBase, REL_BASE, 'pushData : function'),
		lastCopyPush:               grabFn(srcBase, REL_BASE, 'lastCopyPush : function'),
		correctString:              grabDecl(srcWcp, REL_WCP, 'function CopyPasteCorrectString(str)')
	};

	/* guard against extracting the wrong thing */
	assert.ok(f.checkCopyToClipboard.indexOf('this.copyProcessor.getText(activeRange, ws)') !== -1,
		'extracted the wrong checkCopyToClipboard');
	assert.ok(f._getTextFromSheet.indexOf('getValueWithFormat()') !== -1,
		'extracted the wrong _getTextFromSheet');
	assert.ok(f._getTextFromSheet.indexOf("addByStr('\\t')") !== -1,
		'extracted the wrong _getTextFromSheet (no column separator)');
	assert.ok(f.Copy_New.indexOf('new ClipboardItem(clipboardData)') !== -1,
		'extracted the wrong Copy_New');
	assert.ok(f.Copy_New.indexOf('navigator.clipboard.write') !== -1,
		'extracted the wrong Copy_New');
	assert.ok(f._generateHtmlDocStr.indexOf('<table cellpadding=') !== -1,
		'extracted the wrong _generateHtmlDocStr');
	return f;
}

/* ---------------- stubs: the product's own constants and shapes ---------------- */
/* common/clipboard_base.js:56 */
const c_oAscClipboardDataFormat = { Text: 1, Html: 2, Internal: 4, HtmlElement: 8, Rtf: 16, Image: 32 };
/* cell/apiDefines.js */
const c_oAscSelectionType = { RangeCells: 1, RangeCol: 2, RangeRow: 3, RangeMax: 4 };
const c_oAscBorderStyles = { None: 0, Thin: 1 };
const gc_nMaxRow0 = 1048576 - 1, gc_nMaxCol0 = 16384 - 1;

function number2color(n) { return '#' + ('000000' + n.toString(16)).slice(-6); }

function Range(c1, r1, c2, r2) { this.c1 = c1; this.r1 = r1; this.c2 = c2; this.r2 = r2; }
/* the real Range.getType from cell/utils/utils.js:1027, transcribed only because
 * it is selection bookkeeping, not code under test */
Range.prototype.getType = function () {
	const bRow = 0 === this.c1 && gc_nMaxCol0 === this.c2;
	const bCol = 0 === this.r1 && gc_nMaxRow0 === this.r2;
	if (bCol && bRow) return c_oAscSelectionType.RangeMax;
	if (bCol) return c_oAscSelectionType.RangeCol;
	if (bRow) return c_oAscSelectionType.RangeRow;
	return c_oAscSelectionType.RangeCells;
};
Range.prototype.clone = function () { return new Range(this.c1, this.r1, this.c2, this.r2); };

const Asc = {
	Range: function (c1, r1, c2, r2) { return new Range(c1, r1, c2, r2); },
	c_oAscVAlign: { Bottom: 0, Center: 1, Dist: 2, Just: 3, Top: 4 },
	c_oAscSelectionType: c_oAscSelectionType,
	c_oAscError: { ID: { CopyMultiselectAreaError: 1 }, Level: { NoCritical: 1 } },
	EUnderline: { underlineNone: 0 },
	editor: null
};
Asc.Range.prototype = Range.prototype;

const defaultFormat = {
	getSkip: () => false, getName: () => 'Calibri', getSize: () => 11,
	getColor: () => null, getVerticalAlign: () => 0, getBold: () => false,
	getItalic: () => false, getUnderline: () => 0, getStrikeout: () => false
};
function fragment(text) { return { format: defaultFormat, getFragmentText: () => text }; }

/* a sheet is a sparse map "row,col" -> {value, type, fill} */
function makeModel(cells) {
	return {
		bExcludeHiddenRows: false,
		Drawings: [],
		workbook: { getDefaultFont: () => 'Calibri', getDefaultSize: () => 11, checkProtectedValue: false },
		getRowHidden: () => false,
		getRowHeight: () => 14.25,
		excludeHiddenRows: function () {}, ignoreWriteFormulas: function () {},
		autoFilters: { bIsExcludeHiddenRows: () => false },
		selectionRange: null,
		getCell3: function (r, c) { return this.getRange3(r, c, r, c); },
		getRange3: function (r1, c1, r2, c2) {
			const cell = cells[r1 + ',' + c1] || null;
			const bbox = new Range(c1, r1, c2, r2);
			return {
				bbox: bbox,
				getBBox0: () => bbox,
				hasMerged: () => null,
				/* Workbook.js:17408 - a formula whose result is a string stores
				 * CellValueType.String, so an "empty looking" formula cell has a type */
				getType: () => (cell ? cell.type : null),
				getValueWithFormat: () => (cell ? cell.value : ''),
				getValue2: () => (cell ? [fragment(cell.value)] : []),
				getAlign: () => ({ getWrap: () => false, getAlignHorizontal: () => null, getAlignVertical: () => null }),
				getBorderFull: () => ({ l: null, r: null, t: null, b: null }),
				getFillColor: () => (cell && cell.fill != null ? { getRgb: () => cell.fill } : null),
				getEffectiveHyperlink: () => null
			};
		}
	};
}

function makeWorksheetView(cells, range) {
	const model = makeModel(cells);
	model.selectionRange = {
		ranges: [range],
		activeCell: { clone: () => ({ row: range.r1, col: range.c1 }) },
		getLast: () => range,
		clone: function () { return this; }
	};
	const wbView = {
		getCellEditMode: () => false,
		cellEditor: { copySelection: () => null },
		handlers: { trigger: () => {} },
		model: { checkProtectedValue: false },
		/* a real canvas is out of scope; the image flavour is not what is under test */
		printForCopyPaste: () => ({ canvas: { toDataURL: () => 'data:image/png;base64,' + Buffer.from('PNG').toString('base64') } })
	};
	Asc.editor = { wb: wbView };
	return {
		model: model,
		workbook: wbView,
		handlers: { trigger: () => {} },
		objectRender: {
			controller: { getTargetDocContent: () => null, getSelectionImage: () => null },
			getSelectedGraphicObjects: () => [],
			selectedGraphicObjectsExists: () => false
		},
		getSelectedRange: () => model.getRange3(range.r1, range.c1, range.r2, range.c2),
		getColumnWidth: () => 48,
		_getRowTop: (r) => r * 20,
		_getColLeft: (c) => c * 64,
		_getRowHeight: () => 20,
		setCutRange: function (v) { this.__cutRange = v; },
		isNeedSelectionCut: () => false,
		isMultiSelect: () => false
	};
}

/* the spec-accurate ClipboardItem: "If items is empty, then throw a TypeError" */
function SpecClipboardItem(items) {
	const keys = Object.keys(items);
	if (keys.length === 0) throw new TypeError('Empty dictionary argument');
	this.types = keys;
	this.items = items;
}

function build(fns) {
	const body = `
'use strict';
var navigator = ENV.navigator;
var ClipboardItem = ENV.ClipboardItem;
var atob = ENV.atob;
var doc = null;
var copyPasteUseBinary = true;
var c_MaxStringLength = 536870888;
var History = { TurnOff: function(){}, TurnOn: function(){} };
var AscFormat = { ExecuteNoHistory: function(f, ctx, args){ return f.apply(ctx, args); } };

${fns.correctString}

function CopyProcessorExcel(){}
CopyProcessorExcel.prototype = {
	constructor: CopyProcessorExcel,
	getHtml: function ${fns.getHtml},
	getText: function ${fns.getText},
	canCopy: function ${fns.canCopy},
	_generateHtml: function ${fns._generateHtml},
	_generateHtmlDocStr: function ${fns._generateHtmlDocStr},
	_getRangeMaxRowCol: function ${fns._getRangeMaxRowCol},
	_getSelectedDrawingIndex: function ${fns._getSelectedDrawingIndex},
	_makeNodesFromCellValueStr: function ${fns._makeNodesFromCellValueStr},
	_getTextFromSheet: function ${fns._getTextFromSheet},
	/* the binary writer needs the whole workbook serialiser; stubbed, and it is
	   not where the 1x1/range asymmetry lives */
	getBinaryForCopy: function(){ return "xslData;STUBBEDBINARY"; },
	_getTextFromShape: function(){ return null; }
};

function Clipboard(){ this.copyProcessor = new CopyProcessorExcel(); }
Clipboard.prototype.checkCopyToClipboard = function ${fns.checkCopyToClipboard};
Clipboard.prototype.drawSelectedArea = function ${fns.drawSelectedArea};

function CClipboardBase(){ this.ClosureParams = {}; this.LastCopyBinary = null; this.bCut = false; this.Api = null; }
CClipboardBase.prototype.Copy_New = function ${fns.Copy_New};
CClipboardBase.prototype.pushData = function ${fns.pushData};
CClipboardBase.prototype.lastCopyPush = function ${fns.lastCopyPush};
CClipboardBase.prototype.isCopyOutEnabled = function(){ return true; };
CClipboardBase.prototype.isCopyEnabled = function(){ return true; };
CClipboardBase.prototype.SendCopyEvent = function(){};
CClipboardBase.prototype.SendCopyDisabledEvent = function(){};
CClipboardBase.prototype._isUseMobileNewCopy = function(){ return false; };

return { Clipboard: Clipboard, CClipboardBase: CClipboardBase };
`;

	const writes = [];
	const AscCommon = {
		c_oAscClipboardDataFormat: c_oAscClipboardDataFormat,
		gc_nMaxCol: gc_nMaxCol0 + 1, gc_nMaxRow: gc_nMaxRow0 + 1,
		align_Left: 1, align_Right: 2, align_Center: 3, align_Justify: 4,
		vertalign_SubScript: 1, vertalign_SuperScript: 2,
		AscBrowser: { isIE: false, isSafariMacOs: false },
		g_specialPasteHelper: { SpecialPasteButton_Hide: function () {} },
		g_clipboardBase: { bCut: false }
	};
	const AscCommonExcel = {
		MultiplyRange: function (ranges) { this.getUnionRange = () => ranges[0]; },
		getFragmentsText: () => ''
	};
	const windowStub = { AscCommon: AscCommon, Asc: Asc };
	const ENV = {
		navigator: { clipboard: { write: function (arr) { writes.push(arr); return Promise.resolve(); } } },
		ClipboardItem: SpecClipboardItem,
		atob: (s) => Buffer.from(s, 'base64').toString('binary')
	};
	const api = new Function('window', 'AscCommon', 'AscCommonExcel', 'Asc',
		'c_oAscClipboardDataFormat', 'c_oAscBorderStyles', 'number2color', 'ENV', body)
		(windowStub, AscCommon, AscCommonExcel, Asc, c_oAscClipboardDataFormat, c_oAscBorderStyles, number2color, ENV);
	return { api, writes };
}

/* ---------------- the two revisions under test ---------------- */
// This test compares both revisions side by side in one process, so it proves its
// own toothiness structurally: section 0 asserts the baseline really does drop
// text/plain, and section 2 asserts the working tree does not. Revert the fix and
// both fail.
//
// BASELINE=1 is honoured anyway, because every other test in fork-fix-tests/ uses
// that convention and a reader will try it. It points "WORKING" at the baseline
// too, so the run must FAIL - if it passes, the baseline already contains the fix
// and BASE_REF is wrong.
const BASELINE = !!process.env.BASELINE;
const WORKING = build(extract(BASELINE ? readGit : readWorking));
const BASE = build(extract(readGit));

/* ---------------- operations ---------------- */
function copyToClipboardFlavours(built, cells, range) {
	const ws = makeWorksheetView(cells, range);
	const clip = new built.api.Clipboard();
	const cb = new built.api.CClipboardBase();
	cb.Api = {
		asc_IsFocus: () => true,
		asc_CheckCopy: (data, formats) => clip.checkCopyToClipboard(ws, data, formats),
		asc_SelectionCut: () => {},
		broadcastChannel: null,
		getEditorId: () => 1
	};
	built.writes.length = 0;
	const ret = cb.Copy_New(false, false);
	const item = built.writes[0] && built.writes[0][0];
	return { ret: ret, flavours: item ? item.types : null, marchingAnts: !!ws.__cutRange };
}

function sheetText(built, cells, range) {
	const ws = makeWorksheetView(cells, range);
	const clip = new built.api.Clipboard();
	const pushed = {};
	clip.checkCopyToClipboard(ws, { pushData: (f, d) => { pushed[f] = d; } },
		c_oAscClipboardDataFormat.Text | c_oAscClipboardDataFormat.Html | c_oAscClipboardDataFormat.Internal);
	return pushed;
}

/* D4 holds =IF(...,"",...) -> CellValueType.String with an empty string, fill yellow */
const EMPTY_FORMULA = { '3,3': { value: '', type: 1, fill: 0xFFFF00 },
                        '3,4': { value: '', type: 1, fill: 0xFFFF00 },
                        '4,3': { value: '', type: 1, fill: 0xFFFF00 } };
const WITH_TEXT     = { '3,3': { value: 'hello', type: 1, fill: 0xFFFF00 } };
const ONE_CELL   = new Range(3, 3, 3, 3);
const TWO_COLS   = new Range(3, 3, 4, 3);
const TWO_ROWS   = new Range(3, 3, 3, 4);

let failures = 0;
function check(name, fn) {
	try { fn(); console.log('  ok   ' + name); }
	catch (e) { failures++; console.log('  FAIL ' + name + '\n         ' + e.message); }
}

console.log('\n0. harness: the working tree differs from the pinned baseline ' + BASE_REF.slice(0, 10) + ' only where it should');
check('the fix changes the 1x1 empty-cell case and nothing about it is accidental', () => {
	// This started life as "nothing was changed", from the investigation pass that
	// deliberately edited no source. Now that the fix is in, the assertion is the
	// other way round: the baseline must drop text/plain and the working tree must
	// keep it. If these ever agree again, the fix has been reverted.
	const a = copyToClipboardFlavours(WORKING, EMPTY_FORMULA, ONE_CELL).flavours || [];
	const b = copyToClipboardFlavours(BASE, EMPTY_FORMULA, ONE_CELL).flavours || [];
	assert.ok(a.indexOf('text/plain') !== -1, 'working tree lost text/plain: ' + JSON.stringify(a));
	assert.ok(b.indexOf('text/plain') === -1, 'baseline already had text/plain - is BASE_REF wrong? ' + JSON.stringify(b));
});

console.log('\n1. _getTextFromSheet: only a 1x1 selection can produce an empty plain-text payload');
check('1x1, cell renders empty  -> ""', () => {
	assert.strictEqual(sheetText(WORKING, EMPTY_FORMULA, ONE_CELL)[c_oAscClipboardDataFormat.Text], '');
});
check('1x1, cell has text       -> "hello"', () => {
	assert.strictEqual(sheetText(WORKING, WITH_TEXT, ONE_CELL)[c_oAscClipboardDataFormat.Text], 'hello');
});
check('1x2, both render empty   -> "\\t"  (separator saves it)', () => {
	assert.strictEqual(sheetText(WORKING, EMPTY_FORMULA, TWO_COLS)[c_oAscClipboardDataFormat.Text], '\t');
});
check('2x1, both render empty   -> "\\r\\n" (separator saves it)', () => {
	assert.strictEqual(sheetText(WORKING, EMPTY_FORMULA, TWO_ROWS)[c_oAscClipboardDataFormat.Text], '\r\n');
});
check('the html flavour is produced for the 1x1 case regardless', () => {
	const html = sheetText(WORKING, EMPTY_FORMULA, ONE_CELL)[c_oAscClipboardDataFormat.Html];
	assert.ok(html && html.indexOf('<table') === 0, 'no table: ' + JSON.stringify(html));
	assert.ok(html.indexOf('xslData;') !== -1, 'the internal binary is not carried on the table class');
});

console.log('\n2. Copy_New: what actually reaches the system clipboard  (THIS IS THE DEFECT)');
check('copying a range puts text/plain on the clipboard', () => {
	const r = copyToClipboardFlavours(WORKING, EMPTY_FORMULA, TWO_COLS);
	assert.ok(r.flavours, 'nothing was written to the clipboard');
	assert.ok(r.flavours.indexOf('text/plain') !== -1,
		'no text/plain among ' + JSON.stringify(r.flavours));
});
check('copying one cell with text puts text/plain on the clipboard', () => {
	const r = copyToClipboardFlavours(WORKING, WITH_TEXT, ONE_CELL);
	assert.ok(r.flavours.indexOf('text/plain') !== -1,
		'no text/plain among ' + JSON.stringify(r.flavours));
});
check('copying ONE cell that renders empty must still put text/plain on the clipboard', () => {
	const r = copyToClipboardFlavours(WORKING, EMPTY_FORMULA, ONE_CELL);
	assert.ok(r.flavours.indexOf('text/plain') !== -1,
		'clipboard_base.js Copy_New dropped the empty text payload; clipboard carries only '
		+ JSON.stringify(r.flavours));
});

console.log('\n3. what is NOT broken (so the report does not overclaim)');
check('the copy still completes and draws the marching ants', () => {
	const r = copyToClipboardFlavours(WORKING, EMPTY_FORMULA, ONE_CELL);
	assert.strictEqual(r.ret, true, 'Copy_New reported failure');
	assert.strictEqual(r.marchingAnts, true, 'setCutRange was never reached');
});
check('text/html (which carries the internal binary, and which the paste handler prefers) is written', () => {
	const r = copyToClipboardFlavours(WORKING, EMPTY_FORMULA, ONE_CELL);
	assert.ok(r.flavours.indexOf('text/html') !== -1, JSON.stringify(r.flavours));
});
check('ordinary range copy is byte-identical between working tree and baseline', () => {
	// The html flavour is no longer byte-identical for selections that contain
	// BLANK cells: a later fix in cell/model/clipboard.js stopped _generateHtmlDocStr
	// from discarding the style of a cell whose getType() is null, so such a cell
	// now carries the width/fill/borders that were previously computed and thrown
	// away. That change is pinned exactly - including its per-cell size cost - in
	// fork-fix-tests/clipboard-empty-cell-style-and-clamp-test.js. Here the claim
	// is narrowed to what #1364 is actually about, and made sharper rather than
	// weaker: the text and internal flavours are unchanged everywhere, and the
	// html differs ONLY in the style attribute of blank <td>s.
	const tdTags = (h) => h.match(/<td[^>]*>/g) || [];
	for (const range of [ONE_CELL, TWO_COLS, TWO_ROWS, new Range(1, 1, 6, 9)]) {
		for (const cells of [EMPTY_FORMULA, WITH_TEXT, {}]) {
			const a = sheetText(WORKING, cells, range), b = sheetText(BASE, cells, range);
			for (const flavour of [c_oAscClipboardDataFormat.Text, c_oAscClipboardDataFormat.Internal]) {
				assert.deepStrictEqual(a[flavour], b[flavour], 'flavour ' + flavour + ' changed for ' + range);
			}
			const ta = tdTags(a[c_oAscClipboardDataFormat.Html]), tb = tdTags(b[c_oAscClipboardDataFormat.Html]);
			assert.strictEqual(ta.length, tb.length, 'a <td> appeared or vanished for ' + range);
			for (let i = 0; i < tb.length; i++) {
				if (tb[i] === '<td>') {
					assert.ok(/^<td style="[^"]*">$/.test(ta[i]), 'unexpected blank-cell markup: ' + ta[i]);
				} else {
					assert.strictEqual(ta[i], tb[i], 'a populated <td> changed for ' + range);
				}
			}
			const strip = (h) => h.replace(/<td[^>]*>/g, '<td>');
			assert.strictEqual(strip(a[c_oAscClipboardDataFormat.Html]), strip(b[c_oAscClipboardDataFormat.Html]),
				'html changed outside the <td> attributes for ' + range);
		}
	}
});

console.log('\n' + (failures ? failures + ' failing check(s) - the defect above is unfixed' : 'all checks passed'));
process.exit(failures ? 1 : 0);
