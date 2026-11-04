/*
 * #2459 - a copied range of "=VLOOKUP(B11, Other!$A$1:$B$5, 2, 0)" formulas,
 * pasted at row 4, came out as VLOOKUP(B11, ...) - or, inside one workbook,
 * as VLOOKUP(B4, ...) in every pasted row. In ms the reference moves with the
 * cell on paste (B4, B5, B6, ...), whatever else the formula refers to.
 *
 * Two independent causes, both reproduced headless with the real cell sdk in
 * Chromium (copy G11:G13, paste at K4 / into a new workbook):
 *
 * 1. Clipboard read, cell/model/Serialize.js InitOpenManager.setFormulaOpen.
 *    The copied fragment is read into a temporary workbook holding only the
 *    copied sheet, so a formula referring to another sheet fails to parse
 *    there. Consecutive rows were still folded into one shared formula
 *    (compareFormula only checks the references found before the parse
 *    stopped), and a shared formula whose master never parsed cannot be
 *    re-offset: getFormula() of every row below returned the master's text.
 *    Fix: a formula that failed to parse does not become a shared master.
 *
 * 2. Paste, cell/view/WorksheetView.js _setPastedDataByCurrentRange. When the
 *    formula does not parse in the destination (the other sheet does not
 *    exist there - the reporter pasted into a new workbook), the original
 *    text was written as it was, relative references included. Fix: shift
 *    the plain cell references of such a formula (also the cell part of a
 *    Sheet!A1 whose sheet is missing) and keep the rest of the text as is.
 *
 * This extracts the real setFormulaOpen + OpenColumnFormula, and the real
 * _setPastedDataByCurrentRange, and runs them against a small parserFormula
 * model of A1 references (unknown sheet -> parse fails, or with ignoreErrors
 * becomes a name spanning the whole Sheet!ref, as the real parser does).
 *
 * NOT claimed: ms additionally turns the missing-sheet reference into an
 * external link to the source file ([Book1.xlsx]Other!$A$1:$B$5) and keeps
 * its values; here the reference stays Other!$A$1:$B$5 and shows #NAME?
 * until such a sheet exists. The parser itself is modelled, not run.
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
const BASE_REF = process.env.BASE_REF || '63a5856996^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match from the first '{' at or after `from`, returning source through its close. */
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

/* ---------- a model of A1 references, standing in for parserFormula ---------- */
const cElementType = { cell: 'cell', cellsRange: 'cellsRange', cell3D: 'cell3D', cellsRange3D: 'cellsRange3D', name: 'name' };
const RX = /((?:'[^']+'|[A-Za-z_][\w.]*)!)?(\$?)([A-Z]{1,3})(\$?)(\d+)(?::(\$?)([A-Z]{1,3})(\$?)(\d+))?/g;
const colNum = s => [...s].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);
const colStr = n => { let s = ''; for (; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; };
const MAX_ROW = 1048576, MAX_COL = 16384;

function Ref(sheet, m) {
	this.sheet = sheet;
	this.p = [{ ac: !!m[2], c: colNum(m[3]), ar: !!m[4], r: +m[5] }];
	if (m[7]) this.p.push({ ac: !!m[6], c: colNum(m[7]), ar: !!m[8], r: +m[9] });
	this.type = sheet ? (this.p.length > 1 ? cElementType.cellsRange3D : cElementType.cell3D)
		: (this.p.length > 1 ? cElementType.cellsRange : cElementType.cell);
}
Ref.prototype.shift = function (offset) {
	const p = this.p.map(x => Object.assign({}, x, { r: x.ar ? x.r : x.r + offset.row, c: x.ac ? x.c : x.c + offset.col }));
	if (p.some(x => x.r < 1 || x.c < 1 || x.r > MAX_ROW || x.c > MAX_COL)) return false;
	this.p = p;
	return true;
};
Ref.prototype.toString = function () {
	return (this.sheet ? this.sheet + '!' : '') +
		this.p.map(x => (x.ac ? '$' : '') + colStr(x.c) + (x.ar ? '$' : '') + x.r).join(':');
};

function makeParser(sheets) {
	function parserFormula(formula, parent, ws) { this.Formula = formula; this.outStack = []; this.spans = []; this.isParsed = false; }
	parserFormula.prototype.parse = function (local, digitDelim, parseResult, ignoreErrors) {
		RX.lastIndex = 0;
		let m;
		while ((m = RX.exec(this.Formula))) {
			const sheet = m[1] ? m[1].slice(0, -1) : null;
			let elem;
			if (sheet && !sheets.has(sheet.replace(/^'|'$/g, ''))) {
				if (!ignoreErrors) { this.outStack = []; return false; }
				elem = { type: cElementType.name, toString() { return m[0].slice(m[1].length).toUpperCase(); } };
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

/* ---------- part 1: reading the clipboard workbook (Serialize.js) ---------- */
{
	const ser = read('cell/model/Serialize.js');
	const setFormulaOpenSrc = extract(ser, 'InitOpenManager.prototype.setFormulaOpen = function');
	const openColumnFormulaSrc = extract(ser, 'function OpenColumnFormula(');
	const ecellAt = ser.indexOf('var ECellFormulaType =');
	const ecellSrc = ser.slice(ecellAt, ser.indexOf(';', ecellAt) + 1);

	/* the clipboard workbook holds only the copied sheet */
	const parserFormula = makeParser(new Set(['Sheet1']));
	parserFormula.prototype.setShared = function (ref, base) { this.shared = { ref, base }; };
	parserFormula.prototype.getShared = function () { return this.shared || null; };
	parserFormula.prototype.getListenerId = function () { return 1; };
	parserFormula.prototype.buildDependencies = function () {};
	/* structure-only comparison: same text once the earlier formula's rows are moved by offsetRow */
	const compareFormula = (f1, refPos, f2, offsetRow) => f1.replace(/([A-Z]+)(\d+)/g, (m, c, r) => c + (+r + offsetRow)) === f2;
	const AscCommonExcel = {
		ParseResult: function (refPos) { this.refPos = refPos; },
		CCellWithFormula: function (ws, nRow, nCol) { this.ws = ws; this.nRow = nRow; this.nCol = nCol; },
		parserFormula, compareFormula,
	};
	const Asc = { Range: function (c1, r1, c2, r2) { Object.assign(this, { c1, r1, c2, r2 }); this.union3 = function (c, r) { this.r2 = Math.max(this.r2, r); }; },
		c_oAscError: { ID: { FrmlMaxReference: -1 } } };
	const AscCommon = { c_oAscMaxFormulaLength: 8192 };

	const setFormulaOpen = new Function('AscCommonExcel', 'Asc', 'AscCommon',
		'"use strict";\n' + ecellSrc + '\n' + openColumnFormulaSrc + '\nreturn function' +
		setFormulaOpenSrc.slice(setFormulaOpenSrc.indexOf('('))
	)(AscCommonExcel, Asc, AscCommon);

	/* read three consecutive rows of one column, as the binary reader does, and give back each cell's formula text */
	function readColumn(texts) {
		const ws = { workbook: { openErrors: [], dependencyFormulas: { addToChangedCell() {} } }, dynamicArrayManager: null };
		const tmp = { prevFormulas: {}, sharedFormulas: {}, siFormulas: {}, bNoBuildDep: true, formulaArray: [], ws };
		const cells = texts.map((v, i) => {
			const cell = { ws, nRow: 10 + i, nCol: 6, setFormulaInternal(p) { this.formulaParsed = p; }, isNullTextString() { return false; } };
			setFormulaOpen.call({ copyPasteObj: { isCopyPaste: true } }, Object.assign(tmp, { cell, formula: { si: null, v, t: null, ref: null, ca: false } }));
			return cell;
		});
		/* Cell.getFormula of a shared cell: the master's parsed formula moved to this row and assembled */
		return cells.map(cell => {
			const p = cell.formulaParsed, sh = p.getShared();
			/* a formula that never parsed can only give back its own text (the master's, for a shared one) */
			if (!sh || cell.nRow === sh.base.nRow || !p.isParsed) return p.Formula;
			const q = new parserFormula(p.Formula); q.parse(); q.changeOffset({ row: cell.nRow - sh.base.nRow, col: 0 }); return q.assemble();
		}).map((f, i) => ({ f, sharedWithFirst: cells[i].formulaParsed === cells[0].formulaParsed }));
	}

	/* sanity: formulas that parse are still folded into one shared formula, and read back per row */
	const ok = readColumn(['B11*2', 'B12*2', 'B13*2']);
	assert.deepStrictEqual(ok.map(x => x.f), ['B11*2', 'B12*2', 'B13*2']);
	assert.ok(ok[1].sharedWithFirst && ok[2].sharedWithFirst, 'parseable consecutive formulas must stay shared');

	/* the defect: another sheet in the formula, so it does not parse in the clipboard workbook */
	const vl = readColumn(['IFERROR(VLOOKUP(B11,Other!$A$1:$B$5,2,FALSE),0)', 'IFERROR(VLOOKUP(B12,Other!$A$1:$B$5,2,FALSE),0)', 'IFERROR(VLOOKUP(B13,Other!$A$1:$B$5,2,FALSE),0)']);
	assert.ok(!vl[1].sharedWithFirst,
		'a formula that failed to parse became the shared master of the rows below it: they all read "' + vl[1].f + '"');
	assert.deepStrictEqual(vl.map(x => x.f.match(/VLOOKUP\((\w+)/)[1]), ['B11', 'B12', 'B13'],
		'each copied row must keep its own formula text');
}

/* ---------- part 2: pasting a formula that does not parse in the destination (WorksheetView.js) ---------- */
{
	const wsv = read('cell/view/WorksheetView.js');
	const helperSrc = extract(wsv, 'CCellPasteHelper.prototype._setPastedDataByCurrentRange = function');
	assert.ok(helperSrc.includes('calculateValueAndBinaryFormula'), 'extracted the wrong function');

	/* the destination workbook has Sheet1 only */
	const parserFormula = makeParser(new Set(['Sheet1']));
	const AscCommonExcel = {
		parserFormula,
		ParseResult: function (refPos) { this.refPos = refPos; },
		cElementType,
		executeInR1C1Mode: (mode, fn) => fn(),
		UndoRedoData_CellValueData: function (formula, value) { this.formula = formula; this.value = value; },
		CCellValue: function (o) { Object.assign(this, o); },
	};
	const AscCommon = {
		CellBase: function (row, col) { this.row = row; this.col = col; },
		CellAddress: function (id) { const m = /^([A-Z]+)(\d+)$/.exec(id); this.col = colNum(m[1]); this.row = +m[2]; },
		FormulaSeparators: { digitSeparatorDef: '.', digitSeparator: '.' },
	};
	const window = { Asc: { c_oSpecialPasteOperation: { none: 0 } }, AscCommon: { g_specialPasteHelper: {} } };
	const CellValueType = { Number: 0, String: 1 };
	const History = {};
	const Asc = { c_oSpecialPasteProps: {} };
	const setPasted = new Function('AscCommonExcel', 'AscCommon', 'window', 'CellValueType', 'History', 'Asc',
		'"use strict"; return function' + helperSrc.slice(helperSrc.indexOf('('))
	)(AscCommonExcel, AscCommon, window, CellValueType, History, Asc);

	/* paste one copied cell (sId, formula) at row/col (0-based) and return the formula text the cell gets */
	function paste(sId, formula, toRow, toCol) {
		const written = {};
		const range = new Proxy({ bbox: { r1: toRow, c1: toCol, r2: toRow, c2: toCol } }, {
			get(t, k) {
				if (k in t) return t[k];
				if (k === 'setValueData') return v => { written.formula = v.formula; };
				if (k === 'setValue') return v => { written.value = v; };
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
		};
		const specialPasteProps = { formula: true, val: true, cellStyle: true, operation: 0 };
		setPasted.call({ ws: { model: {} } }, range, { colsWidth: {} }, formulaProps, specialPasteProps);
		return arrFormula.length ? arrFormula[0].val.slice(1) : written.formula;
	}

	/* sanity: a formula that parses here is moved by the existing path, on both trees */
	assert.strictEqual(paste('G11', 'B11+Sheet1!B11', 3, 6), 'B4+Sheet1!B4');

	/* the reporter: G11 -> G4 in a workbook without the sheet the lookup table is on */
	assert.strictEqual(paste('G11', 'IFERROR(VLOOKUP(B11,Other!$A$1:$B$5,2,FALSE),0)', 3, 6),
		'IFERROR(VLOOKUP(B4,Other!$A$1:$B$5,2,FALSE),0)',
		'the relative reference of a formula naming a missing sheet did not move with the pasted cell');
	/* the cell part of a reference to the missing sheet moves too, absolute parts stay */
	assert.strictEqual(paste('G11', "B11+Other!B11+SUM('My Sheet'!$A11:B$2)", 3, 7), "C4+Other!C4+SUM('My Sheet'!$A4:C$2)");
	/* moved off the sheet -> #REF!, as ms does */
	assert.strictEqual(paste('B2', 'A1+Other!A1', 0, 1), '#REF!+Other!#REF!');
}

console.log('ok - pasted formulas move their relative references, also when the formula does not parse here');
