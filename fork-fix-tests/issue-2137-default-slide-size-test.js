/*
 * #2137 "Be able to modify the default design when opening a new presentation"
 * (the body: "modify the default size ... 960x540 pt ... to 1920x1080 pt or
 * save the custom as default").
 *
 * Before: a new blank presentation always took the bundled blank template's
 * slide size; there was no setting, only editing the installed template (reset
 * by every update).
 *
 * Now (web-apps, presentation editor, desktop offline only, off by default):
 * the Slide Size dialog has "Use this size for new presentations"; on OK the
 * Toolbar stores {type,width,height} (EMU) as pe-settings-def-slide-size, or
 * removes it when the box is unticked. Main.onDocumentContentReady applies it
 * with api.changeSlideSize when editorConfig.newBlank (desktop blank=true).
 *
 * This extracts the REAL Toolbar.onSlideSize, SlideSizeSettings.getSettings,
 * Main.getDefaultSlideSize and the #2137 block of Main.onDocumentContentReady
 * by brace matching / markers and runs them against stubs (localStorage, api,
 * dialog, mode).
 *
 * NOT claimed: the dialog's look (the check box rendering) or that the new tab
 * shows the size - needs a GUI check; nothing about the theme of new decks.
 *
 *   node fork-fix-tests/issue-2137-default-slide-size-test.js
 *   RD_REPO=<web-apps checkout>   (default ../web-apps)
 *   BASELINE=1                    runs against BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'web-apps');
const BASE_REF = process.env.BASE_REF || 'ad9ffc4e5f^';
const BASELINE = !!process.env.BASELINE;
const APP = 'apps/presentationeditor/main/app/';

function src(rel) {
	return BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
}
function extract(text, marker) {
	const at = text.indexOf(marker);
	if (at === -1) return null;
	const open = text.indexOf('{', at);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(at, i + 1);
	}
	throw new Error('unbalanced braces after ' + marker);
}
function fnOf(text, name) {
	const s = extract(text, name + ': function');
	return s && s.slice(s.indexOf('function'));
}

const toolbarJs = src(APP + 'controller/Toolbar.js');
const mainJs = src(APP + 'controller/Main.js');
const dlgJs = src(APP + 'view/SlideSizeSettings.js');

/* ---- stubs */
function makeStorage(init) {
	const m = Object.assign({}, init);
	return {
		map: m,
		getItem: (k) => (k in m ? m[k] : null),
		setItem: (k, v) => { m[k] = String(v); },
		removeItem: (k) => { delete m[k]; },
		getBool: () => false,
	};
}
const SZ = { SzScreen4x3: 0, SzCustom: 7, SzWidescreen: 13 };
const W1920 = 1920 * 12700, H1080 = 1080 * 12700; // pt -> EMU

/* Toolbar.onSlideSize('advanced') with a dialog stub that returns `settings` */
function runToolbar(storage, mode, settings) {
	const onSlideSize = fnOf(toolbarJs, 'onSlideSize');
	assert.ok(onSlideSize, 'onSlideSize not found');
	let dlgOptions = null, sizeCalls = [];
	const PE = { Views: { SlideSizeSettings: function (o) { dlgOptions = o; this.show = () => {}; this.setSettings = () => {}; } } };
	const Common = {
		localStorage: storage,
		NotificationCenter: { trigger() {} },
		component: { Analytics: { trackEvent() {} } },
	};
	const me = {
		api: { changeSlideSize: (...a) => sizeCalls.push(a) },
		mode,
		currentPageSize: { type: SZ.SzWidescreen, width: 12192000, height: 6858000, firstNum: 1 },
		slideSizeArr: [{ ratio: 0.75 }, { ratio: 6858000 / 12192000 }],
		toolbar: { btnSlideSize: { menu: { items: [{ setChecked() {} }, { setChecked() {} }] } } },
	};
	const f = new Function('PE', 'Common', 'Asc', '_', 'return ' + onSlideSize)(PE, Common, { c_oAscSlideSZType: SZ }, { bind: (fn, c) => fn.bind(c) });
	f.call(me, null, { value: 'advanced' });
	if (settings)
		dlgOptions.handler({ getSettings: () => settings }, 'ok');
	return { dlgOptions, sizeCalls };
}

/* SlideSizeSettings.getSettings with/without the check box */
function runGetSettings(chDefault) {
	const getSettings = fnOf(dlgJs, 'getSettings');
	const self = {
		cmbSlideSize: { getValue: () => SZ.SzCustom },
		spnWidth: { getNumberValue: () => 1920 }, spnHeight: { getNumberValue: () => 1080 },
		spnSlideNum: { getNumberValue: () => 1 },
		chDefault,
	};
	const Common = { Utils: { Metric: { fnRecalcToMM: (v) => v * 25.4 / 72 } } };
	return new Function('Common', 'Asc', 'return ' + getSettings)(Common, { c_oAscSlideSZType: SZ }).call(self);
}

/* Main: the #2137 block of onDocumentContentReady + getDefaultSlideSize */
function runMain(storage, opts) {
	const getDef = fnOf(mainJs, 'getDefaultSlideSize');
	assert.ok(getDef, 'Main.getDefaultSlideSize missing');
	const start = mainJs.indexOf('// #2137: the slide size a new blank desktop presentation gets');
	assert.ok(start !== -1, 'Main #2137 block missing');
	// the #2137 block ends at the next marked block (#527 follows it) or at loadAutoCorrectSettings
	const ends = ['// #527:', 'me.loadAutoCorrectSettings();'].map((m) => mainJs.indexOf(m, start)).filter((i) => i !== -1);
	const end = Math.min(...ends);
	const block = mainJs.slice(start, end);
	const calls = [];
	const me = {
		editorConfig: { newBlank: opts.newBlank },
		appOptions: { isDesktopApp: true, isOffline: true },
		api: {
			get_PresentationWidth: () => 12192000, get_PresentationHeight: () => 6858000,
			changeSlideSize: (...a) => calls.push(a),
		},
	};
	me.getDefaultSlideSize = new Function('Common', 'return ' + getDef)({ localStorage: storage });
	new Function('me', 'Common', 'var value;\n' + block)(me, { localStorage: storage });
	return calls;
}

const DESKTOP = { isDesktopApp: true, isOffline: true };
const cases = [
	['A. dialog offers the box in the desktop app, unticked while nothing is stored', () => {
		const r = runToolbar(makeStorage(), DESKTOP, null);
		assert.strictEqual(r.dlgOptions.canSetDefault, true, 'dialog not asked to offer the box');
		assert.strictEqual(r.dlgOptions.isDefault, false);
	}],
	['B. getSettings reports the box (and undefined without it)', () => {
		assert.strictEqual(runGetSettings({ getValue: () => 'checked' })[4], true);
		assert.strictEqual(runGetSettings({ getValue: () => 'unchecked' })[4], false);
		assert.strictEqual(runGetSettings(undefined)[4], undefined);
	}],
	['C. OK with the box ticked stores the size; reopening shows it ticked', () => {
		const st = makeStorage();
		const r = runToolbar(st, DESKTOP, [SZ.SzCustom, W1920, H1080, 1, true]);
		assert.deepStrictEqual(r.sizeCalls, [[W1920, H1080, SZ.SzCustom, 1]], 'current deck not resized');
		assert.deepStrictEqual(JSON.parse(st.map['pe-settings-def-slide-size']), { type: SZ.SzCustom, width: W1920, height: H1080 });
		assert.strictEqual(runToolbar(st, DESKTOP, null).dlgOptions.isDefault, true);
	}],
	['D. a new blank presentation gets the stored size', () => {
		const st = makeStorage({ 'pe-settings-def-slide-size': JSON.stringify({ type: SZ.SzCustom, width: W1920, height: H1080 }) });
		assert.deepStrictEqual(runMain(st, { newBlank: true }), [[W1920, H1080, SZ.SzCustom]]);
	}],
	['E. unticking removes it', () => {
		const st = makeStorage({ 'pe-settings-def-slide-size': '{"type":7,"width":1,"height":1}' });
		runToolbar(st, DESKTOP, [SZ.SzCustom, W1920, H1080, 1, false]);
		assert.ok(!('pe-settings-def-slide-size' in st.map));
	}],
	/* unchanged behaviour */
	['F. nothing stored: a new blank presentation is not resized', () => {
		assert.deepStrictEqual(runMain(makeStorage(), { newBlank: true }), []);
	}],
	['G. an existing (non-blank) presentation is never resized', () => {
		const st = makeStorage({ 'pe-settings-def-slide-size': JSON.stringify({ type: SZ.SzCustom, width: W1920, height: H1080 }) });
		assert.deepStrictEqual(runMain(st, { newBlank: false }), []);
	}],
	['H. a stored value out of the dialog limits / garbage is ignored', () => {
		assert.deepStrictEqual(runMain(makeStorage({ 'pe-settings-def-slide-size': '{"width":5,"height":5}' }), { newBlank: true }), []);
		assert.deepStrictEqual(runMain(makeStorage({ 'pe-settings-def-slide-size': 'not json' }), { newBlank: true }), []);
	}],
	['I. online editor: no box, OK stores nothing', () => {
		const st = makeStorage();
		const r = runToolbar(st, { isDesktopApp: false }, [SZ.SzCustom, W1920, H1080, 1, undefined]);
		assert.strictEqual(r.dlgOptions.canSetDefault, false);
		assert.deepStrictEqual(st.map, {});
	}],
];

let failed = 0;
for (const [name, fn] of cases) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failed++; console.log('FAIL ' + name + ' :: ' + e.message.split('\n')[0]); }
}
if (failed) {
	console.log(`FAIL #2137: ${failed}/${cases.length} cases` + (BASELINE ? ' (BASELINE, expected)' : ''));
	process.exit(1);
}
console.log('PASS #2137: the Slide Size dialog can set the size of new blank presentations; off by default' + (BASELINE ? ' (BASELINE?!)' : ''));
