/*
 * #371 - Thai text broke lines inside words. Thai (like Lao, Khmer, Myanmar)
 * has no spaces between words, so a run of it was one "word" for the line
 * breaker and FindLineBreakInLongWord cut it at whatever letter reached the
 * margin: "ดูการบ้านดูการบ้านดูการบ้าน" (Tahoma 48, the reporter's docx) came
 * out as "...ดูกา|รบ้าน" instead of "...ดู|การบ้าน".
 *
 * Fix (an option, off by default because it reflows existing documents):
 * AscWord.ComplexScriptLineBreaker (TextHyphenator.js) asks Intl.Segmenter
 * for word boundaries; Paragraph.SegmentLineBreaks/IsLineBreakAfter
 * (Paragraph_Recalculate.js) keep them; Run.js's Recalculate_Range treats
 * them as break-after points; api.asc_setComplexScriptLineBreak turns it on.
 *
 * What runs: the REAL ComplexScriptLineBreaker block and the REAL
 * SegmentLineBreaks / IsLineBreakAfter, extracted by brace matching, on a
 * stub paragraph whose runs hold the reporter's string (plus a Latin word and
 * a space). Node's Intl.Segmenter is the same ICU dictionary breaker Chromium
 * uses. Checked: off -> no break points; on -> breaks exactly after
 * ดู|การบ้าน|ดู|การบ้าน|ดู (never inside a word, never next to Latin);
 * toggling recomputes; and the recalculation hooks are wired (Run.js
 * isBreakAfter uses Para.IsLineBreakAfter, both HyphenateText call sites are
 * followed by SegmentLineBreaks, the API is exported).
 *
 * NOT claimed here: the full layout. That was run separately through x2t
 * (docx -> PDF with the built word sdk, option forced on): the line breaks as
 * "ดูการบ้านดูการบ้านดู" / "การบ้าน"; with the option off it is unchanged.
 * The web-apps checkbox needs a GUI check.
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs); BASELINE=1 reads BASE_REF and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const BASE_REF = process.env.BASE_REF || 'f302f97ceb^';

function src(rel) {
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
function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found (no Thai word breaking in this tree)');
	return block(text, at);
}

const hyph = src('word/Editor/Paragraph/TextHyphenator.js');
const recalc = src('word/Editor/Paragraph_Recalculate.js');
const run = src('word/Editor/Run.js');
const api = src('word/api.js');

/* the module-level state and helpers in front of the object, then the object itself */
const start = hyph.indexOf('let complexScriptLineBreak = false;');
assert.notStrictEqual(start, -1, 'ComplexScriptLineBreaker state not found (no Thai word breaking in this tree)');
const objAt = hyph.indexOf('const ComplexScriptLineBreaker = {', start);
const breakerSrc = hyph.slice(start, objAt) + block(hyph, objAt) + ';';
const Breaker = new Function(breakerSrc + '\nreturn ComplexScriptLineBreaker;')();

function Paragraph(runs) { this.runs = runs; this.RecalcInfo = { SegmentText: true, SegmentTextId: 0 }; }
Paragraph.prototype.CheckRunContent = function (f) {
	for (const r of this.runs) if (f(r, 0, r.items.length)) return true;
};
const AscWord = { ComplexScriptLineBreaker: Breaker };
new Function('Paragraph', 'AscWord',
	extract(recalc, 'Paragraph.prototype.SegmentLineBreaks = function') + ';\n' +
	extract(recalc, 'Paragraph.prototype.IsLineBreakAfter = function') + ';')(Paragraph, AscWord);

function textItem(ch) { return { ch, IsText: () => true, GetCodePoint: () => ch.codePointAt(0) }; }
const space = { ch: ' ', IsText: () => false };
function makeRun(str) { return { items: Array.from(str).map(textItem), GetElement(i) { return this.items[i]; } }; }

const thai = 'ดูการบ้านดูการบ้านดูการบ้าน';
const r1 = makeRun(thai);
const r2 = { items: [space], GetElement(i) { return this.items[i]; } };
const r3 = makeRun('Hello');
const para = new Paragraph([r1, r2, r3]);

function breaksAfter() {
	para.SegmentLineBreaks();
	let out = '', all = r1.items.concat(r3.items);
	for (const it of r1.items) out += it.ch + (para.IsLineBreakAfter(it) ? '|' : '');
	const latin = r3.items.some(it => para.IsLineBreakAfter(it));
	return { out, latin, count: all.filter(it => para.IsLineBreakAfter(it)).length };
}

let res = breaksAfter();
assert.strictEqual(res.count, 0, 'option off must keep today\'s layout (no break points)');
console.log('ok   option off: no break points (today\'s layout kept)');

assert.strictEqual(Breaker.setEnabled(true), true);
res = breaksAfter();
assert.strictEqual(res.out, 'ดู|การบ้าน|ดู|การบ้าน|ดู|การบ้าน', 'break points: ' + res.out);
assert.strictEqual(res.latin, false, 'no break points in Latin text');
console.log('ok   option on: ' + res.out + ' (never inside a word, none in Latin)');

Breaker.setEnabled(false);
res = breaksAfter();
assert.strictEqual(res.count, 0, 'turning the option off again must drop the break points');
console.log('ok   toggling off again recomputes (no break points)');

assert.ok(/let isBreakAfter = Item\.IsSpaceAfter\(textPr\.RFonts\.Hint\) \|\| Para\.IsLineBreakAfter\(Item\);/.test(run),
	'Run.js Recalculate_Range does not use the break points');
assert.strictEqual((recalc.match(/HyphenateText\(\);\s*\n\s*this\.SegmentLineBreaks\(\);/g) || []).length, 2,
	'both HyphenateText() call sites must be followed by SegmentLineBreaks()');
assert.ok(api.includes('asc_docs_api.prototype["asc_setComplexScriptLineBreak"]'), 'API not exported');
console.log('ok   wired: Run.js isBreakAfter, both recalc entry points, asc_setComplexScriptLineBreak exported');
