/*
 * #1675 - open a document at the last edited position.
 *
 * Before: a reopened document always started with the caret at the top; nothing
 * remembered where the user had been, so long documents meant scrolling back by hand.
 *
 * Now, as an OPTION (File > Advanced settings > "Offer to continue where you left
 * off when a document is reopened", desktop local files, off by default):
 * - sdkjs: CDocument.GetCaretPath / MoveCursorToCaretPath (word/Editor/Document.js),
 *   api.asc_GetCaretPath / asc_MoveCursorToCaretPath (word/api.js), turn the caret in
 *   the main text into plain numbers (element indexes down to the paragraph, a table
 *   adding row and cell, then the characters before the caret in that paragraph - run
 *   indexes are not stable across save and reopen) and back. Indexes the
 *   document no longer has are refused (false), never thrown on.
 * - web-apps (documenteditor Main.js initResumePosition and helpers): the caret is kept
 *   in localStorage 'de-resume-positions' under a hash of the file path (the path is not
 *   stored), most recent first, at most 100 files; written 1 s after the caret settles.
 *   On reopening, a non-blocking tip offers "Continue where you left off"; its button
 *   moves the caret there. While the tip is up the caret at open does not overwrite the
 *   kept place; closing the tip or editing ends that. Turning the option off forgets the
 *   kept places.
 *
 * Part A runs the WHOLE word engine headless in docbuilder (bundle concatenated from
 * RD_REPO, or BASE_REF with BASELINE=1, as issue-1203-move-paragraph-test.js): a document
 * with plain paragraphs, a table and a block content control; the caret is put in the
 * middle of a word in each, its path taken and JSON round-tripped, the document SAVED to
 * DOCX and REOPENED, and the caret put back from the path; the text before the caret
 * must be the same as before.
 * Part B extracts by brace matching the REAL Main.js methods (resumePositionHash,
 * getResumePositions, findResumePosition, storeResumePosition, initResumePosition) and
 * runs them against stubs (localStorage, api, tip, desktop bridge, timers), plus checks
 * the Advanced settings wiring in FileMenuPanels.js and en.json.
 *
 * NOT claimed: the tip as drawn and the scroll to the caret (GUI check); headers,
 * footnotes and text boxes (not kept: the path is null there); a file changed elsewhere
 * between sessions lands on whatever is at the same indexes (or is refused).
 *
 * RD_REPO=<sdkjs> (default ../sdkjs), RD_WEBAPPS=<web-apps> (default ../web-apps).
 * BASELINE=1 reads sources at BASE_REF / WEBAPPS_BASE_REF, where it must fail.
 * RD_CORE_BIN / RD_CORE_LIB override the core build dirs (exit 2 when missing).
 */
'use strict';
const { spawnSync, execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
// Pinned to the parents of the commits that landed this feature, never HEAD.
const BASE_REF = process.env.BASE_REF || 'c1be872fcf^';
const WEBAPPS = process.env.RD_WEBAPPS || path.join(ROOT, 'web-apps');
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '9754c42810^';
const CORE_BIN = process.env.RD_CORE_BIN || path.join(ROOT, 'core', 'build', 'bin', 'mac_arm64');
const CORE_LIB = process.env.RD_CORE_LIB || path.join(ROOT, 'core', 'build', 'lib', 'mac_arm64');
const TEMPLATE = path.join(ROOT, 'document-templates', 'new', 'en-US', 'new.docx');
const XREGEXP = path.join(ROOT, 'web-apps', 'vendor', 'xregexp', 'xregexp-all-min.js');
const UNDERSCORE = path.join(ROOT, 'web-apps', 'vendor', 'underscore', 'underscore-min.js');
const FONTS = path.join(ROOT, 'core-fonts');

for (const p of [path.join(CORE_BIN, 'docbuilder'), path.join(CORE_BIN, 'x2t'), path.join(CORE_BIN, 'allfontsgen'),
	path.join(CORE_LIB, 'doctrenderer.framework'), TEMPLATE, XREGEXP, UNDERSCORE, FONTS]) {
	if (!fs.existsSync(p)) {
		console.log('CANNOT RUN: missing ' + p);
		process.exit(2);
	}
}

const CHECKS = [];
const check = (name, ok, got) => CHECKS.push([name, !!ok, got]);

// ---------------------------------------------------------------- part A: sdkjs in docbuilder
function readMany(repo, ref, rels) {
	if (!process.env.BASELINE)
		return rels.map((r) => fs.readFileSync(path.join(repo, r)));
	const out = spawnSync('git', ['-C', repo, 'cat-file', '--batch'],
		{ input: rels.map((r) => `${ref}:${r}\n`).join(''), maxBuffer: 1 << 30 });
	if (out.status !== 0) throw new Error('git cat-file failed: ' + out.stderr);
	const buf = out.stdout, res = [];
	let pos = 0;
	for (const r of rels) {
		const nl = buf.indexOf(10, pos);
		const header = buf.slice(pos, nl).toString();
		const m = /^\S+ blob (\d+)$/.exec(header);
		if (!m) throw new Error(`${ref}:${r}: ${header}`);
		const size = Number(m[1]);
		res.push(buf.slice(nl + 1, nl + 1 + size));
		pos = nl + 1 + size + 1;
	}
	return res;
}
const config = JSON.parse(readMany(SDKJS, BASE_REF, ['configs/word.json'])[0].toString()).sdk;
const minFiles = config.min.concat((config.desktop && config.desktop.min) || []);
const commonFiles = config.common.concat((config.desktop && config.desktop.common) || []);
const join = (bufs) => bufs.map((b) => b.toString('utf8') + '\n').join('');

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'rd-1675-'));
const mk = (p) => fs.mkdirSync(path.join(work, p), { recursive: true });
['bin', 'fonts', 'editors/sdkjs/word', 'editors/sdkjs/common/Native', 'editors/sdkjs/common/libfont',
	'editors/web-apps/vendor/xregexp'].forEach(mk);
fs.symlinkSync(CORE_LIB, path.join(work, 'Frameworks'));
for (const b of ['docbuilder', 'x2t', 'allfontsgen']) {
	fs.copyFileSync(path.join(CORE_BIN, b), path.join(work, 'bin', b), fs.constants.COPYFILE_FICLONE);
	fs.chmodSync(path.join(work, 'bin', b), 0o755);
}
fs.writeFileSync(path.join(work, 'editors/sdkjs/word/sdk-all-min.js'), join(readMany(SDKJS, BASE_REF, minFiles)));
fs.writeFileSync(path.join(work, 'editors/sdkjs/word/sdk-all.js'),
	'(function(window, undefined) {\n' + join(readMany(SDKJS, BASE_REF, commonFiles)) + '})(window);\n');
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

const saved = path.join(work, 'resume.docx');
const helpers = `function out(name, value) { console.log('RESULT ' + JSON.stringify([name, value])); }
var doc = Api.GetDocument();
var logic = editor.WordControl.m_oLogicDocument;
// the text before the caret in its paragraph (selects back to the paragraph start, then puts the caret back)
function before() {
	var p = logic.GetCurrentParagraph();
	var pos = p.Get_ParaContentPos(false, false);
	var start = p.Get_StartPos();
	p.Selection.Use = true;
	p.Set_SelectionContentPos(start, pos);
	var t = p.GetSelectedText(false);
	p.RemoveSelection();
	p.Set_ParaContentPos(pos, false, -1, -1);
	return p.GetText().trim() + '|' + t;
}
`;
const script = `builder.OpenFile(${JSON.stringify(path.join(work, 'new.docx'))});
${helpers}
var paths = {}, wants = {};
var targets = ['Alpha words here', 'Bravo in the middle', 'Charlie in a cell', 'Delta in a control', 'Echo at the end', 'Hotel with a link'];
try {
	doc.RemoveAllElements();
	var p1 = Api.CreateParagraph(); p1.AddText(targets[0]); doc.Push(p1);
	var p2 = Api.CreateParagraph(); p2.AddText(targets[1]); doc.Push(p2);
	var table = Api.CreateTable(2, 2); doc.Push(table);
	table.GetCell(1, 1).GetContent().GetElement(0).AddText(targets[2]);
	var cc = Api.CreateBlockLvlSdt(); cc.GetContent().GetElement(0).AddText(targets[3]); doc.Push(cc);
	var p5 = Api.CreateParagraph(); p5.AddText(targets[4]); doc.Push(p5);
	var p6 = Api.CreateParagraph(); p6.AddText(targets[5]); doc.Push(p6);
	doc.Search('with a')[0].AddHyperlink('https://example.com/', 'with a');
	out('link', !!p6.GetElement(1) && p6.GetElement(1).GetClassType());
	for (var i = 0; i < targets.length; i++) {
		var range = doc.Search(targets[i])[0];
		range.Select();
		logic.MoveCursorLeft(false, false);        // collapse to the start of the words
		for (var k = 0; k < 7; k++) logic.MoveCursorRight(false, false);
		paths[targets[i]] = JSON.parse(JSON.stringify(editor.asc_GetCaretPath()));
		wants[targets[i]] = before();
	}
	out('paths', paths);
	out('wants', wants);
} catch (e) {
	out('error', String(e && e.stack || e));
}
builder.SaveFile('docx', ${JSON.stringify(saved)});
builder.CloseFile();
`;
// the reopened document runs in a fresh docbuilder, as a new editor session would
const script2 = (paths) => `builder.OpenFile(${JSON.stringify(saved)});
${helpers}
var paths = ${JSON.stringify(paths)};
try {
	var got = {};
	for (var t in paths) {
		logic.MoveCursorToStartPos(false);
		var ok = editor.asc_MoveCursorToCaretPath(paths[t]);
		got[t] = [ok, before()];
	}
	out('got', got);
	logic.MoveCursorToStartPos(false);
	out('start-caret', before());
	var bad = [];
	[{b: [999], c: 0}, {b: [1, 5], c: 0}, {b: [3, 9, 0, 0], c: 0}, {b: [1]}, {b: ['1'], c: 0}, null, 'x', {b: [-1], c: 0}, {b: [1], c: -2}]
		.forEach(function(path) {
			try { bad.push(editor.asc_MoveCursorToCaretPath(path)); } catch (e) { bad.push('threw ' + e.message); }
		});
	out('bad', bad);
	out('bad-caret', before());
} catch (e) {
	out('error2', String(e && e.stack || e));
}
builder.CloseFile();
`;
const R = {};
function docbuilder(text) {
	fs.writeFileSync(path.join(work, 'run.js'), text);
	const run = spawnSync(path.join(work, 'bin/docbuilder'), [path.join(work, 'run.js')],
		{ cwd: path.join(work, 'bin'), encoding: 'utf8', timeout: 180000 });
	for (const line of (run.stdout || '').split('\n')) {
		const m = /^RESULT (.*)$/.exec(line);
		if (m) { const r = JSON.parse(m[1]); R[r[0]] = r[1]; }
	}
	return run;
}
let run = docbuilder(script);
if (R.paths && fs.existsSync(saved))
	run = docbuilder(script2(R.paths));
fs.rmSync(work, { recursive: true, force: true });
const T = ['Alpha words here', 'Bravo in the middle', 'Charlie in a cell', 'Delta in a control', 'Echo at the end', 'Hotel with a link'];
check('sdkjs: a caret path is taken in a paragraph, a table cell and a content control',
	!R.error && R.paths && T.every((t) => R.paths[t] && Array.isArray(R.paths[t].b) && R.paths[t].c === 7),
	R.error || JSON.stringify(R.paths));
check('sdkjs: the caret was 7 characters into each target',
	R.wants && T.every((t) => R.wants[t] === t + '|' + t.slice(0, 7)), JSON.stringify(R.wants));
check('sdkjs: the last target has its middle words as a hyperlink (caret inside it)', R.link === 'hyperlink', R.link);
check('sdkjs: a table cell path carries row and cell (index, row, cell, index)',
	R.paths && R.paths[T[2]] && R.paths[T[2]].b.length === 4 && R.paths[T[2]].b[1] === 1 && R.paths[T[2]].b[2] === 1,
	R.paths && JSON.stringify(R.paths[T[2]]));
check('sdkjs: after save + reopen, each path puts the caret back at the same place',
	!R.error2 && R.got && T.every((t) => R.got[t] && R.got[t][0] === true && R.got[t][1] === R.wants[t]),
	R.error2 || JSON.stringify(R.got));
check('sdkjs: paths the document does not have are refused, nothing throws',
	JSON.stringify(R.bad) === JSON.stringify([false, false, false, false, false, false, false, false, false]), JSON.stringify(R.bad));
check('sdkjs: a refused path leaves the caret where it was', R['start-caret'] !== undefined && R['bad-caret'] === R['start-caret'], R['bad-caret']);
if (!R.got) console.log((run.stdout || '').slice(-1500) + (run.stderr || '').slice(-1500));

// ---------------------------------------------------------------- part B: web-apps
function readWeb(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', WEBAPPS, 'show', `${WEBAPPS_BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(WEBAPPS, rel), 'utf8');
}
function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
const mainSrc = readWeb('apps/documenteditor/main/app/controller/Main.js');
function method(name) {
	const at = mainSrc.indexOf('            ' + name + ': function(');
	return at === -1 ? null : matched(mainSrc, mainSrc.indexOf('function', at));
}
const value = (name) => { const m = new RegExp('\\n            ' + name + ': ([^,\\n]+),').exec(mainSrc); return m ? m[1] : 'undefined'; };
const names = ['resumePositionHash', 'getResumePositions', 'findResumePosition', 'storeResumePosition', 'initResumePosition'];
const bodies = names.map(method);
check('web-apps: Main.js has ' + names.join(', '), bodies.every(Boolean), names.filter((n, i) => !bodies[i]).join(', '));

function makeController(env) {
	const _ = require(UNDERSCORE);
	const ctx = {
		_, console, JSON, Math, String, Array, Object,
		$: (x) => (x === env.window ? { on: (ev, fn) => { env.unload = fn; } } : { selector: x }),
		setTimeout: (fn) => { env.timers.push(fn); return env.timers.length; },
		clearTimeout: (id) => { if (id) env.timers[id - 1] = null; },
		Common: {
			localStorage: {
				getItem: (k) => (k in env.store ? env.store[k] : null),
				setItem: (k, v) => { env.store[k] = String(v); },
				removeItem: (k) => { delete env.store[k]; },
			},
			Utils: { InternalSettings: { get: (k) => env.settings[k], set: (k, v) => { env.settings[k] = v; } } },
			Controllers: { Desktop: { isActive: () => true, isFeatureAvailable: (f) => f === 'LocalFileGetSourcePath',
				call: (f) => (f === 'LocalFileGetSourcePath' ? env.path : undefined) } },
			UI: { SynchronizeTip: function(opts) {
				const tip = { opts, handlers: {}, shown: false, closed: false,
					on(ev, fn) { this.handlers[ev] = fn; return this; }, show() { this.shown = true; }, close() { this.closed = true; } };
				env.tips.push(tip);
				return tip;
			} },
			NotificationCenter: { trigger: () => {} },
		},
	};
	ctx.window = env.window;
	vm.createContext(ctx);
	const src = '({ resumePositionsKey: ' + value('resumePositionsKey') + ', resumePositionsMax: ' + value('resumePositionsMax') +
		', textResumePosition: "T", textResumeContinue: "C", ' + names.map((n, i) => n + ': ' + bodies[i]).join(',\n') + '})';
	const me = vm.runInContext(src, ctx);
	me.appOptions = { isOffline: true };
	me.api = {
		cb: {},
		asc_registerCallback(name, fn) { (this.cb[name] = this.cb[name] || []).push(fn); },
		fire(name) { (this.cb[name] || []).forEach((fn) => fn()); },
		asc_GetCaretPath: () => env.caret,
		asc_MoveCursorToCaretPath: (p) => { env.moved.push(p); env.caret = p; return true; },
		isDocumentModified: () => env.modified,
	};
	return me;
}
function open(env, filePath) {
	Object.assign(env, { path: filePath, tips: [], timers: [], moved: [], modified: false, window: {} });
	const me = makeController(env);
	me.initResumePosition();
	return me;
}
const flush = (env) => { const t = env.timers.slice(); env.timers.length = 0; t.forEach((fn) => fn && fn()); };

if (bodies.every(Boolean)) {
	const A = '/Users/u/Docs/Long report.docx', B = 'C:\\Users\\u\\Other.docx';
	const START = { b: [0], c: 0 }, DEEP = { b: [40, 1, 2, 0], c: 5 };
	const env = { store: {}, settings: {}, caret: START };

	// option off (the default): nothing happens
	let me = open(env, A);
	me.api.fire('asc_onFocusObject'); flush(env);
	check('web-apps: option off (default): no tip, nothing registered or kept',
		env.tips.length === 0 && Object.keys(me.api.cb).length === 0 && Object.keys(env.store).length === 0, JSON.stringify(env.store));

	// option on, first open: no tip; the caret is kept 1 s after it settles, under a hash, not the path
	env.settings['de-settings-resume-position'] = true;
	me = open(env, A);
	env.caret = DEEP;
	me.api.fire('asc_onFocusObject');
	const keptEarly = env.store['de-resume-positions'];
	flush(env);
	const list = JSON.parse(env.store['de-resume-positions'] || '[]');
	check('web-apps: first open shows no tip', env.tips.length === 0, env.tips.length);
	check('web-apps: the caret is written after the timer, not on every move', keptEarly === undefined && list.length === 1, keptEarly);
	check('web-apps: kept under a hash of the path; the path is not stored',
		list[0] && list[0].k === me.resumePositionHash(A) && JSON.stringify(list[0].c) === JSON.stringify(DEEP) &&
		!/Long report|Users/.test(env.store['de-resume-positions']), env.store['de-resume-positions']);

	// reopen: tip offered; the caret at open does not overwrite the kept place; the button moves there
	env.caret = START;
	me = open(env, A);
	const tip = env.tips[0];
	check('web-apps: reopening shows the "Continue where you left off" tip', tip && tip.shown && tip.opts.textButton === 'C' && tip.opts.showButton,
		tip && JSON.stringify(tip.opts));
	me.api.fire('asc_onFocusObject'); flush(env);
	check('web-apps: while the tip is up, the caret at open does not replace the kept place',
		JSON.stringify(me.findResumePosition(me.resumePositionHash(A))) === JSON.stringify(DEEP), env.store['de-resume-positions']);
	tip && tip.handlers.buttonclick && tip.handlers.buttonclick();
	check('web-apps: the button moves the caret to the kept place and closes the tip',
		JSON.stringify(env.moved) === JSON.stringify([DEEP]) && tip && tip.closed, JSON.stringify(env.moved));
	env.caret = { b: [41], c: 2 };
	me.api.fire('asc_onFocusObject'); flush(env);
	check('web-apps: after that, new caret positions are kept again',
		JSON.stringify(me.findResumePosition(me.resumePositionHash(A))) === JSON.stringify(env.caret), env.store['de-resume-positions']);

	// closing the tip without using it keeps recording; editing closes it
	me = open(env, A);
	env.tips[0] && env.tips[0].handlers.closeclick && env.tips[0].handlers.closeclick();
	check('web-apps: closing the tip does not move the caret', env.moved.length === 0, JSON.stringify(env.moved));
	env.caret = START;
	me = open(env, A);
	env.modified = true; me.api.fire('asc_onDocumentModifiedChanged');
	check('web-apps: an edit closes the tip', env.tips[0] && env.tips[0].closed, env.tips[0] && env.tips[0].closed);

	// a caret already at the kept place: no tip; another file: no tip
	env.caret = me.findResumePosition(me.resumePositionHash(A));
	me = open(env, A);
	check('web-apps: no tip when the caret already is at the kept place', env.tips.length === 0, env.tips.length);
	me = open(env, B);
	check('web-apps: another file gets no tip', env.tips.length === 0, env.tips.length);
	check('web-apps: the hash treats \\ and / alike and differs per file',
		me.resumePositionHash('C:\\a\\b.docx') === me.resumePositionHash('C:/a/b.docx') && me.resumePositionHash(A) !== me.resumePositionHash(B), '');

	// the list is capped, most recent first
	for (let i = 0; i < 130; i++) me.storeResumePosition('h' + i, { b: [i], c: 0 });
	const capped = JSON.parse(env.store['de-resume-positions']);
	check('web-apps: at most 100 files are kept, most recent first', capped.length === 100 && capped[0].k === 'h129' && capped[99].k === 'h30',
		capped.length + ' ' + (capped[0] && capped[0].k));
	env.store['de-resume-positions'] = '{bad json';
	check('web-apps: a damaged list is read as empty', Array.isArray(me.getResumePositions()) && me.getResumePositions().length === 0, '');

	// switched off mid-session: nothing more is written
	env.store = {};
	env.settings['de-settings-resume-position'] = true;
	me = open(env, B);
	env.settings['de-settings-resume-position'] = false;
	me.api.fire('asc_onFocusObject'); flush(env);
	check('web-apps: turned off during the session, nothing more is written', Object.keys(env.store).length === 0, JSON.stringify(env.store));
}

const panels = readWeb('apps/documenteditor/main/app/view/FileMenuPanels.js');
const en = JSON.parse(readWeb('apps/documenteditor/main/locale/en.json'));
check('web-apps: Advanced settings has the checkbox, stores it, and forgets the places when it is turned off',
	/setBool\("de-settings-resume-position", this\.chResumePosition\.isChecked\(\)\)/.test(panels) &&
	/removeItem\('de-resume-positions'\)/.test(panels) && /tr\.resume-position/.test(panels),
	'');
check('web-apps: en.json has the setting and the tip strings',
	en['DE.Views.FileMenuPanels.Settings.txtResumePosition'] && en['DE.Controllers.Main.textResumePosition'] && en['DE.Controllers.Main.textResumeContinue'], '');
check('web-apps: Main.js reads the setting off by default',
	/InternalSettings\.set\("de-settings-resume-position", Common\.localStorage\.getBool\("de-settings-resume-position"\)\)/.test(mainSrc), '');

let failed = 0;
for (const [name, ok, got] of CHECKS) {
	if (!ok) failed++;
	console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : ': got ' + String(got).slice(0, 600)}`);
}
console.log(failed ? `FAIL: ${failed} of ${CHECKS.length} checks` : `PASS: ${CHECKS.length} checks`);
process.exit(failed ? 1 : 0);
