/*
 * #1203 - list items (and paragraphs in general) could not be reordered from
 * the keyboard: Word's Alt+Shift+Up / Alt+Shift+Down ("move paragraph up /
 * down") did nothing but extend the selection a line, and there was no other
 * command; the only way was cut and paste.
 *
 * Fix (sdkjs): document shortcut actions MoveParagraphUp / MoveParagraphDown
 * (word/apiDefines.js, defaults Alt+Shift+Up/Down - Option+Shift on macOS - in
 * word/Editor/Shortcuts.js, customizable like the others) run
 * CDocument.MoveSelectedParagraphs (word/Editor/Document.js): the paragraph
 * next to the paragraphs holding the cursor or selection is moved to their
 * other side, with PreventPreDelete so its comments/bookmarks stay; numbering
 * is recounted, the cursor/selection stays on the moved paragraphs, one undo
 * step. Not across a table, content control or section break, not with track
 * changes on.
 *
 * This runs the WHOLE document engine headless in docbuilder: the word bundle
 * is concatenated from RD_REPO (or BASE_REF with BASELINE=1) as build/build.py
 * does from configs/word.json (desktop), docbuilder/x2t from the main tree's
 * core build (as issue-2288-row-indirect-false-cycle-test.js). A document with
 * a numbered list, a commented item, a table and plain paragraphs is built
 * with the builder API; the moves go through the real key handling
 * (CDocument.OnKeyDown with Alt+Shift+Up/Down) and the result is also saved to
 * DOCX and reopened.
 *
 * web-apps: the Keyboard Shortcuts dialog names its rows from
 * Common.Controllers.Shortcuts.txtLabel<Action> in the document and PDF
 * editors' en.json; the test checks both new actions have a label and a
 * description there.
 *
 * NOT claimed: drawing/scrolling in the editor and co-editing locks (not
 * exercised by docbuilder); the dialog as drawn - GUI check.
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs), RD_WEBAPPS=<web-apps> (default
 * ../web-apps). BASELINE=1 reads sources at BASE_REF / WEBAPPS_BASE_REF with
 * git, where it must fail. RD_CORE_BIN / RD_CORE_LIB override the
 * core build dirs. Exits 2 (CANNOT RUN) when the core build is missing.
 */
'use strict';
const { spawnSync, execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '63f1738698^';
const WEBAPPS = process.env.RD_WEBAPPS || path.join(ROOT, 'web-apps');
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '4729f16bc5^';
const CORE_BIN = process.env.RD_CORE_BIN || path.join(ROOT, 'core', 'build', 'bin', 'mac_arm64');
const CORE_LIB = process.env.RD_CORE_LIB || path.join(ROOT, 'core', 'build', 'lib', 'mac_arm64');
const TEMPLATE = path.join(ROOT, 'document-templates', 'new', 'en-US', 'new.docx');
const XREGEXP = path.join(ROOT, 'web-apps', 'vendor', 'xregexp', 'xregexp-all-min.js');
const FONTS = path.join(ROOT, 'core-fonts');

for (const p of [path.join(CORE_BIN, 'docbuilder'), path.join(CORE_BIN, 'x2t'), path.join(CORE_BIN, 'allfontsgen'),
	path.join(CORE_LIB, 'doctrenderer.framework'), TEMPLATE, XREGEXP, FONTS]) {
	if (!fs.existsSync(p)) {
		console.log('CANNOT RUN: missing ' + p);
		process.exit(2);
	}
}

function readMany(rels) {
	if (!process.env.BASELINE)
		return rels.map((r) => fs.readFileSync(path.join(SDKJS, r)));
	const out = spawnSync('git', ['-C', SDKJS, 'cat-file', '--batch'],
		{ input: rels.map((r) => `${BASE_REF}:${r}\n`).join(''), maxBuffer: 1 << 30 });
	if (out.status !== 0) throw new Error('git cat-file failed: ' + out.stderr);
	const buf = out.stdout, res = [];
	let pos = 0;
	for (const r of rels) {
		const nl = buf.indexOf(10, pos);
		const header = buf.slice(pos, nl).toString();
		const m = /^\S+ blob (\d+)$/.exec(header);
		if (!m) throw new Error(`${BASE_REF}:${r}: ${header}`);
		const size = Number(m[1]);
		res.push(buf.slice(nl + 1, nl + 1 + size));
		pos = nl + 1 + size + 1;
	}
	return res;
}
const config = JSON.parse(readMany(['configs/word.json'])[0].toString()).sdk;
const minFiles = config.min.concat((config.desktop && config.desktop.min) || []);
const commonFiles = config.common.concat((config.desktop && config.desktop.common) || []);
const join = (bufs) => bufs.map((b) => b.toString('utf8') + '\n').join('');

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'rd-1203-'));
const mk = (p) => fs.mkdirSync(path.join(work, p), { recursive: true });
['bin', 'fonts', 'editors/sdkjs/word', 'editors/sdkjs/common/Native', 'editors/sdkjs/common/libfont',
	'editors/web-apps/vendor/xregexp'].forEach(mk);
fs.symlinkSync(CORE_LIB, path.join(work, 'Frameworks'));
for (const b of ['docbuilder', 'x2t', 'allfontsgen']) {
	fs.copyFileSync(path.join(CORE_BIN, b), path.join(work, 'bin', b), fs.constants.COPYFILE_FICLONE);
	fs.chmodSync(path.join(work, 'bin', b), 0o755);
}
fs.writeFileSync(path.join(work, 'editors/sdkjs/word/sdk-all-min.js'), join(readMany(minFiles)));
fs.writeFileSync(path.join(work, 'editors/sdkjs/word/sdk-all.js'),
	'(function(window, undefined) {\n' + join(readMany(commonFiles)) + '})(window);\n');
for (const f of ['native.js', 'jquery_native.js'])
	fs.copyFileSync(path.join(SDKJS, 'common/Native', f), path.join(work, 'editors/sdkjs/common/Native', f));
fs.cpSync(path.join(SDKJS, 'common/libfont/engine'), path.join(work, 'editors/sdkjs/common/libfont/engine'), { recursive: true });
fs.copyFileSync(XREGEXP, path.join(work, 'editors/web-apps/vendor/xregexp/xregexp-all-min.js'));
fs.copyFileSync(TEMPLATE, path.join(work, 'new.docx'));
fs.writeFileSync(path.join(work, 'bin/DoctRenderer.config'), `<Settings>
<file>../editors/sdkjs/common/Native/native.js</file>
<file>../editors/sdkjs/common/Native/jquery_native.js</file>
<file>../editors/web-apps/vendor/xregexp/xregexp-all-min.js</file>
<allfonts>../fonts/AllFonts.js</allfonts>
<sdkjs>../editors/sdkjs</sdkjs>
</Settings>
`);
execFileSync(path.join(work, 'bin/allfontsgen'), ['--input=' + FONTS, '--allfonts=' + path.join(work, 'fonts/AllFonts.js'),
	'--selection=' + path.join(work, 'fonts/font_selection.bin'), '--use-system=false'], { stdio: 'ignore' });

const saved = path.join(work, 'moved.docx');
const script = `builder.OpenFile(${JSON.stringify(path.join(work, 'new.docx'))});
function out(name, value) { console.log('RESULT ' + JSON.stringify([name, value])); }
var doc = Api.GetDocument();
var logic = editor.WordControl.m_oLogicDocument;
doc.RemoveAllElements();
var numbering = doc.CreateNumbering('numbered');
var paras = {};
function add(text, numbered) {
	var p = Api.CreateParagraph();
	p.AddText(text);
	if (numbered) p.SetNumbering(numbering.GetLevel(0));
	doc.Push(p);
	paras[text] = p;
	return p;
}
add('Intro', false); add('One', true); add('Two', true); add('Three', true); add('Four', true); add('Middle', false);
var table = Api.CreateTable(2, 2);
doc.Push(table);
var cell = table.GetCell(0, 0).GetContent();
cell.GetElement(0).AddText('X');
var y = Api.CreateParagraph(); y.AddText('Y'); cell.Push(y); paras['Y'] = y;
function cellTexts() { var r = []; for (var i = 0; i < cell.GetElementsCount(); i++) r.push(cell.GetElement(i).GetText().trim()); return r.join(','); }
add('After', false);
paras['Three'].AddComment('note on three', 'Tester');
// RemoveAllElements leaves an empty paragraph first, and Push(table) one after the table: drop both
for (var i = logic.Content.length - 1; i >= 0; i--)
	if (logic.Content[i].IsParagraph() && logic.Content[i].IsEmpty() && i < logic.Content.length - 1) doc.RemoveElement(i);
// as in the editor: every action is a history point
logic.History.TurnOn && logic.History.TurnOn();
function texts() {
	var res = [];
	for (var i = 0; i < logic.Content.length; i++) {
		var el = logic.Content[i];
		if (!el.IsParagraph()) { res.push('[table]'); continue; }
		res.push(el.GetText().replace(/\t/g, ' ').trim());
	}
	return res.join(' | ');
}
function key(code) {
	// Alt+Shift+<arrow>, as the editor gets it
	return logic.OnKeyDown({ KeyCode: code, CtrlKey: false, ShiftKey: true, AltKey: true, MacCmdKey: false,
		IsCtrl: function() { return false; }, IsShift: function() { return true; }, IsAlt: function() { return true; } });
}
function cursorIn() { var p = logic.GetCurrentParagraph(); return p ? p.GetText().replace(/^\\d+\\.\\t/, '').trim() : null; }
function caret(text) { paras[text].Select(); logic.RemoveSelection(); }

try {
	out('start', texts());
	out('history', [logic.History.Is_On ? logic.History.Is_On() : null]);
	out('shortcut', [editor.getShortcut({ KeyCode: 38, CtrlKey: false, ShiftKey: true, AltKey: true, MacCmdKey: false }),
		editor.getShortcut({ KeyCode: 40, CtrlKey: false, ShiftKey: true, AltKey: true, MacCmdKey: false })]);

	caret('Three');
	key(38);
	out('three-up', texts());
	out('three-up-cursor', cursorIn());
	out('comments', doc.GetAllComments().length);

	logic.Document_Undo();
	out('undo', texts());

	var range = paras['One'].GetRange().ExpandTo(paras['Two'].GetRange());
	range.Select();
	key(40);
	out('two-down', texts());
	out('comments-neighbour', doc.GetAllComments().length);
	out('two-down-selected', logic.GetSelectedParagraphs().map(function(p) { return p.GetText().replace(/^\\d+\\.\\t/, '').trim(); }));

	caret('Intro');
	key(38);
	out('first-up', texts());

	caret('Middle');
	key(40);
	out('middle-before-table', texts());

	caret('After');
	key(38);
	out('after-table', texts());

	caret('Y');
	key(38);
	out('cell', [cellTexts(), cursorIn()]);
	logic.Document_Undo();

	logic.SetTrackRevisions(true);
	caret('Four');
	key(38);
	out('tracked', texts());
	logic.SetTrackRevisions(false);
} catch (e) {
	out('error', String(e && e.message || e));
}
builder.SaveFile('docx', ${JSON.stringify(saved)});
builder.CloseFile();
builder.OpenFile(${JSON.stringify(saved)});
var c = editor.WordControl.m_oLogicDocument.Content, t = [];
for (var i = 0; i < c.length; i++) t.push(c[i].IsParagraph() ? c[i].GetText().replace(/\t/g, ' ').trim() : '[table]');
console.log('RESULT ' + JSON.stringify(['reopened', t.join(' | ')]));
builder.CloseFile();
`;
fs.writeFileSync(path.join(work, 'run.js'), script);
const run = spawnSync(path.join(work, 'bin/docbuilder'), [path.join(work, 'run.js')],
	{ cwd: path.join(work, 'bin'), encoding: 'utf8', timeout: 180000 });
fs.rmSync(work, { recursive: true, force: true });
if (run.error) {
	console.log('FAIL: docbuilder did not finish: ' + run.error.message);
	process.exit(1);
}
const R = {};
for (const line of (run.stdout || '').split('\n')) {
	const m = /^RESULT (.*)$/.exec(line);
	if (m) { const r = JSON.parse(m[1]); R[r[0]] = r[1]; }
}

const START = 'Intro | 1. One | 2. Two | 3. Three | 4. Four | Middle | [table] | After';
const AFTER_UP = 'Intro | 1. One | 2. Three | 3. Two | 4. Four | Middle | [table] | After';
const AFTER_DOWN = 'Intro | 1. Three | 2. One | 3. Two | 4. Four | Middle | [table] | After';
const CHECKS = [
	['the document as built', () => R.start === START, R.start],
	['Alt+Shift+Up / Down are the MoveParagraphUp / MoveParagraphDown shortcuts (148, 149)',
		() => JSON.stringify(R.shortcut) === '[148,149]', JSON.stringify(R.shortcut)],
	['Alt+Shift+Up in "Three" puts it above "Two", numbering recounted', () => R['three-up'] === AFTER_UP, R['three-up']],
	['the cursor stays in "Three"', () => R['three-up-cursor'] === 'Three', R['three-up-cursor']],
	['the comment on the moved item is kept', () => R.comments === 1, R.comments],
	['one Undo restores the order', () => R.undo === START, R.undo],
	['Alt+Shift+Down with "One".."Two" selected moves both below "Three"', () => R['two-down'] === AFTER_DOWN, R['two-down']],
	['the comment on "Three", the paragraph that moved round them, is kept', () => R['comments-neighbour'] === 1, R['comments-neighbour']],
	['the selection stays on "One" and "Two"', () => JSON.stringify(R['two-down-selected']) === '["One","Two"]', JSON.stringify(R['two-down-selected'])],
	['nothing moves above the first paragraph', () => R['first-up'] === AFTER_DOWN, R['first-up']],
	['nothing moves across a table (down)', () => R['middle-before-table'] === AFTER_DOWN, R['middle-before-table']],
	['nothing moves across a table (up)', () => R['after-table'] === AFTER_DOWN, R['after-table']],
	['in a table cell: "Y" moves above "X", the cursor stays in it', () => JSON.stringify(R.cell) === '["Y,X","Y"]', JSON.stringify(R.cell)],
	['nothing moves with track changes on', () => R.tracked === AFTER_DOWN, R.tracked],
	['the new order is saved to DOCX', () => R.reopened === AFTER_DOWN, R.reopened],
];
const enLabels = {};
for (const app of ['documenteditor', 'pdfeditor']) {
	const rel = `apps/${app}/main/locale/en.json`;
	const json = process.env.BASELINE
		? execFileSync('git', ['-C', WEBAPPS, 'show', `${WEBAPPS_BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(WEBAPPS, rel), 'utf8');
	const en = JSON.parse(json);
	enLabels[app] = ['MoveParagraphUp', 'MoveParagraphDown'].every((a) =>
		en['Common.Controllers.Shortcuts.txtLabel' + a] && en['Common.Controllers.Shortcuts.txtDescription' + a]);
}
CHECKS.push(['the Keyboard Shortcuts dialog has names for both actions (document and PDF en.json)',
	() => enLabels.documenteditor && enLabels.pdfeditor, JSON.stringify(enLabels)]);
let failed = 0;
for (const [name, fn, got] of CHECKS) {
	const ok = !R.error && fn();
	if (!ok) failed++;
	console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : ': got ' + got}`);
}
if (R.error || R.error2) console.log('script error: ' + (R.error || R.error2));
if (!('reopened' in R)) console.log((run.stdout || '').slice(-2000) + (run.stderr || '').slice(-2000));
console.log(failed ? `FAIL: ${failed} of ${CHECKS.length} checks` : `PASS: ${CHECKS.length} checks`);
process.exit(failed ? 1 : 0);
