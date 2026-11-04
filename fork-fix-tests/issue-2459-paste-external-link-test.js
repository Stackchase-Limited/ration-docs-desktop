/*
 * #2459 - copying =VLOOKUP(B11,Tabelle2!$A$1:$B$5,2,FALSE) from workbook A
 * and pasting it into a workbook B that has no sheet Tabelle2 kept
 * "Tabelle2!..." as text, and the cell showed #NAME?. ms turns the reference
 * into an external reference to the source file - [Src.xlsx]Tabelle2!$A$1:$B$5,
 * written as an externalLink part - so the value can be updated from the
 * source and the link survives saving.
 *
 * Fix, cell/view/WorksheetView.js:
 * - _setPastedDataByCurrentRange: a pasted formula that does not parse here
 *   goes through linkUnparsedFormula, which finds its Sheet!ref references to
 *   sheets missing in this workbook, asks for the external reference to the
 *   source holding those sheets and rewrites them as [n]Sheet!ref; the
 *   formula then takes the normal paste path (relative references move).
 * - _pasteFromBinary: _getPastedExternalLinkIndex finds or adds that external
 *   reference once per paste, under the same conditions as "Paste link"
 *   (isAllowPasteLink + getPastedLinkInfo; not for the same document, not
 *   without a source path in the desktop), adds the missing sheet names and
 *   keeps the copied cells as cached values when the sheet is the copied one.
 *
 * This extracts the real _setPastedDataByCurrentRange and runs it against a
 * small parserFormula model of A1 / Sheet!A1 / [n]Sheet!A1 references (as in
 * issue-2459-paste-formula-offset-test.js), and extracts the real
 * _getPastedExternalLinkIndex, getPastedLinkInfo, isAllowPasteLink and
 * buildRelativePath and runs them with a stubbed desktop host, workbook and
 * ExternalReference.
 *
 * NOT claimed here: the real parser, the external reference classes and the
 * xlsx writer are not run. They were run headless in Chromium against the
 * built sdk (copy A10:I26 from Src.xlsx, paste into Dst.xlsx): the formula
 * reads '[Src.xlsx]Tabelle2'!$A$1:$B$5, one ExternalReference "Src.xlsx",
 * undo/redo remove/restore it, a second paste reuses it; x2t writes
 * xl/externalLinks/externalLink1.xml (+ rels Target="Src.xlsx") and the file
 * reopens with the link. Values from sheets of the source that were not
 * copied are not in the clipboard: they show after the link is updated
 * (needs the desktop host to read the source file - not tested).
 *
 * RD_REPO overrides the sdkjs checkout. BASELINE=1 reads the parent of the fix
 * (BASE_REF), where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '48e65355ef^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function extract(source, marker) {
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(source, at);
}
const fnExpr = src => 'function' + src.slice(src.indexOf('('));

const wsv = read('cell/view/WorksheetView.js');

/* ---------- a model of references, standing in for parserFormula ---------- */
const cElementType = { cell: 'cell', cellsRange: 'cellsRange', cell3D: 'cell3D', cellsRange3D: 'cellsRange3D', name: 'name' };
const RX = /((?:'[^']+'|(?:\[\d+\])?[A-Za-z_][\w.]*)!)?(\$?)([A-Z]{1,3})(\$?)(\d+)(?::(\$?)([A-Z]{1,3})(\$?)(\d+))?/g;
const colNum = s => [...s].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);
const colStr = n => { let s = ''; for (; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; };

function Ref(sheet, m) {
	this.sheet = sheet;
	this.p = [{ ac: !!m[2], c: colNum(m[3]), ar: !!m[4], r: +m[5] }];
	if (m[7]) this.p.push({ ac: !!m[6], c: colNum(m[7]), ar: !!m[8], r: +m[9] });
	this.type = sheet ? (this.p.length > 1 ? cElementType.cellsRange3D : cElementType.cell3D)
		: (this.p.length > 1 ? cElementType.cellsRange : cElementType.cell);
}
Ref.prototype.shift = function (offset) {
	const p = this.p.map(x => Object.assign({}, x, { r: x.ar ? x.r : x.r + offset.row, c: x.ac ? x.c : x.c + offset.col }));
	if (p.some(x => x.r < 1 || x.c < 1)) return false;
	this.p = p;
	return true;
};
Ref.prototype.toString = function () {
	return (this.sheet ? this.sheet + '!' : '') + this.p.map(x => (x.ac ? '$' : '') + colStr(x.c) + (x.ar ? '$' : '') + x.r).join(':');
};

/* sheets: names in this workbook; external: Map index -> Set of sheet names of that external reference */
function makeParser(sheets, external) {
	const known = sheet => {
		const s = sheet.replace(/^'|'$/g, '');
		const ext = /^\[(\d+)\](.*)$/.exec(s);
		return ext ? !!(external.get(+ext[1]) && external.get(+ext[1]).has(ext[2])) : sheets.has(s);
	};
	function parserFormula(formula) { this.Formula = formula; this.outStack = []; this.spans = []; this.isParsed = false; }
	parserFormula.prototype.parse = function (local, digitDelim, parseResult, ignoreErrors) {
		RX.lastIndex = 0;
		let m;
		while ((m = RX.exec(this.Formula))) {
			const sheet = m[1] ? m[1].slice(0, -1) : null;
			let elem;
			if (sheet && !known(sheet)) {
				if (!ignoreErrors) { this.outStack = []; return false; }
				elem = { type: cElementType.name };
			} else {
				elem = new Ref(sheet, m);
			}
			const span = { start: m.index, end: m.index + m[0].length, index: this.outStack.length, oper: elem };
			parseResult && parseResult.refPos && parseResult.refPos.push(span);
			this.spans.push(span);
			this.outStack.push(elem);
		}
		return this.isParsed = true;
	};
	parserFormula.prototype._changeOffsetElem = function (elem, container, index, offset) {
		if (elem instanceof Ref && !elem.shift(offset)) container[index] = { type: 'error', toString() { return '#REF!'; } };
		return elem;
	};
	parserFormula.prototype.changeOffset = function (offset) {
		this.spans.forEach(s => this._changeOffsetElem(s.oper, this.outStack, s.index, offset));
		return this;
	};
	parserFormula.prototype.assemble = function () {
		let out = '', last = 0;
		this.spans.forEach(s => { out += this.Formula.slice(last, s.start) + this.outStack[s.index].toString(); last = s.end; });
		return out + this.Formula.slice(last);
	};
	parserFormula.prototype.getArrayFormulaRef = function () { return null; };
	return parserFormula;
}

/* ---------- part 1: the pasted formula (real _setPastedDataByCurrentRange) ---------- */
{
	const helperSrc = extract(wsv, 'CCellPasteHelper.prototype._setPastedDataByCurrentRange = function');
	assert.ok(helperSrc.includes('calculateValueAndBinaryFormula'), 'extracted the wrong function');

	/* paste one copied cell (sId, formula) at row/col (0-based) into a workbook holding Sheet1 only;
	   linkIndex: what the external reference lookup answers (null: the source can't be linked) */
	function paste(sId, formula, toRow, toCol, linkIndex) {
		const external = new Map();
		const asked = [];
		const parserFormula = makeParser(new Set(['Sheet1']), external);
		const AscCommonExcel = {
			parserFormula, cElementType,
			ParseResult: function (refPos) { this.refPos = refPos; },
			executeInR1C1Mode: (mode, fn) => fn(),
			UndoRedoData_CellValueData: function (f, value) { this.formula = f; this.value = value; },
			CCellValue: function (o) { Object.assign(this, o); },
		};
		const AscCommon = {
			CellBase: function (row, col) { this.row = row; this.col = col; },
			CellAddress: function (id) { const m = /^([A-Z]+)(\d+)$/.exec(id); this.col = colNum(m[1]); this.row = +m[2]; },
			FormulaSeparators: { digitSeparatorDef: '.', digitSeparator: '.' },
		};
		const window = { Asc: { c_oSpecialPasteOperation: { none: 0 } }, AscCommon: { g_specialPasteHelper: {} } };
		const CellValueType = { Number: 0, String: 1 };
		const setPasted = new Function('AscCommonExcel', 'AscCommon', 'window', 'CellValueType', 'History', 'Asc',
			'"use strict"; return ' + fnExpr(helperSrc))(AscCommonExcel, AscCommon, window, CellValueType, {}, { c_oSpecialPasteProps: {} });

		const written = {};
		const range = new Proxy({ bbox: { r1: toRow, c1: toCol, r2: toRow, c2: toCol } }, {
			get(t, k) {
				if (k in t) return t[k];
				if (k === 'setValueData') return v => { written.formula = v.formula; };
				return () => null;
			},
		});
		const newVal = {
			getValueData: () => new AscCommonExcel.UndoRedoData_CellValueData(formula, { type: CellValueType.Number, number: 0 }),
			getFormula: () => formula, getName: () => sId, isNullText: () => false, getValue: () => '0', getType: () => CellValueType.Number,
		};
		const arrFormula = [];
		const formulaProps = {
			fromBinary: true, newVal, arrFormula, tablesMap: null, isOneMerge: false,
			cell: { formulaParsed: null, getFormulaParsed: () => ({ ca: false }), getNumberValue: () => 0 },
			fromRange: null, activeCellsPasteFragment: null, transposeRange: null,
			/* stands in for _getPastedExternalLinkIndex (part 2) */
			getPastedExternalLinkIndex(sheetNames) {
				asked.push(sheetNames.slice());
				if (linkIndex) external.set(linkIndex, new Set(sheetNames));
				return linkIndex;
			},
		};
		const specialPasteProps = { formula: true, val: true, cellStyle: true, operation: 0 };
		const wsModel = { workbook: { getWorksheetByName: n => (n === 'Sheet1' ? {} : null) } };
		setPasted.call({ ws: { model: wsModel } }, range, { colsWidth: {} }, formulaProps, specialPasteProps);
		return { f: arrFormula.length ? arrFormula[0].val.slice(1) : written.formula, asked };
	}

	/* unchanged on both trees: a formula that parses here */
	assert.strictEqual(paste('G11', 'B11+Sheet1!B11', 3, 6, 1).f, 'B4+Sheet1!B4');

	/* the reporter: the lookup table is on a sheet of the source that this workbook does not have */
	const r = paste('G11', 'IFERROR(VLOOKUP(B11,Tabelle2!$A$1:$B$5,2,FALSE),0)', 3, 6, 1);
	assert.strictEqual(r.f, 'IFERROR(VLOOKUP(B4,[1]Tabelle2!$A$1:$B$5,2,FALSE),0)',
		'a reference to a sheet missing here must become a reference to the source workbook, got ' + JSON.stringify(r.f));
	assert.deepStrictEqual(r.asked, [['Tabelle2']]);

	/* quoted names, several sheets, a relative part that moves */
	const q = paste('G11', "B11+'My Data'!B11+SUM(Tabelle2!$A$1:$A$3,'My Data'!$C$1)", 3, 7, 2);
	assert.strictEqual(q.f, "C4+'[2]My Data'!C4+SUM([2]Tabelle2!$A$1:$A$3,'[2]My Data'!$C$1)");
	assert.deepStrictEqual(q.asked, [['My Data', 'Tabelle2']]);

	/* the source can't be linked (same document, unsaved file): as before, text with its relative parts moved */
	assert.strictEqual(paste('G11', 'IFERROR(VLOOKUP(B11,Tabelle2!$A$1:$B$5,2,FALSE),0)', 3, 6, null).f,
		'IFERROR(VLOOKUP(B4,Tabelle2!$A$1:$B$5,2,FALSE),0)');
}

/* ---------- part 2: the external reference to the source (real _getPastedExternalLinkIndex) ---------- */
{
	const getIndexSrc = extract(wsv, 'var _getPastedExternalLinkIndex = function');
	const linkInfoSrc = extract(wsv, 'CCellPasteHelper.prototype.getPastedLinkInfo = function');
	const allowSrc = extract(wsv, 'function isAllowPasteLink(pastedWb)');
	const relPathSrc = extract(wsv, 'function buildRelativePath(fromPath, thisPath)');

	function ExternalReference() { this.Id = null; this.referenceData = null; this.SheetNames = []; this.cached = {}; }
	ExternalReference.prototype.getSheetByName = function (n) { const i = this.SheetNames.indexOf(n); return i < 0 ? null : i; };
	ExternalReference.prototype.addSheetName = function (n) { this.SheetNames.push(n); };
	ExternalReference.prototype.initWorksheetFromSheetDataSet = function () {};
	ExternalReference.prototype.updateSheetData = function (n, sheet, ranges) {
		if (this.getSheetByName(n) === null) this.addSheetName(n);
		this.cached[n] = { sheet, ranges };
	};

	/* a paste of a fragment copied from `src` into Dst.xlsx; existing: Ids of external references already in Dst */
	function setup(src, existing) {
		const log = [];
		const wb = {
			aWorksheets: [{ sName: 'Sheet1' }],
			externalReferences: (existing || []).map(id => Object.assign(new ExternalReference(), { Id: id })),
			addExternalReferences(arr) { log.push('add'); this.externalReferences.push(...arr); },
			changeExternalReference(i, eR) { log.push('change ' + i); this.externalReferences[i - 1] = eR; },
			getExternalLinkIndexByName(n) { const i = this.externalReferences.findIndex(e => e.Id === n); return i < 0 ? null : i + 1; },
			getExternalReferenceByReferenceData() { return null; },
		};
		const ws = { model: { sName: 'Sheet1', workbook: wb } };
		const window = {
			Asc: { editor: { DocInfo: { Id: 'dst-doc' } } },
			AscDesktopEditor: { IsLocalFile: () => true, LocalFileGetSourcePath: () => '/Users/x/Docs/Dst.xlsx', LocalFileGetSaved: () => true },
		};
		const AscCommonExcel = {
			ExternalReference,
			g_clipboardExcel: { pasteProcessor: { _checkPastedInOriginalDoc: (pwb) => pwb.Core.identifier === window.Asc.editor.DocInfo.Id } },
		};
		const pastedWs = { sName: 'Tabelle1' };
		const val = { workbook: { aWorksheets: [pastedWs], Core: { identifier: src.id, contentStatus: src.path, category: null, title: 'Src.xlsx' } } };
		const helper = new Function('window', 'AscCommonExcel', 'ws',
			'"use strict";\n' + relPathSrc + '\nreturn ' + fnExpr(linkInfoSrc))(window, AscCommonExcel, ws);
		const t = { ws, getPastedLinkInfo: helper };
		const fragment = { r1: 9, c1: 0, r2: 25, c2: 8 };
		const made = new Function('window', 'AscCommonExcel', 'val', 't', 'ws', 'activeCellsPasteFragment',
			'"use strict";\nvar isLinkToOtherWorkbook = false, pastedExternalLink;\n' + allowSrc + '\n' + getIndexSrc +
			';\nreturn {get: _getPastedExternalLinkIndex, linked: function () { return isLinkToOtherWorkbook; }};')(
			window, AscCommonExcel, val, t, ws, fragment);
		return { get: made.get, linked: made.linked, wb, log, pastedWs, fragment };
	}

	/* another saved file next to this one: one external reference "Src.xlsx", reused by every formula of the paste */
	let p = setup({ id: 'src-doc', path: '/Users/x/Docs/Src.xlsx' });
	assert.strictEqual(p.get(['Tabelle2']), 1);
	assert.strictEqual(p.get(['Tabelle2']), 1);
	assert.strictEqual(p.get(['Tabelle2', 'Tabelle1']), 1);
	assert.strictEqual(p.wb.externalReferences.length, 1);
	const eR = p.wb.externalReferences[0];
	assert.strictEqual(eR.Id, 'Src.xlsx', 'the desktop link is the source path relative to this file');
	assert.deepStrictEqual(eR.SheetNames, ['Tabelle2', 'Tabelle1']);
	assert.deepStrictEqual(p.log, ['add', 'change 1'], 'added once, changed once when a sheet was added');
	assert.ok(eR.cached.Tabelle1 && eR.cached.Tabelle1.sheet === p.pastedWs && eR.cached.Tabelle1.ranges[0] === p.fragment,
		'the copied sheet keeps the copied cells as cached values');
	assert.ok(p.linked(), 'the "external data added" notice must be raised, as after a paste link');

	/* a link to that file already exists here: it is reused */
	p = setup({ id: 'src-doc', path: '/Users/x/Docs/Src.xlsx' }, ['Other.xlsx', 'Src.xlsx']);
	assert.strictEqual(p.get(['Tabelle2']), 2);
	assert.deepStrictEqual(p.log, ['change 2']);
	assert.strictEqual(p.wb.externalReferences.length, 2);

	/* same document (e.g. its sheet was deleted meanwhile): no link to itself */
	p = setup({ id: 'dst-doc', path: '/Users/x/Docs/Dst.xlsx' });
	assert.strictEqual(p.get(['Tabelle2']), null);
	assert.strictEqual(p.wb.externalReferences.length, 0);

	/* the source was never saved, so it has no path to link to: unchanged behaviour */
	p = setup({ id: 'src-doc', path: '' });
	assert.strictEqual(p.get(['Tabelle2']), null);
	assert.strictEqual(p.wb.externalReferences.length, 0);
	assert.ok(!p.linked());
}

console.log('ok - formulas pasted from another workbook refer to its missing sheets through one external reference');
