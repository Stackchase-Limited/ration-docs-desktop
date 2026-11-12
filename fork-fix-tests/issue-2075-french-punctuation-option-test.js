/*
 * #2075 - "Option to Disable Automatic Space Insertion Before Punctuation": in French
 * (fr-FR) text the editor always put a non-breaking space before : ; ? ! (and, since our
 * #925, inside « »), and nothing in the app could turn it off.
 *
 * Cause: sdkjs has had the switch for years - CAutoCorrectSettings.FrenchPunctuation
 * (common/api/autoCorrectSettings.js), checked by
 * CRunAutoCorrect.private_ProcessFrenchPunctuation via CDocument/CPresentation
 * .IsAutoCorrectFrenchPunctuation - but no setter on the document, no api method and no UI,
 * so it was always true. (The reporter's workaround - language detection off and fr-CA -
 * only works because the rule is fr-FR only.)
 * Fix: CDocument/CPresentation.SetAutoCorrectFrenchPunctuation and
 * asc_SetAutoCorrectFrenchPunctuation (word/api.js, slide/api.js, exported), and in web-apps
 * an AutoCorrect > AutoFormat As You Type checkbox "Non-breaking spaces with French
 * punctuation" (on by default, stored as de-/pe-settings-autoformat-french-punctuation and
 * applied when a document loads, like "Add period with double-space").
 *
 * What runs: the REAL CAutoCorrectSettings module, the REAL CDocument Is/Set methods and the
 * REAL word and slide asc_SetAutoCorrectFrenchPunctuation, toggling the setting that the REAL
 * RunAutoCorrect.js (loaded as in issue-925-french-guillemets-nbsp-test.js, same stubs)
 * reads while text is typed; and from web-apps the REAL checkbox change handler of
 * AutoCorrectDialog.js and the REAL load-time lines of both Main.js controllers against
 * stubs, plus the template slot and the en.json strings.
 *
 * Claimed: switched off, "Quoi?" / "Note : x" / "«a»" are left as typed; switched on (the
 * default) they get the non-breaking spaces as before; the checkbox stores the choice and
 * calls the api; a stored "false" is applied on load. NOT claimed: the dialog rendering
 * (needs a GUI look), the mobile editors, the PDF editor.
 *
 *   RD_REPO=<sdkjs> (default ../sdkjs), RD_WEBAPPS=<web-apps> (default ../web-apps)
 *   BASELINE=1 reads sdkjs at BASE_REF and web-apps at WEBAPPS_BASE_REF (parents of the fix);
 *   it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
const WEBAPPS = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
// Pinned to the parents of the fix commits, never HEAD.
const BASE_REF = process.env.BASE_REF || '7a99b84860^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '196bada5b0^';

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
/* `marker = function ... {...}` as a statement, or null */
function assignment(text, marker) {
	const at = text.indexOf(marker);
	return at === -1 ? null : block(text, at) + ';';
}

let failed = 0;
function check(name, f) {
	try { f(); console.log('ok   - ' + name); }
	catch (e) { failed++; console.log('FAIL - ' + name + '\n       ' + e.message); }
}

/* --- the real settings object, document methods and api methods --- */
const acWindow = { AscCommon: { CFirstLetterExceptions: function () {} } };
new Function('window', 'AscCommon', src('common/api/autoCorrectSettings.js'))(acWindow, acWindow.AscCommon);
function CDocument() { this.AutoCorrectSettings = new acWindow.AscCommon.CAutoCorrectSettings(); }
const docSrc = src('word/Editor/Document.js');
for (const m of ['CDocument.prototype.IsAutoCorrectFrenchPunctuation = function', 'CDocument.prototype.SetAutoCorrectFrenchPunctuation = function']) {
	const code = assignment(docSrc, m);
	if (code) new Function('CDocument', code)(CDocument);
}
const logicDocument = new CDocument();

function apiSetter(rel) {
	const text = src(rel);
	function asc_docs_api() { this.WordControl = { m_oLogicDocument: logicDocument }; }
	asc_docs_api.prototype.private_GetLogicDocument = function () { return this.WordControl.m_oLogicDocument; };
	const code = assignment(text, 'asc_docs_api.prototype.asc_SetAutoCorrectFrenchPunctuation = function');
	if (code) new Function('asc_docs_api', code)(asc_docs_api);
	const exported = /\['asc_SetAutoCorrectFrenchPunctuation'\]\s*=\s*asc_docs_api\.prototype\.asc_SetAutoCorrectFrenchPunctuation/.test(text);
	return { api: new asc_docs_api(), exported };
}
const wordApi = apiSetter('word/api.js');
const slideApi = apiSetter('slide/api.js');

const para_Text = 1, para_Space = 2;
const window = { AscWord: {} };
const AscWord = window.AscWord;

/* --- run elements: real GetAutoCorrectFlags --- */
function CRunText(v) { this.Value = v; }
CRunText.prototype.Type = para_Text;
CRunText.prototype.IsText = () => true;
CRunText.prototype.IsNBSP = function () { return 0x00A0 === this.Value; };
CRunText.prototype.IsNumber = function () { return this.Value >= 0x30 && this.Value <= 0x39; };
CRunText.prototype.IsPunctuation = function () { return !/[\p{L}\p{N}]/u.test(String.fromCodePoint(this.Value)); };
function CRunSpace(v) { this.Value = undefined !== v ? v : 0x20; }
CRunSpace.prototype.Type = para_Space;
CRunSpace.prototype.IsText = () => false;
CRunSpace.prototype.IsNBSP = () => false;
AscWord.CRunText = CRunText;
AscWord.CRunSpace = CRunSpace;

/* --- the paragraph model the autocorrect walks --- */
class Pos {
	constructor(arr) { this.arr = arr.slice(); }
	Update(v, d) { this.arr[d] = v; this.arr.length = d + 1; }
	GetDepth() { return this.arr.length - 1; }
	Copy() { return new Pos(this.arr); }
	get idx() { return this.arr[this.arr.length - 1]; }
}
function CParagraphRunElements(contentPos, count, types) {
	this.pos = contentPos; this.count = count; this.types = types; this.els = []; this.positions = [];
	this.breakOnBadType = false;
}
CParagraphRunElements.prototype.SetBreakOnBadType = function (b) { this.breakOnBadType = b; };
CParagraphRunElements.prototype.SetBreakOnDifferentClass = function () {};
CParagraphRunElements.prototype.SetBreakOnMath = function () {};
CParagraphRunElements.prototype.SetSaveContentPositions = function () {};
CParagraphRunElements.prototype.GetElements = function () { return this.els; };
CParagraphRunElements.prototype.GetContentPositions = function () { return this.positions; };
CParagraphRunElements.prototype.take = function (el, i) {
	if (this.types && this.types.indexOf(el.Type) === -1) return !this.breakOnBadType;
	this.els.push(el); this.positions.push(new Pos([0, i]));
	return this.els.length < this.count;
};

let actions = 0;
const doc = {
	IsDocumentEditor: () => true, IsPresentationEditor: () => false,
	IsAutoCorrectFrenchPunctuation() { return logicDocument.IsAutoCorrectFrenchPunctuation(); },
	StartAction() { actions++; }, FinalizeAction() {},
	GetHistory: () => ({}), IsSelectionLocked: () => false,
};
function makeRun() {
	const para = {
		GetLogicDocument: () => doc, GetPosByElement: () => new Pos([0]),
		TurnOffCorrectContent() {}, TurnOnCorrectContent() {},
		GetPrevRunElements(re) { for (let i = re.pos.idx - 1; i >= 0 && re.take(run.Content[i], i); i--); },
		GetNextRunElements(re) { for (let i = re.pos.idx; i < run.Content.length && re.take(run.Content[i], i); i++); },
		RemoveRunElement(p) { run.RemoveFromContent(p.idx, 1); return true; },
	};
	const run = {
		Content: [], State: { ContentPos: 0 },
		AddToContent(i, el) { this.Content.splice(i, 0, el); },
		RemoveFromContent(i, n) { this.Content.splice(i, n); },
		GetElement(i) { return this.Content[i]; },
		GetElementsCount() { return this.Content.length; },
		Get_CompiledPr: () => ({ Lang: { Val: 1036 } }),
		GetParagraph: () => para, GetParentForm: () => null,
	};
	return run;
}

/* --- load the real module --- */
const AscDFH = { historydescription_Document_AutoCorrectCommon: 1, historydescription_Document_AutoCorrectSmartQuotes: 2 };
new Function('window', 'AscWord', 'AscDFH', 'AscCommon', 'CParagraphRunElements', 'para_Text', 'para_Space', 'para_Math', 'para_Run',
	src('word/Editor/Paragraph/Run/RunAutoCorrect.js'))(window, AscWord, AscDFH, {}, CParagraphRunElements, para_Text, para_Space, 99, 98);
const FRENCH = AscWord.AUTOCORRECT_FLAGS_FRENCH_PUNCTUATION;
assert.ok(FRENCH && AscWord.CRunAutoCorrect, 'module loaded');
const textSrc = src('word/Editor/Paragraph/RunContent/Text.js');
const spaceSrc = src('word/Editor/Paragraph/RunContent/Space.js');
CRunText.prototype.GetAutoCorrectFlags = new Function('AscWord', 'return ' + fn(textSrc, 'CRunText.prototype.GetAutoCorrectFlags = function'))(AscWord);
CRunSpace.prototype.GetAutoCorrectFlags = new Function('AscWord', 'return ' + fn(spaceSrc, 'CRunSpace.prototype.GetAutoCorrectFlags = function'))(AscWord);

/* ParaRun.Add: add at the cursor, then autocorrect from the element's own flags */
function type(s, run = makeRun()) {
	for (const ch of s) {
		const cp = ch.codePointAt(0);
		const el = 0x20 === cp ? new CRunSpace(cp) : new CRunText(cp);
		run.AddToContent(run.State.ContentPos, el);
		run.State.ContentPos++;
		const flags = el.GetAutoCorrectFlags();
		if (flags & FRENCH)
			new AscWord.CRunAutoCorrect(run, run.State.ContentPos - 1).DoAutoCorrect(flags & FRENCH);
	}
	return run.Content.map(e => (0x00A0 === e.Value ? '~' : String.fromCodePoint(e.Value))).join('');
}


const setFrench = (api, v) => {
	assert.strictEqual(typeof api.api.asc_SetAutoCorrectFrenchPunctuation, 'function', 'no asc_SetAutoCorrectFrenchPunctuation');
	api.api.asc_SetAutoCorrectFrenchPunctuation(v);
};

check('on by default: "Quoi?" -> "Quoi~?" (unchanged behaviour)', () => assert.strictEqual(type('Quoi?'), 'Quoi~?'));
check('document api: switched off, "Quoi?" stays as typed', () => {
	setFrench(wordApi, false);
	assert.strictEqual(type('Quoi?'), 'Quoi?');
	assert.strictEqual(type('Note : x'), 'Note : x');
	assert.strictEqual(type('«a»'), '«a»');
});
check('document api: switched back on, the spaces come back', () => {
	setFrench(wordApi, true);
	assert.strictEqual(type('Note : x'), 'Note~: x');
});
check('presentation api switches the same setting', () => {
	setFrench(slideApi, false);
	assert.strictEqual(type('Quoi!'), 'Quoi!');
	setFrench(slideApi, true);
});
check('both apis export the method under its public name (minified build)', () => {
	assert(wordApi.exported, 'word/api.js does not export asc_SetAutoCorrectFrenchPunctuation');
	assert(slideApi.exported, 'slide/api.js does not export asc_SetAutoCorrectFrenchPunctuation');
});

/* --- web-apps --- */
const dlg = wsrc('apps/common/main/lib/view/AutoCorrectDialog.js');
check('AutoCorrect dialog: the checkbox stores the choice and calls the api', () => {
	const at = dlg.indexOf('this.chFrenchPunctuation = new Common.UI.CheckBox(');
	assert.notStrictEqual(at, -1, 'no French punctuation checkbox in AutoCorrectDialog.js');
	const end = dlg.indexOf('});', dlg.indexOf(".on('change'", at)) + 3;
	let handler = null, opts = null;
	const stored = {}, calls = [];
	const Common = {
		UI: { CheckBox: function (o) { opts = o; this.on = (ev, f) => { handler = f; return this; }; } },
		localStorage: { setBool: (k, v) => { stored[k] = v; } },
		Utils: { InternalSettings: { get: (k) => stored['get:' + k], set: (k, v) => { stored['set:' + k] = v; } } },
	};
	const self = { appPrefix: 'de-', textFrenchPunctuation: 'label' };
	const me = { appPrefix: 'de-', api: { asc_SetAutoCorrectFrenchPunctuation: (v) => calls.push(v) } };
	const panelAutoFormat = { find: (sel) => sel };
	new Function('Common', 'me', 'panelAutoFormat', dlg.slice(at, end)).call(self, Common, me, panelAutoFormat);
	assert.strictEqual(opts.el, '#id-autocorrect-dialog-chk-french-punctuation');
	handler({ getValue: () => 'unchecked' });
	assert.strictEqual(stored['de-settings-autoformat-french-punctuation'], false);
	assert.deepStrictEqual(calls, [false]);
	assert(/textFrenchPunctuation:\s*'[^']+'/.test(dlg), 'no textFrenchPunctuation default string');
	assert(/getFocusedComponents[\s\S]*this\.chFrenchPunctuation/.test(dlg), 'checkbox not in the focus order');
});
check('AutoCorrect dialog template has the checkbox slot in the document/presentation panel', () => {
	const tpl = wsrc('apps/common/main/lib/template/AutoCorrectDialog.template');
	const de = tpl.slice(tpl.indexOf('id-autocorrect-dialog-settings-de-autoformat'), tpl.indexOf('id-autocorrect-dialog-settings-sse-autoformat'));
	assert(de.includes('id="id-autocorrect-dialog-chk-french-punctuation"'));
});
for (const [pre, app] of [['de', 'documenteditor'], ['pe', 'presentationeditor']]) {
	check(app + ': a stored "off" is applied when a document loads; default on', () => {
		const main = wsrc('apps/' + app + '/main/app/controller/Main.js');
		const key = pre + '-settings-autoformat-french-punctuation';
		const at = main.indexOf('value = Common.localStorage.getBool("' + key + '"');
		assert.notStrictEqual(at, -1, 'Main.js does not load ' + key);
		const end = main.indexOf('asc_SetAutoCorrectFrenchPunctuation(value);', at);
		assert.notStrictEqual(end, -1);
		const code = main.slice(at, end + 'asc_SetAutoCorrectFrenchPunctuation(value);'.length);
		const run = (storedVal) => {
			const calls = [];
			const Common = {
				localStorage: { getBool: (k, def) => (k === key && storedVal !== undefined ? storedVal : def) },
				Utils: { InternalSettings: { set() {} } },
			};
			new Function('Common', 'me', 'var value;' + code)(Common, { api: { asc_SetAutoCorrectFrenchPunctuation: (v) => calls.push(v) } });
			return calls;
		};
		assert.deepStrictEqual(run(false), [false]);
		assert.deepStrictEqual(run(undefined), [true]);
		const en = wsrc('apps/' + app + '/main/locale/en.json');
		assert(/"Common\.Views\.AutoCorrectDialog\.textFrenchPunctuation":/.test(en), 'en.json lacks the label');
	});
}

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
