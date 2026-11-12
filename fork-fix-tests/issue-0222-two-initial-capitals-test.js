/*
 * DesktopEditors #222 - "Automatically correct wrongly capitalized second
 * letter": holding Shift a moment too long gives "HEllo"; Word and LibreOffice
 * correct it to "Hello" (TWo INitial CApitals), ONLYOFFICE left it.
 *
 * Cause: sdkjs had no such autocorrect at all - word/Editor/Paragraph/Run/
 * RunAutoCorrect.js CRunAutoCorrect.DoAutoCorrect runs French punctuation,
 * smart quotes, dashes, hyperlinks, first letter of sentence and lists only,
 * and common/api/autoCorrectSettings.js has no setting for it.
 * Fix: AUTOCORRECT_FLAGS_TWO_INITIAL_CAPITALS, started by the characters that
 * end a word (space, tab, Enter, line break, punctuation - not a digit), and
 * private_ProcessTwoInitialCapitalsAutoCorrect: a word just typed of 3+
 * letters, first two capitals, the rest lowercase, gets its second letter
 * lowercased as one undoable autocorrect step. 3-letter plurals (CDs, IDs)
 * and ?Hz units (MHz, GHz) are left alone; Turkish/Azeri lowercase I to
 * dotless i. CAutoCorrectSettings.TwoInitialCapitals (off by default - opt-in; Word ships it on, like
 * Word/LibreOffice and like our other autocorrects that Word has on), with
 * CDocument/CPresentation Set/IsAutoCorrectTwoInitialCapitals and
 * asc_SetAutoCorrectTwoInitialCapitals in the word and slide apis; web-apps
 * adds the AutoCorrect checkbox.
 *
 * This loads the REAL RunAutoCorrect.js module and the REAL
 * CRunText/CRunSpace/CRunParagraphMark.GetAutoCorrectFlags and
 * CAutoCorrectSettings, then types strings character by character into a
 * one-run paragraph the way ParaRun.Add does (add, ask the element for its
 * flags, CRunAutoCorrect.DoAutoCorrect with those flags restricted to the
 * TWo INitial CApitals flag; the stub document answers from the real
 * CAutoCorrectSettings).
 *
 * From web-apps: the REAL checkbox change handler of AutoCorrectDialog.js
 * and the REAL load-time lines of both Main.js controllers against stubs, the
 * template slot and the en.json strings; and the REAL word/slide
 * asc_SetAutoCorrectTwoInitialCapitals switching the real setting.
 *
 * Claimed: HEllo -> Hello after space/./,/Enter, not after a digit; words
 * with more capitals, 2 letters, CDs, MHz, x2ABc unchanged; the setting off
 * leaves HEllo; default off (opt-in); Turkish KIrmizi -> Kırmizi; the checkbox stores
 * and applies the choice, a stored "off" is applied on load.
 * NOT claimed: the other autocorrects in the same DoAutoCorrect pass, undo in
 * the GUI, the dialog's look (needs a GUI check), Enter at the real paragraph
 * end (the harness puts the paragraph mark in the same run).
 *
 *   node fork-fix-tests/issue-0222-two-initial-capitals-test.js
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs), RD_WEBAPPS=<web-apps> (default ../web-apps)
 *   BASELINE=1 reads sdkjs at BASE_REF and web-apps at WEBAPPS_BASE_REF; it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || '1fd3361a6e^';
const WEBAPPS = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '49cd3bbf26^';

function read(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}
const src = (rel) => read(SDKJS, BASE_REF, rel);
const wsrc = (rel) => read(WEBAPPS, WEBAPPS_BASE_REF, rel);

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

function fn(text, marker) {
	const at = text.indexOf(marker);
	if (at === -1) throw new Error(marker + ' not found');
	return block(text, text.indexOf('function', at));
}

const para_Text = 1, para_Space = 2, para_End = 3;
const window = { AscWord: {}, AscCommon: {} };
const AscWord = window.AscWord;
const AscCommon = window.AscCommon;
AscCommon.IsGeorgianScript = (cp) => cp >= 0x10A0 && cp <= 0x10FF;
AscCommon.CFirstLetterExceptions = function () {};

/* --- run elements: real GetAutoCorrectFlags --- */
function CRunText(v) { this.Value = v; }
CRunText.prototype.Type = para_Text;
CRunText.prototype.GetCodePoint = function () { return this.Value; };
CRunText.prototype.IsNBSP = function () { return 0x00A0 === this.Value; };
CRunText.prototype.IsNumber = function () { return this.Value >= 0x30 && this.Value <= 0x39; };
CRunText.prototype.IsPunctuation = function () { return !/[\p{L}\p{N}]/u.test(String.fromCodePoint(this.Value)); };
CRunText.prototype.IsLetter = function () { return !this.IsPunctuation() && !this.IsNumber() && !this.IsNBSP(); };
function CRunSpace(v) { this.Value = undefined !== v ? v : 0x20; }
CRunSpace.prototype.Type = para_Space;
function CRunParagraphMark() { this.Value = 0x0A; }
CRunParagraphMark.prototype.Type = para_End;
AscWord.CRunText = CRunText;
AscWord.CRunSpace = CRunSpace;

/* --- the paragraph model the autocorrect walks --- */
class Pos {
	constructor(arr) { this.arr = arr.slice(); }
	Update(v, d) { this.arr[d] = v; this.arr.length = d + 1; }
	GetDepth() { return this.arr.length - 1; }
	Get(d) { return this.arr[d]; }
	DecreaseDepth(n) { this.arr.length -= n; }
	Copy() { return new Pos(this.arr); }
	get idx() { return this.arr[this.arr.length - 1]; }
}
function CParagraphRunElements(contentPos, count, types) {
	this.pos = contentPos; this.count = count; this.types = types; this.els = []; this.positions = [];
	this.breakOnBadType = false; this.end = true;
}
CParagraphRunElements.prototype.SetBreakOnBadType = function (b) { this.breakOnBadType = b; };
CParagraphRunElements.prototype.SetBreakOnDifferentClass = function () {};
CParagraphRunElements.prototype.SetBreakOnMath = function () {};
CParagraphRunElements.prototype.SetSaveContentPositions = function () {};
CParagraphRunElements.prototype.GetElements = function () { return this.els; };
CParagraphRunElements.prototype.GetContentPositions = function () { return this.positions; };
CParagraphRunElements.prototype.IsEnd = function () { return this.end; };
CParagraphRunElements.prototype.take = function (el, i) {
	if (this.types && this.types.indexOf(el.Type) === -1) { this.end = false; return !this.breakOnBadType; }
	if (this.els.length >= this.count) { this.end = false; return false; }
	this.els.push(el); this.positions.push(new Pos([0, i]));
	return true;
};

const settings = {};
let actions = 0;
const doc = {
	IsDocumentEditor: () => true, IsPresentationEditor: () => false,
	IsAutoCorrectTwoInitialCapitals: () => settings.cur.IsTwoInitialCapitals(),
	StartAction() { actions++; }, FinalizeAction() {}, Recalculate() {},
	GetHistory: () => ({ CheckAsYouTypeAutoCorrect: () => true }), IsSelectionLocked: () => false,
};
function ParaRun() {}
function makeRun(lang) {
	const para = {
		GetLogicDocument: () => doc, GetPosByElement: () => new Pos([0]),
		TurnOffCorrectContent() {}, TurnOnCorrectContent() {},
		GetElementByPos: (p) => (p.GetDepth() === 0 ? run : null),
		GetPrevRunElements(re) { for (let i = re.pos.idx - 1; i >= 0 && re.take(run.Content[i], i); i--); },
	};
	const run = Object.assign(new ParaRun(), {
		Content: [], State: { ContentPos: 0 },
		AddToContent(i, el) { this.Content.splice(i, 0, el); },
		RemoveFromContent(i, n) { this.Content.splice(i, n); },
		GetElement(i) { return this.Content[i]; },
		GetElementsCount() { return this.Content.length; },
		Get_CompiledPr: () => ({ Lang: { Val: lang || 1033 } }),
		GetParagraph: () => para, GetParentForm: () => null,
	});
	return run;
}

/* --- load the real modules --- */
const AscDFH = { historydescription_Document_AutoCorrectCommon: 1, historydescription_Document_AutoCorrectFirstLetterOfSentence: 2 };
new Function('window', 'AscWord', 'AscDFH', 'AscCommon', 'CParagraphRunElements', 'para_Text', 'para_Space', 'para_Math', 'para_Run', 'ParaRun',
	src('word/Editor/Paragraph/Run/RunAutoCorrect.js'))(window, AscWord, AscDFH, AscCommon, CParagraphRunElements, para_Text, para_Space, 99, 98, ParaRun);
new Function('window', 'AscCommon', src('common/api/autoCorrectSettings.js').replace(/^\s*"use strict";/m, ''))(window, AscCommon);
const TWO = AscWord.AUTOCORRECT_FLAGS_TWO_INITIAL_CAPITALS;
let failed = 0;
function ok(cond, msg) { if (cond) console.log('ok   - ' + msg); else { failed++; console.log('FAIL - ' + msg); } }
ok(!!TWO, 'RunAutoCorrect.js exports AUTOCORRECT_FLAGS_TWO_INITIAL_CAPITALS');
const fresh = new AscCommon.CAutoCorrectSettings();
webAppsChecks();
ok(typeof fresh.IsTwoInitialCapitals === 'function' && fresh.IsTwoInitialCapitals() === false, 'CAutoCorrectSettings: TWo INitial CApitals off by default (opt-in; existing behaviour stays the default)');
if (!TWO || typeof fresh.IsTwoInitialCapitals !== 'function') {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE ' + BASE_REF + ')' : ''}`);
	process.exit(1);
}
settings.cur = fresh;
// the rule is opt-in (#222 default off); the correction checks run with it switched on, as a user would
if (typeof fresh.SetTwoInitialCapitals === 'function') fresh.SetTwoInitialCapitals(true);

const textSrc = src('word/Editor/Paragraph/RunContent/Text.js');
CRunText.prototype.GetAutoCorrectFlags = new Function('AscWord', 'return ' + fn(textSrc, 'CRunText.prototype.GetAutoCorrectFlags = function'))(AscWord);
CRunSpace.prototype.GetAutoCorrectFlags = new Function('AscWord', 'return ' + fn(src('word/Editor/Paragraph/RunContent/Space.js'), 'CRunSpace.prototype.GetAutoCorrectFlags = function'))(AscWord);
CRunParagraphMark.prototype.GetAutoCorrectFlags = new Function('AscWord', 'return ' + fn(src('word/Editor/Paragraph/RunContent/ParagraphMark.js'), 'CRunParagraphMark.prototype.GetAutoCorrectFlags = function'))(AscWord);

/* ParaRun.Add: add at the cursor, then autocorrect from the element's own flags; '\n' = Enter */
function type(s, lang) {
	const run = makeRun(lang);
	for (const ch of s) {
		const cp = ch.codePointAt(0);
		const el = 0x20 === cp ? new CRunSpace(cp) : 0x0A === cp ? new CRunParagraphMark() : new CRunText(cp);
		run.AddToContent(run.State.ContentPos, el);
		run.State.ContentPos++;
		const flags = el.GetAutoCorrectFlags();
		if (flags & TWO)
			new AscWord.CRunAutoCorrect(run, run.State.ContentPos - 1).DoAutoCorrect(flags & TWO);
	}
	return run.Content.map(e => String.fromCodePoint(e.Value)).join('');
}

function check(name, input, expected, lang) {
	let got;
	try { got = type(input, lang); assert.strictEqual(got, expected); console.log(`ok   - ${name}: ${JSON.stringify(input)} -> ${JSON.stringify(got)}`); }
	catch (e) { failed++; console.log(`FAIL - ${name}: ${JSON.stringify(input)} -> ${JSON.stringify(got)} (want ${JSON.stringify(expected)})`); }
}

check('space ends the word', 'HEllo world', 'Hello world');
check('full stop ends the word', 'Say HEllo.', 'Say Hello.');
check('comma ends the word', 'THe, end', 'The, end');
check('Enter ends the word', 'HEllo\n', 'Hello\n');
check('after an opening bracket', '(HEllo) ', '(Hello) ');
check('non-ASCII letters', 'ÉCole ', 'École ');
check('a digit does not end the word', 'HEllo2', 'HEllo2');
check('all caps unchanged', 'HELLO world', 'HELLO world');
check('three capitals unchanged', 'HELlo world', 'HELlo world');
check('mixed case later unchanged', 'HEllO world', 'HEllO world');
check('two letters unchanged', 'HE said', 'HE said');
check('3-letter plural of an abbreviation', 'CDs and IDs ', 'CDs and IDs ');
check('frequency units', 'MHz GHz ', 'MHz GHz ');
check('digit before the word', 'x2ABc ', 'x2ABc ');
check('Turkish I lowercases to dotless i', 'KIrmizi ', 'Kırmizi ', 1055);
/* the real api setters switch the setting the autocorrect reads */
function apiCheck(rel, cur) {
	const text = src(rel);
	const at = text.indexOf('asc_docs_api.prototype.asc_SetAutoCorrectTwoInitialCapitals = function');
	if (at === -1) return ok(false, rel + ': asc_SetAutoCorrectTwoInitialCapitals');
	function CDocument() { this.AutoCorrectSettings = cur; }
	const dsrc = src(rel.startsWith('word') ? 'word/Editor/Document.js' : 'slide/Editor/Format/Presentation.js');
	const cls = rel.startsWith('word') ? 'CDocument' : 'CPresentation';
	new Function(cls, block(dsrc, dsrc.indexOf(cls + '.prototype.SetAutoCorrectTwoInitialCapitals = function')) + ';')(CDocument);
	function asc_docs_api() { this.WordControl = { m_oLogicDocument: new CDocument() }; }
	asc_docs_api.prototype.private_GetLogicDocument = function () { return this.WordControl.m_oLogicDocument; };
	new Function('asc_docs_api', block(text, at) + ';')(asc_docs_api);
	new asc_docs_api().asc_SetAutoCorrectTwoInitialCapitals(false);
	ok(/\['asc_SetAutoCorrectTwoInitialCapitals'\]\s*=\s*asc_docs_api\.prototype\.asc_SetAutoCorrectTwoInitialCapitals/.test(text), rel + ' exports asc_SetAutoCorrectTwoInitialCapitals');
}
const before = actions;
settings.cur = new AscCommon.CAutoCorrectSettings();
apiCheck('word/api.js', settings.cur);
check('switched off through the document api', 'HEllo world', 'HEllo world');
ok(actions === before, 'setting off: no autocorrect action started');
settings.cur = new AscCommon.CAutoCorrectSettings();
apiCheck('slide/api.js', settings.cur);
check('switched off through the presentation api', 'HEllo world', 'HEllo world');

/* --- web-apps --- */
function webAppsChecks() {
	const dlg = wsrc('apps/common/main/lib/view/AutoCorrectDialog.js');
	try {
		const at = dlg.indexOf('this.chkTwoInitialCaps = new Common.UI.CheckBox(');
		assert.notStrictEqual(at, -1, 'no TWo INitial CApitals checkbox in AutoCorrectDialog.js');
		const end = dlg.indexOf('});', dlg.indexOf(".on('change'", at)) + 3;
		let handler = null, opts = null;
		const stored = {}, calls = [];
		const Common = {
			UI: { CheckBox: function (o) { opts = o; this.on = (ev, f) => { handler = f; return this; }; } },
			localStorage: { setBool: (k, v) => { stored[k] = v; } },
			Utils: { InternalSettings: { get: () => true, set: (k, v) => { stored['set:' + k] = v; } } },
		};
		const me = { appPrefix: 'pe-', api: { asc_SetAutoCorrectTwoInitialCapitals: (v) => calls.push(v) } };
		new Function('Common', 'me', '$window', dlg.slice(at, end)).call({ appPrefix: 'pe-', textTwoInitialCaps: 'label' }, Common, me, { find: (sel) => sel });
		assert.strictEqual(opts.el, '#auto-correct-exceptions-chk-two-caps');
		handler({ getValue: () => 'unchecked' });
		assert.strictEqual(stored['pe-settings-autocorrect-two-caps'], false);
		assert.deepStrictEqual(calls, [false]);
		assert(/textTwoInitialCaps:\s*'[^']+'/.test(dlg), 'no textTwoInitialCaps default string');
		assert(/getFocusedComponents[\s\S]*this\.chkTwoInitialCaps/.test(dlg), 'checkbox not in the focus order');
		const tpl = wsrc('apps/common/main/lib/template/AutoCorrectDialog.template');
		const ex = tpl.slice(tpl.indexOf('id-autocorrect-dialog-settings-exceptions'));
		assert(ex.includes('id="auto-correct-exceptions-chk-two-caps"'), 'template slot missing');
		ok(true, 'AutoCorrect dialog: the checkbox stores the choice and calls the api');
	} catch (e) { ok(false, 'AutoCorrect dialog checkbox: ' + e.message); }
	for (const [pre, app] of [['de', 'documenteditor'], ['pe', 'presentationeditor']]) {
		try {
			const main = wsrc('apps/' + app + '/main/app/controller/Main.js');
			const key = pre + '-settings-autocorrect-two-caps';
			const at = main.indexOf('value = Common.localStorage.getBool("' + key + '"');
			assert.notStrictEqual(at, -1, 'Main.js does not load ' + key);
			const tail = 'asc_SetAutoCorrectTwoInitialCapitals(value);';
			const code = main.slice(at, main.indexOf(tail, at) + tail.length);
			const run = (storedVal) => {
				const calls = [];
				const Common = {
					localStorage: { getBool: (k, def) => (k === key && storedVal !== undefined ? storedVal : def) },
					Utils: { InternalSettings: { set() {} } },
				};
				new Function('Common', 'me', 'var value;' + code)(Common, { api: { asc_SetAutoCorrectTwoInitialCapitals: (v) => calls.push(v) } });
				return calls;
			};
			assert.deepStrictEqual(run(false), [false]);
			assert.deepStrictEqual(run(true), [true]);
			assert.deepStrictEqual(run(undefined), [false]);
			assert(/"Common\.Views\.AutoCorrectDialog\.textTwoInitialCaps":/.test(wsrc('apps/' + app + '/main/locale/en.json')), 'en.json lacks the label');
			ok(true, app + ': the stored choice is applied when a document loads; default off');
		} catch (e) { ok(false, app + ': ' + e.message); }
	}
}

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE ' + BASE_REF + ')' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
