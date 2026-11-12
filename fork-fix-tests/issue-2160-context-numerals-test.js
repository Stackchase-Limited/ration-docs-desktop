/*
 * #2160 - "Adding an extra option to the 'Numeral' option". File > Advanced settings >
 * Numeral offered Arabic (0-9) and Hindi (U+0660-0669) for the whole document. Word and
 * LibreOffice also have "Context": Hindi digits where the text runs right to left, Arabic
 * digits elsewhere, for documents that mix RTL and LTR. Now possible in the document editor.
 *
 * Upstream had half of it: Asc.c_oNumeralType.context exists in commonDefines.js and the
 * combo item was commented out in web-apps FileMenuPanels.js, but asc_setNumeralType
 * returned without doing anything for it, and the shaper (TextShaper.js
 * private_IsReplaceToHindiDigits) only knew "hindi". Now: the combo offers Context;
 * asc_setNumeralType loads both digit sets and reshapes; the shaper uses Hindi digits for
 * a digit in a paragraph whose direction is right-to-left (Paragraph.isRtlDirection, the
 * rule the reporter describes); and changing a paragraph's direction (CChangesParagraphBidi)
 * marks its text for reshaping, as the digit forms now depend on it. Arabic and Hindi, and
 * the default (Arabic), behave as before.
 *
 * This extracts the REAL asc_setNumeralType (word/api.js), private_IsReplaceToHindiDigits
 * (word/Editor/Paragraph/TextShaper.js) and CChangesParagraphBidi.private_SetValue
 * (word/Editor/ParagraphChanges.js) and drives them with stub paragraphs/documents; and
 * checks that the web-apps combo lists the Context value.
 *
 * NOT claimed: the rendering itself (glyph choice uses the existing Hindi-digit path);
 * Word's finer rule (digits following the preceding text's script inside an LTR paragraph)
 * - here a paragraph's direction decides; the setting is per user (localStorage) as before,
 * not saved in the file. GUI check: set Numeral = Context, type 123 in an RTL and an LTR
 * paragraph, toggle the direction.
 *
 *   RD_REPO=<sdkjs> RD_WEBAPPS=<web-apps> (defaults ../sdkjs, ../web-apps)
 *   BASELINE=1 reads both from their BASE_REFs -> must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.resolve(__dirname, '..', 'web-apps');
// Pinned to the parents of the commits that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '84afc71c38^';
const BASE_REF_WEBAPPS = process.env.BASE_REF_WEBAPPS || 'aaa725f624^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}
function matched(text, from, open) {
	const close = { '{': '}', '[': ']' }[open];
	const start = text.indexOf(open, from);
	let depth = 0;
	for (let i = start; i < text.length; i++) {
		if (text[i] === open) depth++;
		else if (text[i] === close && --depth === 0) return text.slice(start, i + 1);
	}
	throw new Error('unbalanced ' + open);
}
function fnAt(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	const p = text.indexOf('(', at + marker.length - 10);
	return 'function' + text.slice(p, text.indexOf(')', p) + 1) + matched(text, p, '{');
}

const defines = src(SDKJS, BASE_REF, 'common/commonDefines.js');
const c_oNumeralType = new Function('return ' + matched(defines, defines.indexOf('const c_oNumeralType ='), '{'))();
const Asc = { c_oNumeralType, editor: { isPdfEditor: () => false } };

const shaperJs = src(SDKJS, BASE_REF, 'word/Editor/Paragraph/TextShaper.js');
const isReplace = new Function('Asc', 'return ' + fnAt(shaperJs, 'CParagraphTextShaper.prototype.private_IsReplaceToHindiDigits = function'))(Asc);
const apiJs = src(SDKJS, BASE_REF, 'word/api.js');
const fonts = { asked: [] };
const AscFonts = { FontPickerByCharacter: { checkText: (s, api, cb) => { fonts.asked.push(s); cb(); } } };
const setNumeralType = new Function('Asc', 'AscFonts', 'return ' + fnAt(apiJs, 'asc_docs_api.prototype.asc_setNumeralType = function'))(Asc, AscFonts);
const changesJs = src(SDKJS, BASE_REF, 'word/Editor/ParagraphChanges.js');
const bidiSetValue = new Function('return ' + fnAt(changesJs, 'CChangesParagraphBidi.prototype.private_SetValue = function'))();

function doc(type) {
	return { type, reshaped: 0, IsDocumentEditor: () => true, GetNumeralType() { return this.type; }, SetNumeralType(t) { this.type = t; },
		GetAllParagraphs: () => [], RecalculateFromStart() { this.reshaped++; } };
}
function para(d, rtl) {
	return { rtl, shape: false, GetLogicDocument: () => d, isRtlDirection() { return this.rtl; }, GetParent: () => ({}),
		Pr: {}, CompiledPr: {}, private_UpdateTrackRevisionOnChangeParaPr() {}, RecalcInfo: { NeedShapeText() { this.owner.shape = true; } } };
}
function hindi(type, rtl) {
	const p = para(doc(type), rtl);
	return isReplace.call({ MaskSymbol: null, Paragraph: p });
}

let failures = 0;
function check(what, got, want) {
	const ok = JSON.stringify(got) === JSON.stringify(want);
	failures += !ok;
	console.log(`  ${what.padEnd(56)} ${JSON.stringify(got).padEnd(10)} ${ok ? 'ok' : 'FAILED (want ' + JSON.stringify(want) + ')'}`);
}

console.log('sdkjs ' + (process.env.BASELINE ? '@ ' + BASE_REF : SDKJS));
const T = c_oNumeralType;
check('Arabic: digit in an LTR paragraph -> Hindi?', hindi(T.arabic, false), false);
check('Arabic: digit in an RTL paragraph -> Hindi?', hindi(T.arabic, true), false);
check('Hindi: digit in an LTR paragraph -> Hindi?', hindi(T.hindi, false), true);
check('Hindi: digit in an RTL paragraph -> Hindi?', hindi(T.hindi, true), true);
check('Context: digit in an LTR paragraph -> Hindi?', hindi(T.context, false), false);
check('Context: digit in an RTL paragraph -> Hindi?', hindi(T.context, true), true);
check('Hindi, masked text (password form) -> Hindi?', isReplace.call({ MaskSymbol: 42, Paragraph: para(doc(T.hindi), true) }), false);

for (const [name, t] of [['Arabic', T.arabic], ['Hindi', T.hindi], ['Context', T.context]]) {
	const d = doc(T.arabic);
	fonts.asked = [];
	setNumeralType.call({ private_GetLogicDocument: () => d }, t);
	const digits = fonts.asked.join('');
	check(`asc_setNumeralType(${name}): stored + reshaped`, [d.type === t, d.reshaped], [true, 1]);
	check(`asc_setNumeralType(${name}): digit fonts checked`, [/[0-9]/.test(digits), /[٠-٩]/.test(digits)],
		[t !== T.hindi, t !== T.arabic]);
}

const p = para(doc(T.context), false);
p.RecalcInfo.owner = p;
bidiSetValue.call({ Class: p }, true);
check('paragraph direction changed -> text reshaped', [p.Pr.Bidi, p.shape], [true, true]);

const panels = process.env.BASELINE
	? execFileSync('git', ['-C', WEBAPPS, 'show', `${BASE_REF_WEBAPPS}:apps/documenteditor/main/app/view/FileMenuPanels.js`], { encoding: 'utf8' })
	: fs.readFileSync(path.join(WEBAPPS, 'apps/documenteditor/main/app/view/FileMenuPanels.js'), 'utf8');
const combo = panels.slice(panels.indexOf('this.cmbNumeral = new Common.UI.ComboBox('));
const data = new Function('Asc', 'return ' + matched(combo, combo.indexOf('data'), '[')).call({ txtArabic: 'Arabic', txtHindi: 'Hindi', txtContext: 'Context' }, Asc);
check('web-apps Numeral combo values', data.map((d) => d.value), [T.arabic, T.hindi, T.context]);

console.log(failures ? '\nFAILED' : '\nok - Numeral: Context gives Hindi digits in RTL paragraphs, Arabic elsewhere');
process.exit(failures ? 1 : 0);
