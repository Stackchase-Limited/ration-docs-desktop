/*
 * #2437 - spreadsheet cell borders printed (or saved as PDF) with a gap after
 * every vertical border: a cell's top/bottom border did not reach the border on
 * its left, so a bordered table printed as separate dashes (the reporter's
 * 400% screenshot: the left border stands apart from every horizontal line).
 *
 * Cause: WorksheetView._drawCellsBorders places borders for the screen
 * context's convention. DrawingContext.lineHor/lineVer draw a line of odd pixel
 * width half a pixel down/right, so a 1px line given x fills pixel column
 * [x, x+1). The vertical border before a cell is given x = left - 1 and the
 * cell's horizontal border starts at left, so on screen they meet exactly.
 * CPdfPrinter.lineHor/lineVer (the print / Save as PDF context) drew the same
 * call on the given coordinate itself, i.e. centred half a pixel to the left /
 * above, so the vertical line ended half a pixel short of the horizontal one.
 * x2t, 9.4 baseline, thin borders on A1:D4: vertical at 104.457pt, width 0.75pt
 * (ends 104.832pt); next cell's top border starts at 105.207pt: a 0.375pt gap
 * (the same at the outer left border). Fixed: CPdfPrinter remembers the line
 * width and applies the same half-pixel shift for odd widths.
 *
 * This extracts the REAL CPdfPrinter setLineWidth/lineHor/lineVer
 * (cell/graphics/pdfprinter.js) and the REAL DrawingContext lineHor/lineVer/
 * _calcRect (cell/graphics/DrawingContext.js), feeds both the same calls with
 * an identity transform and a recording renderer/canvas, and requires the PDF
 * path to lie where the screen path lies, for line widths 1, 2 and 3.
 * Claimed: the print context now follows the coordinate convention the border
 * layout is written for. NOT claimed: anything about dashed/double border
 * patterns, diagonal borders or the *PrevPx variants (unchanged), or a check in
 * a real print dialog.
 *
 *   node issue-2437-print-border-gaps-test.js            working tree, must PASS
 *   BASELINE=1 node issue-2437-print-border-gaps-test.js  BASE_REF, must FAIL
 *   RD_REPO=<sdkjs checkout>  (default ../sdkjs)
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the fix commit, never HEAD (HEAD carries the fix).
const BASE_REF = process.env.BASE_REF || '5073b97d08^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match a block starting at `from`, returning the source through its close. */
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

/* --- the print context: object-literal methods of CPdfPrinter.prototype --- */
const printer = src('cell/graphics/pdfprinter.js');
const proto = printer.slice(printer.indexOf('CPdfPrinter.prototype ='));
const method = (name) => extract(proto, name + ' : function').replace(/^(\w+)\s*:\s*function/, 'function');
const pdfMethods = new Function('vector_koef',
	'return {setLineWidth: ' + method('setLineWidth') + ', lineHor: ' + method('lineHor') +
	', lineVer: ' + method('lineVer') + '};')(1);

function pdfContext() {
	const path = [];
	const ctx = Object.assign({
		DocumentRenderer: {
			p_width() {},
			_m(x, y) { path.push(['M', x, y]); },
			_l(x, y) { path.push(['L', x, y]); },
		},
	}, pdfMethods);
	return { ctx, path };
}

/* --- the screen context: DrawingContext over a recording canvas, identity transform --- */
const dc = src('cell/graphics/DrawingContext.js');
function DrawingContext() {}
const identity = { transformPointX: (x) => x, transformPointY: (x, y) => y };
new Function('DrawingContext', 'asc_round',
	extract(dc, 'DrawingContext.prototype.lineHor = function') + ';\n' +
	extract(dc, 'DrawingContext.prototype.lineVer = function') + ';\n' +
	extract(dc, 'DrawingContext.prototype._calcRect = function') + ';')(DrawingContext, Math.round);

function screenContext(width) {
	const path = [];
	const ctx = new DrawingContext();
	ctx._mft = identity;
	ctx.ctx = {
		lineWidth: width,
		moveTo(x, y) { path.push(['M', x, y]); },
		lineTo(x, y) { path.push(['L', x, y]); },
	};
	return { ctx, path };
}

/* The calls _drawCellsBorders makes for one junction: a vertical border at the
   column boundary and a horizontal border along the row boundary. */
let compared = 0;
for (const width of [1, 2, 3]) {
	const screen = screenContext(width);
	const pdf = pdfContext();
	pdf.ctx.setLineWidth(width);
	for (const c of [screen.ctx, pdf.ctx]) {
		c.lineVer(103, 40, 61);
		c.lineHor(104, 40, 157);
	}
	assert.deepStrictEqual(pdf.path, screen.path,
		`width ${width}px: the PDF draws borders ${JSON.stringify(pdf.path)} but the layout is computed for ` +
		`${JSON.stringify(screen.path)} - a ${width % 2 ? 'half-pixel gap at every vertical border' : 'mismatch'}`);
	compared++;
}

console.log(`PASS #2437: print borders lie where the screen draws them (${compared} widths)` +
	(process.env.BASELINE ? ' (BASELINE?!)' : ''));
