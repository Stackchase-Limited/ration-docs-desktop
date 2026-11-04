/*
 * #2554 - in the slideshow, text that sticks out above/below its text box was
 * cut off, while the editor drew it whole. Reporter's deck (a Canva export) has
 * text boxes with tIns/bIns 0 and exact line spacing smaller than the font, e.g.
 * "Pitch Deck Presentation": sz=16014 (160 pt) on <a:lnSpc><a:spcPts val="12811"/>
 * (128 pt).
 *
 * Cause: the slideshow draws every shape into a texture the size of
 * getBoundsByDrawing() (shape bounds + 3 mm). The bounds come from drawing the
 * shape into CSlideBoundsChecker, which does not draw text: CTextBody.draw only
 * adds the rectangle of the content lines. For exact spacing,
 * CParaLineMetrics.Recalculate_LineGap shrinks the line's Ascent/Descent below
 * the font's TextAscent/TextDescent, but glyphs are still drawn at full height,
 * so they reach outside the bounds and the texture clips them.
 *
 * This extracts the real CParaLineMetrics (Paragraph_Recalculate.js), the real
 * CTextBody.prototype.draw (TextBody.js) and the real
 * CGraphicObjectBase.prototype.getBoundsByDrawing (GraphicObjectBase.js), lays
 * out two lines with the deck's numbers, collects what the bounds-checker branch
 * reports, and checks the glyph extents fit inside the texture rectangle.
 *
 * NOT claimed: the font metrics are a typical sans ratio (0.905/0.212 em), not
 * the real Aileron Heavy (or its substitute); the CSlideBoundsChecker itself,
 * the texture blit and the actual pixels are not exercised (needs a GUI check of
 * the reporter's deck in the slideshow).
 *
 * BASELINE=1 runs against the parent of the fix, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '542e927821^';

function src(rel) {
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

function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const recalc = src('word/Editor/Paragraph_Recalculate.js');
const textBody = src('common/Drawings/Format/TextBody.js');
const base = src('common/Drawings/Format/GraphicObjectBase.js');

const Asc = { linerule_AtLeast: 0, linerule_Auto: 1, linerule_Exact: 2 };
const AscCommon = { IsShapeToImageConverter: false };

/* --- real line metrics --- */
function CParaLineMetrics() {
	this.Ascent = 0; this.Descent = 0; this.TextAscent = 0; this.TextAscent2 = 0; this.TextDescent = 0; this.LineGap = 0;
}
new Function('CParaLineMetrics', 'Asc', extract(recalc, 'CParaLineMetrics.prototype =') + ';')(CParaLineMetrics, Asc);

const PT = 25.4 / 72;
const fontMM = 160.14 * PT;
const textAscent = 0.905 * fontMM, textDescent = 0.212 * fontMM;
const paraPr = { Spacing: { LineRule: Asc.linerule_Exact, Line: 128.11 * PT } };

const contentY = 0;
const lines = [];
let top = contentY;
for (let i = 0; i < 2; i++) {
	const m = new CParaLineMetrics();
	m.Update(textAscent, textAscent, textDescent, textAscent, textDescent, paraPr);
	lines.push({ Y: top - contentY + m.Ascent, Metrics: m });
	top += m.Ascent + m.Descent + m.LineGap;
}
const summaryHeight = top - contentY;
assert.ok(lines[0].Metrics.Ascent < textAscent - 3, 'setup: exact spacing must shrink the ascent by more than the 3 mm margin');

/* --- real CTextBody.draw, bounds-checker branch --- */
function CTextBody() {}
new Function('CTextBody', 'AscCommon', extract(textBody, 'CTextBody.prototype.draw = function') + ';')(CTextBody, AscCommon);

const para = { Lines: lines, Pages: [{ Y: contentY }] };
const body = new CTextBody();
body.parent = { isEmptyPlaceholder: () => false, isControl: () => false };
body.content = {
	X: 0, Y: contentY, XLimit: 100, Content: [para],
	Is_Empty: () => false, IsEmpty: () => false, GetSummaryHeight: () => summaryHeight,
};

const seen = { l: Infinity, t: Infinity, r: -Infinity, b: -Infinity };
const graphics = {
	isSupportTextDraw: () => false,
	rect(x, y, w, h) {
		seen.l = Math.min(seen.l, x); seen.t = Math.min(seen.t, y);
		seen.r = Math.max(seen.r, x + w); seen.b = Math.max(seen.b, y + h);
	},
};
body.draw(graphics);

/* --- real getBoundsByDrawing: the texture rectangle --- */
function CGraphicObjectBase() {}
new Function('CGraphicObjectBase', extract(base, 'CGraphicObjectBase.prototype.getBoundsByDrawing = function') + ';')(CGraphicObjectBase);
const shape = new CGraphicObjectBase();
shape.bounds = {
	l: seen.l, t: seen.t, r: seen.r, b: seen.b,
	copy() { const c = Object.assign({}, this); return c; },
	checkWH() {},
};
const tex = shape.getBoundsByDrawing(false);

const glyphTop = contentY + lines[0].Y - textAscent;
const glyphBottom = contentY + lines[1].Y + textDescent;
console.log(`texture t=${tex.t.toFixed(2)} b=${tex.b.toFixed(2)} mm; glyphs ${glyphTop.toFixed(2)}..${glyphBottom.toFixed(2)} mm`);
assert.ok(tex.t <= glyphTop, `top of the first line's glyphs (${glyphTop.toFixed(2)}) is clipped by the texture (t=${tex.t.toFixed(2)})`);
assert.ok(tex.b >= glyphBottom, `bottom of the last line's glyphs (${glyphBottom.toFixed(2)}) is clipped by the texture (b=${tex.b.toFixed(2)})`);

/* normal spacing must not grow the bounds beyond the content rectangle */
const auto = new CParaLineMetrics();
auto.Update(textAscent, textAscent, textDescent, textAscent, textDescent, { Spacing: { LineRule: Asc.linerule_Auto, Line: 1 } });
const autoPara = { Lines: [{ Y: auto.Ascent, Metrics: auto }], Pages: [{ Y: 0 }] };
const rects = [];
body.content.Content = [autoPara];
body.content.GetSummaryHeight = () => auto.Ascent + auto.Descent + auto.LineGap;
body.draw({ isSupportTextDraw: () => false, rect: (x, y, w, h) => rects.push([x, y, w, h]) });
assert.strictEqual(rects.length, 1, 'single-spaced text needs only the content rectangle');

console.log('PASS #2554: slideshow texture bounds include glyphs outside exact-spaced lines' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
