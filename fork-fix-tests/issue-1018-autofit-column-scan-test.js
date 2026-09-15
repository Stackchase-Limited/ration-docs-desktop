/*
 * DesktopEditors #1018 - "DesktopEditors hangup when applying autofit in big xlsx file".
 *
 * Reproduction as filed: open a big xlsx, select the first 4 columns, apply
 * "AutoFit column width". The editor stops responding.
 *
 * asc_autoFitColumnWidth -> WorksheetView.autoFitColumnsWidth builds, for every
 * selected range, a range whose rows are 0 .. model.getRowsCount()-1, and
 * _autoFitColumnsWidth hands each column to _autoFitColumnWidth, whose body is a
 * DENSE index loop (cell/view/WorksheetView.js):
 *
 *     if (null == r2) { r2 = this.model.getRowsCount() - 1; }
 *     ...
 *     for (row = r1; row <= r2; ++row) {
 *         this._addCellTextToCache(col, row);
 *         ct = this._getCellTextCache(col, row);
 *         if (ct === undefined) { continue; }
 *         ...
 *     }
 *
 * Worksheet.getRowsCount() is the sheet's ROW EXTENT, not a cell count: it is
 * raised by every Row record (Worksheet._initRow, cell/model/Workbook.js) and by
 * rowsData.getMaxIndex(), so a workbook whose rows carry whole-sheet formatting
 * reports 1048576 even when the columns hold a hundred values. Autofitting four
 * columns then runs _addCellTextToCache 4 * 1048576 times - and every one of those
 * calls builds a Range, builds a CellFlags, and asks the merge manager - to read
 * four hundred cells.
 *
 * For COLUMN WIDTH those rows cannot contribute: _addCellTextToCache returns at
 * "if (c.isEmptyTextString())" before it reaches any measuring or any
 * _changeColWidth, it leaves nothing in the text cache, so _getCellTextCache
 * returns undefined and the loop body does "continue".
 *
 * The empty-cell branch is NOT a no-op, though. WorksheetView.js:9532:
 *
 *     if (c.isEmptyTextString()) {
 *         if (!angle && c.isNotDefaultFont() && !(mergeType & c_oAscMergeType.rows)) {
 *             ... measures 'A' in the cell's font ...
 *             let cache = this._fetchCellCache(col, row);
 *             cache.metrics = tm;
 *             this._updateRowHeight(cache, row);
 *         }
 *         return mc ? mc.c2 : col;
 *     }
 *
 * and _updateRowHeight writes through to the model (this.model.setRowHeight), which
 * MATERIALISES a Row record per row (setRowHeight -> _foreachRow -> _initRow). So on
 * a sheet whose columns carry a non-default font the old scan also grew, and created
 * a record for, every row in the sheet. Section 4 measures exactly that.
 *
 * The fix clamps the loop to the column's own cell extent - the same bound
 * Range._foreachNoEmptyByCol uses (colData.getMinIndex()/getMaxIndex(),
 * cell/model/SheetMemory.js).
 *
 * Sections 0-1 are harness/behaviour checks and pass in both trees.
 * Section 2 is the complexity claim and FAILS with BASELINE=1.
 * Section 3 runs the working tree and BASE_REF side by side on column widths.
 * Section 4 does the same for ROW HEIGHTS and Row-record materialisation, and is
 * where the one deliberate behaviour difference is measured rather than argued.
 *
 *   node fork-fix-tests/issue-1018-autofit-column-scan-test.js
 *   BASELINE=1 node fork-fix-tests/issue-1018-autofit-column-scan-test.js   # must fail
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL_WSV = 'cell/view/WorksheetView.js';
const REL_WB = 'cell/model/Workbook.js';
const REL_UTILS = 'cell/utils/utils.js';
// Pinned to the parent of the commit that landed this fix. It must NOT default to
// HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
// and the test passes forever while testing nothing.
const BASE_REF = process.env.BASE_REF || '26cb022b7c^';

function readGit(rel) {
	return execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 });
}
function read(rel) {
	return process.env.BASELINE ? readGit(rel) : fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}
const srcWsv = read(REL_WSV);
/* sections 3 and 4 run the working tree and BASE_REF against each other in one process */
const srcWsvBase = readGit(REL_WSV);
/* model-side helpers: untouched by this fix, taken from one revision */
const srcWb = read(REL_WB);
const srcUtils = read(REL_UTILS);

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
	return matched(source, at + assign.length);
}
/* whole `function name(...) {...}` declaration, kept verbatim */
function grabDecl(source, rel, head) {
	const at = source.indexOf(head);
	assert.notStrictEqual(at, -1, 'not found in ' + rel + ': ' + head);
	return matched(source, at);
}
function grabConst(source, rel, re) {
	const m = source.match(re);
	assert.ok(m, 'not found in ' + rel + ': ' + re);
	return m[0];
}

/* ---------------- the real code under test, per revision ---------------- */
function extract(source) {
	const fns = {
		autoFitCol:  grabFn(source, REL_WSV, 'WorksheetView.prototype._autoFitColumnWidth = function'),
		autoFitCols: grabFn(source, REL_WSV, 'WorksheetView.prototype._autoFitColumnsWidth = function'),
		cellCache:   grabFn(source, REL_WSV, 'WorksheetView.prototype._getCellCache = function'),
		textCache:   grabFn(source, REL_WSV, 'WorksheetView.prototype._getCellTextCache = function'),
		updRowH:     grabFn(source, REL_WSV, 'WorksheetView.prototype._updateRowHeight = function'),
		rowDesc:     grabFn(source, REL_WSV, 'WorksheetView.prototype._getRowDescender = function'),
		rowHReal:    grabFn(source, REL_WSV, 'WorksheetView.prototype._getRowHeightReal = function')
	};
	/* guard against extracting the wrong thing */
	assert.ok(fns.autoFitCol.indexOf('this._addCellTextToCache(col, row)') !== -1,
		'extracted the wrong _autoFitColumnWidth');
	assert.ok(fns.autoFitCol.indexOf('this.model.getRowsCount() - 1') !== -1,
		'extracted the wrong _autoFitColumnWidth');
	assert.ok(fns.autoFitCols.indexOf('this._autoFitColumnWidth(') !== -1,
		'extracted the wrong _autoFitColumnsWidth');
	assert.ok(fns.textCache.indexOf('getMergedByCell') !== -1,
		'extracted the wrong _getCellTextCache');
	assert.ok(fns.updRowH.indexOf('this.model.setRowHeight(') !== -1,
		'extracted the wrong _updateRowHeight');
	return fns;
}
const FNS = extract(srcWsv);
const FNS_BASE = extract(srcWsvBase);

/* the real font resolution for a cell that has no stored record */
const srcCompiledFromArray = grabDecl(srcWb, REL_WB, 'function getCompiledStyleFromArray(');
const srcCompiledStyle     = grabDecl(srcWb, REL_WB, 'function getCompiledStyle(');
const srcEmptyComponents   = grabConst(srcWb, REL_WB, /var emptyStyleComponents = \{table: \[\], conditional: \[\]\};/);
const srcRangeGetFont      = grabFn(srcWb, REL_WB, 'Range.prototype.getFont = function');
const srcRangeNotDefFont   = grabFn(srcWb, REL_WB, 'Range.prototype.isNotDefaultFont = function');
const srcWsCompiledStyle   = grabFn(srcWb, REL_WB, 'Worksheet.prototype.getCompiledStyle = function');
const srcWsRowCustomH      = grabFn(srcWb, REL_WB, 'Worksheet.prototype.getRowCustomHeight = function');
const srcCellCompiledStyle = grabFn(srcWb, REL_WB, 'Cell.prototype.getCompiledStyle = function');
assert.ok(srcRangeNotDefFont.indexOf('oAllCol') !== -1, 'extracted the wrong isNotDefaultFont');
assert.ok(srcCompiledStyle.indexOf('_getColNoEmptyWithAll') !== -1, 'extracted the wrong getCompiledStyle');

/* the real unit conversions _updateRowHeight rounds through */
const srcRound        = grabDecl(srcUtils, REL_UTILS, 'function round(x)');
const srcCeil         = grabDecl(srcUtils, REL_UTILS, 'function ceil(x)');
const srcConvertPtToPx = grabDecl(srcUtils, REL_UTILS, 'function convertPtToPx(value)');
const srcConvertPxToPt = grabDecl(srcUtils, REL_UTILS, 'function convertPxToPt(value)');
const srcSizePxinPt   = grabConst(srcUtils, REL_UTILS, /var sizePxinPt = 72 \/ 96;/);
const srcKLeftLim1    = grabConst(srcUtils, REL_UTILS, /var kLeftLim1\s*=\s*[^;]+;/);

/* --- constants, copied from where the product defines them --- */
/* cell/apiDefines.js:211 */
const c_oAscCanChangeColWidth = { none: 0, numbers: 1, all: 2 };
/* cell/apiDefines.js:218 */
const c_oAscMergeType = { none: 0, cols: 1, rows: 2 };
/* common/commonDefines.js:657 */
const CellValueType = { Number: 0, String: 1, Bool: 2, Error: 3 };
/* common/commonDefines.js:454 */
const c_oAscMaxColumnWidth = 255;
/* common/commonDefines.js:1793 */
const c_oAscVAlign = { Bottom: 0, Center: 1, Dist: 2, Just: 3, Top: 4 };
const gc_nMaxRow0 = 1048576 - 1;
const gc_nMaxCol0 = 16384 - 1;
const DEFAULT_ROW_HEIGHT_PT = 14.25;   // AscCommonExcel.oDefaultMetrics.RowHeight

/* --- stubs --- */
function Range(c1, r1, c2, r2) { this.c1 = c1; this.r1 = r1; this.c2 = c2; this.r2 = r2; }
const Asc = { Range: function (c1, r1, c2, r2) { return new Range(c1, r1, c2, r2); } };
Asc.Range.prototype = Range.prototype;
/* _autoFitColumnWidth reads the cap off Asc, not off the file-local alias */
Asc.c_oAscMaxColumnWidth = c_oAscMaxColumnWidth;
Asc.c_oAscVAlign = c_oAscVAlign;

const AscBrowser = { retinaPixelRatio: 1 };
const AscCommonExcel = { oDefaultMetrics: { RowHeight: DEFAULT_ROW_HEIGHT_PT, ColWidthChars: 8.43 } };

/* the real round/ceil and the real pt<->px conversions */
const units = new Function('Asc', 'AscBrowser', '"use strict";\n' +
	srcSizePxinPt + '\n' + srcKLeftLim1 + '\n' + srcRound + '\n' + srcCeil + '\n' +
	srcConvertPtToPx + '\n' + srcConvertPxToPt + '\n' +
	'return {round: round, ceil: ceil, convertPtToPx: convertPtToPx, convertPxToPt: convertPxToPt};')(Asc, AscBrowser);
Asc.round = units.round;
Asc.ceil = units.ceil;
AscCommonExcel.convertPtToPx = units.convertPtToPx;
AscCommonExcel.convertPxToPt = units.convertPxToPt;

const History = {
	Create_NewPoint: function () {},
	StartTransaction: function () {},
	EndTransaction: function () {},
	TurnOff: function () {},
	TurnOn: function () {}
};

/* mirrors SheetMemory: indexA/indexB are -1 until a cell is written (cell/model/SheetMemory.js) */
function ColData() { this.indexA = -1; this.indexB = -1; }
ColData.prototype.checkIndex = function (i) {
	if (this.indexA === -1) { this.indexA = this.indexB = i; return; }
	if (i < this.indexA) this.indexA = i;
	if (i > this.indexB) this.indexB = i;
};
ColData.prototype.getMinIndex = function () { return this.indexA; };
ColData.prototype.getMaxIndex = function () { return this.indexB; };

/* one measurable "glyph" is 7px wide, so a string's width is 7 * length */
const GLYPH_PX = 7;

function Font(name, size) { this.name = name; this.size = size; }
Font.prototype.getName = function () { return this.name; };
Font.prototype.getSize = function () { return this.size; };
const DEFAULT_FONT = new Font('Arial', 11);
const g_oDefaultFormat = { Font: DEFAULT_FONT };

function Xfs(font) { this.font = font; }
/* table/conditional style arrays are empty in this harness, so merge is never
 * reached; make that loud rather than silently wrong if it ever is. */
Xfs.prototype.merge = function () { throw new Error('Xfs.merge reached - the stub owes a real implementation'); };

/* a Row record - what setRowHeight materialises through _initRow */
function RowRec(index) {
	this.index = index; this.xfs = null; this.h = null;
	this.hidden = false; this.customHeight = false; this.calcHeight = false;
}
RowRec.prototype.getHidden = function () { return this.hidden; };
RowRec.prototype.getCustomHeight = function () { return this.customHeight; };
RowRec.prototype.getCalcHeight = function () { return this.calcHeight; };
function ColRec(index) { this.index = index; this.xfs = null; }

/* a stored cell. getCompiledStyle is the real Cell.prototype.getCompiledStyle,
 * attached further down - it delegates to ws.getCompiledStyle with opt_cell set,
 * which means a stored cell resolves to its OWN xfs, not the column's. That is why
 * setColFont below also stamps the cells it covers: applying a format to a whole
 * column is what writes that xfs onto the cells that are already there. */
function CellRec(ws, nCol, nRow, text, type, xfs) {
	this.ws = ws; this.nCol = nCol; this.nRow = nRow;
	this.text = text; this.type = type; this.xfs = xfs || null;
}
CellRec.prototype.getStyle = function () { return this.xfs; };

function Model() {
	this.cells = [];               // cells[col][row] = CellRec for cells that exist
	this.cellsByCol = [];          // col -> ColData, the real name and shape
	this.cellsByColRowsCount = 0;
	this.nRowsCount = 0;           // the ROW EXTENT, what getRowsCount() returns
	this.nColsCount = 0;
	this.colWidthChars = [];       // col -> width in chars
	this.bestFit = {};             // col -> width last handed to setColBestFit
	this.merges = [];              // {c1, r1, c2, r2}
	this.rowRecs = {};             // index -> RowRec, "this row has a record"
	this.colRecs = [];             // index -> ColRec
	this.oAllCol = null;
	this.oAllRow = null;
	this.rowHeights = {};          // index -> height in pt, what the user would see
	this.rowRecordsMaterialised = 0;
	this.bExcludeCollapsed = false;
	this.selectionRange = { ranges: [] };
	this.sheetMergedStyles = { getStyle: function () { return { table: [], conditional: [] }; } };
	this.hiddenManager = {};
}
Model.prototype.setCell = function (col, row, text, type, xfs) {
	if (!this.cells[col]) this.cells[col] = [];
	const style = xfs || (this.colRecs[col] ? this.colRecs[col].xfs : null);
	this.cells[col][row] = new CellRec(this, col, row, text, (type === undefined ? CellValueType.String : type), style);
	this.getColData(col).checkIndex(row);
	this.cellsByColRowsCount = Math.max(this.cellsByColRowsCount, row + 1);
	this.nRowsCount = Math.max(this.nRowsCount, row + 1);
	this.nColsCount = Math.max(this.nColsCount, col + 1);
};
/* what a Row record does to the extent - Worksheet._initRow, cell/model/Workbook.js */
Model.prototype.addRowRecord = function (row, font) {
	this.nRowsCount = Math.max(this.nRowsCount, row + 1);
	if (font) {
		const r = this.rowRecs[row] || (this.rowRecs[row] = new RowRec(row));
		r.xfs = new Xfs(font);
	}
};
/* applying a format to a whole column: the Col record carries it for the rows that
 * have no cell, and the cells that DO exist get it stamped on their own xfs. */
Model.prototype.setColFont = function (col, font) {
	const c = this.colRecs[col] || (this.colRecs[col] = new ColRec(col));
	c.xfs = new Xfs(font);
	const existing = this.cells[col] || [];
	for (let r = 0; r < existing.length; ++r) {
		if (existing[r]) { existing[r].xfs = c.xfs; }
	}
	this.nColsCount = Math.max(this.nColsCount, col + 1);
};
Model.prototype.setRowCustomHeight = function (row, heightPt) {
	const r = this.rowRecs[row] || (this.rowRecs[row] = new RowRec(row));
	r.customHeight = true;
	r.h = heightPt;
	this.rowHeights[row] = heightPt;
	this.nRowsCount = Math.max(this.nRowsCount, row + 1);
};
Model.prototype.getColData = function (i) {
	if (!this.cellsByCol[i]) this.cellsByCol[i] = new ColData();
	return this.cellsByCol[i];
};
Model.prototype.getColDataNoEmpty = function (i) { return this.cellsByCol[i]; };
Model.prototype.getColDataLength = function () { return this.cellsByCol.length; };
Model.prototype.getRowsCount = function () { return this.nRowsCount; };
Model.prototype.getColsCount = function () { return this.nColsCount; };
Model.prototype.getPivotTableButtons = function () { return []; };
/* the anchor (mc.c1, mc.r1) keeps its cell; the covered coordinates do not */
Model.prototype.addMerge = function (c1, r1, c2, r2, text) {
	this.merges.push({ c1: c1, r1: r1, c2: c2, r2: r2 });
	this.setCell(c1, r1, text);
	this.nRowsCount = Math.max(this.nRowsCount, r2 + 1);
	this.nColsCount = Math.max(this.nColsCount, c2 + 1);
};
Model.prototype.getMergedByCell = function (row, col) {
	for (const m of this.merges) {
		if (m.c1 <= col && col <= m.c2 && m.r1 <= row && row <= m.r2) { return m; }
	}
	return null;
};
Model.prototype.colWidthToCharCount = function (px) { return px / GLYPH_PX; };
Model.prototype.charCountToModelColWidth = function (cc) { return cc; };
Model.prototype.setColBestFit = function (bBestFit, width, start, stop) {
	for (let c = start; c <= stop; ++c) {
		this.bestFit[c] = width;
		this.colWidthChars[c] = width;
	}
};
/* the shapes getCompiledStyle / isNotDefaultFont / _getRowHeightReal walk */
Model.prototype._getRowNoEmpty = function (nRow, fAction) { fAction(this.rowRecs[nRow] || null); };
Model.prototype._getRowNoEmptyWithAll = function (nRow, fAction) {
	fAction(this.rowRecs[nRow] || this.oAllRow || null);
};
Model.prototype._getCellNoEmpty = function (row, col, fAction) {
	fAction((this.cells[col] && this.cells[col][row]) || null);
};
Model.prototype._getColNoEmptyWithAll = function (nCol) { return this.colRecs[nCol] || this.oAllCol || null; };
/*
 * Stands in for Worksheet.setRowHeight. The part that matters here is what the
 * real one does through getRange3(start,0,stop,0)._foreachRow(fProcessRow):
 * _foreachRow calls _initRow for any row without a record, so every row it touches
 * gets a Row record it did not have before.
 */
Model.prototype.setRowHeight = function (height, start, stop, isCustom) {
	if (0 === height) { return; }
	if (null == start) { return; }
	if (null == stop) { stop = start; }
	for (let r = start; r <= stop; ++r) {
		let row = this.rowRecs[r];
		if (!row) { row = this.rowRecs[r] = new RowRec(r); this.rowRecordsMaterialised++; }
		row.h = height;
		if (isCustom) { row.customHeight = true; }
		row.calcHeight = true;
		row.hidden = false;
		this.rowHeights[r] = height;
		this.nRowsCount = Math.max(this.nRowsCount, r + 1);
	}
};
Model.prototype.getRowHeight = function (row) {
	const r = this.rowRecs[row];
	return (r && r.h > 0) ? r.h : DEFAULT_ROW_HEIGHT_PT;
};

/* the real compiled-style resolution and the real font comparison */
const modelBits = new Function(
	'Model', 'CellRef', 'CellRec', 'g_oDefaultFormat', 'AscCommonExcel', 'Asc',
	'"use strict";\n' +
	srcEmptyComponents + '\n' +
	srcCompiledFromArray + '\n' +
	srcCompiledStyle + '\n' +
	'Model.prototype.getCompiledStyle = function' + srcWsCompiledStyle + ';\n' +
	'Model.prototype.getRowCustomHeight = function' + srcWsRowCustomH + ';\n' +
	'CellRec.prototype.getCompiledStyle = function' + srcCellCompiledStyle + ';\n' +
	'CellRef.prototype.getFont = function' + srcRangeGetFont + ';\n' +
	'CellRef.prototype.isNotDefaultFont = function' + srcRangeNotDefFont + ';\n');

/* what _getCell returns: the product hands back a Range over one cell, never null
 * for a valid coordinate (Worksheet.getCell3 -> getRange3). */
function CellRef(worksheet, col, row) {
	this.worksheet = worksheet;
	this.bbox = new Range(col, row, col, row);
}
CellRef.prototype.stored = function () {
	const col = this.bbox.c1, row = this.bbox.r1;
	return (this.worksheet.cells[col] && this.worksheet.cells[col][row]) || null;
};
CellRef.prototype.isEmptyTextString = function () {
	const c = this.stored();
	return !c || !c.text;
};
CellRef.prototype.getValue2 = function () {
	const c = this.stored();
	return c && c.text ? [{ text: c.text }] : [{ text: '' }];
};
modelBits(Model, CellRef, CellRec, g_oDefaultFormat, AscCommonExcel, Asc);

/* the view's per-row cache entry */
function RowInfo(descender, heightPx) {
	this.descender = descender; this.height = heightPx; this.top = 0; this._heightForPrint = null;
}
RowInfo.prototype.setHeight = function (h) { this.height = h; };

function View(model) {
	this.model = model;
	this.workbook = { printPreviewState: { isStart: function () { return false; } } };
	this.cache = { rows: [] };
	this.cols = [];
	this.canChangeColWidth = c_oAscCanChangeColWidth.none;
	this.skipUpdateRowHeight = false;
	this.notUpdateRowHeight = false;
	this.isZooming = false;
	this.maxRowHeightPx = 409;
	this.maxDigitWidth = GLYPH_PX;
	this.defaultColWidthChars = 8.43;
	this.defaultRowDescender = 3;
	this.settings = { cells: { padding: 2 } };
	this.stringRender = {
		measureString: function () { throw new Error('unexpected re-measure'); },
		getTransformBound: function () { throw new Error('unexpected getTransformBound'); }
	};
	/* the product sizes this.rows to model.getRowsCount() in _calcHeightRows */
	this.rows = [];
	const n = model.getRowsCount();
	for (let i = 0; i < n; ++i) {
		this.rows.push(new RowInfo(this.defaultRowDescender, AscCommonExcel.convertPtToPx(DEFAULT_ROW_HEIGHT_PT)));
	}
	/* instrumentation */
	this.visits = 0;            // _addCellTextToCache calls = rows the loop touched
	this.hits = 0;              // of those, rows that actually had a cell with text
	this.emptyFontHits = 0;     // empty cells that took the isNotDefaultFont branch
	this.rowHeightUpdates = 0;  // _updateRowHeight calls
	this.calcColWidth = 0;
}
View.prototype.getZoom = function () { return 1; };
View.prototype.getRetinaPixelRatio = function () { return 1; };
View.prototype.getColumnWidthInSymbols = function (col) {
	const w = this.model.colWidthChars[col];
	return w === undefined ? this.defaultColWidthChars : w;
};
View.prototype._calcColWidth = function () { this.calcColWidth++; };
View.prototype._checkFilterButtonInRange = function () { return false; };
View.prototype._getFilterButtonSize = function () { return 12; };
View.prototype._getCell = function (col, row) {
	if (col < 0 || col > gc_nMaxCol0 || row < 0 || row > gc_nMaxRow0) { return null; }
	return new CellRef(this.model, col, row);
};
View.prototype._roundTextMetrics = function (tm) { return tm; };
View.prototype._fetchCellCache = function (col, row) {
	let r = this.cache.rows[row];
	if (!r) { r = this.cache.rows[row] = { columns: [], columnsWithText: [] }; }
	let c = r.columns[col];
	if (!c) { c = r.columns[col] = {}; }
	return c;
};
/* text metrics as a deterministic function of the font, so heights are comparable */
function metricsFor(font, text) {
	const size = font.getSize();
	return {
		width: (text === undefined ? 1 : text.length) * GLYPH_PX,
		height: Asc.round(size * 1.32),
		baseline: Asc.round(size * 1.05)
	};
}
/*
 * Stands in for WorksheetView._addCellTextToCache, reproducing the two branches
 * _autoFitColumnWidth depends on, with the real isNotDefaultFont and the real
 * _updateRowHeight doing the work:
 *   - a cell with no text takes the "if (c.isEmptyTextString())" branch, which
 *     leaves NOTHING in the text cache but DOES call _updateRowHeight when the
 *     cell's font is not the row's font;
 *   - a cell with text ends with _fetchCellCache + _fetchCellCacheText and its own
 *     _updateRowHeight (WorksheetView.js:9765).
 */
View.prototype._addCellTextToCache = function (col, row) {
	this.visits++;
	const mc = this.model.getMergedByCell(row, col);
	const mergeType = mc ? (mc.r1 !== mc.r2 ? c_oAscMergeType.rows : 0) | (mc.c1 !== mc.c2 ? c_oAscMergeType.cols : 0) : 0;
	if (null !== mc && (col !== mc.c1 || row !== mc.r1)) {
		/* the real one delegates a covered coordinate to the merge anchor */
		if (undefined === this._getCellTextCache(mc.c1, mc.r1, true)) {
			return this._addCellTextToCache(mc.c1, mc.r1);
		}
		return mc.c2;
	}
	const c = this._getCell(col, row);
	if (null === c) { return col; }

	if (c.isEmptyTextString()) {
		if (c.isNotDefaultFont() && !(mergeType & c_oAscMergeType.rows)) {
			this.emptyFontHits++;
			const cache = this._fetchCellCache(col, row);
			cache.metrics = metricsFor(c.getFont());
			this.rowHeightUpdates++;
			this._updateRowHeight(cache, row);
		}
		return mc ? mc.c2 : col;
	}

	this.hits++;
	const cache = this._fetchCellCache(col, row);
	cache.flags = {
		merged: mc,
		isMerged: function () { return null !== this.merged; },
		getMergeType: function () { return mergeType; },
		wrapText: false
	};
	cache.metrics = metricsFor(c.getFont(), c.stored().text);
	cache.angle = 0;
	cache.cellVA = null;
	cache.cellHA = null;
	cache.textBound = undefined;
	cache.state = null;
	cache.cellType = c.stored().type;
	this.cache.rows[row].columnsWithText[col] = true;
	this.rowHeightUpdates++;
	this._updateRowHeight(cache, row);
	return mc ? mc.c2 : col;
};

/*
 * Builds a View subclass carrying the real methods extracted from one revision of
 * WorksheetView.js, so two revisions can be run side by side.
 */
function viewClassFrom(fns) {
	function V(model) { View.call(this, model); }
	V.prototype = Object.create(View.prototype);
	V.prototype.constructor = V;
	const build = new Function(
		'V', 'Asc', 'History', 'AscCommonExcel', 'c_oAscCanChangeColWidth', 'c_oAscMergeType',
		'CellValueType', 'c_oAscMaxColumnWidth', 'gc_nMaxRow0', 'gc_nMaxCol0', 'window',
		'"use strict";\n' +
		'V.prototype._getCellCache = function' + fns.cellCache + ';\n' +
		'V.prototype._getCellTextCache = function' + fns.textCache + ';\n' +
		'V.prototype._getRowDescender = function' + fns.rowDesc + ';\n' +
		'V.prototype._getRowHeightReal = function' + fns.rowHReal + ';\n' +
		'V.prototype._updateRowHeight = function' + fns.updRowH + ';\n' +
		'V.prototype._autoFitColumnWidth = function' + fns.autoFitCol + ';\n' +
		'V.prototype._autoFitColumnsWidth = function' + fns.autoFitCols + ';\n');
	build(V, Asc, History, AscCommonExcel, c_oAscCanChangeColWidth, c_oAscMergeType,
		CellValueType, c_oAscMaxColumnWidth, gc_nMaxRow0, gc_nMaxCol0, {});
	return V;
}
const View_ = viewClassFrom(FNS);          // the tree as it stands
const View_base = viewClassFrom(FNS_BASE); // BASE_REF, for the side-by-side checks

/*
 * The range autoFitColumnsWidth builds for a whole-column selection:
 * "var r1 = 0, r2 = this.model.getRowsCount() - 1" then
 * "ranges.push(new Asc.Range(sel.c1, r1, sel.c2, r2))".
 */
function selectionRangeForColumns(model, c1, c2) {
	return [new Range(c1, 0, c2, model.getRowsCount() - 1)];
}

function autofitFirstFourColumns(model, Klass) {
	const view = new (Klass || View_)(model);
	view._autoFitColumnsWidth(selectionRangeForColumns(model, 0, 3));
	return view;
}

/* a sheet with `dataRows` rows of text in columns A..D and a row extent of `extent` */
function sheet(dataRows, extent) {
	const m = new Model();
	for (let r = 0; r < dataRows; ++r) {
		for (let c = 0; c < 4; ++c) {
			m.setCell(c, r, 'r' + r + 'c' + c + 'x'.repeat((r + c) % 5));
		}
	}
	if (extent > m.nRowsCount) { m.addRowRecord(extent - 1); }
	return m;
}

let failures = 0;
function section(name, fn) {
	try { fn(); console.log('ok   - ' + name); }
	catch (e) { failures++; console.log('FAIL - ' + name + '\n       ' + e.message); }
}

/* ------------------------------------------------------------------ *
 * 0. harness check - the extracted code really runs and really fits   *
 * ------------------------------------------------------------------ */
section('0. harness: autofit of a dense sheet widens the columns it is given', function () {
	const m = sheet(50, 50);
	const view = autofitFirstFourColumns(m);
	assert.strictEqual(view.hits, 200, 'expected 4 columns x 50 cells with text, got ' + view.hits);
	for (let c = 0; c < 4; ++c) {
		assert.ok(m.bestFit[c] !== undefined, 'column ' + c + ' was never sized');
		assert.ok(m.bestFit[c] > 0, 'column ' + c + ' got a non-positive width');
	}
});

section('0b. harness: the real isNotDefaultFont sees a COLUMN font on a cell with no record', function () {
	const m = new Model();
	m.setColFont(0, new Font('Arial', 48));
	m.addRowRecord(999);
	const big = new CellRef(m, 0, 500);        // no cell record at all
	assert.strictEqual(big.getFont().getSize(), 48, 'the column font did not reach the empty cell');
	assert.strictEqual(big.isNotDefaultFont(), true, 'a column-styled empty cell must report a non-default font');
	const plain = new CellRef(m, 1, 500);      // unstyled column
	assert.strictEqual(plain.isNotDefaultFont(), false, 'an unstyled empty cell must report the default font');
});

section('0c. harness: a ROW font alone does NOT make a cell report a non-default font', function () {
	const m = new Model();
	m.addRowRecord(500, new Font('Arial', 48));  // whole-row formatting
	m.addRowRecord(999);
	const c = new CellRef(m, 0, 500);
	assert.strictEqual(c.getFont().getSize(), 48, 'the row font should reach the cell');
	assert.strictEqual(c.isNotDefaultFont(), false,
		'getCompiledStyle resolves the row xfs and isNotDefaultFont compares against that same row font');
});

/* ------------------------------------------------------------------ *
 * 1. behaviour - the sizes autofit produces must not move             *
 * ------------------------------------------------------------------ */
function expectedChars(model, col, dataRows) {
	let maxPx = 0;
	for (let r = 0; r < dataRows; ++r) {
		const c = model.cells[col] && model.cells[col][r];
		if (c && c.text) { maxPx = Math.max(maxPx, c.text.length * GLYPH_PX); }
	}
	if (maxPx <= 0) { return null; }
	const pad = 2 * 2 + 1;
	return Math.min((maxPx + pad) / GLYPH_PX, c_oAscMaxColumnWidth);
}

section('1. behaviour: autofit produces the arithmetically correct column width', function () {
	const m = sheet(50, 50);
	autofitFirstFourColumns(m);
	for (let c = 0; c < 4; ++c) {
		assert.strictEqual(m.bestFit[c], expectedChars(m, c, 50),
			'column ' + c + ' width changed: got ' + m.bestFit[c] + ', want ' + expectedChars(m, c, 50));
	}
});

section('1b. behaviour: a padded row extent does not change the sizes', function () {
	const tight = sheet(120, 120);
	const padded = sheet(120, 40000);
	autofitFirstFourColumns(tight);
	autofitFirstFourColumns(padded);
	for (let c = 0; c < 4; ++c) {
		assert.strictEqual(padded.bestFit[c], tight.bestFit[c],
			'column ' + c + ': padded sheet sized to ' + padded.bestFit[c] +
			' but the same data in a tight sheet sized to ' + tight.bestFit[c]);
		assert.strictEqual(tight.bestFit[c], expectedChars(tight, c, 120), 'column ' + c + ' width is wrong');
	}
});

section('1c. behaviour: a column with a gap still measures the cells below the gap', function () {
	const m = new Model();
	m.setCell(0, 0, 'short');
	m.setCell(0, 900, 'a much much longer value');   // far below the gap
	m.addRowRecord(40000);
	const view = new View_(m);
	view._autoFitColumnsWidth([new Range(0, 0, 0, m.getRowsCount() - 1)]);
	assert.strictEqual(view.hits, 2, 'both cells must be measured, measured ' + view.hits);
	assert.strictEqual(m.bestFit[0], expectedChars(m, 0, 901), 'wrong width for a column with a gap');
});

/* ------------------------------------------------------------------ *
 * 2. the defect - how many rows the scan touches                      *
 * ------------------------------------------------------------------ */
section('2. scan is bounded by the cells, not by the sheet row extent', function () {
	const DATA_ROWS = 100;
	const m = sheet(DATA_ROWS, gc_nMaxRow0 + 1);   // rows formatted to the bottom of the sheet
	assert.strictEqual(m.getRowsCount(), 1048576, 'the stub sheet should report a full row extent');

	const view = autofitFirstFourColumns(m);
	const cells = 4 * DATA_ROWS;

	console.log('       row extent           : ' + m.getRowsCount());
	console.log('       cells with content   : ' + cells);
	console.log('       _addCellTextToCache  : ' + view.visits);
	console.log('       wasted visits        : ' + (view.visits - view.hits));

	assert.ok(view.visits <= cells,
		'autofit of 4 columns holding ' + cells + ' cells called _addCellTextToCache ' +
		view.visits + ' times (' + (view.visits / cells).toFixed(0) + 'x the work); ' +
		'the loop is walking the sheet row extent instead of the column cell extent');
});

section('2b. scan cost does not grow with the empty row extent', function () {
	const counts = [10000, 100000, gc_nMaxRow0 + 1].map(function (extent) {
		return { extent: extent, visits: autofitFirstFourColumns(sheet(100, extent)).visits };
	});
	counts.forEach(function (c) {
		console.log('       extent ' + String(c.extent).padStart(8) + ' -> visits ' + c.visits);
	});
	assert.strictEqual(counts[0].visits, counts[2].visits,
		'visits grew from ' + counts[0].visits + ' to ' + counts[2].visits +
		' when only the empty row extent grew (100x more empty rows, same 400 cells)');
});

/* ------------------------------------------------------------------ *
 * 3. no behaviour change in COLUMN WIDTH                              *
 * ------------------------------------------------------------------ *
 * Both revisions of the real _autoFitColumnWidth are extracted into this one
 * process and run over the same corpus. Every column must come out the same
 * width, and every cell BASE_REF measured must still be measured.
 * Extents are kept at 40000 so the baseline side stays runnable; sections 2/2b
 * already carry the full 1048576 count.
 */
const EXTENT = 40000;
const corpus = [
	['dense text, 200 rows', function () { return sheet(200, 200); }],
	['dense text, 200 rows, padded extent', function () { return sheet(200, EXTENT); }],
	['numeric cells', function () {
		const m = new Model();
		for (let r = 0; r < 150; ++r) {
			for (let c = 0; c < 4; ++c) { m.setCell(c, r, String(r * 1000 + c) + '.' + r, CellValueType.Number); }
		}
		m.addRowRecord(EXTENT - 1);
		return m;
	}],
	['sparse cells with big gaps', function () {
		const m = new Model();
		[0, 5, 77, 199, 4000].forEach(function (r) {
			for (let c = 0; c < 4; ++c) { m.setCell(c, r, 'v'.repeat(3 + (r % 11) + c)); }
		});
		m.addRowRecord(EXTENT - 1);
		return m;
	}],
	['column data starting well below row 0', function () {
		const m = new Model();
		for (let r = 500; r < 560; ++r) {
			for (let c = 0; c < 4; ++c) { m.setCell(c, r, 'below-' + r + '-' + c); }
		}
		m.addRowRecord(EXTENT - 1);
		return m;
	}],
	['a merge spanning rows only, inside column A', function () {
		const m = sheet(40, 40);
		m.addMerge(0, 60, 0, 80, 'a tall merged label that is much wider than the rest');
		m.addRowRecord(EXTENT - 1);
		return m;
	}],
	['a merge spanning columns', function () {
		const m = sheet(40, 40);
		m.addMerge(0, 60, 2, 60, 'a wide merged banner nobody should autofit against');
		m.addRowRecord(EXTENT - 1);
		return m;
	}],
	['one of the four columns holds nothing', function () {
		const m = new Model();
		for (let r = 0; r < 120; ++r) {
			for (const c of [0, 1, 3]) { m.setCell(c, r, 'c' + c + '-' + 'y'.repeat(r % 9)); }
		}
		m.addRowRecord(EXTENT - 1);
		return m;
	}],
	['completely empty sheet with a padded extent', function () {
		const m = new Model();
		m.addRowRecord(EXTENT - 1);
		m.nColsCount = 4;
		return m;
	}]
];

section('3. no behaviour change: same column widths as ' + BASE_REF, function () {
	for (const [name, make] of corpus) {
		const mNew = make(), mOld = make();
		const vNew = autofitFirstFourColumns(mNew, View_);
		const vOld = autofitFirstFourColumns(mOld, View_base);

		assert.deepStrictEqual(mNew.bestFit, mOld.bestFit,
			name + ': setColBestFit widths differ\n       now  ' + JSON.stringify(mNew.bestFit) +
			'\n       ' + BASE_REF + ' ' + JSON.stringify(mOld.bestFit));
		assert.deepStrictEqual(Array.from(mNew.colWidthChars), Array.from(mOld.colWidthChars),
			name + ': resulting column widths differ');
		assert.strictEqual(vNew.hits, vOld.hits,
			name + ': measured ' + vNew.hits + ' cells but ' + BASE_REF + ' measured ' + vOld.hits);
		console.log('       ' + name.padEnd(42) + ' widths ' + JSON.stringify(mNew.bestFit) +
			'  cells measured ' + vNew.hits + '  rows touched ' + vNew.visits + ' (was ' + vOld.visits + ')');
	}
});

/* ------------------------------------------------------------------ *
 * 4. ROW HEIGHTS - where the one deliberate difference lives          *
 * ------------------------------------------------------------------ *
 * The empty-cell branch of _addCellTextToCache calls _updateRowHeight when
 * isNotDefaultFont() is true, and _updateRowHeight writes through to
 * model.setRowHeight, which materialises a Row record. This section reports the
 * row heights and the Row records both revisions leave behind.
 */
const BIG = new Font('Arial', 48);
const heightCorpus = [
	['no column styling at all', function () {
		const m = sheet(40, EXTENT);
		return m;
	}],
	['whole-sheet ROW formatting, 48pt, no column styling', function () {
		const m = sheet(40, 40);
		for (let r = 0; r < EXTENT; r += 997) { m.addRowRecord(r, BIG); }
		m.addRowRecord(EXTENT - 1);
		return m;
	}],
	['column A styled 48pt, data only in rows 0..39', function () {
		const m = sheet(40, 40);
		m.setColFont(0, BIG);
		m.addRowRecord(EXTENT - 1);
		return m;
	}],
	['column A styled 48pt, cells at rows 0..39 and 20000', function () {
		const m = sheet(40, 40);
		m.setColFont(0, BIG);
		for (let c = 0; c < 4; ++c) { m.setCell(c, 20000, 'tail-' + c); }
		m.addRowRecord(EXTENT - 1);
		return m;
	}],
	['column A styled 48pt, some rows custom-height', function () {
		const m = sheet(40, 40);
		m.setColFont(0, BIG);
		[100, 5000, 30000].forEach(function (r) { m.setRowCustomHeight(r, 33); });
		m.addRowRecord(EXTENT - 1);
		return m;
	}],
	['all four columns styled 48pt', function () {
		const m = sheet(40, 40);
		for (let c = 0; c < 4; ++c) { m.setColFont(c, BIG); }
		m.addRowRecord(EXTENT - 1);
		return m;
	}]
];

const heightReport = [];
section('4. row heights: measured against ' + BASE_REF + ', differences reported not assumed', function () {
	for (const [name, make] of heightCorpus) {
		const mNew = make(), mOld = make();
		const vNew = autofitFirstFourColumns(mNew, View_);
		const vOld = autofitFirstFourColumns(mOld, View_base);

		const rowsNew = Object.keys(mNew.rowHeights).map(Number).sort(function (a, b) { return a - b; });
		const rowsOld = Object.keys(mOld.rowHeights).map(Number).sort(function (a, b) { return a - b; });
		const onlyOld = rowsOld.filter(function (r) { return mNew.rowHeights[r] !== mOld.rowHeights[r]; });
		const onlyNew = rowsNew.filter(function (r) { return mNew.rowHeights[r] !== mOld.rowHeights[r]; });

		heightReport.push({
			name: name,
			rowsSizedNow: rowsNew.length, rowsSizedBase: rowsOld.length,
			recordsNow: mNew.rowRecordsMaterialised, recordsBase: mOld.rowRecordsMaterialised,
			differing: onlyOld.length, grownOnlyByBase: onlyOld.length, grownOnlyByNow: onlyNew.length,
			sampleBase: onlyOld.slice(0, 3).map(function (r) {
				return r + ':' + (mOld.rowHeights[r]) + 'pt vs ' + (mNew.rowHeights[r] === undefined ? 'default' : mNew.rowHeights[r]);
			})
		});
		console.log('       ' + name.padEnd(48) +
			' rows sized ' + String(rowsNew.length).padStart(6) + ' (was ' + String(rowsOld.length).padStart(6) + ')' +
			'  Row records ' + String(mNew.rowRecordsMaterialised).padStart(6) + ' (was ' + String(mOld.rowRecordsMaterialised).padStart(6) + ')');
		if (onlyOld.length) {
			console.log('         differs on ' + onlyOld.length + ' row(s), e.g. ' + heightReport[heightReport.length - 1].sampleBase.join(', '));
		}
	}

	/* the claims this section is allowed to make */
	const byName = {};
	heightReport.forEach(function (r) { byName[r.name] = r; });

	assert.strictEqual(byName['no column styling at all'].differing, 0,
		'with no column font, row heights must be identical');
	assert.strictEqual(byName['whole-sheet ROW formatting, 48pt, no column styling'].differing, 0,
		'row-only formatting must not change row heights either way (isNotDefaultFont is false there)');
	assert.strictEqual(byName['all four columns styled 48pt'].grownOnlyByNow, 0,
		'the fix must never grow a row that ' + BASE_REF + ' left alone');
	heightReport.forEach(function (r) {
		assert.ok(r.recordsNow <= r.recordsBase,
			r.name + ': the fix materialised MORE Row records (' + r.recordsNow + ') than ' + BASE_REF + ' (' + r.recordsBase + ')');
	});
});

section('4b. row heights: rows inside the column cell extent are still sized identically', function () {
	/* column A styled 48pt with cells in rows 0..39: every row the fix still visits
	 * must come out at exactly the height BASE_REF gave it. */
	const make = function () {
		const m = sheet(40, 40);
		m.setColFont(0, BIG);
		m.addRowRecord(EXTENT - 1);
		return m;
	};
	const mNew = make(), mOld = make();
	autofitFirstFourColumns(mNew, View_);
	autofitFirstFourColumns(mOld, View_base);
	for (let r = 0; r < 40; ++r) {
		assert.strictEqual(mNew.rowHeights[r], mOld.rowHeights[r],
			'row ' + r + ' is inside the data and must keep its height: ' +
			mNew.rowHeights[r] + ' vs ' + mOld.rowHeights[r]);
	}
	assert.ok(mNew.rowHeights[0] > DEFAULT_ROW_HEIGHT_PT,
		'the 48pt column should have grown row 0 in both trees, got ' + mNew.rowHeights[0]);
});

process.exitCode = failures ? 1 : 0;
console.log(failures ? '\n' + failures + ' section(s) failed' : '\nall sections passed');
