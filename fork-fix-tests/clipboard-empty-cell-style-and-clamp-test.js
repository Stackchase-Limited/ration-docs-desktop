/*
 * Two deferred defects in sdkjs/cell/model/clipboard.js, both found while
 * root-causing DesktopEditors #1364 and both left alone at the time.
 *
 * DEFECT 1 - a styled but EMPTY cell loses all its styling in the HTML flavour.
 *
 *   _generateHtmlDocStr (string flavour) and _generateHtmlDoc (DOM flavour) both
 *   computed the column width into `style` and then, for a cell whose
 *   getType() is null, threw the whole thing away:
 *
 *       style += "width:" + worksheet.getColumnWidth(col, 1) + "pt" + ";";
 *       ...
 *       if (cell.getType() !== null) {
 *           ... align, borders, fill appended to style ...
 *           addByStr(' style="' + style + '">');      // <- only here
 *           addByStr(this._makeNodesFromCellValueStr(cell.getValue2(), ...));
 *       } else {
 *           addByStr('>');                            // <- style discarded
 *       }
 *
 *   A cell with a fill and borders but no value has type null, so it reached the
 *   clipboard as a bare <td> - no fill, no borders, not even the width that had
 *   just been computed for it. Paste into Word or LibreOffice and the coloured
 *   blanks arrive white. Pasting back into Ration Docs looks fine because the
 *   internal binary flavour wins there, which is why it survived.
 *
 * DEFECT 2 - two of the three copy paths are missing a clamp the third has.
 *
 *   _getRangeMaxRowCol seeds maxRow/maxCol at 0 and raises them from
 *   _foreachNoEmpty. A selection with no stored cells at all visits nothing, so
 *   the result comes back BELOW the selection origin. getBinaryForCopy clamps it
 *   up to (r1,c1); _generateHtmlDocStr and _getTextFromSheet do not, so their
 *   loops run zero iterations and emit nothing while the binary still carries
 *   the cell at (r1,c1). Select an entirely empty column and the three flavours
 *   disagree about what was copied.
 *
 * Both fixes are in cell/model/clipboard.js only.
 *
 * Note on _generateHtmlDoc: it carries defect 1 identically but is DEAD CODE in
 * this tree - _generateHtml routes the sheet case to _generateHtmlDocStr and
 * nothing else names it (grep across sdkjs and web-apps finds only its own
 * definition). It is fixed and tested here anyway: the string variant was
 * transcribed from it in 0375bef8e2, which is precisely how one bug came to
 * exist in two places, and leaving the two out of step invites the next one.
 *
 * This test extracts the real prototype methods out of both revisions by brace
 * matching and runs them side by side in one process, so it proves its own
 * toothiness structurally: every "must fail before the fix" assertion has a
 * matching assertion that the pinned baseline really does still exhibit the bug.
 * Nothing under test is retyped here.
 *
 *   node fork-fix-tests/clipboard-empty-cell-style-and-clamp-test.js
 *   BASELINE=1 node ...   -> must FAIL (points WORKING at the baseline too)
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL_CB = 'cell/model/clipboard.js';
const REL_WCP = 'common/wordcopypaste.js';
/* pinned, never HEAD: ef815d5784 is "Land #1364", the tree these two defects
 * were deferred from. Left on HEAD this test would stop differing the moment
 * the fix is committed and would then pass forever while testing nothing. */
const BASE_REF = process.env.BASE_REF || 'ef815d57848bfcd642ba7a29d4d59bfc1b5530ef';

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
	return matched(source, at + assign.length);   /* "(args) { ... }" */
}
function grabDecl(source, rel, head) {
	const at = source.indexOf(head);
	assert.notStrictEqual(at, -1, 'not found in ' + rel + ': ' + head);
	return matched(source, at);
}

function extract(read) {
	const srcCb = read(REL_CB);
	const srcWcp = read(REL_WCP);
	const f = {
		_generateHtmlDoc:           grabFn(srcCb, REL_CB, '_generateHtmlDoc: function'),
		_generateHtmlDocStr:        grabFn(srcCb, REL_CB, '_generateHtmlDocStr: function'),
		_getRangeMaxRowCol:         grabFn(srcCb, REL_CB, '_getRangeMaxRowCol: function'),
		_getTextFromSheet:          grabFn(srcCb, REL_CB, '_getTextFromSheet: function'),
		_makeNodesFromCellValue:    grabFn(srcCb, REL_CB, '_makeNodesFromCellValue: function'),
		_makeNodesFromCellValueStr: grabFn(srcCb, REL_CB, '_makeNodesFromCellValueStr: function'),
		getBinaryForCopy:           grabFn(srcCb, REL_CB, 'getBinaryForCopy: function'),
		correctString:              grabDecl(srcWcp, REL_WCP, 'function CopyPasteCorrectString(str)')
	};
	/* guard against extracting the wrong thing */
	assert.ok(f._generateHtmlDocStr.indexOf('<table cellpadding=') !== -1,
		'extracted the wrong _generateHtmlDocStr');
	assert.ok(f._generateHtmlDocStr.indexOf('_makeNodesFromCellValueStr(cell.getValue2()') !== -1,
		'extracted the wrong _generateHtmlDocStr (no value emission)');
	assert.ok(f._generateHtmlDoc.indexOf('td.setAttribute("style", style)') !== -1,
		'extracted the wrong _generateHtmlDoc');
	assert.ok(f._getRangeMaxRowCol.indexOf('_foreachNoEmpty') !== -1,
		'extracted the wrong _getRangeMaxRowCol');
	assert.ok(f._getTextFromSheet.indexOf('getValueWithFormat()') !== -1,
		'extracted the wrong _getTextFromSheet');
	assert.ok(f.getBinaryForCopy.indexOf('new AscCommonExcel.BinaryFileWriter') !== -1,
		'extracted the wrong getBinaryForCopy');
	/* both html variants must still contain the type test somewhere, before and
	 * after the fix - if it vanished entirely the fix went too far */
	for (const k of ['_generateHtmlDoc', '_generateHtmlDocStr']) {
		assert.ok(f[k].indexOf('cell.getType() !== null') !== -1,
			k + ' no longer tests cell.getType() at all');
	}
	return f;
}

/* ---------------- stubs: the product's own constants and shapes ---------------- */
const c_oAscClipboardDataFormat = { Text: 1, Html: 2, Internal: 4, HtmlElement: 8, Rtf: 16, Image: 32 };
const c_oAscSelectionType = { RangeCells: 1, RangeCol: 2, RangeRow: 3, RangeMax: 4 };
const c_oAscBorderStyles = { None: 0, Thin: 1, Medium: 2, Thick: 3, Double: 4, Hair: 5, Dotted: 6, Dashed: 7 };
const gc_nMaxRow0 = 1048576 - 1, gc_nMaxCol0 = 16384 - 1;
/* cell/model/Workbook.js CellValueType */
const CellValueType = { Number: 0, String: 1, Bool: 2, Error: 3 };

function number2color(n) { return '#' + ('000000' + n.toString(16)).slice(-6); }

function Range(c1, r1, c2, r2) { this.c1 = c1; this.r1 = r1; this.c2 = c2; this.r2 = r2; }
/* cell/utils/utils.js Range.prototype.getType - selection bookkeeping, not code under test */
Range.prototype.getType = function () {
	const bRow = 0 === this.c1 && gc_nMaxCol0 === this.c2;
	const bCol = 0 === this.r1 && gc_nMaxRow0 === this.r2;
	if (bCol && bRow) return c_oAscSelectionType.RangeMax;
	if (bCol) return c_oAscSelectionType.RangeCol;
	if (bRow) return c_oAscSelectionType.RangeRow;
	return c_oAscSelectionType.RangeCells;
};
Range.prototype.clone = function () { return new Range(this.c1, this.r1, this.c2, this.r2); };
Range.prototype.toString = function () { return 'R(c' + this.c1 + ',r' + this.r1 + '..c' + this.c2 + ',r' + this.r2 + ')'; };

const Asc = {
	Range: function (c1, r1, c2, r2) { return new Range(c1, r1, c2, r2); },
	c_oAscVAlign: { Bottom: 0, Center: 1, Dist: 2, Just: 3, Top: 4 },
	c_oAscSelectionType: c_oAscSelectionType,
	EUnderline: { underlineNone: 0 },
	editor: null
};
Asc.Range.prototype = Range.prototype;

/* ---------------- a DOM just large enough for _generateHtmlDoc ---------------- */
function Node(tag) {
	this.tagName = tag.toUpperCase();
	this.style = {};
	this.attrs = {};
	this.childNodes = [];
	this.textContent = '';
	this.innerHTML = '';
}
Node.prototype.appendChild = function (n) { this.childNodes.push(n); return n; };
Node.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
Node.prototype.getAttribute = function (k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; };
const fakeDocument = { createElement: (t) => new Node(t) };
function findAll(node, tag, out) {
	out = out || [];
	if (node.tagName === tag) out.push(node);
	node.childNodes.forEach((c) => findAll(c, tag, out));
	return out;
}

/* ---------------- the sheet stub ---------------- */
const defaultFormat = {
	getSkip: () => false, getName: () => 'Calibri', getSize: () => 11,
	getColor: () => null, getVerticalAlign: () => 0, getBold: () => false,
	getItalic: () => false, getUnderline: () => 0, getStrikeout: () => false
};
function fragment(text) { return { format: defaultFormat, getFragmentText: () => text }; }
function border(rgb) { return { s: c_oAscBorderStyles.Thin, w: 1, getRgbOrNull: () => rgb }; }
const NO_BORDERS = { l: null, r: null, t: null, b: null };

/*
 * A sheet is a sparse map "row,col" -> spec, and that map IS the storage: a cell
 * is present in it exactly when the real workbook would hold a Cell object for
 * it. A cell with only formatting and no value IS stored (it has an xfs), which
 * is why _foreachNoEmpty below visits it - Range.prototype._foreachNoEmpty
 * (Workbook.js:18803) iterates stored cells via RowIterator, it does not test
 * for a value. Only a never-touched cell is absent.
 *
 * spec: { type, value, fill, borders }   type null => "styled but valueless"
 */
function cellObj(spec, r, c, ws) {
	return {
		nRow: r, nCol: c, ws: ws,
		bbox: new Range(c, r, c, r),
		getBBox0: function () { return this.bbox; },
		hasMerged: () => (spec && spec.merged ? spec.merged : null),
		/* Cell.prototype.getType (Workbook.js:16010) returns this.type, null when unset */
		getType: () => (spec && spec.type !== undefined ? spec.type : null),
		/* Cell.prototype.getValueWithFormat - the displayed text */
		getValueWithFormat: () => (spec && spec.value != null ? spec.value : ''),
		/* Cell.prototype._getValue2Result (Workbook.js:17851): when sText and aText
		 * are both null it sets sText = "", so even a typeless cell yields exactly
		 * one empty fragment - never an empty array. */
		getValue2: () => [fragment(spec && spec.value != null ? spec.value : '')],
		getAlign: () => ({
			getWrap: () => false,
			getAlignHorizontal: () => null,
			getAlignVertical: () => Asc.c_oAscVAlign.Bottom
		}),
		getBorderFull: () => (spec && spec.borders ? spec.borders : NO_BORDERS),
		getFillColor: () => (spec && spec.fill != null ? { getRgb: () => spec.fill } : null),
		getEffectiveHyperlink: () => null
	};
}

function makeModel(cells) {
	const model = {
		bExcludeHiddenRows: false,
		Drawings: [],
		workbook: null,
		getRowHidden: () => false,
		getColHidden: () => false,
		getRowHeight: () => 14.25,
		selectionRange: null,
		getCell3: function (r, c) { return cellObj(cells[r + ',' + c] || null, r, c, this); },
		getRange3: function (r1, c1, r2, c2) {
			const self = this;
			const bbox = new Range(c1, r1, c2, r2);
			return {
				bbox: bbox,
				getBBox0: () => bbox,
				/* Workbook.js:18803 - visits STORED cells inside the bbox, in row
				 * order. It does not test for a value, so a formatting-only cell
				 * counts as present. */
				_foreachNoEmpty: function (actionCell) {
					Object.keys(cells).sort(function (a, b) {
						const A = a.split(',').map(Number), B = b.split(',').map(Number);
						return A[0] - B[0] || A[1] - B[1];
					}).forEach(function (key) {
						const rc = key.split(',').map(Number);
						if (rc[0] >= r1 && rc[0] <= r2 && rc[1] >= c1 && rc[1] <= c2) {
							actionCell(cellObj(cells[key], rc[0], rc[1], self));
						}
					});
				}
			};
		}
	};
	model.workbook = {
		getDefaultFont: () => 'Calibri', getDefaultSize: () => 11,
		oApi: null, Core: null
	};
	return model;
}

function makeWorksheetView(cells, range) {
	const model = makeModel(cells);
	model.selectionRange = { ranges: [range], getLast: () => range };
	Asc.editor = { wb: { getWorksheet: () => ({ objectRender: null }) } };
	return {
		model: model,
		objectRender: { controller: { getTargetDocContent: () => null, getSelectionImage: () => null } },
		getColumnWidth: (col) => 48 + col,   /* distinct per column, so a lost width is visible */
		getSelectedRange: () => model.getRange3(range.r1, range.c1, range.r2, range.c2)
	};
}

/* ---------------- build one revision ---------------- */
function build(fns) {
	const body = `
'use strict';
var doc = ENV.document;
var document = ENV.document;
var window = ENV.window;
var c_MaxStringLength = 536870888;
var AscFormat = { ExecuteNoHistory: function (f, ctx, args) { return f.apply(ctx, args); } };
var pptx_content_writer = {
	Start_UseFullUrl: function () {}, End_UseFullUrl: function () {},
	Start_CopyPaste: function () {}, End_CopyPaste: function () {},
	BinaryFileWriter: { ClearIdMap: function () {} }
};
function CCopyPasteExcelOptions() { this.wb = null; this.setOldWorkbookCoreParameters = function () {}; }
var notSupportExternalReferenceFileFormat = {};

${fns.correctString}

function CopyProcessorExcel() {}
CopyProcessorExcel.prototype = {
	constructor: CopyProcessorExcel,
	_generateHtmlDoc: function ${fns._generateHtmlDoc},
	_generateHtmlDocStr: function ${fns._generateHtmlDocStr},
	_getRangeMaxRowCol: function ${fns._getRangeMaxRowCol},
	_getTextFromSheet: function ${fns._getTextFromSheet},
	_makeNodesFromCellValue: function ${fns._makeNodesFromCellValue},
	_makeNodesFromCellValueStr: function ${fns._makeNodesFromCellValueStr},
	getBinaryForCopy: function ${fns.getBinaryForCopy},
	_getBinaryShapeContent: function () { return null; }
};
return { CopyProcessorExcel: CopyProcessorExcel };
`;
	/* what the binary writer was actually handed */
	const binaryRanges = [];
	const AscCommon = {
		c_oAscClipboardDataFormat: c_oAscClipboardDataFormat,
		gc_nMaxCol: gc_nMaxCol0 + 1, gc_nMaxRow: gc_nMaxRow0 + 1,
		gc_nMaxDigCountView: 11,
		align_Left: 1, align_Right: 2, align_Center: 3, align_Justify: 4,
		vertalign_SubScript: 1, vertalign_SuperScript: 2,
		CCore: function () {}
	};
	const AscCommonExcel = {
		MultiplyRange: function (ranges) { this.getUnionRange = () => ranges[0]; },
		BinaryFileWriter: function (wb, range) {
			binaryRanges.push(range);
			this.Write = () => 'STUBBEDBINARY';
		}
	};
	const ENV = { document: fakeDocument, window: { AscCommon: AscCommon, Asc: Asc } };
	const api = new Function('AscCommon', 'AscCommonExcel', 'Asc',
		'c_oAscClipboardDataFormat', 'c_oAscBorderStyles', 'number2color', 'ENV', body)
		(AscCommon, AscCommonExcel, Asc, c_oAscClipboardDataFormat, c_oAscBorderStyles, number2color, ENV);
	return { api, binaryRanges };
}

/* ---------------- the two revisions ---------------- */
const BASELINE = !!process.env.BASELINE;
const WORKING = build(extract(BASELINE ? readGit : readWorking));
const BASE = build(extract(readGit));

/* ---------------- operations ---------------- */
function htmlStr(built, cells, range) {
	const ws = makeWorksheetView(cells, range);
	const p = new built.api.CopyProcessorExcel();
	return p._generateHtmlDocStr(ws.getSelectedRange(), ws, null);
}
function htmlDomTds(built, cells, range) {
	const ws = makeWorksheetView(cells, range);
	const p = new built.api.CopyProcessorExcel();
	const table = p._generateHtmlDoc(ws.getSelectedRange(), ws);
	return findAll(table, 'TD', []);
}
function plainText(built, cells, range) {
	const ws = makeWorksheetView(cells, range);
	const p = new built.api.CopyProcessorExcel();
	return p._getTextFromSheet(ws.getSelectedRange(), ws);
}
function binaryRange(built, cells, range) {
	const ws = makeWorksheetView(cells, range);
	const p = new built.api.CopyProcessorExcel();
	built.binaryRanges.length = 0;
	p.getBinaryForCopy(ws.model, ws.objectRender, null, false, false, false);
	return built.binaryRanges[0];
}
/* the <td> tags of a string-flavour document, and their style attributes. Scoped
 * deliberately: the <table> itself always carries background-color:transparent,
 * so a document-wide search for "background-color" is not evidence about a cell. */
function tdTags(html) { return html.match(/<td[^>]*>/g) || []; }
function tdStyles(html) {
	return tdTags(html).map(function (t) {
		const m = /\sstyle="([^"]*)"/.exec(t);
		return m ? m[1] : null;
	});
}

/* the row/col span each flavour actually walked, derived from its output */
function htmlSpan(built, cells, range) {
	const s = htmlStr(built, cells, range);
	const rows = (s.match(/<tr /g) || []).length;
	const tds = (s.match(/<td/g) || []).length;
	return { rows: rows, tds: tds };
}

let failures = 0;
function check(name, fn) {
	try { fn(); console.log('  ok   ' + name); }
	catch (e) { failures++; console.log('  FAIL ' + name + '\n         ' + String(e.message).split('\n')[0]); }
}

/* ---------------- fixtures ---------------- */
const YELLOW = 0xFFFF00, RED = 0xFF0000;
/* B2 coloured with a full box border but NO value: the reported case */
const STYLED_EMPTY = {
	'1,1': { fill: YELLOW, borders: { l: border(RED), r: border(RED), t: border(RED), b: border(RED) } }
};
/* the same block with one ordinary text cell next to it */
const MIXED = {
	'1,1': { fill: YELLOW, borders: { l: border(RED), r: border(RED), t: border(RED), b: border(RED) } },
	'1,2': { type: CellValueType.String, value: 'hello' }
};
const ORDINARY = {
	'1,1': { type: CellValueType.String, value: 'alpha' },
	'1,2': { type: CellValueType.Number, value: '42' },
	'2,1': { type: CellValueType.String, value: 'beta', fill: YELLOW },
	'2,2': { type: CellValueType.String, value: 'gamma', borders: { l: border(RED), r: null, t: null, b: null } }
};
const B2        = new Range(1, 1, 1, 1);
const B2_C2     = new Range(1, 1, 2, 1);
const BLOCK     = new Range(1, 1, 2, 2);
/* whole column C, and whole row 6 - the shapes Range.getType calls RangeCol/RangeRow */
const WHOLE_COL_C = new Range(2, 0, 2, gc_nMaxRow0);
const WHOLE_ROW_6 = new Range(0, 5, gc_nMaxCol0, 5);
const SELECT_ALL  = new Range(0, 0, gc_nMaxCol0, gc_nMaxRow0);

console.log('\n0. harness: the working tree and the pinned baseline ' + BASE_REF.slice(0, 10) + ' differ only where they should');
check('the baseline still exhibits DEFECT 1 (so this test has teeth)', () => {
	const s = htmlStr(BASE, STYLED_EMPTY, B2);
	assert.deepStrictEqual(tdTags(s), ['<td>'], 'baseline no longer emits a bare <td> - is BASE_REF wrong? ' + s);
	assert.deepStrictEqual(tdStyles(s), [null], 'baseline td already carries a style: ' + s);
});
check('the baseline still exhibits DEFECT 2 (so this test has teeth)', () => {
	const mrc = (function () {
		const ws = makeWorksheetView({}, WHOLE_COL_C);
		return new BASE.api.CopyProcessorExcel()._getRangeMaxRowCol(ws.model, WHOLE_COL_C, ws.getSelectedRange());
	})();
	assert.strictEqual(mrc.col, 0, 'baseline already clamps col - is BASE_REF wrong?');
	assert.ok(mrc.col < WHOLE_COL_C.c1, 'baseline result is not below the selection origin');
});

console.log('\n1. DEFECT 1 - a styled but valueless cell keeps its styling  (string flavour)');
check('B2 is coloured and has a box border, but no value -> type is null', () => {
	const ws = makeWorksheetView(STYLED_EMPTY, B2);
	assert.strictEqual(ws.model.getCell3(1, 1).getType(), null);
	assert.notStrictEqual(ws.model.getCell3(1, 1).getFillColor(), null);
});
check('its <td> carries the fill', () => {
	const s = htmlStr(WORKING, STYLED_EMPTY, B2);
	assert.ok(s.indexOf('background-color:#ffff00;') !== -1, 'no fill in: ' + s);
});
check('its <td> carries all four borders', () => {
	const s = htmlStr(WORKING, STYLED_EMPTY, B2);
	for (const side of ['border-left', 'border-right', 'border-top', 'border-bottom']) {
		assert.ok(s.indexOf(side + ':1px solid #ff0000;') !== -1, 'no ' + side + ' in: ' + s);
	}
});
check('its <td> carries the column width that was computed and then discarded', () => {
	const s = htmlStr(WORKING, STYLED_EMPTY, B2);
	assert.ok(s.indexOf('width:49pt;') !== -1, 'no width in: ' + s);   /* getColumnWidth(1) = 49 */
});
check('the VALUE is still skipped - no empty <span> is emitted for a typeless cell', () => {
	const s = htmlStr(WORKING, STYLED_EMPTY, B2);
	assert.strictEqual(s.indexOf('<span'), -1, 'an empty span leaked in: ' + s);
	assert.ok(/<td style="[^"]+"><\/td>/.test(s), 'td is not empty: ' + s);
});
check('a bare <td> with no style attribute is no longer produced at all', () => {
	const s = htmlStr(WORKING, STYLED_EMPTY, B2);
	assert.ok(!/<td>/.test(s), 'still a bare td: ' + s);
});
check('the styled-empty cell and its ordinary neighbour are both styled', () => {
	const s = htmlStr(WORKING, MIXED, B2_C2);
	assert.strictEqual((s.match(/<td style=/g) || []).length, 2, s);
	assert.ok(s.indexOf('>hello</span>') !== -1, 'neighbour lost its value: ' + s);
});

check('a MERGED, filled, valueless block - a title bar - keeps its fill and spans', () => {
	/* B2:D2 merged, yellow, no text. Very common, and the merge branch reads the
	 * bottom-right cell's borders from inside the block that used to be skipped. */
	const mb = new Range(1, 1, 3, 1);
	const merged = {
		'1,1': { fill: YELLOW, merged: mb },
		'1,3': { borders: { l: null, r: border(RED), t: null, b: border(RED) } }
	};
	const s = htmlStr(WORKING, merged, new Range(1, 1, 3, 1));
	const tags = tdTags(s);
	assert.strictEqual(tags.length, 1, 'merge was not honoured: ' + s);
	assert.ok(tags[0].indexOf('colspan=3') !== -1, tags[0]);
	assert.ok(tags[0].indexOf('background-color:#ffff00;') !== -1, tags[0]);
	/* the merged width is the sum of the three column widths: 49+50+51 */
	assert.ok(tags[0].indexOf('width:150pt;') !== -1, tags[0]);
	/* right/bottom borders come from the merge's last cell */
	assert.ok(tags[0].indexOf('border-right:1px solid #ff0000;') !== -1, tags[0]);
	assert.ok(tags[0].indexOf('border-bottom:1px solid #ff0000;') !== -1, tags[0]);
	/* the baseline dropped all of it */
	assert.deepStrictEqual(tdStyles(htmlStr(BASE, merged, new Range(1, 1, 3, 1))), [null],
		'baseline already styled the merged block');
});

console.log('\n1b. DEFECT 1 - the same defect in the DOM flavour  (_generateHtmlDoc, currently dead code)');
check('the DOM variant had the identical bug: baseline TD has no style attribute', () => {
	const tds = htmlDomTds(BASE, STYLED_EMPTY, B2);
	assert.strictEqual(tds.length, 1);
	assert.strictEqual(tds[0].getAttribute('style'), null,
		'baseline DOM td already styled - is BASE_REF wrong? ' + tds[0].getAttribute('style'));
});
check('the fixed DOM variant sets a style attribute carrying width, fill and borders', () => {
	const tds = htmlDomTds(WORKING, STYLED_EMPTY, B2);
	const style = tds[0].getAttribute('style');
	assert.ok(style, 'no style attribute at all');
	assert.ok(style.indexOf('width:49pt;') !== -1, style);
	assert.ok(style.indexOf('background-color:#ffff00;') !== -1, style);
	assert.ok(style.indexOf('border-left:1px solid #ff0000;') !== -1, style);
});
check('the fixed DOM variant still appends no value node for a typeless cell', () => {
	const tds = htmlDomTds(WORKING, STYLED_EMPTY, B2);
	assert.strictEqual(tds[0].childNodes.length, 0, 'a value node was appended');
});
check('the two html flavours now agree about the styled-empty cell', () => {
	const domStyle = htmlDomTds(WORKING, STYLED_EMPTY, B2)[0].getAttribute('style');
	const strStyle = /<td style="([^"]*)"/.exec(htmlStr(WORKING, STYLED_EMPTY, B2))[1];
	assert.strictEqual(domStyle, strStyle);
});

console.log('\n2. DEFECT 2 - the clamp the other two paths were missing');
check('an entirely empty whole-column selection: baseline binary copies C1, html and text copy nothing', () => {
	const br = binaryRange(BASE, {}, WHOLE_COL_C);
	assert.deepStrictEqual([br.c1, br.r1, br.c2, br.r2], [2, 0, 2, 0], 'binary range: ' + br);
	assert.strictEqual(htmlSpan(BASE, {}, WHOLE_COL_C).tds, 0, 'baseline html already emits a td');
	assert.strictEqual(plainText(BASE, {}, WHOLE_COL_C), '', 'baseline text is not empty');
});
check('after the fix all three paths walk exactly the cell at (r1,c1)', () => {
	const br = binaryRange(WORKING, {}, WHOLE_COL_C);
	assert.deepStrictEqual([br.c1, br.r1, br.c2, br.r2], [2, 0, 2, 0], 'binary range moved: ' + br);
	const span = htmlSpan(WORKING, {}, WHOLE_COL_C);
	assert.deepStrictEqual(span, { rows: 1, tds: 1 }, 'html span: ' + JSON.stringify(span));
	assert.strictEqual(plainText(WORKING, {}, WHOLE_COL_C), '', 'one empty cell still reads as ""');
});
check('an entirely empty whole-ROW selection: baseline html emits no rows at all', () => {
	assert.strictEqual(htmlSpan(BASE, {}, WHOLE_ROW_6).rows, 0, 'baseline already emits a row');
	const br = binaryRange(BASE, {}, WHOLE_ROW_6);
	assert.deepStrictEqual([br.c1, br.r1, br.c2, br.r2], [0, 5, 0, 5], 'binary range: ' + br);
});
check('after the fix the empty whole-row selection walks exactly A6 everywhere', () => {
	const br = binaryRange(WORKING, {}, WHOLE_ROW_6);
	assert.deepStrictEqual([br.c1, br.r1, br.c2, br.r2], [0, 5, 0, 5], 'binary range moved: ' + br);
	assert.deepStrictEqual(htmlSpan(WORKING, {}, WHOLE_ROW_6), { rows: 1, tds: 1 });
});
check('select-all on an empty sheet already agreed (c1=r1=0) and still does', () => {
	for (const rev of [BASE, WORKING]) {
		const br = binaryRange(rev, {}, SELECT_ALL);
		assert.deepStrictEqual([br.c1, br.r1, br.c2, br.r2], [0, 0, 0, 0], 'binary: ' + br);
		assert.deepStrictEqual(htmlSpan(rev, {}, SELECT_ALL), { rows: 1, tds: 1 });
	}
});
check('the two defects interlock: an empty-but-COLOURED column now copies its colour', () => {
	/* C1 has a fill and no value. It IS stored, so _foreachNoEmpty finds it and
	 * the clamp is not what saves this one - defect 1 is. Both must be fixed for
	 * the colour to reach the clipboard. */
	const coloured = { '0,2': { fill: YELLOW } };
	assert.deepStrictEqual(tdStyles(htmlStr(BASE, coloured, WHOLE_COL_C)), [null], 'baseline already carried it');
	const style = tdStyles(htmlStr(WORKING, coloured, WHOLE_COL_C))[0];
	assert.ok(style && style.indexOf('background-color:#ffff00;') !== -1, String(style));
});
check('the clamp is a no-op for any selection that is not entirely empty', () => {
	const cases = [
		[{ '0,2': { type: CellValueType.String, value: 'x' } }, WHOLE_COL_C],
		[{ '9,2': { type: CellValueType.String, value: 'x' } }, WHOLE_COL_C],
		[{ '5,3': { type: CellValueType.String, value: 'x' } }, WHOLE_ROW_6],
		[ORDINARY, SELECT_ALL]
	];
	for (const [cells, range] of cases) {
		const ws = makeWorksheetView(cells, range);
		const a = new WORKING.api.CopyProcessorExcel()._getRangeMaxRowCol(ws.model, range, ws.getSelectedRange());
		const b = new BASE.api.CopyProcessorExcel()._getRangeMaxRowCol(ws.model, range, ws.getSelectedRange());
		assert.deepStrictEqual(a, b, 'clamp changed a non-empty selection: ' + range);
	}
});
check('_getRangeMaxRowCol still returns null for an ordinary cell-range selection', () => {
	const ws = makeWorksheetView(ORDINARY, BLOCK);
	assert.strictEqual(new WORKING.api.CopyProcessorExcel()._getRangeMaxRowCol(ws.model, BLOCK, ws.getSelectedRange()), null);
});

console.log('\n3. no regression - ordinary copy of ordinary cells is unchanged');
check('string flavour is BYTE-IDENTICAL to the baseline when every cell in the selection has a value', () => {
	/* B1:C2 is fully populated in ORDINARY, so no cell in it is typeless */
	for (const range of [B2, B2_C2, BLOCK]) {
		assert.strictEqual(htmlStr(WORKING, ORDINARY, range), htmlStr(BASE, ORDINARY, range),
			'html differs for ' + range);
	}
});
check('DOM flavour is byte-identical to the baseline when every cell in the selection has a value', () => {
	for (const range of [B2, B2_C2, BLOCK]) {
		const a = htmlDomTds(WORKING, ORDINARY, range).map((td) => td.getAttribute('style'));
		const b = htmlDomTds(BASE, ORDINARY, range).map((td) => td.getAttribute('style'));
		assert.deepStrictEqual(a, b, 'dom differs for ' + range);
		assert.ok(a.every((x) => x !== null), 'a populated cell lost its style');
	}
});
check('every cell that HAS a type is untouched, even in a selection that also contains blanks', () => {
	/* A1:D4 over ORDINARY: only B2,B3,C2,C3 are stored, the other twelve are blank */
	const SPARSE = new Range(0, 0, 3, 3);
	const a = tdTags(htmlStr(WORKING, ORDINARY, SPARSE));
	const b = tdTags(htmlStr(BASE, ORDINARY, SPARSE));
	assert.strictEqual(a.length, b.length, 'a <td> appeared or vanished');
	assert.strictEqual(a.length, 16, 'expected a full 4x4 of <td>: ' + a.length);
	for (let i = 0; i < a.length; i++) {
		if (b[i] === '<td>') continue;              /* blank - checked in the next test */
		assert.strictEqual(a[i], b[i], 'a populated <td> changed at index ' + i);
	}
	/* and the text content of the whole document is unchanged */
	const strip = (h) => h.replace(/<td[^>]*>/g, '<td>');
	assert.strictEqual(strip(htmlStr(WORKING, ORDINARY, SPARSE)), strip(htmlStr(BASE, ORDINARY, SPARSE)),
		'something other than the <td> attributes changed');
});
check('a blank cell changes in exactly one way: it gains a style attribute, and gains nothing else', () => {
	/* This IS a deliberate behaviour change, and it is the point of the fix: the
	 * width was already computed for these cells and thrown away. State it
	 * exactly rather than hide it behind a loose assertion. */
	const SPARSE = new Range(0, 0, 3, 3);
	const a = tdTags(htmlStr(WORKING, ORDINARY, SPARSE));
	const b = tdTags(htmlStr(BASE, ORDINARY, SPARSE));
	let blanks = 0;
	for (let i = 0; i < b.length; i++) {
		if (b[i] !== '<td>') continue;
		blanks++;
		assert.ok(/^<td style="width:\d+pt;white-space:nowrap;vertical-align:bottom;">$/.test(a[i]),
			'unexpected blank-cell markup: ' + a[i]);
	}
	assert.strictEqual(blanks, 12, 'expected 12 blank cells in A1:D4, saw ' + blanks);
	/* no value node is emitted for them, in either flavour */
	assert.strictEqual(htmlStr(WORKING, ORDINARY, SPARSE).match(/<span/g).length,
		htmlStr(BASE, ORDINARY, SPARSE).match(/<span/g).length, 'a value span appeared');
	const domBlank = htmlDomTds(WORKING, ORDINARY, SPARSE).filter((td, i) => b[i] === '<td>');
	assert.ok(domBlank.every((td) => td.childNodes.length === 0), 'a DOM value node appeared');
});
check('the size cost of that change is bounded and pinned  (blank <td>: 9 bytes -> 70)', () => {
	/* dc4a593072 was titled "Copy table optimization (html)", so the cost is
	 * recorded here deliberately. The expensive half of that optimization - the
	 * getValue2() call and the <span> it builds - is still skipped; what is paid
	 * back is markup size only. If this number moves, it was moved on purpose. */
	const one = { '0,0': { type: CellValueType.String, value: 'x' } };
	const R = new Range(0, 0, 9, 9);   /* 100 cells, 99 of them blank */
	const grew = htmlStr(WORKING, one, R).length - htmlStr(BASE, one, R).length;
	/* + ' style="width:NNpt;white-space:nowrap;vertical-align:bottom;"' */
	assert.strictEqual(grew / 99, 61, 'per-blank-cell growth changed: ' + (grew / 99));
	/* and it is a constant per cell, not super-linear */
	const R2 = new Range(0, 0, 19, 19);   /* 400 cells, 399 blank */
	assert.strictEqual((htmlStr(WORKING, one, R2).length - htmlStr(BASE, one, R2).length) / 399, 61);
});
check('plain text is byte-identical to the baseline everywhere tested', () => {
	for (const cells of [ORDINARY, MIXED, STYLED_EMPTY, {}]) {
		for (const range of [B2, B2_C2, BLOCK, WHOLE_COL_C, WHOLE_ROW_6, SELECT_ALL]) {
			/* the two clamped-empty cases are the fix and are checked above */
			const empty = Object.keys(cells).length === 0 &&
				[WHOLE_COL_C, WHOLE_ROW_6].indexOf(range) !== -1;
			if (empty) continue;
			assert.strictEqual(plainText(WORKING, cells, range), plainText(BASE, cells, range),
				'text differs for ' + range);
		}
	}
});
check('the binary flavour range is byte-identical to the baseline in every case', () => {
	for (const cells of [ORDINARY, MIXED, STYLED_EMPTY, {}]) {
		for (const range of [B2, B2_C2, BLOCK, WHOLE_COL_C, WHOLE_ROW_6, SELECT_ALL]) {
			const a = binaryRange(WORKING, cells, range), b = binaryRange(BASE, cells, range);
			assert.deepStrictEqual([a.c1, a.r1, a.c2, a.r2], [b.c1, b.r1, b.c2, b.r2],
				'binary differs for ' + range);
		}
	}
});
check('a cell that renders empty but HAS a type is untouched by the defect-1 change', () => {
	/* the #1364 shape: =IF(...,"",...) -> CellValueType.String with "" */
	const emptyFormula = { '1,1': { type: CellValueType.String, value: '', fill: YELLOW } };
	assert.strictEqual(htmlStr(WORKING, emptyFormula, B2), htmlStr(BASE, emptyFormula, B2));
	assert.strictEqual(plainText(WORKING, emptyFormula, B2), plainText(BASE, emptyFormula, B2));
});

console.log('\n' + (failures ? failures + ' failing check(s)' : 'all checks passed'));
process.exit(failures ? 1 : 0);
