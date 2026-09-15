/*
 * #2263 (confirmed-bug) - "Justified issue". Justified alignment in a
 * spreadsheet cell has no effect on Chinese text: the line stays flush left
 * however wide the cell is. The reporter's own diagnosis is right - there are no
 * spaces between the characters.
 *
 * cell/view/StringRender.js computes the slack to add per gap in
 * computeWordDeltaX (nested in StringRender.prototype._doRender). It counted a
 * gap only where a non-space follows a space, so a line of East Asian text has
 * zero gaps, the function returns 0 and nothing is justified. Excel spreads such
 * a line between the characters themselves.
 *
 * The count now goes through StringRender.prototype._calcJustifyGaps, which asks
 * _isJustifyBreak per position; the drawing side
 * (TableCellDrawState.handleBidiFlow) asks the same predicate, so the pen and
 * the arithmetic cannot disagree and push text out of the cell.
 *
 * This extracts the real computeWordDeltaX by brace matching - out of the middle
 * of _doRender - together with the real prototype helpers it calls and the real
 * codesHypSp table, and drives it over hand-built lines. AscCommon.isEastAsianScript
 * is the real one, brace-matched out of common/editorscommon.js (untouched by
 * this change, so it is read from disk in both directions).
 *
 * BASELINE=1 re-reads cell/view/StringRender.js from git and must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'cell/view/StringRender.js';
const BASE_REF = process.env.BASE_REF || 'HEAD';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

const editorsCommon = fs.readFileSync(path.join(SDKJS, 'common/editorscommon.js'), 'utf8');

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

/* --- the real AscCommon.isEastAsianScript --- */
const eaAt = editorsCommon.indexOf('function isEastAsianScript(value)');
assert.notStrictEqual(eaAt, -1, 'isEastAsianScript not found in common/editorscommon.js');
const AscCommon = {
	align_Justify: 3,
	isEastAsianScript: new Function('"use strict"; return ' + matched(editorsCommon, eaAt))()
};
assert.strictEqual(AscCommon.isEastAsianScript(0x4E2D), true, '中 must be East Asian');
assert.strictEqual(AscCommon.isEastAsianScript(0x61), false, '"a" must not be');

/* --- the real computeWordDeltaX, out of the middle of _doRender --- */
const cwdAt = source.indexOf('function computeWordDeltaX()');
assert.notStrictEqual(cwdAt, -1, 'computeWordDeltaX not found');
const cwdSrc = matched(source, cwdAt);
assert.ok(cwdSrc.includes('renderedWidth'), 'extracted the wrong function');

/* it closes over align, n, self, l and maxWidth - hand them in as parameters */
const makeCompute = new Function(
	'AscCommon', 'align', 'n', 'self', 'l', 'maxWidth',
	'"use strict";\n' + cwdSrc + '\nreturn computeWordDeltaX;'
);

/* --- the real codesHypSp table --- */
const spAt = source.indexOf('this.codesHypSp = {');
assert.notStrictEqual(spAt, -1, 'codesHypSp not found');
const codesHypSp = new Function('"use strict"; return ' + matched(source, spAt + 'this.codesHypSp = '.length))();
assert.strictEqual(codesHypSp[0x20], 1, 'a plain space must be a space');

/* --- the real prototype helpers, when the file defines them --- */
function protoMethod(name) {
	const at = source.indexOf('StringRender.prototype.' + name + ' = function');
	if (at === -1) return null;
	const parenAt = source.indexOf('(', at + ('StringRender.prototype.' + name + ' = function').length - 1);
	return new Function('AscCommon', '"use strict"; return function' + matched(source, parenAt))(AscCommon);
}

/* --- a StringRender stand-in carrying whatever the file really defines --- */
function renderer(text) {
	const self = {
		chars: [],
		charWidths: [],
		charProps: {},
		codesHypSp: codesHypSp,
		lines: []
	};
	for (const ch of text) {
		self.chars.push(ch.codePointAt(0));
		// every glyph 10 wide, every space 5, so the arithmetic below is exact
		self.charWidths.push(codesHypSp[ch.codePointAt(0)] ? 5 : 10);
	}
	for (const name of ['_isJustifyBreak', '_calcJustifyGaps']) {
		const fn = protoMethod(name);
		if (fn) self[name] = fn;
	}
	return self;
}

/* one line covering the whole string, and a second so it is not the last line */
function line(self) {
	self.lines = [{ beg: 0, end: self.chars.length - 1 }, { beg: 0, end: 0 }];
	return self.lines[0];
}

function deltaX(text, maxWidth, lineIndex) {
	const self = renderer(text);
	const l = line(self);
	const compute = makeCompute(AscCommon, AscCommon.align_Justify, lineIndex === undefined ? 0 : lineIndex, self, l, maxWidth);
	return compute();
}
function renderedWidth(text) {
	return renderer(text).charWidths.reduce((a, b) => a + b, 0);
}

/* --- 0. the premise: the drawing side asks the same question ---
 * If the pen stops going through _isJustifyBreak, the widths computed here stop
 * describing where the characters land and this test measures nothing. */
if (protoMethod('_isJustifyBreak')) {
	const hbfAt = source.indexOf('TableCellDrawState.prototype.handleBidiFlow = function');
	assert.notStrictEqual(hbfAt, -1, 'handleBidiFlow not found');
	const hbfSrc = matched(source, source.indexOf('(', hbfAt + 50));
	assert.ok(/_isJustifyBreak\(\s*this\.prevCharInLine\s*,\s*char\s*\)/.test(hbfSrc),
		'handleBidiFlow must decide where to add the slack with the same predicate ' +
		'the width arithmetic uses, or the text drifts out of the cell');
}

/* --- 1. the defect: a line of Chinese gets no justification --- */
{
	const text = '中文字体';          // four ideographs, no spaces anywhere
	const maxWidth = 101;             // 40 of glyph, 60 of slack, 1 of the usual margin
	const dx = deltaX(text, maxWidth);

	assert.ok(dx > 0,
		'justified Chinese must be spread across the cell - a line with no spaces ' +
		'in it got no slack at all, which is #2263 (dx was ' + dx + ')');

	assert.strictEqual(dx, (maxWidth - 1 - renderedWidth(text)) / 3,
		'four ideographs join at three places, so each join takes a third of the slack');

	/* the drawn line must end exactly at the edge, never past it */
	assert.strictEqual(renderedWidth(text) + 3 * dx, maxWidth - 1,
		'the glyphs plus the slack must come to exactly the usable width');
}

/* --- 2. Japanese and Korean too, and a single character has nowhere to spread --- */
{
	assert.ok(deltaX('ひらがな', 101) > 0, 'kana must justify as well');
	assert.ok(deltaX('한국어글', 101) > 0, 'hangul must justify as well');
	assert.strictEqual(deltaX('中', 101), 0, 'one character has no join to widen');
}

/* --- 3. Latin text is untouched --- */
{
	const text = 'ab cd ef';         // 6 glyphs at 10, 2 spaces at 5 => 70
	const maxWidth = 101;
	const dx = deltaX(text, maxWidth);
	assert.strictEqual(renderedWidth(text), 70);
	assert.strictEqual(dx, (maxWidth - 1 - 70) / 2,
		'three Latin words are still spread at their two spaces, nowhere else');
}

/* --- 4. mixed text: the spaces and the ideograph joins both count --- */
{
	const text = '中文 abc';          // 中|文 is one join, the space before "abc" another
	const maxWidth = 101;
	const dx = deltaX(text, maxWidth);
	assert.strictEqual(dx, (maxWidth - 1 - renderedWidth(text)) / 2,
		'"abc" is one word and gets no interior joins');
}

/* --- 5. leading spaces are not a place to put slack --- */
{
	const withLead = deltaX('  中文字体', 201);
	const self = renderer('  中文字体');
	assert.strictEqual(withLead, (201 - 1 - self.charWidths.reduce((a, b) => a + b, 0)) / 3,
		'slack goes between the characters, never in front of the first one');
}

/* --- 6. the last line of a justified cell stays flush left --- */
{
	assert.strictEqual(deltaX('中文字体', 101, 1), 0,
		'the last line of justified text is not stretched');
}

console.log('ok - justified East Asian text in a cell is spread between its characters');
